"""ChannelProfile store — atomic create/read/update/delete.

Persistence layout: ``output/channels/{channel_id}.json`` via
``safe_json_write`` / ``safe_json_read``. Soft-delete moves the primary file
(and its ``.bak``) into ``output/TRASH/channels/``, matching the workflow
store's trash discipline.

``version`` (content revision) starts at 1 on create and increments on every
successful update. ``schema_version`` is the document-format revision and is
advanced only by ``migrations.apply_migrations``.
"""

from __future__ import annotations

import os
import random
import shutil
import string
import threading
from copy import deepcopy
from typing import Any

from config import CHANNELS_DIR, TRASH_DIR
from scriptase.channels.migrations import SCHEMA_VERSION, apply_migrations
from scriptase.channels.models import (
    CHANNEL_ID_RE,
    ChannelProfile,
    parse_channel,
    parse_draft,
    validation_problems,
)
from scriptase.shared.io_utils import now_iso, safe_json_read, safe_json_write
from scriptase.shared.security import safe_join

from pydantic import ValidationError


class ChannelNotFound(FileNotFoundError):
    """Raised when a channel id does not resolve on disk."""

    def __init__(self, channel_id: str):
        super().__init__(channel_id)
        self.channel_id = channel_id


class ChannelConflict(RuntimeError):
    """Optimistic concurrency failure (expected_version mismatch)."""

    def __init__(self, channel_id: str):
        super().__init__(f"Channel version conflict: {channel_id}")
        self.channel_id = channel_id


class ChannelValidationError(ValueError):
    """Schema validation failed; ``problems`` carries structured details."""

    def __init__(self, problems: list[dict[str, Any]]):
        super().__init__("Channel document failed schema validation")
        self.problems = problems
        self.code = "CHANNEL_INVALID"


# Module-level roots so tests can rebind without patching config.
_channels_dir: str = CHANNELS_DIR
_trash_dir: str = os.path.join(TRASH_DIR, "channels")

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def _thread_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.Lock()
        return lock


def _path(channel_id: str) -> str:
    if not isinstance(channel_id, str) or not CHANNEL_ID_RE.fullmatch(channel_id):
        raise ValueError("channel_id must match ch_[A-Z0-9]{6}")
    return safe_join(_channels_dir, f"{channel_id}.json")


def _generate_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(200):
        candidate = "ch_" + "".join(random.SystemRandom().choices(alphabet, k=6))
        if not os.path.exists(_path(candidate)):
            return candidate
    raise RuntimeError("Could not allocate a channel id")


def _validate_document(data: dict[str, Any]) -> ChannelProfile:
    try:
        return parse_channel(data)
    except ValidationError as exc:
        raise ChannelValidationError(validation_problems(exc)) from exc


def _validate_draft(data: dict[str, Any]):
    try:
        return parse_draft(data)
    except ValidationError as exc:
        raise ChannelValidationError(validation_problems(exc)) from exc


def _write(document: ChannelProfile) -> ChannelProfile:
    os.makedirs(_channels_dir, exist_ok=True)
    path = _path(document.id)
    safe_json_write(path, document.to_document(), indent=2)
    return document


def _load_raw(channel_id: str) -> dict[str, Any]:
    path = _path(channel_id)
    try:
        return safe_json_read(path)
    except FileNotFoundError as exc:
        raise ChannelNotFound(channel_id) from exc


def create_channel(draft: dict[str, Any]) -> ChannelProfile:
    """Create a Channel from a draft. Assigns id, version=1, timestamps."""
    parsed = _validate_draft(draft)
    timestamp = now_iso()
    document = ChannelProfile(
        id=_generate_id(),
        name=parsed.name,
        version=1,
        schema_version=SCHEMA_VERSION,
        branding=parsed.branding,
        content=parsed.content,
        visual_direction=parsed.visual_direction,
        audio_defaults=parsed.audio_defaults,
        captions=parsed.captions,
        provider_defaults=parsed.provider_defaults,
        fallback_policies=parsed.fallback_policies,
        review_policy=parsed.review_policy,
        budget=parsed.budget,
        export_defaults=parsed.export_defaults,
        default_workflow_id=parsed.default_workflow_id,
        cadence=parsed.cadence,
        created_at=timestamp,
        updated_at=timestamp,
    )
    return _write(document)


def get_channel(channel_id: str) -> ChannelProfile:
    """Load, migrate, and validate a Channel. Raises ChannelNotFound."""
    raw = _load_raw(channel_id)
    migrated, changed = apply_migrations(raw)
    document = _validate_document(migrated)
    if changed:
        # Persist the schema stamp so the next load is a no-op. Content
        # ``version`` is left alone — migrations are format-only.
        _write(document)
    return document


