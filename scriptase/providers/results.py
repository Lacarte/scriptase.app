"""The provider result envelope and the egress validator — step 11.4.

Implements contracts.md §31 (`ProviderResult`, `UnitResult`, provenance, partial
results) and the mechanical half of §36: `validate_egress()` rejects absolute
paths, sensitive keys, `bytes`, non-JSON types, and oversized fields *at the
boundary*, so no raw provider exception, credential, arbitrary filesystem path,
or provider-specific response can reach a workflow record or an API response.

One envelope serves all five domains; only `payload` varies by domain.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from loguru import logger

from config import OUTPUT_DIR
from scriptase.providers.errors import (
    PROVIDER_ARTIFACT_UNMANAGED,
    PROVIDER_RESULT_INVALID,
    ProviderError,
    ProviderErrorPayload,
)
from scriptase.providers.validation import sanitize_message


RESULT_VERSION = 1

SUCCEEDED = "succeeded"
PARTIAL = "partial"
FAILED = "failed"
ENVELOPE_STATES = frozenset({SUCCEEDED, PARTIAL, FAILED})

UNIT_SUCCEEDED = "succeeded"
UNIT_FAILED = "failed"
UNIT_SKIPPED = "skipped"
UNIT_CANCELLED = "cancelled"
UNIT_STATES = frozenset({UNIT_SUCCEEDED, UNIT_FAILED, UNIT_SKIPPED, UNIT_CANCELLED})

# §31.1 caps.
METADATA_MAX_KEYS = 40
METADATA_STRING_MAX = 500
WARNINGS_MAX = 50
WARNING_MESSAGE_MAX = 200

# A result field may not carry an absolute or UNC path (§31.2). POSIX absolute,
# drive-letter, and UNC forms all count, on every platform: the check must not
# depend on which OS produced the string.
_ABSOLUTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|//[^/]|/(?!/))")


# -- artifact references (contracts.md §30.2) -------------------------------


def _managed_root(output_dir: str | None) -> str:
    """The managed root, read at call time so a test can relocate OUTPUT_DIR."""
    return os.path.abspath(output_dir or OUTPUT_DIR)


def normalize_ref(path: str, *, output_dir: str | None = None) -> str:
    """An absolute path becomes the relative POSIX ref that leaves a provider.

    The same rule `adapters.common.artifact_ref` applies, raised as a
    `ProviderError` rather than an `AdapterError` so the provider layer does not
    import the workflow layer.
    """
    absolute = os.path.abspath(path)
    root = _managed_root(output_dir)
    try:
        if os.path.commonpath([root, absolute]) != root:
            raise ValueError
    except ValueError as exc:
        raise ProviderError(
            PROVIDER_ARTIFACT_UNMANAGED,
            "Artifact is outside the managed output directory",
        ) from exc
    return os.path.relpath(absolute, root).replace("\\", "/")


def resolve_ref(ref: str, *, output_dir: str | None = None) -> str:
    """Resolve a relative ref back to an absolute path (§30.2).

    The one shared helper every consumer uses. Step 15.3 retired the absolute
    `wav_path` / `path` keys on TTS port payloads; `timing.align` and every
    later consumer read `artifact_refs` (or a relative `wav_path`) and resolve
    here.
    """
    from scriptase.shared.security import safe_join

    if not isinstance(ref, str) or not ref.strip():
        raise ProviderError(PROVIDER_RESULT_INVALID, "Empty artifact reference")
    if _ABSOLUTE_PATH_RE.match(ref):
        raise ProviderError(
            PROVIDER_ARTIFACT_UNMANAGED, "Artifact reference must be relative"
        )
    return safe_join(_managed_root(output_dir), ref)


def dedupe_refs(refs: Iterable[Any]) -> list[str]:
    """Deduplicated, order-stable, POSIX-normalized refs (§31.1)."""
    seen: list[str] = []
    for ref in refs or ():
        if not isinstance(ref, str):
            continue
        candidate = ref.replace("\\", "/").strip()
        if candidate and candidate not in seen:
            seen.append(candidate)
    return seen


# -- provenance (contracts.md §31.3, extended step 0.4) ---------------------


@dataclass(frozen=True)
class Provenance:
    """Who ran, with what, and why — filled by the platform, never a provider.

    Step 0.4 added generation-reproducibility fields (`seed`, `request_id`,
    `model_revision`). Snapshotting configuration is not reproducibility with
    generative providers; these three pin what the provider actually produced so
    a repair can vary one axis ("preserve character, change lighting") rather
    than re-rolling. `provider_instance_id` is the configured instance that ran
    (step 3.1); `provider_id` remains the discovered provider type id.
    """

    invocation_id: str = ""
    domain: str = ""
    provider_id: str = ""
    # Configured instance id (step 3.1). Empty only for pre-3.1 recorded results.
    provider_instance_id: str = ""
    provider_version: str = ""
    contract_version: int = 1
    settings_version: int = 0
    resolved_settings_redacted: Mapping[str, Any] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)
    # Which rung of the selection chain chose this provider.
    # Values: request | node_config | settings | channel | default |
    # fallback_after:<instance_id>
    selection_reason: str = "default"
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    cache_hit: bool = False
    # Generation reproducibility (step 0.4). Null/empty when the provider does
    # not expose the value — never invented by the platform.
    seed: int | None = None
    request_id: str = ""
    model_revision: str = ""
    # Optional cost report when the provider surfaces one (step 9.3 accounting).
    cost: Mapping[str, Any] | None = None

    def to_dict(self) -> dict:
        payload = {
            "invocation_id": self.invocation_id,
            "domain": self.domain,
            "provider_id": self.provider_id,
            "provider_instance_id": self.provider_instance_id,
            "provider_version": self.provider_version,
            "contract_version": self.contract_version,
            "settings_version": self.settings_version,
            "resolved_settings_redacted": dict(self.resolved_settings_redacted),
            "options": dict(self.options),
            "selection_reason": self.selection_reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "cache_hit": self.cache_hit,
            "seed": self.seed,
            "request_id": self.request_id,
            "model_revision": self.model_revision,
            "cost": dict(self.cost) if self.cost is not None else None,
        }
        return payload

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "Provenance":
        """Build provenance from a dict, ignoring unknown keys (forward-compat)."""
        if not isinstance(data, Mapping):
            return cls()
        known = cls.__dataclass_fields__
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key not in known:
                continue
            if key in {"resolved_settings_redacted", "options"} and isinstance(value, Mapping):
                kwargs[key] = dict(value)
            elif key == "cost":
                kwargs[key] = dict(value) if isinstance(value, Mapping) else None
            elif key == "seed":
                kwargs[key] = _coerce_seed(value)
            elif key in {"contract_version", "settings_version", "duration_ms"}:
                try:
                    kwargs[key] = int(value or 0)
                except (TypeError, ValueError):
                    kwargs[key] = 0
            elif key == "cache_hit":
                kwargs[key] = bool(value)
            else:
                kwargs[key] = value if value is not None else ""
        return cls(**kwargs)


def _coerce_seed(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_reproducibility(
    *,
    metadata: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Lift seed / request_id / model_revision from platform-visible surfaces.

    Providers never write `Provenance` directly. They may surface these values
    in result `metadata` (or request `options` for a caller-supplied seed); the
    platform harvests them into the envelope. Values are never invented: missing
    stays null/empty.
    """
    meta = dict(metadata or {})
    opts = dict(options or {})

    seed = _coerce_seed(meta["seed"] if "seed" in meta else opts.get("seed"))

    request_id = meta.get("request_id")
    if request_id is None or request_id == "":
        request_id = meta.get("requestId") or ""
    request_id = str(request_id)[:200] if request_id not in (None, "") else ""

    model_revision = meta.get("model_revision")
    if model_revision is None or model_revision == "":
        # Prefer an explicit revision; fall back to a provider-reported model
        # string when that is all the domain surfaces today (e.g. TTS `model`).
        model_revision = meta.get("model") or ""
    model_revision = (
        str(model_revision)[:200] if model_revision not in (None, "") else ""
    )

    return {
        "seed": seed,
        "request_id": request_id,
        "model_revision": model_revision,
    }


