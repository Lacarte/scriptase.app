"""`n8n` script provider — sends a flat Channel-shaped payload to a webhook.

Unlike `gemini`, this provider does not build a system/user prompt: the n8n
workflow behind the webhook owns the prompting. It POSTs exactly the fields the
Channel resolves — niche, style, category, tone, language, duration, and the
script template's brief + section outline — and parses the returned script into
the standard `stories/{id}/story.json` document.

HTTP mechanics (retry, backoff, fail-closed on non-200) are the shared
`call_webhook`; section parsing, word count, and history reuse the script
service helpers. Everything else here is the payload shape and the mapping of
transport/response failures onto the `ProviderError` catalog with correct
retryability — no third-party response body is ever copied into an error (L2).
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any, Callable, Mapping

import requests as http_requests

from config import N8N_STORY_WEBHOOK_URL, STORIES_DIR
from scriptase.shared.io_utils import safe_json_write
from scriptase.shared.security import is_safe_webhook_url
from scriptase.shared.webhooks import WebhookResponseError, call_webhook
from scriptase.providers.errors import (
    PROVIDER_REQUEST_INVALID,
    PROVIDER_RESPONSE_MALFORMED,
    PROVIDER_TIMEOUT,
    PROVIDER_TRANSPORT_FAILED,
    ProviderError,
    classify_webhook_error,
)
from scriptase.modules.script.providers.base import ScriptProvider
from scriptase.modules.script.engine import parse_story_sections
from scriptase.modules.script.history import append_history
from scriptase.modules.script.prompts import WORDS_PER_SECOND

_DOMAIN = "script"
_PROVIDER_ID = "n8n"

# The Channel's default template outline, used only when the configuration
# carries none. Mirrors DEFAULT_SCRIPT_TEMPLATE_* in channels.models so a run
# with no template still sends a sensible brief and sections.
_DEFAULT_TEMPLATE_BRIEF = (
    "Open with an immediate hook, introduce a surprising turn, explain why it "
    "matters, reframe the idea, and finish with a memorable landing."
)
_DEFAULT_TEMPLATE_SECTIONS = ["Hook", "Turn", "Why", "Reframe", "Landing"]


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sections(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        if cleaned:
            return cleaned
    return list(_DEFAULT_TEMPLATE_SECTIONS)


def _build_payload(configuration: Mapping[str, Any]) -> dict[str, Any]:
    """The flat request this provider sends. Accepts node/legacy and §32.1 keys.

    The shape is the Channel's own resolved fields — no prompt is built here;
    the n8n workflow is responsible for turning these into an LLM call.
    """
    data = dict(configuration or {})
    return {
        "niche_preset": str(data.get("niche_preset") or "").strip(),
        "preset_style": str(data.get("preset_style") or data.get("style") or "").strip(),
        "story_category": str(
            data.get("story_category") or data.get("category") or ""
        ).strip(),
        "story_tone": str(data.get("story_tone") or data.get("tone") or "").strip(),
        "language": str(data.get("language") or "en").strip() or "en",
        "duration": _int(
            data.get("duration")
            if data.get("duration") not in (None, "")
            else data.get("target_duration_s"),
            60,
        ),
        "template_brief": str(
            data.get("template_brief") or _DEFAULT_TEMPLATE_BRIEF
        ).strip(),
        "template_sections": _sections(data.get("template_sections")),
    }


def _extract_script(result: Mapping[str, Any]) -> str:
    """The script text from the webhook response, across the common keys."""
    for key in ("story_text", "script_text", "output", "text", "response"):
        value = result.get(key) if isinstance(result, Mapping) else None
        if isinstance(value, str) and value.strip():
            return value
    return ""


class N8nScriptProvider(ScriptProvider):
    """Registered script provider that delegates prompting to an n8n workflow."""

    def generate(
        self,
        configuration: Mapping[str, Any],
        *,
        project_id: str,
        webhook_caller: Callable[..., Mapping[str, Any]] | None = None,
    ) -> dict:
        settings = dict(configuration.get("settings") or {}) if isinstance(configuration, Mapping) else {}
        webhook_url = (
            str(settings.get("webhook_url") or "").strip()
            or str((configuration or {}).get("webhook_url") or "").strip()
            or N8N_STORY_WEBHOOK_URL
        )
        allow_private = os.environ.get("STS_ALLOW_PRIVATE_WEBHOOKS", "true").lower() == "true"
        if not is_safe_webhook_url(webhook_url, allow_private=allow_private):
            raise ProviderError(
                PROVIDER_REQUEST_INVALID,
                "The script webhook URL is not allowed",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
            )

        payload = _build_payload(configuration)
        started = time.perf_counter()
        caller = webhook_caller or call_webhook
        try:
            result = caller(webhook_url, payload, timeout=120, label="Script webhook")
        except http_requests.Timeout as exc:
            raise ProviderError(
                PROVIDER_TIMEOUT,
                "The script webhook timed out",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
                cause_type=type(exc).__name__,
            ) from exc
        except http_requests.ConnectionError as exc:
            raise ProviderError(
                PROVIDER_TRANSPORT_FAILED,
                "Could not reach the script webhook",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
                cause_type=type(exc).__name__,
            ) from exc
        except WebhookResponseError as exc:
            # The webhook itself reported a failure — classify it (billing, auth,
            # rate, bad request) via the shared mapper so the user learns *why*,
            # without forwarding the raw third-party text verbatim (§34.4).
            code, message = classify_webhook_error(getattr(exc, "status", None), str(exc))
            raise ProviderError(
                code, message,
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
                cause_type=type(exc).__name__,
            ) from exc
        except RuntimeError as exc:
            # `call_webhook` exhausts retries or fails closed on non-200 bodies.
            # Never forward the raw body — it may embed third-party text (L2).
            raise ProviderError(
                PROVIDER_TRANSPORT_FAILED,
                "The script webhook failed after retries",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
                cause_type=type(exc).__name__,
            ) from exc

        raw_text = _extract_script(result or {})
        if not raw_text.strip():
            raise ProviderError(
                PROVIDER_RESPONSE_MALFORMED,
                "The script webhook returned no script text",
                domain=_DOMAIN,
                provider_id=_PROVIDER_ID,
            )

        parsed = parse_story_sections(raw_text)
        generated_at = datetime.now().astimezone().isoformat()
        generation_time = round(time.perf_counter() - started, 3)
        estimated_duration = round(parsed["word_count"] / WORDS_PER_SECOND)

        story_data = {
            "project_id": project_id,
            "story_text": parsed["story_text"],
            "sections": parsed["sections"],
            "metadata": {
                "preset_style": payload["preset_style"],
                "language": payload["language"],
                "story_category": payload["story_category"],
                "story_tone": payload["story_tone"],
                "duration": payload["duration"],
                "niche_preset": payload["niche_preset"],
                "word_count": parsed["word_count"],
                "estimated_duration": estimated_duration,
                "provider": _PROVIDER_ID,
                "generation_time": generation_time,
                "timestamp": generated_at,
            },
            "pipeline_ref": {"tts_project_id": None, "scenes_project_id": None},
        }
        path = os.path.join(STORIES_DIR, project_id, "story.json")
        safe_json_write(path, story_data, indent=2)

        try:
            append_history(
                preset_style=payload["preset_style"],
                category=payload["story_category"],
                language=payload["language"],
                hook=parsed["sections"].get("hook", ""),
                opening=(parsed["sections"].get("build", "") or "").split(".")[0],
                timestamp=generated_at,
                concept_family="",
            )
        except Exception:
            # History improves prompt diversity but is not part of the result.
            pass

        return {**story_data, "path": path}


def create() -> N8nScriptProvider:
    return N8nScriptProvider()


def health_check(settings: dict) -> dict:
    """Report whether a script webhook is configured. No request is made."""
    configured = bool((settings or {}).get("webhook_url") or N8N_STORY_WEBHOOK_URL)
    return {
        "status": "ok" if configured else "warn",
        "latency_ms": 0,
        "message": (
            "Script webhook configured"
            if configured
            else "No script webhook URL is configured"
        ),
    }


def validate_settings(settings: dict) -> list[dict]:
    issues: list[dict] = []
    url = str((settings or {}).get("webhook_url") or "").strip()
    if not url:
        return issues
    allow_private = os.environ.get("STS_ALLOW_PRIVATE_WEBHOOKS", "true").lower() == "true"
    if not is_safe_webhook_url(url, allow_private=allow_private):
        issues.append({
            "field": "webhook_url",
            "severity": "error",
            "message": "Unsafe webhook URL",
        })
    return issues
