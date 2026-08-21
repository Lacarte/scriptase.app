"""Lab experiments — run a (variant × channel × provider) and score the result.

An experiment run generates one script through the real script provider, using
a Channel's resolved dimensions as the inputs and a prompt variant's knobs as
overrides, then scores it with the offline Virality Scorer. The prompt, the
script, and the score are stored so variants can be compared and ranked.

The prompt *engine* stays in code; a variant only parameterizes its inputs.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, Mapping

from config import OUTPUT_DIR
from scriptase.shared.io_utils import safe_json_write
from scriptase.modules.lab.variants import get_variant
from scriptase.modules.script.engine import parse_story_sections
from scriptase.modules.script.prompts import (
    WORDS_PER_SECOND,
    build_story_system_prompt,
    build_story_user_prompt,
    choose_story_concept_family,
    compute_word_target,
)
from scriptase.modules.viral.service import score_script

RUNS_DIR = os.path.join(OUTPUT_DIR, "lab", "runs")


class ExperimentError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _channel_inputs(channel_id: str | None) -> dict:
    """Resolve a Channel into the prompt inputs (niche/style/tone/duration)."""
    if not channel_id:
        return {}
    from scriptase.channels.presets import resolve_niche
    from scriptase.channels.store import ChannelNotFound, get_channel

    try:
        channel = get_channel(channel_id)
    except ChannelNotFound:
        raise ExperimentError("CHANNEL_NOT_FOUND", "That channel does not exist")

    # A Channel stores its niche on content; resolve_niche fills the dimensions.
    niche_preset = ""
    for candidate in (getattr(channel.content, "niche", ""),):
        if candidate:
            niche_preset = candidate
            break
    resolved = resolve_niche({
        "niche_preset": niche_preset,
        "visual_style": channel.visual_direction.style,
        "story_tone": channel.content.tone,
    })
    return {
        "niche_preset": niche_preset,
        "preset_style": resolved.get("visual_style") or "cinematic",
        "story_category": resolved.get("category") or channel.content.niche or "",
        "story_tone": resolved.get("story_tone") or channel.content.tone or "",
        "language": channel.content.language or "english",
        "duration": channel.content.duration_target or 60,
    }


def build_prompt(*, channel_id=None, variant_id="builtin", overrides=None) -> dict:
    """Compose the system + user prompt for a (channel, variant) pair.

    `overrides` is a plain inputs dict (niche/style/tone/duration/idea) that
    wins over the channel's resolved values — the Lab lets a run edit them.
    """
    variant = get_variant(variant_id) or get_variant("builtin")
    base = _channel_inputs(channel_id)
    base.update({k: v for k, v in dict(overrides or {}).items() if v not in (None, "")})

    preset_style = str(base.get("preset_style") or "cinematic").strip() or "cinematic"
    story_category = str(base.get("story_category") or "").strip()
    language = str(base.get("language") or "english").strip() or "english"
    idea = str(base.get("idea") or "").strip() or None
    niche_preset = str(base.get("niche_preset") or "").strip() or None
    try:
        duration = int(base.get("duration") or 60)
    except (TypeError, ValueError):
        duration = 60

    # Variant knobs override the resolved tone / level.
    story_tone = (variant.get("tone_override") or base.get("story_tone") or "").strip() or None
    language_level = (variant.get("language_level") or "").strip() or None

    concept_family = choose_story_concept_family(
        preset_style, story_category, language, niche_preset=niche_preset
    )
    system_prompt = build_story_system_prompt(
        preset_style, story_category, duration, language,
        story_tone=story_tone, language_level=language_level,
    )
    user_prompt = build_story_user_prompt(
        preset_style, story_category, duration, language,
        idea=idea, niche_preset=niche_preset, concept_family=concept_family,
        angle_pool=variant.get("angle_pool") or None,
        extra_directives=variant.get("extra_directives") or None,
        word_target_ratio=variant.get("word_target_ratio") or 1.0,
    )
    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "word_target": round(compute_word_target(duration) * float(variant.get("word_target_ratio") or 1.0)),
        "temperature": variant.get("temperature"),
        "structure": ["hook", "build", "climax", "cta"],
        "inputs": {
            "preset_style": preset_style,
            "story_category": story_category,
            "story_tone": story_tone or "",
            "language": language,
            "language_level": language_level or "",
            "duration": duration,
            "niche_preset": niche_preset or "",
            "idea": idea or "",
            "concept_family": concept_family,
        },
        "variant": {"id": variant.get("id"), "name": variant.get("name")},
        "channel_id": channel_id or "",
    }


def run_experiment(
    *,
    channel_id=None,
    variant_id="builtin",
    provider_id="script_n8n",
    overrides=None,
    webhook_caller=None,
) -> dict:
    """Generate one script for a (channel, variant, provider) and score it.

    Returns a stored run record: the prompt, the generated script + sections,
    and the Virality Score (0-100 + per-dimension breakdown). The offline
    scorer means a run is measurable immediately, before any view data exists.
    """
    prompt = build_prompt(channel_id=channel_id, variant_id=variant_id, overrides=overrides)

    started = time.perf_counter()
    raw_text = _generate(provider_id, prompt, webhook_caller=webhook_caller)
    elapsed = round(time.perf_counter() - started, 3)

    parsed = parse_story_sections(raw_text)
    score = score_script(
        sections=parsed["sections"],
        story_text=parsed["story_text"],
        target_duration=prompt["inputs"]["duration"],
    )

    record = {
        "id": f"run_{format(int(time.time() * 1000) & 0xFFFFFFFFFF, 'x')}",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "channel_id": channel_id or "",
        "provider_id": provider_id,
        "variant": prompt["variant"],
        "inputs": prompt["inputs"],
        "prompt": {
            "system_prompt": prompt["system_prompt"],
            "user_prompt": prompt["user_prompt"],
            "word_target": prompt["word_target"],
        },
        "story_text": parsed["story_text"],
        "sections": parsed["sections"],
        "word_count": parsed["word_count"],
        "estimated_duration": round(parsed["word_count"] / WORDS_PER_SECOND),
        "generation_time": elapsed,
        "score": {
            "score": score.score,
            "band": score.band,
            "dimensions": [
                {"id": d.id, "score": round(d.score, 3), "points": d.points}
                for d in score.dimensions
            ],
        },
    }
    safe_json_write(os.path.join(RUNS_DIR, f"{record['id']}.json"), record, indent=2)
    return record


def _generate(provider_id: str, prompt: Mapping[str, Any], *, webhook_caller=None) -> str:
    """Send the prompt through the resolved script provider's webhook."""
    import os as _os

    from config import N8N_STORY_WEBHOOK_URL
    from scriptase.shared.security import is_safe_webhook_url
    from scriptase.shared.webhooks import call_webhook

    webhook_url = N8N_STORY_WEBHOOK_URL
    allow_private = _os.environ.get("STS_ALLOW_PRIVATE_WEBHOOKS", "true").lower() == "true"
    if not is_safe_webhook_url(webhook_url, allow_private=allow_private):
        raise ExperimentError("WEBHOOK_UNSAFE", "The story webhook URL is not allowed")

    payload = {
        "system_prompt": prompt["system_prompt"],
        "user_prompt": prompt["user_prompt"],
        "word_target": prompt["word_target"],
        "structure": prompt["structure"],
        "language": prompt["inputs"]["language"],
        "story_category": prompt["inputs"]["story_category"],
        "story_tone": prompt["inputs"]["story_tone"],
        "duration": prompt["inputs"]["duration"],
    }
    if prompt.get("temperature") is not None:
        payload["temperature"] = prompt["temperature"]

    caller = webhook_caller or call_webhook
    try:
        result = caller(webhook_url, payload, timeout=120, label="Lab experiment")
    except Exception as exc:  # noqa: BLE001 — never forward a third-party body (L2)
        raise ExperimentError("GENERATION_FAILED", "Script generation failed") from exc

    for key in ("story_text", "script_text", "output", "text", "response"):
        value = result.get(key) if isinstance(result, Mapping) else None
        if isinstance(value, str) and value.strip():
            return value
    raise ExperimentError("EMPTY_RESULT", "The provider returned no script text")


