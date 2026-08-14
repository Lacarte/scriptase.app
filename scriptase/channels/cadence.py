"""Channel content cadence — cron-driven Job creation (step 9.2).

Mirrors ``scriptase.engine.scheduled_runs.ScheduleService`` cursor policy:
advance the cursor **before** enqueue so a crash can lose one fire but never
duplicate on restart. State lives under ``output/channels/cadence-state/`` so
ticks never bump the Channel content version or make an editor tab stale.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from loguru import logger

from config import OUTPUT_DIR
from scriptase.channels.models import ChannelProfile
from scriptase.channels.store import list_channels
from scriptase.engine.scheduled_runs import (
    CronExpression,
    CronExpressionError,
    _iso,
    _parse_time,
    _utc,
)
from scriptase.providers.validation import sanitize_message
from scriptase.shared.io_utils import safe_json_read, safe_json_write
from scriptase.shared.security import safe_join

CADENCE_STATE_DIR = os.path.join(OUTPUT_DIR, "channels", "cadence-state")


class ChannelCadenceService:
    """Poll enabled Channel cadences and create schedule-sourced Jobs."""

    def __init__(
        self,
        *,
        state_root: str = CADENCE_STATE_DIR,
        channel_loader: Callable[[], Iterable[ChannelProfile | Mapping[str, Any]]] | None = None,
        enqueue: Callable[[ChannelProfile | Mapping[str, Any]], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        poll_seconds: float = 15.0,
    ):
        self.state_root = state_root
        self.channel_loader = channel_loader or self._load_channels
        self.enqueue = enqueue or self._enqueue
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _load_channels() -> list[ChannelProfile]:
        return list_channels(limit=10000)

    @staticmethod
    def _enqueue(channel: ChannelProfile | Mapping[str, Any]) -> Any:
        from scriptase.jobs.triggers import create_job_from_channel_cadence

        return create_job_from_channel_cadence(channel)

    def _state_path(self, channel_id: str) -> str:
        return safe_join(self.state_root, f"{channel_id}.json")

    def _read_state(self, channel_id: str) -> dict:
        try:
            value = safe_json_read(self._state_path(channel_id))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, OSError, ValueError):
            return {}

    @staticmethod
    def _cadence_block(channel: ChannelProfile | Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(channel, ChannelProfile):
            return channel.cadence.model_dump(mode="json") if channel.cadence else {}
        raw = channel.get("cadence") if isinstance(channel, Mapping) else None
        return dict(raw) if isinstance(raw, Mapping) else {}

    @staticmethod
    def _channel_id(channel: ChannelProfile | Mapping[str, Any]) -> str:
        if isinstance(channel, ChannelProfile):
            return channel.id
        return str(channel.get("id") or "")

    def tick(self, now: datetime | None = None) -> list[dict]:
        """Evaluate every Channel cadence once; return enqueued fires."""
        now = _utc(now or self.clock())
        enqueued: list[dict] = []
        for channel in self.channel_loader():
            channel_id = self._channel_id(channel)
            if not channel_id:
                continue
            cadence = self._cadence_block(channel)
            state = self._read_state(channel_id)
            last_checked = state.get("last_checked_at")
            due = None
            enabled = bool(cadence.get("enabled"))
            cron = cadence.get("cron") or ""
            if enabled and last_checked and cron:
                try:
                    due = CronExpression(str(cron)).latest_between(
                        _parse_time(str(last_checked)), now
                    )
                except (ValueError, CronExpressionError):
                    due = None
            # Advance cursor before enqueue (same crash policy as workflow schedules).
            next_state: dict[str, Any] = {
                "channel_id": channel_id,
                "last_checked_at": _iso(now),
            }
            if due:
                next_state["last_fire_at"] = _iso(due)
            elif state.get("last_fire_at"):
                next_state["last_fire_at"] = state["last_fire_at"]
            os.makedirs(self.state_root, exist_ok=True)
            safe_json_write(self._state_path(channel_id), next_state, indent=2)
            if not due:
                continue
            try:
                result = self.enqueue(channel)
            except Exception as exc:
                # Malformed channel / missing workflow must not kill the loop;
                # cursor already advanced so we do not hammer a broken channel.
                # Log so the lost fire is not silent (step 10.4).
                logger.exception(
                    "[channel-cadence] enqueue failed for channel {}: {}",
                    channel_id,
                    sanitize_message(exc),
                )
                continue
            enqueued.append({
                "channel_id": channel_id,
                "fire_at": _iso(due),
                "result": result,
            })
        return enqueued

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="channel-cadence", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(1.0, self.poll_seconds + 0.5))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                # A single bad channel or store fault must not kill the
                # app-wide cadence thread; log so the failure is not silent
                # (step 10.4).
                logger.exception(
                    "[channel-cadence] tick failed: {}",
                    sanitize_message(exc),
                )
            self._stop.wait(self.poll_seconds)

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())


channel_cadence_service = ChannelCadenceService()


__all__ = [
    "CADENCE_STATE_DIR",
    "ChannelCadenceService",
    "channel_cadence_service",
]