# -- per-unit results (contracts.md §31.5) ----------------------------------


@dataclass(frozen=True)
class UnitResult:
    """One requested unit of a multi-unit domain.

    Media-neutral: it replaces the storyboard `SceneResult` (`image_url` /
    `image_path`) and the animator one (`video_url` / `video_path`) with the
    single shape both domains produce (§33.1).

    Optional per-unit reproducibility fields (seed / request_id /
    model_revision / provider_id / provider_instance_id / selection_reason) are
    frozen for step 8.3 fallback: a multi-instance run produces units from
    different providers, so provenance must be per unit. When these are empty
    the unit inherits the envelope `provenance`. Sparse serialization keeps
    single-provider fixtures compact.
    """

    unit_index: int
    state: str = UNIT_SUCCEEDED
    artifact_refs: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    error: ProviderErrorPayload | None = None
    # Per-unit generation reproducibility (step 0.4 freeze; used by 8.3).
    seed: int | None = None
    request_id: str = ""
    model_revision: str = ""
    provider_id: str = ""
    provider_instance_id: str = ""
    selection_reason: str = ""

    def to_dict(self) -> dict:
        payload = {
            "unit_index": self.unit_index,
            "state": self.state,
            "artifact_refs": list(self.artifact_refs),
            "metadata": dict(self.metadata),
        }
        if self.error is not None:
            payload["error"] = self.error.to_dict()
        # Sparse: only emit per-unit overrides when set, so envelope provenance
        # remains the single source for ordinary single-provider runs.
        if self.seed is not None:
            payload["seed"] = self.seed
        if self.request_id:
            payload["request_id"] = self.request_id
        if self.model_revision:
            payload["model_revision"] = self.model_revision
        if self.provider_id:
            payload["provider_id"] = self.provider_id
        if self.provider_instance_id:
            payload["provider_instance_id"] = self.provider_instance_id
        if self.selection_reason:
            payload["selection_reason"] = self.selection_reason
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UnitResult":
        error = data.get("error")
        return cls(
            unit_index=int(data.get("unit_index", 0)),
            state=str(data.get("state", UNIT_SUCCEEDED)),
            artifact_refs=tuple(dedupe_refs(data.get("artifact_refs") or ())),
            metadata=dict(data.get("metadata") or {}),
            error=(
                ProviderErrorPayload.from_error(ProviderError.from_payload(error))
                if isinstance(error, Mapping)
                else None
            ),
            seed=_coerce_seed(data.get("seed")),
            request_id=str(data.get("request_id") or ""),
            model_revision=str(data.get("model_revision") or ""),
            provider_id=str(data.get("provider_id") or ""),
            provider_instance_id=str(data.get("provider_instance_id") or ""),
            selection_reason=str(data.get("selection_reason") or ""),
        )


