"""Workflow adapter for the Review node (`review.run`) — step 11.1.

Phases 7 and 8 built the Reviewer and the Repair Router and never connected
them: the `review` domain was the only one of six with no node consuming it, so
no ReviewIssue was ever produced by a real run. This adapter is the missing
consumer. It writes almost no new logic — it drives the existing
`gates.units_from_*` builders and `run_technical_validators()`, and dispatches
the optional semantic pass through the provider hub.

Semantic review goes through the hub rather than importing
`SemanticReviewProvider` directly (which is what `gates._semantic_image_issues`
does) so the node honours the instance the operator actually selected. That is
the whole point of the `provider_id` field: an AI reviewer dropped in beside
`semantic` must become selectable without an edit here (contracts §26).

Scope boundary for this step: the node **reports**. It emits structured
findings on its `issues` port and nothing else. Persisting them through
`scriptase/review/store.py` is step 11.2; routing them to the responsible node
is step 11.3. `fail_on_blocking` lets a graph refuse to continue today, and
defaults off so adding Review to a working workflow cannot start failing runs.
"""

from __future__ import annotations

from typing import Any, Mapping

from .common import (
    AdapterError,
    context_value,
    inherited_config,
    outputs,
    provider_id,
    provider_run_options,
    resolve_provider,
    resolve_provider_binding,
)

DOMAIN = "review"


def _blocking_severities() -> frozenset[str]:
    """The gate's own threshold, read rather than redeclared."""
    from scriptase.review.gates import _BLOCKING_SEVERITIES

    return _BLOCKING_SEVERITIES


def _as_dict(issue: Any) -> dict[str, Any]:
    """Normalize a TechnicalIssue / ReviewIssueItem / mapping to plain JSON."""
    if hasattr(issue, "model_dump"):
        return issue.model_dump(mode="json")
    if isinstance(issue, Mapping):
        return dict(issue)
    # `assert_structured_issues` and `ReviewResultPayload` both reject free text
    # upstream, so anything reaching here is a programming error.
    raise AdapterError(
        "PROVIDER_RESULT_INVALID", "Review produced a finding that is not structured"
    )


def _scene_list(scenes_payload: Any) -> list[dict] | None:
    if not isinstance(scenes_payload, Mapping):
        return None
    raw = scenes_payload.get("scenes")
    if isinstance(raw, list):
        return [scene for scene in raw if isinstance(scene, Mapping)]
    return None


class _SemanticPass:
    """One resolved review instance, invoked once per gate unit.

    Constructed only when semantic review is switched on, so the free
    technical-only path never touches the hub or the settings file.
    """

    def __init__(self, selected: str, config: Mapping[str, Any], context: Any):
        from scriptase.providers import settings_manager
        from scriptase.providers.hub import hub

        self.instance_id, self.type_id = resolve_provider_binding(DOMAIN, selected)
        # Fail closed: a bound provider that cannot be constructed fails the
        # node, rather than silently downgrading the run to technical-only.
        self.provider = resolve_provider(DOMAIN, selected)
        self.package = hub.get(DOMAIN, self.type_id)
        saved = settings_manager.get_instance_settings(DOMAIN, self.instance_id)
        self.settings = (
            self.package.resolve_settings(saved, instance_id=self.instance_id)
            if self.package is not None
            else dict(saved)
        )
        self.options = provider_run_options(DOMAIN, selected, config)
        self.context = context

    def __call__(self, unit, *, subject_kind: str, job_id: str) -> list[dict[str, Any]]:
        from scriptase.providers import boundary
        from scriptase.providers.invocation import build_invocation
        from scriptase.review.providers.contract import ReviewRequest

        request = ReviewRequest(
            job_id=job_id,
            subject_kind=subject_kind,
            scene_id=unit.scene_id,
            target_node_id=unit.target_node_id,
            target_artifact_id=unit.target_artifact_id,
            artifact_ref=unit.path_ref or "",
            caption=unit.caption,
            image_prompt=unit.image_prompt,
            expected_subject=unit.expected_subject,
            expected_style=unit.expected_style,
            duration_s=unit.duration_s,
            expected_duration_s=unit.expected_duration_s,
        )
        invocation = build_invocation(
            self.context,
            domain=DOMAIN,
            provider_id=self.type_id,
            project_id=job_id,
            settings=self.settings,
            options=self.options,
            provider_instance_id=self.instance_id,
        )
        result = boundary.invoke(
            lambda inv: self.provider.invoke(request, inv),
            invocation,
            provider_version=getattr(self.package, "version", "") or "",
            contract_version=getattr(self.package, "contract_version", 2) or 2,
        )
        issues = (result.payload or {}).get("issues") or []
        return [_as_dict(issue) for issue in issues]


