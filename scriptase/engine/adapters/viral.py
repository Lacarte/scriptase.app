"""Workflow adapter for the Script Analyzer node (`script.analyze`) — step 16.2.

Step 16.1 built the scorer as an importable service with no transport and no
node. This adapter is the node, and it deliberately contains no scoring logic:
it assembles a `ViralRequest` from whichever ports the graph actually connected
and dispatches it through the provider hub. Everything that decides a number
lives behind the `viral` domain, so replacing the deterministic scorer with an
LLM judge is a package drop rather than an edit here (contracts §26).

The node never fails a run on a low score. Reporting and deciding are separate
concerns: step 16.3 reads this output against the Channel threshold and raises
the ReviewIssue that the Repair Router acts on. Until then — and after, for a
canvas run that no Job owns — the score rides the `score` port and nothing
downstream is obliged to read it.
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
    # bare context.
    job_id = (
        str(context_value(context, "job_id", "") or "").strip()
        or str(context_value(context, "project_id", "") or "").strip()
        or "job_ANALYZE"
    )

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
            # The frozen 16.1 contract, unmodified. `ViralScore.model_validate`
            # accepts this key exactly, and that round trip is how Review reads
            # the breakdown without this adapter owning a second schema.
            "viral_score": score_document,
        }
    )
