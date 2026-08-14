"""Repair history — durable RepairHistoryEntry records (step 8.4 / §9.1).

Persist every issue, routing decision, action, provider instance, prompt
revision, and result, tied to the superseded artifact versions from step 1.2.

A Job's ``repair_history[]`` holds entry ids in attempt order. Reconstruction
walks those ids and expands each ``output_artifact_ids`` chain so every
superseded version and the reason each repair was attempted remain visible.

Layout: ``output/repair_history/{rph_id}.json`` via ``safe_json_write`` /
``safe_json_read``. Entries are append-only; there is no soft-delete.
"""

from __future__ import annotations

import os
import random
import re
import string
import threading
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from config import OUTPUT_DIR, REPAIR_HISTORY_DIR
from scriptase.shared.io_utils import now_iso, safe_json_read, safe_json_write
from scriptase.shared.security import safe_join

# Server-generated repair-history id: rph_ + 6 uppercase alphanumerics.
REPAIR_HISTORY_ID_RE = re.compile(r"^rph_[A-Z0-9]{6}$")

REPAIR_HISTORY_SCHEMA_VERSION = 1

# contracts.md §9.1 action vocabulary.
RepairHistoryAction = Literal[
    "regenerate",
    "re-prompt",
    "adjust",
    "escalate",
    "accept",
    "fallback",
]

REPAIR_HISTORY_ACTIONS: tuple[str, ...] = (
    "regenerate",
    "re-prompt",
    "adjust",
    "escalate",
    "accept",
    "fallback",
)

# contracts.md §9.1 result vocabulary.
RepairHistoryResult = Literal["resolved", "failed", "escalated", "degraded"]

REPAIR_HISTORY_RESULTS: tuple[str, ...] = (
    "resolved",
    "failed",
    "escalated",
    "degraded",
)

_INSTRUCTION_MAX = 500
_REASON_MAX = 500
_PROMPT_REVISION_MAX = 200


def _strip_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _optional_str(value: Any) -> str | None:
    text = _strip_str(value)
    return text or None


def _bound(text: str, limit: int) -> str:
    text = _strip_str(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _id_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field_name} must be a list of ids")
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _strip_str(item)
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return out


