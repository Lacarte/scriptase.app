"""Cron-style workflow triggers with latest-only startup catch-up.

Schedules live in ``workflow.settings.schedules``.  Runtime cursors are kept
separately so a scheduler tick never changes a workflow's optimistic locking
token or makes an editor tab stale.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Mapping

from config import OUTPUT_DIR
from scriptase.shared.io_utils import safe_json_read, safe_json_write
from scriptase.shared.security import safe_join

from .execution import execution_manager
from .persistence import list_workflows, load_workflow


SCHEDULE_STATE_DIR = os.path.join(OUTPUT_DIR, "workflows", "schedule-state")


class CronExpressionError(ValueError):
    pass


def _field(text: str, minimum: int, maximum: int, *, sunday: bool = False) -> tuple[set[int], bool]:
    if not isinstance(text, str) or not text:
        raise CronExpressionError("Cron fields cannot be empty")
    values: set[int] = set()
    wildcard = text == "*"
    for part in text.split(","):
        base, slash, raw_step = part.partition("/")
        try:
            step = int(raw_step) if slash else 1
        except ValueError as exc:
            raise CronExpressionError("Cron step must be an integer") from exc
        if step < 1:
            raise CronExpressionError("Cron step must be positive")
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            raw_start, raw_end = base.split("-", 1)
            try:
                start, end = int(raw_start), int(raw_end)
            except ValueError as exc:
                raise CronExpressionError("Cron range must contain integers") from exc
        else:
            try:
                start = end = int(base)
            except ValueError as exc:
                raise CronExpressionError("Cron value must be an integer") from exc
        if start < minimum or end > maximum or start > end:
            raise CronExpressionError(f"Cron value must be between {minimum} and {maximum}")
        values.update(range(start, end + 1, step))
    if sunday and 7 in values:
        values.remove(7)
        values.add(0)
    return values, wildcard


class CronExpression:
    """A dependency-free standard five-field cron expression (UTC)."""

    def __init__(self, expression: str):
        parts = expression.split() if isinstance(expression, str) else []
        if len(parts) != 5:
            raise CronExpressionError("Cron expression must have five fields")
        self.expression = expression
        self.minutes, _ = _field(parts[0], 0, 59)
        self.hours, _ = _field(parts[1], 0, 23)
        self.days, self.day_wildcard = _field(parts[2], 1, 31)
        self.months, _ = _field(parts[3], 1, 12)
        self.weekdays, self.weekday_wildcard = _field(parts[4], 0, 7, sunday=True)

    def matches(self, moment: datetime) -> bool:
        moment = _utc(moment)
        # Python Monday=0; cron Sunday=0.
        weekday = (moment.weekday() + 1) % 7
        day_match = moment.day in self.days
        weekday_match = weekday in self.weekdays
        if self.day_wildcard:
            calendar_match = weekday_match
        elif self.weekday_wildcard:
            calendar_match = day_match
        else:
            calendar_match = day_match or weekday_match
        return (
            moment.minute in self.minutes
            and moment.hour in self.hours
            and moment.month in self.months
            and calendar_match
        )

    def next_after(self, moment: datetime) -> datetime:
        candidate = _utc(moment).replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = candidate + timedelta(days=366 * 6)
        while candidate <= limit:
            if self.matches(candidate):
                return candidate
            candidate += timedelta(minutes=1)
        raise CronExpressionError("Cron expression has no fire time in the next six years")

    def latest_between(self, start: datetime, end: datetime) -> datetime | None:
        """Return only the latest fire in ``(start, end]`` (catch-up policy)."""
        start, end = _utc(start), _utc(end)
        if end <= start:
            return None
        candidate = end.replace(second=0, microsecond=0)
        floor = start.replace(second=0, microsecond=0)
        while candidate >= floor:
            if candidate > start and self.matches(candidate):
                return candidate
            candidate -= timedelta(minutes=1)
        return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def schedule_details(workflow: Mapping, *, now: datetime | None = None) -> list[dict]:
    now = _utc(now or datetime.now(timezone.utc))
    details = []
    for item in (workflow.get("settings") or {}).get("schedules", []):
        row = dict(item)
        row["timezone"] = "UTC"
        row["next_fire_at"] = _iso(CronExpression(item["cron"]).next_after(now)) if item["enabled"] else None
        details.append(row)
    return details


class ScheduleService:
    def __init__(
        self,
        *,
        state_root: str = SCHEDULE_STATE_DIR,
        workflow_loader: Callable[[], Iterable[Mapping]] | None = None,
        enqueue: Callable[[Mapping], object] | None = None,
        clock: Callable[[], datetime] | None = None,
        poll_seconds: float = 15.0,
    ):
        self.state_root = state_root
        self.workflow_loader = workflow_loader or self._load_workflows
        self.enqueue = enqueue or self._enqueue
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _load_workflows() -> list[dict]:
        summaries, _ = list_workflows(limit=10000)
        return [load_workflow(item["workflow_id"]) for item in summaries]

    @staticmethod
    def _enqueue(workflow: Mapping):
        return execution_manager.start(
            workflow, run_mode="full", target_node_ids=[], source="schedule"
        )

    def _state_path(self, workflow_id: str) -> str:
        return safe_join(self.state_root, f"{workflow_id}.json")

    def _read_state(self, workflow_id: str) -> dict:
        try:
            value = safe_json_read(self._state_path(workflow_id))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, OSError, ValueError):
            return {}

    def tick(self, now: datetime | None = None) -> list[dict]:
        """Evaluate every schedule once and return the runs that were enqueued."""
        now = _utc(now or self.clock())
        enqueued = []
        for workflow in self.workflow_loader():
            workflow_id = workflow["workflow_id"]
            state = self._read_state(workflow_id)
            schedule_state = state.get("schedules") if isinstance(state.get("schedules"), dict) else {}
            active_ids = set()
            for schedule in (workflow.get("settings") or {}).get("schedules", []):
                schedule_id = schedule["id"]
                active_ids.add(schedule_id)
                cursor = schedule_state.get(schedule_id) or {}
                last_checked = cursor.get("last_checked_at")
                due = None
                if schedule.get("enabled") and last_checked:
                    try:
                        due = CronExpression(schedule["cron"]).latest_between(_parse_time(last_checked), now)
                    except (ValueError, CronExpressionError):
                        due = None
                # Advance the cursor before enqueueing. A process crash can lose
                # one run, but can never duplicate a scheduled fire on restart.
                next_cursor = {"last_checked_at": _iso(now)}
                if due:
                    next_cursor["last_fire_at"] = _iso(due)
                elif cursor.get("last_fire_at"):
                    next_cursor["last_fire_at"] = cursor["last_fire_at"]
                schedule_state[schedule_id] = next_cursor
                os.makedirs(self.state_root, exist_ok=True)
                safe_json_write(self._state_path(workflow_id), {
                    "workflow_id": workflow_id,
                    "schedules": {key: value for key, value in schedule_state.items() if key in active_ids},
                }, indent=2)
                if due:
                    result = self.enqueue(workflow)
                    enqueued.append({
                        "workflow_id": workflow_id,
                        "schedule_id": schedule_id,
                        "fire_at": _iso(due),
                        "result": result,
                    })
            if not active_ids and state:
                safe_json_write(self._state_path(workflow_id), {
                    "workflow_id": workflow_id, "schedules": {}
                }, indent=2)
        return enqueued

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="workflow-schedules", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(1.0, self.poll_seconds + 0.5))

    def _run(self) -> None:
        # The first tick establishes cursors for new schedules and catches up
        # persisted cursors from the previous app session.
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                # A malformed/corrupt individual workflow must not kill the
                # app-wide trigger thread; validation and API calls report it.
                pass
            self._stop.wait(self.poll_seconds)


schedule_service = ScheduleService()

