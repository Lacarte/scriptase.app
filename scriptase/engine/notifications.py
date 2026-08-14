"""Durable workflow run notifications and optional delivery channels."""

from __future__ import annotations

import html
import os
import subprocess
import threading
from copy import deepcopy
from typing import Any, Mapping
from urllib.parse import urlparse

import requests

from scriptase.shared.io_utils import now_iso, safe_json_read, safe_json_write
from scriptase.shared.security import safe_join
from scriptase.providers.validation import sanitize_message

from .persistence import EXECUTION_ID_RE
from .validation import WORKFLOW_ID_RE


_LOCK = threading.Lock()


def validate_notification_settings(value: Any, problems: list[dict]) -> None:
    """Validate the exportable, per-workflow notification configuration."""
    if value is None:
        return
    path = "settings.notifications"
    if not isinstance(value, dict):
        problems.append(_problem("settings.notifications must be an object", path))
        return
    allowed = {"on_completion", "on_failure", "windows_toast", "webhook"}
    for unknown in sorted(set(value) - allowed):
        problems.append(_problem(f"Unknown notification field: {unknown}", f"{path}.{unknown}"))
    for field in ("on_completion", "on_failure", "windows_toast"):
        if not isinstance(value.get(field, False), bool):
            problems.append(_problem(f"{path}.{field} must be a boolean", f"{path}.{field}"))
    webhook = value.get("webhook")
    if webhook is None:
        return
    if not isinstance(webhook, dict):
        problems.append(_problem(f"{path}.webhook must be an object", f"{path}.webhook"))
        return
    for unknown in sorted(set(webhook) - {"enabled", "url"}):
        problems.append(_problem(f"Unknown notification webhook field: {unknown}", f"{path}.webhook.{unknown}"))
    if not isinstance(webhook.get("enabled", False), bool):
        problems.append(_problem(f"{path}.webhook.enabled must be a boolean", f"{path}.webhook.enabled"))
    url = webhook.get("url", "")
    if not isinstance(url, str) or len(url) > 2048:
        problems.append(_problem(f"{path}.webhook.url must be a string of at most 2048 characters", f"{path}.webhook.url"))
    elif webhook.get("enabled") and not _valid_webhook_url(url):
        problems.append(_problem("Enabled notification webhook needs an http(s) URL without credentials", f"{path}.webhook.url"))


def _problem(message: str, path: str) -> dict:
    return {"code": "WORKFLOW_INVALID", "message": message, "severity": "error", "path": path}


def _valid_webhook_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password
    except (TypeError, ValueError):
        return False


def _root(output_dir: str) -> str:
    return os.path.join(output_dir, "workflows", "notifications")


def _record_path(execution_id: str, *, root: str) -> str:
    if not isinstance(execution_id, str) or not EXECUTION_ID_RE.fullmatch(execution_id):
        raise ValueError("execution_id must match ex_XXXXXX")
    return safe_join(root, f"{execution_id}.json")