def derive_status(units: Iterable[UnitResult]) -> str:
    """Envelope status from unit states — derived, never provider-declared.

    §31.5 rule 3, in its frozen precedence order. Cancellation is checked first
    so a cancellation arriving after one completed scene is not misreported as
    ordinary partial success. `"cancelled"` is returned as a distinct value: the
    caller raises `ProviderCancelled` rather than building an envelope.
    """
    units = list(units)
    if not units:
        return SUCCEEDED
    states = [unit.state for unit in units]
    if UNIT_CANCELLED in states and UNIT_FAILED not in states:
        return UNIT_CANCELLED
    if all(state == UNIT_SUCCEEDED for state in states):
        return SUCCEEDED
    if any(state == UNIT_SUCCEEDED for state in states):
        return PARTIAL
    return FAILED


# -- the envelope (contracts.md §31.1) --------------------------------------

_ENVELOPE_KEYS = frozenset({
    "result_version", "domain", "provider_id", "provider_version", "contract_version",
    "status", "payload", "artifact_refs", "units", "metadata", "warnings",
    "provenance", "job",
})


@dataclass
class ProviderResult:
    """One envelope for all five domains (§31.1, `result_version: 1`)."""

    domain: str = ""
    provider_id: str = ""
    provider_version: str = ""
    contract_version: int = 1
    status: str = SUCCEEDED
    payload: Mapping[str, Any] = field(default_factory=dict)
    artifact_refs: list[str] = field(default_factory=list)
    units: list[UnitResult] = field(default_factory=list)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    warnings: list[dict] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)
    job: Any = None
    result_version: int = RESULT_VERSION

    def to_dict(self) -> dict:
        return {
            "result_version": self.result_version,
            "domain": self.domain,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "contract_version": self.contract_version,
            "status": self.status,
            "payload": dict(self.payload),
            "artifact_refs": list(self.artifact_refs),
            "units": [unit.to_dict() for unit in self.units],
            "metadata": dict(self.metadata),
            "warnings": list(self.warnings),
            "provenance": self.provenance.to_dict(),
            "job": self.job.to_dict() if hasattr(self.job, "to_dict") else self.job,
        }

    def warn(self, code: str, message: str, unit_index: int | None = None) -> None:
        """Record a non-fatal warning. A warning never changes `status` (§31.4)."""
        if len(self.warnings) >= WARNINGS_MAX:
            return
        entry = {"code": str(code), "message": sanitize_message(message)[:WARNING_MESSAGE_MAX]}
        if unit_index is not None:
            entry["unit_index"] = int(unit_index)
        self.warnings.append(entry)


