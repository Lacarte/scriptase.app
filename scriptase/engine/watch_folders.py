"""Polling watch-folder trigger with stable-size debounce and atomic claiming."""

from __future__ import annotations

import fnmatch
import os
import shutil
import threading
import time
from copy import deepcopy
from typing import Callable, Iterable, Mapping

from .execution import execution_manager
from .persistence import list_workflows, load_workflow


DEFAULT_STABLE_SECONDS = 1.0
MAX_WATCH_FILE_BYTES = 10_000


def watch_run_payload(workflow: Mapping, content: str, settings: Mapping) -> tuple[dict, dict]:
    """Return an execution snapshot and port overrides for one watched file."""
    snapshot = deepcopy(dict(workflow))
    target_node_id = settings.get("target_node_id") or ""
    target_port = settings.get("target_port") or ""
    if target_node_id and target_port:
        return snapshot, {target_node_id: {target_port: content}}

    script_node = next((
        node for node in snapshot.get("nodes", [])
        if node.get("type") == "script.input" and not node.get("disabled")
    ), None)
    if script_node is None:
        raise ValueError("Watch folder has no enabled Script Input node")
    script_node["configuration"] = {**(script_node.get("configuration") or {}), "text": content}
    return snapshot, {}


class WatchFolderService:
    def __init__(
        self,
        *,
        workflow_loader: Callable[[], Iterable[Mapping]] | None = None,
        enqueue: Callable[[Mapping, str, Mapping], object] | None = None,
        clock: Callable[[], float] | None = None,
        stable_seconds: float = DEFAULT_STABLE_SECONDS,
        poll_seconds: float = 0.25,
    ):
        self.workflow_loader = workflow_loader or self._load_workflows
        self.enqueue = enqueue or self._enqueue
        self.clock = clock or time.monotonic
        self.stable_seconds = max(0.0, float(stable_seconds))
        self.poll_seconds = max(0.05, float(poll_seconds))
        self._observed: dict[tuple[str, str], tuple[tuple[int, int], float]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _load_workflows() -> list[dict]:
        summaries, _ = list_workflows(limit=10000)
        return [load_workflow(item["workflow_id"]) for item in summaries]

    @staticmethod
    def _enqueue(workflow: Mapping, content: str, settings: Mapping):
        snapshot, overrides = watch_run_payload(workflow, content, settings)
        return execution_manager.start(
            snapshot,
            run_mode="full",
            target_node_ids=[],
            source="watch",
            input_overrides=overrides,
        )

    @staticmethod
    def _processed_path(source: str) -> str:
        processed_dir = os.path.join(os.path.dirname(source), "processed")
        os.makedirs(processed_dir, exist_ok=True)
        name = os.path.basename(source)
        destination = os.path.join(processed_dir, name)
        if not os.path.exists(destination):
            return destination
        stem, extension = os.path.splitext(name)
        counter = 1
        while True:
            destination = os.path.join(processed_dir, f"{stem}_{counter}{extension}")
            if not os.path.exists(destination):
                return destination
            counter += 1

    def tick(self) -> list[dict]:
        """Observe configured folders once and enqueue files stable across ticks."""
        now = self.clock()
        active_keys: set[tuple[str, str]] = set()
        enqueued: list[dict] = []
        for workflow in self.workflow_loader():
            settings = (workflow.get("settings") or {}).get("watch_folder")
            if not isinstance(settings, Mapping) or not settings.get("enabled"):
                continue
            folder = os.path.abspath(settings.get("folder", ""))
            pattern = settings.get("pattern", "*.txt")
            if not os.path.isdir(folder):
                continue
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            for entry in entries:
                if not entry.is_file(follow_symlinks=False) or not fnmatch.fnmatchcase(entry.name, pattern):
                    continue
                source = os.path.abspath(entry.path)
                key = (str(workflow.get("workflow_id", "")), os.path.normcase(source))
                active_keys.add(key)
                try:
                    stat = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                signature = (stat.st_size, stat.st_mtime_ns)
                prior = self._observed.get(key)
                if prior is None or prior[0] != signature:
                    self._observed[key] = (signature, now)
                    continue
                if now - prior[1] < self.stable_seconds:
                    continue
                try:
                    if stat.st_size > MAX_WATCH_FILE_BYTES:
                        continue
                    with open(source, "r", encoding="utf-8") as handle:
                        content = handle.read(MAX_WATCH_FILE_BYTES + 1)
                    if len(content.encode("utf-8")) > MAX_WATCH_FILE_BYTES:
                        continue
                    destination = self._processed_path(source)
                    try:
                        os.replace(source, destination)
                    except OSError:
                        shutil.move(source, destination)
                    try:
                        result = self.enqueue(workflow, content, settings)
                    except Exception:
                        # Put an unqueued claim back so a later tick can retry it.
                        if not os.path.exists(source):
                            try:
                                os.replace(destination, source)
                            except OSError:
                                shutil.move(destination, source)
                        self._observed[key] = (signature, now)
                        continue
                except (OSError, UnicodeError):
                    continue
                self._observed.pop(key, None)
                active_keys.discard(key)
                enqueued.append({
                    "workflow_id": workflow.get("workflow_id"),
                    "source_path": source,
                    "processed_path": destination,
                    "result": result,
                })
        for key in list(self._observed):
            if key not in active_keys:
                self._observed.pop(key, None)
        return enqueued

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="workflow-watch-folders", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(1.0, self.poll_seconds + 0.5))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                pass
            self._stop.wait(self.poll_seconds)


watch_folder_service = WatchFolderService()
