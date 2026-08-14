"""Channel snapshot builder for Jobs.

The snapshot rule is absolute (contracts.md §6, product §4.3 / §21):

* Capture non-secret Channel configuration and provider **instance references**
  only.
* Secrets resolve from the provider instance at runtime and never enter a Job,
  an execution record, an export, or a log.

Implementation: copy an explicit allowlist of Channel fields, then run the
engine redactor as belt-and-suspenders. Sensitive keys never make the allowlist
and are scrubbed even if a future caller hands us a raw dict.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from scriptase.channels.models import ChannelProfile
from scriptase.engine.redaction import collect_secrets, is_sensitive_key, redact
from scriptase.shared.io_utils import now_iso

# Configuration blocks frozen onto the Job. Identity timestamps on the live
# Channel are not configuration and are omitted; ``snapshotted_at`` records
# when this freeze happened. Provider **instance ids** live under
# ``provider_defaults`` / ``fallback_policies`` / ``audio_defaults``.
_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "id",
    "name",
    "version",
    "branding",
    "content",
    "visual_direction",
    "audio_defaults",
    "captions",
    "provider_defaults",
    "fallback_policies",
    "review_policy",
    "budget",
    "export_defaults",
    "default_workflow_id",
)


def _as_mapping(channel: ChannelProfile | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(channel, ChannelProfile):
        return channel.to_document()
    if isinstance(channel, Mapping):
        return dict(channel)
    raise TypeError("channel must be a ChannelProfile or mapping")


def _strip_sensitive(value: Any) -> Any:
    """Drop sensitive-keyed entries before redaction so they never persist."""
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            if is_sensitive_key(key):
                continue
            cleaned[key] = _strip_sensitive(child)
        return cleaned
    if isinstance(value, list):
        return [_strip_sensitive(item) for item in value]
    return value


def build_channel_snapshot(
    channel: ChannelProfile | Mapping[str, Any],
    *,
    snapshotted_at: str | None = None,
) -> dict[str, Any]:
    """Build a Job-safe channel snapshot from a Channel document.

    Accepts a validated ``ChannelProfile`` (normal path) or a raw mapping
    (tests / migration repair). Only allowlisted configuration keys are kept;
    any sensitive-keyed entries are dropped, and the result is redacted so
    known secret *values* cannot leak through free-text fields either.
    """
    source = _as_mapping(channel)
    snapshot: dict[str, Any] = {}
    for key in _SNAPSHOT_FIELDS:
        if key not in source:
            continue
        if is_sensitive_key(key):
            continue
        snapshot[key] = _strip_sensitive(deepcopy(source[key]))

    snapshot["snapshotted_at"] = snapshotted_at or now_iso()

    # Defense in depth: redact known secret values and any residual sensitive keys.
    redacted = redact(snapshot)
    if not isinstance(redacted, dict):
        raise RuntimeError("channel snapshot redaction produced a non-object")
    return redacted


def assert_snapshot_has_no_credentials(snapshot: Mapping[str, Any]) -> None:
    """Raise ``ValueError`` if the snapshot still carries credential material.

    Used by the store as a final gate before write, and by tests.
    """
    if not isinstance(snapshot, Mapping):
        raise ValueError("channel_snapshot must be an object")

    # Explicit sensitive keys anywhere in the tree are forbidden (even redacted
    # placeholders should not have been written — we strip them earlier).
    def walk(node: Any, path: str = "") -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                key_path = f"{path}.{key}" if path else str(key)
                if is_sensitive_key(key):
                    raise ValueError(
                        f"channel_snapshot must not contain credential field "
                        f"{key_path!r}"
                    )
                walk(child, key_path)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}[{index}]")

    walk(snapshot)

    leaked = collect_secrets(snapshot)
    if leaked:
        raise ValueError(
            "channel_snapshot still carries secret values under sensitive keys"
        )


def snapshot_contains_credentials(snapshot: Mapping[str, Any]) -> bool:
    """Return True when a snapshot fails the no-credential gate."""
    try:
        assert_snapshot_has_no_credentials(snapshot)
    except ValueError:
        return True
    return False


__all__ = [
    "build_channel_snapshot",
    "assert_snapshot_has_no_credentials",
    "snapshot_contains_credentials",
]