def coerce_result(
    returned: Any,
    *,
    domain: str,
    provider_id: str,
    provider_version: str = "",
    contract_version: int = 1,
) -> ProviderResult:
    """Turn what a provider returned into a validated envelope (§31.1).

    Unknown top-level keys are dropped with a WARN, mirroring the manifest policy
    — a provider written against a newer build must not fail on an older one. An
    invalid *known* field is `PROVIDER_RESULT_INVALID`.

    `domain` and `provider_id` are overwritten from the platform's own values, so
    a provider cannot impersonate another.
    """
    if isinstance(returned, ProviderResult):
        result = returned
    elif isinstance(returned, Mapping):
        result = _from_mapping(returned, provider_id=provider_id)
    else:
        raise ProviderError(
            PROVIDER_RESULT_INVALID,
            "Provider returned a non-object result",
            domain=domain,
            provider_id=provider_id,
        )

    result.domain = domain
    result.provider_id = provider_id
    result.provider_version = provider_version
    result.contract_version = contract_version
    if result.result_version != RESULT_VERSION:
        raise ProviderError(
            PROVIDER_RESULT_INVALID,
            f"Unsupported result_version {result.result_version}",
            domain=domain,
            provider_id=provider_id,
        )

    result.artifact_refs = dedupe_refs(result.artifact_refs)
    result.metadata = _bound_metadata(result.metadata)
    result.warnings = _bound_warnings(result.warnings)

    if result.units:
        derived = derive_status(result.units)
        if derived == UNIT_CANCELLED:
            from scriptase.providers.errors import ProviderCancelled

            raise ProviderCancelled(domain=domain, provider_id=provider_id)
        result.status = derived
        _check_unit_rules(result, domain, provider_id)
        # Envelope refs are the ordered union of unit refs plus domain-level
        # artifacts; no unit-level ref may be missing from it (§31.5 rule 4).
        result.artifact_refs = dedupe_refs(
            [ref for unit in result.units for ref in unit.artifact_refs]
            + result.artifact_refs
        )
    elif result.status not in ENVELOPE_STATES:
        raise ProviderError(
            PROVIDER_RESULT_INVALID,
            f"Unknown result status {result.status!r}",
            domain=domain,
            provider_id=provider_id,
        )

    if result.status == FAILED:
        # A returned `failed` is equivalent to raising, and is converted to one
        # at the boundary; providers should raise (§31.1).
        raise ProviderError(
            PROVIDER_RESULT_INVALID if not result.units else "PROVIDER_UNIT_FAILED",
            _failed_message(result),
            domain=domain,
            provider_id=provider_id,
            details={"units": [unit.to_dict() for unit in result.units]},
        )

    problems = validate_egress(result.to_dict())
    if problems:
        raise ProviderError(
            PROVIDER_RESULT_INVALID,
            f"Result rejected at the egress boundary: {problems[0]}",
            domain=domain,
            provider_id=provider_id,
            details={"violations": problems[:10]},
        )
    return result


def _failed_message(result: ProviderResult) -> str:
    if result.units:
        return f"All {len(result.units)} units failed"
    return "Provider reported a failed result"


def _from_mapping(data: Mapping[str, Any], *, provider_id: str) -> ProviderResult:
    unknown = sorted(set(data) - _ENVELOPE_KEYS)
    for key in unknown:
        logger.warning(
            "[results] {}: unknown result key dropped: {}", provider_id, key
        )
    provenance = data.get("provenance")
    job = data.get("job")
    return ProviderResult(
        status=str(data.get("status", SUCCEEDED)),
        payload=dict(data.get("payload") or {}),
        artifact_refs=list(data.get("artifact_refs") or []),
        units=[
            UnitResult.from_dict(unit) if isinstance(unit, Mapping) else unit
            for unit in (data.get("units") or [])
        ],
        metadata=dict(data.get("metadata") or {}),
        warnings=list(data.get("warnings") or []),
        provenance=Provenance.from_mapping(
            provenance if isinstance(provenance, Mapping) else None
        ),
        job=job,
        result_version=int(data.get("result_version", RESULT_VERSION)),
    )


def _bound_metadata(metadata: Mapping[str, Any]) -> dict:
    """Small, flat, JSON-scalar values only (§31.1)."""
    bounded: dict[str, Any] = {}
    for key, value in list(dict(metadata or {}).items())[:METADATA_MAX_KEYS]:
        if isinstance(value, str):
            bounded[str(key)] = value[:METADATA_STRING_MAX]
        elif value is None or isinstance(value, (bool, int, float)):
            bounded[str(key)] = value
        else:
            logger.debug("[results] non-scalar metadata dropped: {}", key)
    return bounded