def list_runs(limit: int = 50) -> list[dict]:
    """Recent experiment runs, newest first (summary fields only)."""
    if not os.path.isdir(RUNS_DIR):
        return []
    rows: list[dict] = []
    for name in os.listdir(RUNS_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(RUNS_DIR, name), encoding="utf-8") as fh:
                rows.append(json.load(fh))
        except (OSError, json.JSONDecodeError):
            continue
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows[: max(1, int(limit or 50))]


def variant_leaderboard() -> list[dict]:
    """Average score per variant across stored runs — the measurement payoff."""
    agg: dict[str, dict] = {}
    for run in list_runs(limit=500):
        variant = run.get("variant") or {}
        vid = variant.get("id") or "builtin"
        score = (run.get("score") or {}).get("score")
        if not isinstance(score, (int, float)):
            continue
        bucket = agg.setdefault(vid, {"variant_id": vid, "name": variant.get("name") or vid, "runs": 0, "total": 0})
        bucket["runs"] += 1
        bucket["total"] += score
    board = [
        {"variant_id": b["variant_id"], "name": b["name"], "runs": b["runs"],
         "avg_score": round(b["total"] / b["runs"], 1)}
        for b in agg.values() if b["runs"]
    ]
    board.sort(key=lambda b: b["avg_score"], reverse=True)
    return board


__all__ = [
    "ExperimentError",
    "build_prompt",
    "list_runs",
    "run_experiment",
    "variant_leaderboard",
]
