"""Thread-safe, bounded workflow execution event streams."""

from __future__ import annotations

import json
import threading
from collections import OrderedDict, deque
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
    """Per-execution event buffers, LRU-capped so a long-lived process cannot
    accumulate one (up to `max_events`-deep) buffer per job run forever."""

    def __init__(self, *, max_events: int = 1000, max_buffers: int = 64):
        self.max_events = max_events
        self.max_buffers = max_buffers
        self._buffers: "OrderedDict[str, ExecutionEventBuffer]" = OrderedDict()
        self._lock = threading.Lock()

    def create(self, execution_id: str) -> ExecutionEventBuffer:
        with self._lock:
            buffer = self._buffers.get(execution_id)
            if buffer is None:
                buffer = ExecutionEventBuffer(execution_id, max_events=self.max_events)
                self._buffers[execution_id] = buffer
            self._buffers.move_to_end(execution_id)
            # Evict the oldest buffers beyond the cap — finished executions whose
            # SSE replay window has passed. The recent ones (any live stream) stay.
            while len(self._buffers) > self.max_buffers:
                self._buffers.popitem(last=False)
            return buffer

    def get(self, execution_id: str) -> ExecutionEventBuffer | None:
        with self._lock:
            buffer = self._buffers.get(execution_id)
            if buffer is not None:
                self._buffers.move_to_end(execution_id)
            return buffer

    def discard(self, execution_id: str) -> None:
        """Drop a finished execution's buffer once nothing needs its replay."""
        with self._lock:
            self._buffers.pop(execution_id, None)


def sse_frame(event: dict[str, Any]) -> str:
    return f"id: {event['sequence']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"