def dispatch_run_notification(
    workflow: Mapping[str, Any], execution: Mapping[str, Any], *, output_dir: str
) -> dict | None:
    """Persist and deliver one configured success/failure notification.

    Persistence happens first and is idempotent per execution. Channel failures are
    recorded as delivery metadata and never change the run's terminal status.
    """
    status = execution.get("status")
    outcome = "success" if status in {"succeeded", "partial"} else "failure" if status == "failed" else None
    settings = (workflow.get("settings") or {}).get("notifications") or {}
    setting = "on_completion" if outcome == "success" else "on_failure"
    if outcome is None or not settings.get(setting, False):
        return None
    execution_id = execution.get("execution_id")
    root = _root(output_dir)
    path = _record_path(execution_id, root=root)
    with _LOCK:
        if os.path.isfile(path):
            return safe_json_read(path)
        title = f"Workflow {outcome}"
        workflow_name = str(workflow.get("name") or workflow.get("workflow_id") or "Workflow")
        message = f"{workflow_name} {('completed' if outcome == 'success' else 'failed')}"
        record = {
            "notification_id": f"nt_{execution_id[3:]}",
            "execution_id": execution_id,
            "workflow_id": workflow.get("workflow_id"),
            "project_id": execution.get("project_id"),
            "outcome": outcome,
            "title": title,
            "message": message,
            "created_at": execution.get("finished_at") or now_iso(),
            "seen": False,
            "deliveries": {},
            "schema_version": 1,
        }
        safe_json_write(path, record, indent=2)

    deliveries: dict[str, dict[str, Any]] = {}
    if settings.get("windows_toast"):
        try:
            _windows_toast(title, message)
            deliveries["windows_toast"] = {"status": "sent" if os.name == "nt" else "unsupported"}
        except Exception as exc:  # a notification channel must never fail a run
            deliveries["windows_toast"] = {
                "status": "failed",
                "error": sanitize_message(exc),
            }
    webhook = settings.get("webhook") or {}
    if webhook.get("enabled"):
        try:
            response = requests.post(webhook["url"], json=_webhook_payload(record), timeout=5)
            response.raise_for_status()
            deliveries["webhook"] = {"status": "sent", "http_status": response.status_code}
        except Exception as exc:
            # Channel errors may embed URLs, response bodies, or paths — never
            # persist them raw (step 16.4, contracts.md §36).
            deliveries["webhook"] = {
                "status": "failed",
                "error": sanitize_message(exc),
            }
    if deliveries:
        with _LOCK:
            current = safe_json_read(path)
            current["deliveries"] = deliveries
            safe_json_write(path, current, indent=2)
            record = current
    return record


def _webhook_payload(record: Mapping[str, Any]) -> dict:
    return {key: deepcopy(record.get(key)) for key in (
        "notification_id", "execution_id", "workflow_id", "project_id", "outcome",
        "title", "message", "created_at",
    )}


def _windows_toast(title: str, message: str) -> None:
    if os.name != "nt":
        return
    toast_xml = (
        '<toast><visual><binding template="ToastGeneric">'
        f"<text>{html.escape(title)}</text><text>{html.escape(message)}</text>"
        "</binding></visual></toast>"
    )
    escaped_xml = toast_xml.replace("'", "''")
    script = (
        "$xml=New-Object 'Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime';"
        f"$xml.LoadXml('{escaped_xml}');"
        "$toast=[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime]::new($xml);"
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]::CreateToastNotifier('ScriptToScene Studio').Show($toast)"
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def list_notifications(workflow_id: str, *, output_dir: str, limit: int = 100) -> tuple[list[dict], int, int]:
    if not isinstance(workflow_id, str) or not WORKFLOW_ID_RE.fullmatch(workflow_id):
        raise ValueError("workflow_id must match wf_XXXXXX")
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    root = _root(output_dir)
    os.makedirs(root, exist_ok=True)
    items = []
    for filename in os.listdir(root):
        if not filename.endswith(".json"):
            continue
        try:
            record = safe_json_read(safe_join(root, filename))
        except (OSError, ValueError):
            continue
        if record.get("workflow_id") == workflow_id:
            items.append(record)
    items.sort(key=lambda item: (item.get("created_at") or "", item.get("notification_id") or ""), reverse=True)
    unseen = sum(not item.get("seen", False) for item in items)
    return items[:limit], len(items), unseen


def mark_notifications_seen(workflow_id: str, *, output_dir: str) -> int:
    if not isinstance(workflow_id, str) or not WORKFLOW_ID_RE.fullmatch(workflow_id):
        raise ValueError("workflow_id must match wf_XXXXXX")
    root = _root(output_dir)
    # Do not inherit the list endpoint's 200-item response cap: opening the
    # center acknowledges the complete durable log for this workflow.
    os.makedirs(root, exist_ok=True)
    with _LOCK:
        items = []
        for filename in os.listdir(root):
            if not filename.endswith(".json"):
                continue
            try:
                record = safe_json_read(safe_join(root, filename))
            except (OSError, ValueError):
                continue
            if record.get("workflow_id") == workflow_id and not record.get("seen", False):
                items.append(record)
        for record in items:
            record["seen"] = True
            safe_json_write(_record_path(record["execution_id"], root=root), record, indent=2)
    return len(items)