def list_channels(*, limit: int = 200) -> list[ChannelProfile]:
    """Return channels newest-first (by updated_at, then id)."""
    os.makedirs(_channels_dir, exist_ok=True)
    items: list[ChannelProfile] = []
    for filename in os.listdir(_channels_dir):
        if not filename.endswith(".json") or filename.endswith(".json.bak"):
            continue
        channel_id = filename[:-5]
        if not CHANNEL_ID_RE.fullmatch(channel_id):
            continue
        try:
            items.append(get_channel(channel_id))
        except (ChannelNotFound, ChannelValidationError, ValueError, OSError):
            continue
    items.sort(
        key=lambda item: (item.updated_at or "", item.id),
        reverse=True,
    )
    return items[:limit]


def update_channel(
    channel_id: str,
    draft: dict[str, Any],
    *,
    expected_version: int | None = None,
) -> ChannelProfile:
    """Replace channel content and bump ``version``.

    When ``expected_version`` is provided it must equal the stored content
    version or ``ChannelConflict`` is raised (optimistic concurrency).
    """
    if not isinstance(channel_id, str) or not CHANNEL_ID_RE.fullmatch(channel_id):
        raise ValueError("channel_id must match ch_[A-Z0-9]{6}")

    lock = _thread_lock(channel_id)
    with lock:
        current = get_channel(channel_id)
        if expected_version is not None and current.version != expected_version:
            raise ChannelConflict(channel_id)

        parsed = _validate_draft(draft)
        timestamp = now_iso()
        # Content version is monotonic and independent of schema_version.
        next_version = current.version + 1
        document = ChannelProfile(
            id=current.id,
            name=parsed.name,
            version=next_version,
            schema_version=SCHEMA_VERSION,
            branding=parsed.branding,
            content=parsed.content,
            visual_direction=parsed.visual_direction,
            audio_defaults=parsed.audio_defaults,
            captions=parsed.captions,
            provider_defaults=parsed.provider_defaults,
            fallback_policies=parsed.fallback_policies,
            review_policy=parsed.review_policy,
            budget=parsed.budget,
            export_defaults=parsed.export_defaults,
            default_workflow_id=parsed.default_workflow_id,
            cadence=parsed.cadence,
            created_at=current.created_at,
            updated_at=timestamp,
        )
        return _write(document)


def delete_channel(
    channel_id: str,
    *,
    expected_version: int | None = None,
) -> None:
    """Soft-delete: move primary (and .bak) into TRASH/channels/."""
    if not isinstance(channel_id, str) or not CHANNEL_ID_RE.fullmatch(channel_id):
        raise ValueError("channel_id must match ch_[A-Z0-9]{6}")

    lock = _thread_lock(channel_id)
    with lock:
        path = _path(channel_id)
        if not os.path.isfile(path) and not os.path.isfile(path + ".bak"):
            raise ChannelNotFound(channel_id)

        if expected_version is not None:
            current = get_channel(channel_id)
            if current.version != expected_version:
                raise ChannelConflict(channel_id)

        os.makedirs(_trash_dir, exist_ok=True)
        stamp = now_iso().replace(":", "").replace("+", "_")
        dest = os.path.join(_trash_dir, f"{channel_id}_{stamp}.json")
        bak_src = path + ".bak"
        bak_dest = dest + ".bak"

        # Move .bak first so a mid-delete crash leaves the primary intact
        # (safe_json_read would otherwise resurrect from a half-trashed state).
        if os.path.isfile(bak_src):
            try:
                os.replace(bak_src, bak_dest)
            except OSError:
                shutil.move(bak_src, bak_dest)

        if os.path.isfile(path):
            try:
                os.replace(path, dest)
            except OSError:
                shutil.move(path, dest)


def channel_summary(document: ChannelProfile) -> dict[str, Any]:
    """Compact listing payload (no nested blocks)."""
    return {
        "id": document.id,
        "name": document.name,
        "version": document.version,
        "schema_version": document.schema_version,
        "niche": document.content.niche,
        "style": document.visual_direction.style,
        "default_workflow_id": document.default_workflow_id,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }


def default_draft(*, name: str = "New Channel") -> dict[str, Any]:
    """Minimal valid create payload for callers that need a blank channel."""
    return deepcopy({
        "name": name,
        "branding": {},
        "content": {},
        "visual_direction": {
            "pattern": [
                {"narrative_role": "hook", "shot": "extreme close-up"},
                {"narrative_role": "explanation", "shot": "medium cinematic"},
                {"narrative_role": "emotional_beat", "shot": "wide environmental"},
                {"narrative_role": "ending", "shot": "symbolic visual"},
            ],
        },
        "audio_defaults": {},
        "captions": {},
        "provider_defaults": {},
        "fallback_policies": {},
        "review_policy": {},
        "budget": {},
        "export_defaults": {},
        "default_workflow_id": None,
        "cadence": {},
    })


__all__ = [
    "ChannelNotFound",
    "ChannelConflict",
    "ChannelValidationError",
    "create_channel",
    "get_channel",
    "list_channels",
    "update_channel",
    "delete_channel",
    "channel_summary",
    "default_draft",
]
