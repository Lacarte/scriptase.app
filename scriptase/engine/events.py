"""Thread-safe, bounded workflow execution event streams."""

from __future__ import annotations

import json
import threading
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from scriptase.shared.io_utils import now_iso

from .redaction import redact


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "partial"}


@dataclass(frozen=True)
class ReplayBatch:
    events: list[dict[str, Any]]
    terminal: bool


class ExecutionEventBuffer:
    """A monotonically sequenced ring with blocking replay subscribers."""

    def __init__(self, execution_id: str, *, max_events: int = 1000):
        self.execution_id = execution_id
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._sequence = 0
        self._terminal = False
        self._condition = threading.Condition()

    def emit(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._condition:
            if self._terminal:
                return deepcopy(self._events[-1])
            self._sequence += 1
            payload = redact({
                **event,
                "sequence": self._sequence,
                "execution_id": self.execution_id,
                "timestamp": event.get("timestamp") or now_iso(),
            })
            self._events.append(payload)
            if payload.get("node_id") is None and payload.get("status") in TERMINAL_STATUSES:
                self._terminal = True
            self._condition.notify_all()
            return deepcopy(payload)

    def replay(self, last_sequence: int, *, snapshot: Callable[[], dict] | None = None) -> ReplayBatch:
        """Return retained events after ``last_sequence``, with reset if stale."""
        with self._condition:
            events = list(self._events)
            result: list[dict[str, Any]] = []
            if events and last_sequence < events[0]["sequence"] - 1:
                reset_sequence = events[0]["sequence"] - 1
                result.append(redact({
                    "sequence": reset_sequence,
                    "execution_id": self.execution_id,
                    "node_id": None,
                    "status": "reset",
                    "timestamp": now_iso(),
                    "summary": "Requested events are no longer retained; state was reset",
                    "snapshot": snapshot() if snapshot else None,
                }))
            result.extend(deepcopy(event) for event in events if event["sequence"] > last_sequence)
            return ReplayBatch(result, self._terminal)

    def subscribe(
        self,
        last_sequence: int = 0,
        *,
        snapshot: Callable[[], dict] | None = None,
        wait_seconds: float = 15.0,
    ) -> Iterator[dict[str, Any] | None]:
        cursor = last_sequence
        first = True
        while True:
            heartbeat = False
            with self._condition:
                events = list(self._events)
                batch: list[dict[str, Any]] = []
                if first and events and cursor < events[0]["sequence"] - 1:
                    batch.append(redact({
                        "sequence": events[0]["sequence"] - 1,
                        "execution_id": self.execution_id,
                        "node_id": None,
                        "status": "reset",
                        "timestamp": now_iso(),
                        "summary": "Requested events are no longer retained; state was reset",
                        "snapshot": snapshot() if snapshot else None,
                    }))
                batch.extend(deepcopy(event) for event in events if event["sequence"] > cursor)
                terminal = self._terminal
                first = False
                if not batch and not terminal:
                    notified = self._condition.wait(timeout=wait_seconds)
                    if not notified:
                        heartbeat = True
            if heartbeat:
                yield None
                continue
            if not batch and not terminal:
                continue
            for event in batch:
                cursor = max(cursor, int(event["sequence"]))
                yield event
            if terminal and (not events or cursor >= events[-1]["sequence"]):
                return


class EventBroker:
    def __init__(self, *, max_events: int = 1000):
        self.max_events = max_events
        self._buffers: dict[str, ExecutionEventBuffer] = {}
        self._lock = threading.Lock()

    def create(self, execution_id: str) -> ExecutionEventBuffer:
        with self._lock:
            return self._buffers.setdefault(
                execution_id, ExecutionEventBuffer(execution_id, max_events=self.max_events)
            )

    def get(self, execution_id: str) -> ExecutionEventBuffer | None:
        with self._lock:
            return self._buffers.get(execution_id)


def sse_frame(event: dict[str, Any]) -> str:
    return f"id: {event['sequence']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"