def _bound_warnings(warnings: Iterable[Any]) -> list[dict]:
    bounded: list[dict] = []
    for entry in list(warnings or [])[:WARNINGS_MAX]:
        if not isinstance(entry, Mapping):
            continue
        item = {
            "code": str(entry.get("code", "PROVIDER_WARNING")),
            "message": sanitize_message(entry.get("message", ""))[:WARNING_MESSAGE_MAX],
        }
        if entry.get("unit_index") is not None:
            item["unit_index"] = int(entry["unit_index"])
        bounded.append(item)
    return bounded


def _check_unit_rules(result: ProviderResult, domain: str, provider_id: str) -> None:
    """§31.5 rules 1, 2, and 5."""
    seen: set[int] = set()
    for unit in result.units:
        if unit.state not in UNIT_STATES:
            raise ProviderError(
                PROVIDER_RESULT_INVALID,
                f"Unknown unit state {unit.state!r}",
                domain=domain, provider_id=provider_id,
            )
        if unit.unit_index in seen:
            raise ProviderError(
                PROVIDER_RESULT_INVALID,
                f"Duplicate unit_index {unit.unit_index}",
                domain=domain, provider_id=provider_id,
            )
        seen.add(unit.unit_index)
        if unit.state == UNIT_FAILED and unit.error is None:
            raise ProviderError(
                PROVIDER_RESULT_INVALID,
                f"Failed unit {unit.unit_index} carries no error",
                domain=domain, provider_id=provider_id,
            )


# -- egress validator (contracts.md §36) ------------------------------------

# A sensitive key is a leak *unless* it holds nothing but a redaction marker.
# `provenance.resolved_settings_redacted` is the one sanctioned echo of settings
# (§31.3) and it necessarily keeps its original key names, so the rule has to be
# about the value, not the key.
_REDACTION_MARKERS = frozenset({"***", "[REDACTED]", ""})


def _is_redacted(value: Any) -> bool:
    return isinstance(value, str) and value in _REDACTION_MARKERS


def validate_egress(value: Any, *, path: str = "", _depth: int = 0) -> list[str]:
    """Reject the four prohibited classes, mechanically (§31.2, §36).

    Returns a list of human-readable violations; empty means the value may cross
    the boundary. This runs over every `ProviderResult` and over every recorded
    `expected_result.json` fixture, so a leak fails a test rather than a review.
    """
    from scriptase.engine.redaction import is_sensitive_key

    problems: list[str] = []
    if _depth > 12:
        return [f"{path or '<root>'}: nesting is too deep"]

    if isinstance(value, Mapping):
        for key, child in value.items():
            where = f"{path}.{key}" if path else str(key)
            if is_sensitive_key(key) and not _is_redacted(child):
                problems.append(f"{where}: sensitive key is not allowed in a result")
                continue
            problems.extend(validate_egress(child, path=where, _depth=_depth + 1))
        return problems

    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            problems.extend(
                validate_egress(child, path=f"{path}[{index}]", _depth=_depth + 1)
            )
        return problems

    if isinstance(value, bytes):
        return [f"{path or '<root>'}: bytes are not allowed in a result"]

    if isinstance(value, str):
        if _ABSOLUTE_PATH_RE.match(value.strip()):
            return [f"{path or '<root>'}: absolute filesystem path"]
        return problems

    if value is None or isinstance(value, (bool, int, float)):
        return problems

    return [f"{path or '<root>'}: {type(value).__name__} is not JSON-serializable"]


def assert_json_safe(value: Any) -> None:
    """Raise `PROVIDER_RESULT_INVALID` unless the value round-trips as JSON."""
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ProviderError(
            PROVIDER_RESULT_INVALID, f"Result is not JSON-serializable: {exc}"
        ) from None


__all__ = [
    "ENVELOPE_STATES",
    "FAILED",
    "METADATA_MAX_KEYS",
    "METADATA_STRING_MAX",
    "PARTIAL",
    "RESULT_VERSION",
    "SUCCEEDED",
    "UNIT_CANCELLED",
    "UNIT_FAILED",
    "UNIT_SKIPPED",
    "UNIT_STATES",
    "UNIT_SUCCEEDED",
    "WARNINGS_MAX",
    "WARNING_MESSAGE_MAX",
    "Provenance",
    "ProviderResult",
    "UnitResult",
    "assert_json_safe",
    "coerce_result",
    "dedupe_refs",
    "derive_status",
    "extract_reproducibility",
    "normalize_ref",
    "resolve_ref",
    "validate_egress",
]
