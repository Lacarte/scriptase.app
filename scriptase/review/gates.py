"""Early quality gates (step 7.4 / product §12.3).

Two gates save money by failing fast:

* **Image gate** — runs before any video generation call when source stills
  are present. A bad still is caught (and optionally repaired) so expensive
  animation never starts from garbage.
* **Video gate** — runs before final review so motion defects and technical
  video failures never reach the expensive semantic final pass alone.

Deterministic technical validators always run first; semantic review is
optional and never the only layer. Both gates return structured issues only —
never free text.

The Repair Router (phase 8) owns table-driven routing. This module accepts an
optional per-unit ``repair`` callback so a bad image can be regenerated in
place before the video provider is invoked — the done-when proof for 7.4.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Sequence

from config import OUTPUT_DIR
from scriptase.review.technical import (
    TechnicalContext,
    TechnicalIssue,
    assert_structured_issues,
    run_technical_validators,
)

GateKind = Literal["image", "video"]

# Severities that block progression past the gate.
_BLOCKING_SEVERITIES = frozenset({"high", "critical"})

# Error code raised by adapters when a gate fails after repairs are exhausted.
QUALITY_GATE_FAILED = "QUALITY_GATE_FAILED"

_ABSOLUTE_PATH_RE_PREFIXES = ("/", "\\")


@dataclass
class GateUnit:
    """One media unit under quality review (typically one scene)."""

    path: str
    path_ref: str | None = None
    scene_id: str | None = None
    target_node_id: str | None = None
    target_artifact_id: str | None = None
    # Semantic context (optional).
    caption: str = ""
    image_prompt: str = ""
    expected_subject: str = ""
    expected_style: str = ""
    duration_s: float | None = None
    expected_duration_s: float | None = None
    # Extra technical expectations.
    aspect_ratio: str | None = None
    width: int | None = None
    height: int | None = None
    min_seconds: float | None = None
    max_seconds: float | None = None
    require_audio: bool | None = None
    min_frames: int | None = None

    def technical_context(self) -> TechnicalContext:
        return TechnicalContext(
            target_node_id=self.target_node_id,
            target_artifact_id=self.target_artifact_id,
            scene_id=self.scene_id,
            path_ref=self.path_ref or _relative_ref(self.path),
        )


# repair(unit, blocking_issues) -> updated unit, or None if repair failed.
RepairFn = Callable[[GateUnit, Sequence[Any]], GateUnit | None]


@dataclass
class QualityGateResult:
    """Outcome of an early quality gate."""

    gate: GateKind
    passed: bool
    issues: list[Any] = field(default_factory=list)
    repairs_attempted: int = 0
    units_checked: int = 0
    units_repaired: int = 0
    blocked_scene_ids: list[str] = field(default_factory=list)

    @property
    def blocking_issues(self) -> list[Any]:
        return [item for item in self.issues if _is_blocking(item)]

    @property
    def blocking_issue_count(self) -> int:
        return len(self.blocking_issues)

    def to_details(self) -> dict[str, Any]:
        """Adapter / SSE-safe details (no absolute paths, no free-text-only)."""
        issue_rows: list[dict[str, Any]] = []
        for item in self.issues:
            if hasattr(item, "model_dump"):
                raw = item.model_dump(mode="json")
            elif isinstance(item, Mapping):
                raw = dict(item)
            else:
                continue
            # Strip anything that might look like an absolute path.
            path_ref = raw.get("path_ref")
            if isinstance(path_ref, str) and _looks_absolute(path_ref):
                raw["path_ref"] = os.path.basename(path_ref.replace("\\", "/"))
            issue_rows.append(
                {
                    "issue_type": raw.get("issue_type"),
                    "severity": raw.get("severity"),
                    "check_id": raw.get("check_id"),
                    "scene_id": raw.get("scene_id"),
                    "reason": raw.get("reason"),
                    "suggested_action": raw.get("suggested_action"),
                    "repair_instruction": raw.get("repair_instruction"),
                    "observed": raw.get("observed") or {},
                    "expected": raw.get("expected") or {},
                }
            )
        return {
            "gate": self.gate,
            "passed": self.passed,
            "repairs_attempted": self.repairs_attempted,
            "units_checked": self.units_checked,
            "units_repaired": self.units_repaired,
            "blocked_scene_ids": list(self.blocked_scene_ids),
            "issue_count": len(self.issues),
            "blocking_issue_count": len(self.blocking_issues),
            "issues": issue_rows,
        }


def _looks_absolute(path: str) -> bool:
    text = (path or "").strip()
    if not text:
        return False
    if text.startswith(_ABSOLUTE_PATH_RE_PREFIXES):
        return True
    return len(text) >= 3 and text[1] == ":" and text[0].isalpha()


def _relative_ref(path: str | None) -> str | None:
    text = (path or "").strip().replace("\\", "/")
    if not text:
        return None
    # Managed URL-style prefixes first — on Windows abspath("/output/…") is not
    # under OUTPUT_DIR, so strip before treating as absolute.
    if text.startswith("/output/"):
        return text[8:]
    if text.startswith("output/"):
        return text[7:]
    if _looks_absolute(text):
        # Prefer managed relative form when under OUTPUT_DIR.
        try:
            root = os.path.abspath(OUTPUT_DIR)
            abs_path = os.path.abspath(text)
            if os.path.commonpath([root, abs_path]) == root:
                return os.path.relpath(abs_path, root).replace("\\", "/")
        except (ValueError, OSError):
            pass
        return os.path.basename(text)
    return text.lstrip("/")


def resolve_managed_path(ref_or_path: str | None) -> str | None:
    """Resolve a managed relative ref or absolute path to an absolute file path.

    Absolute paths outside ``OUTPUT_DIR`` are rejected (return None) so a
    browser-supplied filesystem path cannot enter the gate.
    """
    text = (ref_or_path or "").strip()
    if not text:
        return None
    # Strip managed URL-style prefixes.
    normalized = text.replace("\\", "/")
    if normalized.startswith("/output/"):
        normalized = normalized[8:]
    elif normalized.startswith("output/"):
        normalized = normalized[7:]

    if _looks_absolute(text) and not normalized.startswith(
        ("storyboard/", "animator/", "exports/", "tts/", "scenes/", "projects/")
    ):
        # Absolute path: only accept when inside OUTPUT_DIR. Missing files still
        # return the path so file_exists can emit a structured issue.
        try:
            root = os.path.abspath(OUTPUT_DIR)
            abs_path = os.path.abspath(text)
            if os.path.commonpath([root, abs_path]) != root:
                return None
            return abs_path
        except (ValueError, OSError):
            return None

    # Relative managed ref.
    try:
        from scriptase.shared.security import safe_join

        return safe_join(OUTPUT_DIR, *normalized.split("/"))
    except (ValueError, OSError):
        return None


def _is_blocking(issue: Any) -> bool:
    severity = getattr(issue, "severity", None)
    if severity is None and isinstance(issue, Mapping):
        severity = issue.get("severity")
    return str(severity or "").strip() in _BLOCKING_SEVERITIES


def _issue_scene_id(issue: Any) -> str | None:
    value = getattr(issue, "scene_id", None)
    if value is None and isinstance(issue, Mapping):
        value = issue.get("scene_id")
    text = str(value).strip() if value is not None else ""
    return text or None


def evaluate_image_unit(
    unit: GateUnit,
    *,
    run_semantic: bool = False,
    job_id: str = "job_GATE",
) -> list[Any]:
    """Technical (then optional semantic) checks for one still image."""
    issues: list[Any] = list(
        run_technical_validators(
            path=unit.path,
            context=unit.technical_context(),
            aspect_ratio=unit.aspect_ratio,
            width=unit.width,
            height=unit.height,
            # Image stills: existence + readable always; dimensions when set.
            expect_exists=True,
            expect_readable=True,
        )
    )
    assert_structured_issues(issues)

    if run_semantic:
        issues.extend(_semantic_image_issues(unit, job_id=job_id))
    return issues


def evaluate_video_unit(
    unit: GateUnit,
    *,
    run_semantic: bool = False,
    job_id: str = "job_GATE",
) -> list[Any]:
    """Technical (then optional semantic) checks for one video clip."""
    issues: list[Any] = list(
        run_technical_validators(
            path=unit.path,
            context=unit.technical_context(),
            aspect_ratio=unit.aspect_ratio,
            width=unit.width,
            height=unit.height,
            min_seconds=unit.min_seconds,
            max_seconds=unit.max_seconds,
            expected_seconds=unit.expected_duration_s,
            require_audio=unit.require_audio,
            min_frames=unit.min_frames,
            expect_exists=True,
            expect_readable=True,
        )
    )
    assert_structured_issues(issues)

    if run_semantic:
        issues.extend(_semantic_video_issues(unit, job_id=job_id))
    return issues


def _semantic_image_issues(unit: GateUnit, *, job_id: str) -> list[Any]:
    """Optional offline semantic image review (never the only layer)."""
    try:
        from scriptase.review.providers.contract import ReviewRequest
        from scriptase.review.providers.semantic.provider import SemanticReviewProvider
    except ImportError:
        return []

    request = ReviewRequest(
        job_id=job_id,
        subject_kind="image",
        scene_id=unit.scene_id,
        target_node_id=unit.target_node_id,
        target_artifact_id=unit.target_artifact_id,
        artifact_ref=unit.path_ref or _relative_ref(unit.path) or "",
        caption=unit.caption,
        image_prompt=unit.image_prompt,
        expected_subject=unit.expected_subject,
        expected_style=unit.expected_style,
    )
    payload = SemanticReviewProvider().review(request)
    return list(payload.issues)


def _semantic_video_issues(unit: GateUnit, *, job_id: str) -> list[Any]:
    try:
        from scriptase.review.providers.contract import ReviewRequest
        from scriptase.review.providers.semantic.provider import SemanticReviewProvider
    except ImportError:
        return []

    request = ReviewRequest(
        job_id=job_id,
        subject_kind="video",
        scene_id=unit.scene_id,
        target_node_id=unit.target_node_id,
        target_artifact_id=unit.target_artifact_id,
        artifact_ref=unit.path_ref or _relative_ref(unit.path) or "",
        caption=unit.caption,
        expected_subject=unit.expected_subject,
        duration_s=unit.duration_s,
        expected_duration_s=unit.expected_duration_s,
    )
    payload = SemanticReviewProvider().review(request)
    return list(payload.issues)


def _run_gate(
    *,
    gate: GateKind,
    units: Sequence[GateUnit],
    evaluate: Callable[..., list[Any]],
    repair: RepairFn | None,
    max_repairs: int,
    run_semantic: bool,
    job_id: str,
    expected_unit_count: int | None,
) -> QualityGateResult:
    # Shallow copy so repair can replace path without mutating caller state.
    working = [
        GateUnit(
            path=u.path,
            path_ref=u.path_ref,
            scene_id=u.scene_id,
            target_node_id=u.target_node_id,
            target_artifact_id=u.target_artifact_id,
            caption=u.caption,
            image_prompt=u.image_prompt,
            expected_subject=u.expected_subject,
            expected_style=u.expected_style,
            duration_s=u.duration_s,
            expected_duration_s=u.expected_duration_s,
            aspect_ratio=u.aspect_ratio,
            width=u.width,
            height=u.height,
            min_seconds=u.min_seconds,
            max_seconds=u.max_seconds,
            require_audio=u.require_audio,
            min_frames=u.min_frames,
        )
        for u in units
    ]

    all_issues: list[Any] = []
    repairs_attempted = 0
    units_repaired = 0
    budget = max(0, int(max_repairs))

    if expected_unit_count is not None:
        count_issues = run_technical_validators(
            expected_artifact_count=expected_unit_count,
            artifacts=working,
            context=TechnicalContext(path_ref=None),
            path=None,
            checks=("expected_artifact_count",),
        )
        all_issues.extend(count_issues)

    # Per-unit evaluate → optional repair loop.
    for index, unit in enumerate(list(working)):
        attempts_for_unit = 0
        while True:
            unit_issues = evaluate(
                unit, run_semantic=run_semantic, job_id=job_id
            )
            blocking = [item for item in unit_issues if _is_blocking(item)]
            if not blocking:
                # Keep non-blocking findings (warnings) for diagnostics.
                all_issues.extend(unit_issues)
                working[index] = unit
                break

            if repair is None or attempts_for_unit >= budget:
                all_issues.extend(unit_issues)
                working[index] = unit
                break

            attempts_for_unit += 1
            repairs_attempted += 1
            repaired = repair(unit, blocking)
            if repaired is None:
                all_issues.extend(unit_issues)
                working[index] = unit
                break
            units_repaired += 1
            unit = repaired
            working[index] = unit
            # Re-evaluate the repaired unit. Prior blocking issues are discarded
            # because the artifact was replaced (phase 8 records supersession
            # history; 7.4 only needs the gate to pass before video runs).

    # Normalize to structured issues only (TechnicalIssue or mapping drafts).
    structured: list[Any] = []
    for item in all_issues:
        if isinstance(item, TechnicalIssue):
            structured.append(item)
        elif isinstance(item, Mapping):
            structured.append(dict(item))
        else:
            raise TypeError(
                f"quality gates must emit structured issues, got {type(item)!r}"
            )

    blocked_scenes: list[str] = []
    for item in structured:
        if _is_blocking(item):
            sid = _issue_scene_id(item)
            if sid and sid not in blocked_scenes:
                blocked_scenes.append(sid)

    passed = not any(_is_blocking(item) for item in structured)

    return QualityGateResult(
        gate=gate,
        passed=passed,
        issues=structured,
        repairs_attempted=repairs_attempted,
        units_checked=len(working),
        units_repaired=units_repaired,
        blocked_scene_ids=blocked_scenes,
    )


def run_image_gate(
    units: Sequence[GateUnit],
    *,
    job_id: str = "job_GATE",
    repair: RepairFn | None = None,
    max_repairs: int = 1,
    run_semantic: bool = False,
    expected_unit_count: int | None = None,
) -> QualityGateResult:
    """Image quality gate — call before any video generation.

    Technical validators run first. When ``repair`` is supplied, each unit with
    blocking issues is offered to the callback up to ``max_repairs`` times and
    re-checked. The video provider is never invoked here.
    """
    return _run_gate(
        gate="image",
        units=units,
        evaluate=evaluate_image_unit,
        repair=repair,
        max_repairs=max_repairs,
        run_semantic=run_semantic,
        job_id=job_id,
        expected_unit_count=expected_unit_count,
    )


def run_video_gate(
    units: Sequence[GateUnit],
    *,
    job_id: str = "job_GATE",
    repair: RepairFn | None = None,
    max_repairs: int = 0,
    run_semantic: bool = False,
    expected_unit_count: int | None = None,
) -> QualityGateResult:
    """Video quality gate — call before final review.

    Default ``max_repairs=0``: phase 8's Repair Router owns video regeneration.
    The gate still blocks final review when technical (or optional semantic)
    checks fail.
    """
    return _run_gate(
        gate="video",
        units=units,
        evaluate=evaluate_video_unit,
        repair=repair,
        max_repairs=max_repairs,
        run_semantic=run_semantic,
        job_id=job_id,
        expected_unit_count=expected_unit_count,
    )


def units_from_storyboard(
    storyboard: Mapping[str, Any] | None,
    *,
    aspect_ratio: str | None = None,
    width: int | None = None,
    height: int | None = None,
    target_node_id: str | None = None,
    scenes: Sequence[Mapping[str, Any]] | None = None,
) -> list[GateUnit]:
    """Build gate units from an animator storyboard port payload."""
    if not isinstance(storyboard, Mapping):
        return []

    scene_meta: dict[str, Mapping[str, Any]] = {}
    if scenes:
        for row in scenes:
            if not isinstance(row, Mapping):
                continue
            sid = str(row.get("scene_id") or row.get("id") or "").strip()
            if sid:
                scene_meta[sid] = row
            # Also index by ordinal for fallback matching.
            if "index" in row:
                scene_meta[str(row["index"])] = row

    units: list[GateUnit] = []
    statuses = storyboard.get("scene_statuses")
    if isinstance(statuses, Mapping) and statuses:
        for key, entry in statuses.items():
            if not isinstance(entry, Mapping):
                continue
            local = entry.get("local_path") or entry.get("path") or ""
            ref = entry.get("artifact_ref") or ""
            if not ref and local:
                ref = _relative_ref(str(local)) or ""
            path = resolve_managed_path(str(local or ref))
            if path is None and ref:
                path = resolve_managed_path(str(ref))
            if path is None:
                # Still emit a unit so file_exists fires with a sensible ref.
                path = str(local or ref or f"missing/{key}")
            sid = str(
                entry.get("scene_id")
                or entry.get("id")
                or (key if str(key).startswith("scn_") else "")
                or ""
            ).strip() or None
            meta = scene_meta.get(sid or "") or scene_meta.get(str(key)) or {}
            units.append(
                GateUnit(
                    path=path,
                    path_ref=ref or _relative_ref(path),
                    scene_id=sid,
                    target_node_id=target_node_id,
                    target_artifact_id=(
                        str(entry.get("artifact_id")).strip()
                        if entry.get("artifact_id")
                        else None
                    ),
                    caption=str(entry.get("caption") or meta.get("caption") or ""),
                    image_prompt=str(
                        entry.get("image_prompt")
                        or meta.get("image_prompt")
                        or meta.get("prompt")
                        or ""
                    ),
                    expected_subject=str(
                        meta.get("expected_subject") or meta.get("subject") or ""
                    ),
                    expected_style=str(meta.get("expected_style") or meta.get("style") or ""),
                    aspect_ratio=aspect_ratio,
                    width=width,
                    height=height,
                )
            )
        if units:
            return units

    # Fallback: artifact_refs list on the storyboard payload.
    refs = storyboard.get("artifact_refs") or []
    if isinstance(refs, Sequence) and not isinstance(refs, (str, bytes)):
        for index, ref in enumerate(refs):
            text = str(ref or "").strip()
            if not text:
                continue
            path = resolve_managed_path(text) or text
            meta = scene_meta.get(str(index)) or {}
            sid = str(meta.get("scene_id") or meta.get("id") or "").strip() or None
            units.append(
                GateUnit(
                    path=path,
                    path_ref=_relative_ref(text),
                    scene_id=sid,
                    target_node_id=target_node_id,
                    image_prompt=str(meta.get("image_prompt") or meta.get("prompt") or ""),
                    expected_subject=str(
                        meta.get("expected_subject") or meta.get("subject") or ""
                    ),
                    aspect_ratio=aspect_ratio,
                    width=width,
                    height=height,
                )
            )
    return units


def units_from_video_assets(
    assets: Mapping[str, Any] | None,
    *,
    aspect_ratio: str | None = None,
    require_audio: bool | None = None,
    target_node_id: str | None = None,
) -> list[GateUnit]:
    """Build gate units from an animator assets port payload."""
    if not isinstance(assets, Mapping):
        return []

    units: list[GateUnit] = []
    statuses = assets.get("scene_statuses")
    if isinstance(statuses, Mapping) and statuses:
        for key, entry in statuses.items():
            if not isinstance(entry, Mapping):
                continue
            local = entry.get("local_path") or entry.get("path") or ""
            ref = entry.get("artifact_ref") or ""
            if not ref and local:
                ref = _relative_ref(str(local)) or ""
            path = resolve_managed_path(str(local or ref))
            if path is None and ref:
                path = resolve_managed_path(str(ref))
            if path is None:
                path = str(local or ref or f"missing/{key}")
            sid = str(
                entry.get("scene_id")
                or entry.get("id")
                or (key if str(key).startswith("scn_") else "")
                or ""
            ).strip() or None
            duration = entry.get("duration_s") or entry.get("duration")
            try:
                duration_s = float(duration) if duration is not None else None
            except (TypeError, ValueError):
                duration_s = None
            units.append(
                GateUnit(
                    path=path,
                    path_ref=ref or _relative_ref(path),
                    scene_id=sid,
                    target_node_id=target_node_id,
                    duration_s=duration_s,
                    expected_duration_s=(
                        float(entry["expected_duration_s"])
                        if entry.get("expected_duration_s") is not None
                        else None
                    ),
                    aspect_ratio=aspect_ratio,
                    require_audio=require_audio,
                    caption=str(entry.get("caption") or ""),
                )
            )
        if units:
            return units

    refs = assets.get("artifact_refs") or []
    if isinstance(refs, Sequence) and not isinstance(refs, (str, bytes)):
        for ref in refs:
            text = str(ref or "").strip()
            if not text:
                continue
            # Prefer video-like refs when the list is mixed.
            lower = text.lower()
            if not any(
                lower.endswith(ext)
                for ext in (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
            ):
                # Still include non-video refs if that's all we have.
                pass
            path = resolve_managed_path(text) or text
            units.append(
                GateUnit(
                    path=path,
                    path_ref=_relative_ref(text),
                    target_node_id=target_node_id,
                    aspect_ratio=aspect_ratio,
                    require_audio=require_audio,
                )
            )
    return units


def enforce_image_gate_for_video(
    inputs: Mapping[str, Any],
    config: Mapping[str, Any] | None,
    context: Any,
    *,
    repair: RepairFn | None = None,
) -> QualityGateResult | None:
    """Run the image gate when the animator has a storyboard; return result.

    Returns ``None`` when there is no storyboard (text-to-video path). Raises
    nothing — callers check ``result.passed`` and raise ``AdapterError`` with
    ``QUALITY_GATE_FAILED`` so the video provider is never invoked on failure.
    """
    from scriptase.modules.video.routing import storyboard_is_present

    if not storyboard_is_present(inputs):
        return None

    cfg = dict(config or {})
    # Explicit opt-out only for isolated adapter unit tests that stub ports.
    if cfg.get("skip_quality_gate") is True:
        return QualityGateResult(gate="image", passed=True, units_checked=0)

    aspect = cfg.get("aspect_ratio") or None
    if isinstance(aspect, str):
        aspect = aspect.strip() or None

    job_id = ""
    if isinstance(context, Mapping):
        job_id = str(context.get("job_id") or context.get("project_id") or "")
    else:
        job_id = str(
            getattr(context, "job_id", None)
            or getattr(context, "project_id", None)
            or ""
        )
    job_id = job_id.strip() or "job_GATE"

    node_id = ""
    if isinstance(context, Mapping):
        node_id = str(context.get("node_id") or "")
    else:
        node_id = str(getattr(context, "node_id", None) or "")

    scenes_payload = inputs.get("scenes") if isinstance(inputs, Mapping) else None
    scenes_list = None
    if isinstance(scenes_payload, Mapping):
        raw = scenes_payload.get("scenes")
        if isinstance(raw, Sequence):
            scenes_list = [s for s in raw if isinstance(s, Mapping)]

    storyboard = inputs.get("storyboard") if isinstance(inputs, Mapping) else None
    units = units_from_storyboard(
        storyboard if isinstance(storyboard, Mapping) else None,
        aspect_ratio=aspect,
        target_node_id=node_id or None,
        scenes=scenes_list,
    )

    max_repairs = cfg.get("image_gate_max_repairs", 1)
    try:
        max_repairs_i = max(0, int(max_repairs))
    except (TypeError, ValueError):
        max_repairs_i = 1

    run_semantic = bool(cfg.get("image_gate_semantic", False))

    # When storyboard is present but yields zero resolvable units, fail closed:
    # empty image list must not skip past the gate into video generation.
    expected_count = None
    if isinstance(storyboard, Mapping):
        total = storyboard.get("total")
        try:
            if total is not None:
                expected_count = int(total)
        except (TypeError, ValueError):
            expected_count = None
        if expected_count is None and units:
            expected_count = len(units)
        if expected_count is None and storyboard.get("ready") is not None:
            try:
                expected_count = int(storyboard.get("ready") or 0)
            except (TypeError, ValueError):
                expected_count = None

    if not units:
        # Synthesize a single missing-file issue so the gate fails structured.
        missing = GateUnit(
            path="storyboard/missing.png",
            path_ref="storyboard/missing.png",
            target_node_id=node_id or None,
            aspect_ratio=aspect,
        )
        return run_image_gate(
            [missing],
            job_id=job_id,
            repair=None,
            max_repairs=0,
            run_semantic=False,
            expected_unit_count=expected_count if expected_count is not None else 1,
        )

    # Prefer a repair callback from config (tests / orchestration inject this).
    repair_fn = repair
    if repair_fn is None:
        candidate = cfg.get("image_gate_repair")
        if callable(candidate):
            repair_fn = candidate  # type: ignore[assignment]

    return run_image_gate(
        units,
        job_id=job_id,
        repair=repair_fn,
        max_repairs=max_repairs_i,
        run_semantic=run_semantic,
        expected_unit_count=expected_count,
    )


__all__ = [
    "QUALITY_GATE_FAILED",
    "GateKind",
    "GateUnit",
    "QualityGateResult",
    "RepairFn",
    "enforce_image_gate_for_video",
    "evaluate_image_unit",
    "evaluate_video_unit",
    "resolve_managed_path",
    "run_image_gate",
    "run_video_gate",
    "units_from_storyboard",
    "units_from_video_assets",
]