def run(inputs, config, context):
    from scriptase.review.gates import (
        QUALITY_GATE_FAILED,
        evaluate_image_unit,
        evaluate_video_unit,
        units_from_storyboard,
        units_from_video_assets,
    )

    inputs = inputs or {}
    merged = inherited_config(config, inputs.get("settings"))

    # The id every ReviewIssue is keyed by (contracts §9). `job_REVIEW` only
    # appears in isolated adapter tests that construct a bare context.
    job_id = str(
        context_value(context, "job_id", "")
        or context_value(context, "project_id", "")
        or ""
    ).strip() or "job_REVIEW"
    node_id = str(context_value(context, "node_id", "") or "") or None

    aspect = merged.get("aspect_ratio") or None
    if isinstance(aspect, str):
        aspect = aspect.strip() or None
    subject = str(merged.get("subject") or "auto").strip() or "auto"
    # `units_from_video_assets` reads None as "do not check", which is what an
    # unticked box means — not "assert the clip is silent".
    require_audio = True if merged.get("require_audio") else None

    images = inputs.get("images") if isinstance(inputs.get("images"), Mapping) else None
    assets = inputs.get("assets") if isinstance(inputs.get("assets"), Mapping) else None
    scenes = _scene_list(inputs.get("scenes"))

    if subject == "images":
        assets = None
    elif subject == "videos":
        images = None

    image_units = units_from_storyboard(
        images, aspect_ratio=aspect, target_node_id=node_id, scenes=scenes
    )
    video_units = units_from_video_assets(
        assets, aspect_ratio=aspect, require_audio=require_audio, target_node_id=node_id
    )

    if not image_units and not video_units:
        raise AdapterError(
            "MISSING_REQUIRED_INPUT",
            f"Review has nothing to inspect for subject '{subject}'",
        )

    semantic = None
    if merged.get("semantic"):
        semantic = _SemanticPass(provider_id(DOMAIN, merged), merged, context)

    progress = context_value(context, "progress")
    findings: list[dict[str, Any]] = []
    total = len(image_units) + len(video_units)
    done = 0

    for kind, units, evaluate in (
        ("image", image_units, evaluate_image_unit),
        ("video", video_units, evaluate_video_unit),
    ):
        for unit in units:
            # `run_semantic=False`: the gate's semantic path hardcodes the
            # `semantic` package, so the selected instance runs here instead.
            findings.extend(
                _as_dict(issue)
                for issue in evaluate(unit, run_semantic=False, job_id=job_id)
            )
            if semantic is not None:
                findings.extend(semantic(unit, subject_kind=kind, job_id=job_id))
            done += 1
            if callable(progress):
                progress(f"Reviewed {done}/{total}")

    blocking_severities = _blocking_severities()
    blocking = [
        issue
        for issue in findings
        if str(issue.get("severity") or "") in blocking_severities
    ]
    payload = {
        "job_id": job_id,
        "subject": subject,
        "semantic": semantic is not None,
        "units_checked": total,
        "images_checked": len(image_units),
        "videos_checked": len(video_units),
        "issue_count": len(findings),
        "blocking_issue_count": len(blocking),
        "clean": not findings,
        "issues": findings,
    }

    if blocking and merged.get("fail_on_blocking"):
        raise AdapterError(
            QUALITY_GATE_FAILED,
            f"Review found {len(blocking)} blocking issue(s)",
            details=payload,
        )

    return outputs(issues=payload)
