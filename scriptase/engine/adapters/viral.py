"""Workflow adapter for the Script Analyzer node (`script.analyze`) — step 16.2.

Step 16.1 built the scorer as an importable service with no transport and no
node. This adapter is the node, and it deliberately contains no scoring logic:
it assembles a `ViralRequest` from whichever ports the graph actually connected
and dispatches it through the provider hub. Everything that decides a number
lives behind the `viral` domain, so replacing the deterministic scorer with an
LLM judge is a package drop rather than an edit here (contracts §26).

The node never fails a run on a low score. Reporting and deciding stay separate:
step 16.3 hands the score to `scriptase.review.viral_gate`, which owns the
comparison against the Channel threshold and the ReviewIssue the Repair Router
acts on. This adapter still holds no policy — it does not know what a good score
is, only who to ask. For a canvas run that no Job owns, or a Channel that set no
threshold, the gate is inert and the score simply rides the `score` port with
nothing downstream obliged to read it.
"""

from __future__ import annotations

from typing import Any, Mapping

from .common import (
    AdapterError,
    context_value,
    outputs,
    provider_id,
    provider_run_options,
    resolve_provider,
    resolve_provider_binding,
)

DOMAIN = "viral"


def _script_text(value: Any) -> str:
    """The `script` port carries plain narration text (`project.py:script_input`)."""
    if isinstance(value, str):
        return value.strip()
    # A generic_json producer wired into the port is tolerated rather than
    # rejected: the analyzer is free, so degrading to "nothing to score" is a
    # worse outcome than reading the obvious key.
    if isinstance(value, Mapping):
        for key in ("story_text", "script", "text"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


def _story_document(value: Any) -> dict[str, Any]:
    """The `story` port payload from `story.generate`, or an empty document."""
    return dict(value) if isinstance(value, Mapping) else {}


def _narrative_roles(scenes_payload: Any) -> list[str]:
    """Ordered Scene Director roles, when the graph has already built scenes."""
    if not isinstance(scenes_payload, Mapping):
        return []
    scenes = scenes_payload.get("scenes")
    if not isinstance(scenes, list):
        return []
    roles: list[str] = []
    for scene in scenes:
        if not isinstance(scene, Mapping):
            continue
        role = scene.get("narrative_role")
        if isinstance(role, str) and role.strip():
            roles.append(role.strip())
    return roles


def _target_duration(config: Mapping[str, Any], story: Mapping[str, Any]) -> int | None:
    """Configured seconds, else the story document's, else the scorer default.

    The configured field defaults to `0` rather than `45` so "the operator set
    a duration" and "the operator left it alone" stay distinguishable. Without
    that, a node fresh out of the palette would silently outrank the duration
    the script was actually written to.
    """
    raw = config.get("target_duration")
    try:
        configured = int(float(raw)) if raw not in (None, "") else 0
    except (TypeError, ValueError):
        configured = 0
    if configured > 0:
        return configured

    metadata = story.get("metadata")
    if isinstance(metadata, Mapping):
        try:
            from_story = int(float(metadata.get("duration") or 0))
        except (TypeError, ValueError):
            from_story = 0
        if from_story > 0:
            return from_story

    # None lets `ViralRequest` apply DEFAULT_TARGET_DURATION rather than this
    # module keeping a second copy of the number.
    return None


def analyze(inputs, config, context):
    from scriptase.modules.viral.providers.contract import ViralRequest
    from scriptase.providers import boundary, settings_manager
    from scriptase.providers.hub import hub
    from scriptase.providers.invocation import build_invocation

    inputs = inputs or {}
    configuration = dict(config or {})

    # Scores belong to a Job the same way ReviewIssues do (contracts §9). The
    # project fallback keeps a canvas run's payload self-describing, and
    # `job_ANALYZE` only appears in isolated adapter tests that construct a
    # bare context. Only the real id can be gated against: a ReviewIssue keyed
    # by a project id would be a finding no Job could ever find (step 11.2).
    owning_job_id = str(context_value(context, "job_id", "") or "").strip()
    job_id = (
        owning_job_id
        or str(context_value(context, "project_id", "") or "").strip()
        or "job_ANALYZE"
    )
    node_id = str(context_value(context, "node_id", "") or "") or None

    story = _story_document(inputs.get("story"))
    request = ViralRequest(
        job_id=job_id,
        sections=story.get("sections") or {},
        story_text=_script_text(inputs.get("script")) or story.get("story_text") or "",
        target_duration=_target_duration(configuration, story),
        narrative_roles=_narrative_roles(inputs.get("scenes")),
    )
    if not request.has_content:
        raise AdapterError(
            "MISSING_REQUIRED_INPUT", "Script Analyzer has no script text to score"
        )

    selected = provider_id(DOMAIN, configuration)
    instance_id, type_id = resolve_provider_binding(DOMAIN, selected)
    provider = resolve_provider(DOMAIN, selected)
    package = hub.get(DOMAIN, type_id)

    saved = settings_manager.get_instance_settings(DOMAIN, instance_id)
    settings = (
        package.resolve_settings(saved, instance_id=instance_id)
        if package is not None
        else dict(saved)
    )
    invocation = build_invocation(
        context,
        domain=DOMAIN,
        provider_id=type_id,
        project_id=job_id,
        settings=settings,
        options=provider_run_options(DOMAIN, selected, configuration),
        provider_instance_id=instance_id,
    )
    result = boundary.invoke(
        lambda inv: provider.invoke(request, inv),
        invocation,
        provider_version=getattr(package, "version", "") or "",
        contract_version=getattr(package, "contract_version", 2) or 2,
    )

    score_document = dict(result.payload or {})

    # Step 16.3. Gating is the review package's call, not this adapter's, and
    # it is deliberately the last thing that happens: a threshold lookup or an
    # issue write that fails must not cost the run the score it just computed.
    verdict: dict[str, Any] = {"threshold": None, "passed": None, "issue_ids": []}
    if owning_job_id:
        from scriptase.review.viral_gate import gate_script_score

        verdict = gate_script_score(
            score_document, job_id=owning_job_id, target_node_id=node_id
        )

    return outputs(
        score={
            "job_id": job_id,
            "provider_id": selected,
            "provider_type": type_id,
            "target_duration": request.target_duration,
            # Flat copies of the two values every consumer wants, so a
            # summarized execution record still carries the verdict.
            "score": score_document.get("score"),
            "band": score_document.get("band"),
            # The Channel bar this score was measured against, or None when no
            # Channel set one. `passed` is tri-state for that reason: None is
            # "not measured", which is not the same claim as "passed".
            "threshold": verdict.get("threshold"),
            "passed": verdict.get("passed"),
            # Durable ReviewIssue ids. The Repair Router reads issues from the
            # store by id, never from this payload — the execution record only
            # keeps a summarized copy of node outputs.
            "issue_ids": verdict.get("issue_ids") or [],
            # The frozen 16.1 contract, unmodified. `ViralScore.model_validate`
            # accepts this key exactly, and that round trip is how Review reads
            # the breakdown without this adapter owning a second schema.
            "viral_score": score_document,
        }
    )