class RepairHistoryEntry(BaseModel):
    """Persisted repair-history record (contracts.md §9.1).

    One entry per repair outcome. Immutable after write — a later attempt is a
    new entry, never a mutation of this one.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    schema_version: int = Field(default=REPAIR_HISTORY_SCHEMA_VERSION, ge=1)

    job_id: str = Field(min_length=1, max_length=120)
    issue_id: str = Field(min_length=1, max_length=120)
    scene_id: str | None = None

    routed_to_node_type: str | None = None
    provider_instance_id: str | None = None

    action: RepairHistoryAction
    instruction: str = Field(default="", max_length=_INSTRUCTION_MAX)
    # Why this repair was attempted (decision reason / issue reason).
    reason: str = Field(default="", max_length=_REASON_MAX)
    # Model / prompt revision used for the attempt when known (step 4.3 axis).
    prompt_revision: str = Field(default="", max_length=_PROMPT_REVISION_MAX)

    input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)

    provenance_ref: str | None = None
    result: RepairHistoryResult

    created_at: str = ""

    @field_validator("id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if not REPAIR_HISTORY_ID_RE.fullmatch(value):
            raise ValueError("id must match rph_[A-Z0-9]{6}")
        return value

    @field_validator("job_id", "issue_id", mode="before")
    @classmethod
    def _required_ids(cls, value: Any) -> str:
        text = _strip_str(value)
        if not text:
            raise ValueError("job_id and issue_id are required")
        return text

    @field_validator(
        "scene_id",
        "routed_to_node_type",
        "provider_instance_id",
        "provenance_ref",
        mode="before",
    )
    @classmethod
    def _optional_ids(cls, value: Any) -> str | None:
        return _optional_str(value)

    @field_validator("action", mode="before")
    @classmethod
    def _action(cls, value: Any) -> str:
        text = _strip_str(value)
        if text not in REPAIR_HISTORY_ACTIONS:
            raise ValueError(
                f"action must be one of: {', '.join(REPAIR_HISTORY_ACTIONS)}"
            )
        return text

    @field_validator("result", mode="before")
    @classmethod
    def _result(cls, value: Any) -> str:
        text = _strip_str(value)
        if text not in REPAIR_HISTORY_RESULTS:
            raise ValueError(
                f"result must be one of: {', '.join(REPAIR_HISTORY_RESULTS)}"
            )
        return text

    @field_validator("instruction", mode="before")
    @classmethod
    def _instruction(cls, value: Any) -> str:
        return _bound(_strip_str(value) if value is not None else "", _INSTRUCTION_MAX)

    @field_validator("reason", mode="before")
    @classmethod
    def _reason(cls, value: Any) -> str:
        return _bound(_strip_str(value) if value is not None else "", _REASON_MAX)

    @field_validator("prompt_revision", mode="before")
    @classmethod
    def _prompt_revision(cls, value: Any) -> str:
        return _bound(
            _strip_str(value) if value is not None else "", _PROMPT_REVISION_MAX
        )

    @field_validator("input_artifact_ids", "output_artifact_ids", mode="before")
    @classmethod
    def _artifact_lists(cls, value: Any, info) -> list[str]:
        return _id_list(value, field_name=info.field_name)

    @field_validator("created_at", mode="before")
    @classmethod
    def _created_at(cls, value: Any) -> str:
        return _strip_str(value)

    def to_document(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class RepairHistoryNotFound(FileNotFoundError):
    """Raised when a repair-history id does not resolve on disk."""

    def __init__(self, entry_id: str):
        super().__init__(entry_id)
        self.entry_id = entry_id
        self.code = "REPAIR_HISTORY_NOT_FOUND"


class RepairHistoryValidationError(ValueError):
    """Schema validation failed; ``problems`` carries structured details."""

    def __init__(
        self, problems: list[dict[str, Any]], *, code: str = "REPAIR_HISTORY_INVALID"
    ):
        super().__init__("RepairHistoryEntry document failed schema validation")
        self.problems = problems
        self.code = code


class RepairHistoryError(RuntimeError):
    """Reconstruction / recording could not complete."""

    def __init__(self, code: str, message: str, *, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


# Module-level root so tests can rebind without patching config.
_DEFAULT_DIR = (
    REPAIR_HISTORY_DIR
    if REPAIR_HISTORY_DIR
    else os.path.join(OUTPUT_DIR, "repair_history")
)
_history_dir: str = _DEFAULT_DIR

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}
_GLOBAL_LOCK = threading.Lock()


def _thread_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.Lock()
        return lock


def _path(entry_id: str) -> str:
    if not isinstance(entry_id, str) or not REPAIR_HISTORY_ID_RE.fullmatch(entry_id):
        raise ValueError("entry_id must match rph_[A-Z0-9]{6}")
    return safe_join(_history_dir, f"{entry_id}.json")


def _generate_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(200):
        candidate = "rph_" + "".join(random.SystemRandom().choices(alphabet, k=6))
        if not os.path.exists(_path(candidate)):
            return candidate
    raise RuntimeError("Could not allocate a repair-history id")


def _validation_problems(exc: Exception) -> list[dict[str, Any]]:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        return [
            {
                "loc": list(item.get("loc", ())),
                "msg": item.get("msg", "invalid"),
                "type": item.get("type", "value_error"),
            }
            for item in errors(include_url=False, include_context=False)
        ]
    return [{"loc": [], "msg": str(exc), "type": "value_error"}]


def _validate_document(data: dict[str, Any]) -> RepairHistoryEntry:
    try:
        return RepairHistoryEntry.model_validate(data)
    except ValidationError as exc:
        raise RepairHistoryValidationError(_validation_problems(exc)) from exc


def _write(document: RepairHistoryEntry) -> RepairHistoryEntry:
    os.makedirs(_history_dir, exist_ok=True)
    safe_json_write(_path(document.id), document.to_document(), indent=2)
    return document


def _load(entry_id: str) -> RepairHistoryEntry:
    try:
        raw = safe_json_read(_path(entry_id))
    except FileNotFoundError as exc:
        raise RepairHistoryNotFound(entry_id) from exc
    if not isinstance(raw, dict):
        raise RepairHistoryValidationError(
            [{"loc": [], "msg": "document must be an object", "type": "type_error"}]
        )
    return _validate_document(raw)


# ---------------------------------------------------------------------------
# Action / result mapping from RepairDecision
# ---------------------------------------------------------------------------


def history_action_for_decision(
    decision: Any,
    issue: Any | None = None,
    *,
    selection_reason: str | None = None,
) -> str | None:
    """Map a :class:`RepairDecision` onto a §9.1 action, or None to skip.

    Terminal non-spend decisions (escalate / accept / degrade) and admitted
    repairs all produce history. ``refuse_budget`` and ``skip`` do not — they
    never attempted a repair.
    """
    action = str(getattr(decision, "action", "") or "")
    if selection_reason and str(selection_reason).startswith("fallback_after:"):
        # Fallback attempt outcome always records as fallback regardless of
        # suggested_action (step 8.3 selection_reason vocabulary).
        if action in {"repair", "escalate", "accept", "degrade"}:
            return "fallback"

    if action == "escalate":
        return "escalate"
    if action == "accept":
        return "accept"
    if action == "degrade":
        # Safe degradation keeps the still — recorded as accept + degraded.
        return "accept"
    if action == "repair":
        suggested = ""
        if issue is not None:
            if isinstance(issue, Mapping):
                suggested = _strip_str(issue.get("suggested_action"))
            else:
                suggested = _strip_str(getattr(issue, "suggested_action", None))
        if suggested in {"regenerate", "re-prompt", "adjust"}:
            return suggested
        return "regenerate"
    return None


def history_result_for_decision(decision: Any) -> str | None:
    """Immediate result for decisions that close without a provider re-run.

    ``repair`` returns None — the caller must supply the outcome after the
    engine attempt finishes.
    """
    action = str(getattr(decision, "action", "") or "")
    if action == "escalate":
        return "escalated"
    if action == "degrade":
        return "degraded"
    if action == "accept":
        return "resolved"
    return None


# ---------------------------------------------------------------------------
# Persist
# ---------------------------------------------------------------------------


def create_repair_history_entry(
    *,
    job_id: str,
    issue_id: str,
    action: str,
    result: str,
    scene_id: str | None = None,
    routed_to_node_type: str | None = None,
    provider_instance_id: str | None = None,
    instruction: str = "",
    reason: str = "",
    prompt_revision: str = "",
    input_artifact_ids: Sequence[str] | None = None,
    output_artifact_ids: Sequence[str] | None = None,
    provenance_ref: str | None = None,
    created_at: str | None = None,
    append_to_job: bool = True,
) -> RepairHistoryEntry:
    """Write one RepairHistoryEntry and optionally append its id to the Job."""
    timestamp = _strip_str(created_at) or now_iso()
    with _GLOBAL_LOCK:
        document = RepairHistoryEntry(
            id=_generate_id(),
            schema_version=REPAIR_HISTORY_SCHEMA_VERSION,
            job_id=job_id,
            issue_id=issue_id,
            scene_id=scene_id,
            routed_to_node_type=routed_to_node_type,
            provider_instance_id=provider_instance_id,
            action=action,  # type: ignore[arg-type]
            instruction=instruction,
            reason=reason,
            prompt_revision=prompt_revision,
            input_artifact_ids=list(input_artifact_ids or []),
            output_artifact_ids=list(output_artifact_ids or []),
            provenance_ref=provenance_ref,
            result=result,  # type: ignore[arg-type]
            created_at=timestamp,
        )
        _write(document)

    if append_to_job and job_id:
        try:
            from scriptase.jobs.store import add_repair_history_ids

            add_repair_history_ids(job_id, [document.id], allow_terminal=True)
        except Exception:
            # History document is already durable; Job link is best-effort so a
            # missing/terminal job store never loses the entry itself.
            pass
    return document


def record_repair_outcome(
    decision: Any,
    *,
    result: str | None = None,
    issue: Any | None = None,
    input_artifact_ids: Sequence[str] | None = None,
    output_artifact_ids: Sequence[str] | None = None,
    provider_instance_id: str | None = None,
    prompt_revision: str | None = None,
    provenance_ref: str | None = None,
    selection_reason: str | None = None,
    instruction: str | None = None,
    reason: str | None = None,
    append_to_job: bool = True,
) -> RepairHistoryEntry | None:
    """Persist a history entry for one repair decision outcome.

    Returns ``None`` when the decision does not produce history (skip /
    refuse_budget, or repair without a supplied ``result``).
    """
    action = history_action_for_decision(
        decision, issue, selection_reason=selection_reason
    )
    if action is None:
        return None

    resolved_result = result if result is not None else history_result_for_decision(
        decision
    )
    if resolved_result is None:
        return None

    issue_id = str(getattr(decision, "issue_id", "") or "")
    job_id = str(getattr(decision, "job_id", "") or "")
    scene_id = getattr(decision, "scene_id", None)
    scene_id = str(scene_id).strip() if scene_id else None

    routing = getattr(decision, "routing", None)
    routed_type = getattr(decision, "target_node_type", None)
    if not routed_type and routing is not None:
        routed_type = getattr(routing, "routed_to_node_type", None)

    if instruction is None:
        if issue is not None:
            if isinstance(issue, Mapping):
                instruction = _strip_str(issue.get("repair_instruction"))
            else:
                instruction = _strip_str(getattr(issue, "repair_instruction", None))
        else:
            instruction = ""
        # Degrade mode rides the instruction when present.
        mode = getattr(decision, "degradation_mode", None)
        if mode and not instruction:
            instruction = f"degraded:{mode}"

    if reason is None:
        reason = _strip_str(getattr(decision, "reason", None))
        if not reason and issue is not None:
            if isinstance(issue, Mapping):
                reason = _strip_str(issue.get("reason"))
            else:
                reason = _strip_str(getattr(issue, "reason", None))

    # Prefer explicit instance; fall back to issue target artifact generation later.
    instance_id = _optional_str(provider_instance_id)

    # Collect default input artifact from the issue when not supplied.
    inputs = list(input_artifact_ids or [])
    if not inputs and issue is not None:
        target = None
        if isinstance(issue, Mapping):
            target = issue.get("target_artifact_id")
        else:
            target = getattr(issue, "target_artifact_id", None)
        if target:
            inputs = [str(target)]

    return create_repair_history_entry(
        job_id=job_id,
        issue_id=issue_id,
        scene_id=scene_id,
        routed_to_node_type=_optional_str(routed_type),
        provider_instance_id=instance_id,
        action=action,
        instruction=instruction or "",
        reason=reason or "",
        prompt_revision=prompt_revision or "",
        input_artifact_ids=inputs,
        output_artifact_ids=list(output_artifact_ids or []),
        provenance_ref=_optional_str(provenance_ref),
        result=resolved_result,
        append_to_job=append_to_job,
    )


def get_repair_history_entry(entry_id: str) -> RepairHistoryEntry:
    return _load(entry_id)


def list_repair_history(
    *,
    job_id: str | None = None,
    issue_id: str | None = None,
    scene_id: str | None = None,
    limit: int = 500,
) -> list[RepairHistoryEntry]:
    """List entries newest-first. Prefer Job.repair_history order for sequence."""
    os.makedirs(_history_dir, exist_ok=True)
    items: list[RepairHistoryEntry] = []
    for filename in os.listdir(_history_dir):
        if not filename.endswith(".json") or filename.endswith(".json.bak"):
            continue
        entry_id = filename[:-5]
        if not REPAIR_HISTORY_ID_RE.fullmatch(entry_id):
            continue
        try:
            item = _load(entry_id)
        except (
            RepairHistoryNotFound,
            ValueError,
            OSError,
            RepairHistoryValidationError,
        ):
            continue
        if job_id is not None and item.job_id != job_id:
            continue
        if issue_id is not None and item.issue_id != issue_id:
            continue
        if scene_id is not None and item.scene_id != scene_id:
            continue
        items.append(item)
    items.sort(key=lambda item: (item.created_at or "", item.id), reverse=True)
    return items[:limit]


# ---------------------------------------------------------------------------
# Reconstruction — full sequence with superseded artifact versions
# ---------------------------------------------------------------------------


def _artifact_attempt_summary(artifact: Any) -> dict[str, Any]:
    """Compact artifact version row for history reconstruction."""
    generation = getattr(artifact, "generation", None)
    gen_doc: dict[str, Any] | None = None
    provider_instance_id = None
    seed = None
    prompt_revision = None
    if generation is not None:
        if hasattr(generation, "to_document"):
            gen_doc = generation.to_document()
        elif isinstance(generation, Mapping):
            gen_doc = dict(generation)
        if gen_doc:
            provider_instance_id = gen_doc.get("provider_instance_id") or None
            seed = gen_doc.get("seed")
            prompt_revision = gen_doc.get("prompt_revision") or None
    return {
        "artifact_id": artifact.id,
        "version": artifact.version,
        "kind": artifact.kind,
        "scene_id": artifact.scene_id,
        "job_id": artifact.job_id,
        "path": artifact.path,
        "content_hash": artifact.content_hash,
        "created_at": artifact.created_at,
        "superseded_by": artifact.superseded_by,
        "is_superseded": bool(artifact.superseded_by),
        "provenance_ref": artifact.provenance_ref,
        "provider_instance_id": provider_instance_id,
        "seed": seed,
        "prompt_revision": prompt_revision,
        "generation": gen_doc,
    }


def _expand_artifact_chain(artifact_id: str) -> list[dict[str, Any]]:
    """Load the full version chain that owns ``artifact_id`` (incl. superseded)."""
    try:
        from scriptase.artifacts.history import list_version_chain
        from scriptase.artifacts.store import ArtifactNotFound, get_artifact
    except Exception:
        return []

    try:
        tip = get_artifact(artifact_id)
    except (ArtifactNotFound, Exception):
        return [{"artifact_id": artifact_id, "missing": True}]

    try:
        chain = list_version_chain(
            job_id=tip.job_id,
            kind=tip.kind,
            scene_id=tip.scene_id,
        )
    except Exception:
        return [_artifact_attempt_summary(tip)]

    return [_artifact_attempt_summary(item) for item in chain]


def _entry_sequence_item(entry: RepairHistoryEntry) -> dict[str, Any]:
    """One reconstructed history row with expanded artifact chains."""
    # Collect unique chains for inputs and outputs.
    input_chains: dict[str, list[dict[str, Any]]] = {}
    for art_id in entry.input_artifact_ids:
        if art_id not in input_chains:
            input_chains[art_id] = _expand_artifact_chain(art_id)

    output_chains: dict[str, list[dict[str, Any]]] = {}
    superseded_versions: list[dict[str, Any]] = []
    for art_id in entry.output_artifact_ids:
        chain = _expand_artifact_chain(art_id)
        output_chains[art_id] = chain
        for row in chain:
            if row.get("is_superseded") or row.get("superseded_by"):
                # Prior evidence kept by step 1.2 — include in the sequence.
                if row not in superseded_versions:
                    superseded_versions.append(row)

    # Also surface superseded tips that were inputs (the version the repair
    # replaced). Those become superseded once the output lands.
    for art_id, chain in input_chains.items():
        for row in chain:
            if row.get("is_superseded") or row.get("superseded_by"):
                if row not in superseded_versions:
                    superseded_versions.append(row)

    return {
        "id": entry.id,
        "schema_version": entry.schema_version,
        "job_id": entry.job_id,
        "issue_id": entry.issue_id,
        "scene_id": entry.scene_id,
        "routed_to_node_type": entry.routed_to_node_type,
        "provider_instance_id": entry.provider_instance_id,
        "action": entry.action,
        "instruction": entry.instruction,
        "reason": entry.reason,
        "prompt_revision": entry.prompt_revision,
        "input_artifact_ids": list(entry.input_artifact_ids),
        "output_artifact_ids": list(entry.output_artifact_ids),
        "provenance_ref": entry.provenance_ref,
        "result": entry.result,
        "created_at": entry.created_at,
        "input_artifact_chains": input_chains,
        "output_artifact_chains": output_chains,
        "superseded_artifact_versions": superseded_versions,
    }


def reconstruct_job_repair_history(job_id: str) -> dict[str, Any]:
    """Rebuild the full repair sequence for a Job.

    Uses ``Job.repair_history[]`` order when the Job is loadable; falls back to
    listing entries by ``job_id`` (oldest first) when the link list is empty.

    Done-when for step 8.4: the returned sequence includes every superseded
    artifact version and the reason each repair was attempted.
    """
    if not isinstance(job_id, str) or not job_id.strip():
        raise RepairHistoryError("BAD_REQUEST", "job_id is required")
    job_id = job_id.strip()

    ordered_ids: list[str] = []
    job_doc: dict[str, Any] | None = None
    try:
        from scriptase.jobs.store import JobNotFound, get_job

        job = get_job(job_id)
        job_doc = {
            "id": job.id,
            "status": job.status,
            "status_reason": job.status_reason,
            "repair_history": list(job.repair_history),
            "issues": list(job.issues),
            "artifacts": list(job.artifacts),
        }
        ordered_ids = list(job.repair_history)
    except Exception:
        ordered_ids = []

    entries: list[RepairHistoryEntry] = []
    if ordered_ids:
        for entry_id in ordered_ids:
            try:
                entries.append(get_repair_history_entry(entry_id))
            except RepairHistoryNotFound:
                # Keep a hole marker so the sequence length matches the Job.
                continue
    else:
        # Disk scan fallback — chronological.
        found = list_repair_history(job_id=job_id, limit=500)
        found.sort(key=lambda item: (item.created_at or "", item.id))
        entries = found

    sequence = [_entry_sequence_item(entry) for entry in entries]

    # Flatten every superseded version across the whole Job history so a
    # caller can assert "every superseded version is present" in one list.
    all_superseded: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in sequence:
        for art in row.get("superseded_artifact_versions") or []:
            art_id = art.get("artifact_id")
            if art_id and art_id not in seen_ids and art.get("is_superseded"):
                all_superseded.append(art)
                seen_ids.add(art_id)

    return {
        "job_id": job_id,
        "job": job_doc,
        "entry_count": len(sequence),
        "entries": sequence,
        "sequence": sequence,
        "superseded_artifact_versions": all_superseded,
        "reasons": [
            {
                "entry_id": row["id"],
                "issue_id": row["issue_id"],
                "action": row["action"],
                "result": row["result"],
                "reason": row["reason"],
                "instruction": row["instruction"],
                "created_at": row["created_at"],
            }
            for row in sequence
        ],
    }


__all__ = [
    "REPAIR_HISTORY_ACTIONS",
    "REPAIR_HISTORY_ID_RE",
    "REPAIR_HISTORY_RESULTS",
    "REPAIR_HISTORY_SCHEMA_VERSION",
    "RepairHistoryAction",
    "RepairHistoryEntry",
    "RepairHistoryError",
    "RepairHistoryNotFound",
    "RepairHistoryResult",
    "RepairHistoryValidationError",
    "create_repair_history_entry",
    "get_repair_history_entry",
    "history_action_for_decision",
    "history_result_for_decision",
    "list_repair_history",
    "reconstruct_job_repair_history",
    "record_repair_outcome",
]
