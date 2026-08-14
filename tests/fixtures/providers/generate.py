"""Regenerate the provider-boundary fixtures (contracts.md §46).

Run from the repository root:

    venv/Scripts/python.exe tests/fixtures/providers/generate.py

`request.json` and `raw_response.json` are **recorded by a human** and are never
touched here. This script only derives each `expected_result.json` from the
recorded response through the shared legacy adapters, and rewrites
`manifest.json` with the SHA-256 of every file, so an accidental edit fails a
test rather than silently changing the meaning of every provider test
(§46.4 rule 4).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))
sys.path.insert(0, ROOT)

from scriptase.shared.io_utils import safe_json_write  # noqa: E402
from scriptase.providers import fixtures, legacy  # noqa: E402
from scriptase.providers.results import coerce_result  # noqa: E402


def _tts_kokoro(raw):
    return legacy.tts_metadata_to_result(
        raw,
        audio_ref="tts/pm_SAMPLE/voice.wav",
        manifest_ref="tts/pm_SAMPLE/tts.json",
        provider_id="kokoro",
        provider_version="1.0.0",
    )


def _visual(domain, provider_id, manifest_ref, version):
    def build(raw):
        return legacy.visual_manifest_to_result(
            raw,
            domain=domain,
            provider_id=provider_id,
            manifest_ref=manifest_ref,
            provider_version=version,
        )
    return build


def _script_random_template(raw):
    """Hand-written catalog pick -> §32.1 envelope (step 13.1)."""
    from scriptase.modules.script.prompts import WORDS_PER_SECOND

    text = str(raw.get("text") or "")
    words = len(text.split())
    document = {
        "story_text": text,
        "sections": {},
        "metadata": {
            "preset_style": "cinematic",
            "language": "english",
            "story_category": raw.get("type") or "",
            "story_tone": "",
            "duration": 45,
            "word_count": words,
            "estimated_duration": round(words / WORDS_PER_SECOND),
            "template_type": raw.get("type") or "",
            "template_styles": ",".join(raw.get("styles") or []),
            "template_index": raw.get("index"),
            "seed": raw.get("seed"),
            "timestamp": "2026-01-01T00:00:00+00:00",
        },
    }
    return legacy.script_document_to_result(
        document,
        document_ref="stories/pm_SAMPLE/story.json",
        provider_id="random_template",
        provider_version="1.0.0",
    )


def _script_gemini(raw):
    """Recorded n8n story webhook body -> §32.1 envelope (step 13.2)."""
    from scriptase.modules.script.engine import parse_story_sections
    from scriptase.modules.script.prompts import WORDS_PER_SECOND

    raw_text = str(raw.get("story_text") or raw.get("output") or raw.get("text") or "")
    parsed = parse_story_sections(raw_text)
    estimated = round(parsed["word_count"] / WORDS_PER_SECOND)
    document = {
        "story_text": parsed["story_text"],
        "sections": parsed["sections"],
        "metadata": {
            "preset_style": "neural_glow",
            "language": "english",
            "story_category": "horror",
            "story_tone": "suspenseful",
            "duration": 50,
            "word_count": parsed["word_count"],
            "estimated_duration": estimated,
            # Dropped by the legacy adapter — provenance owns identity (P33).
            "provider": "gemini",
            "generation_time": 1.25,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "concept_family": "recurring dreams that bleed into waking life",
        },
    }
    return legacy.script_document_to_result(
        document,
        document_ref="stories/pm_SAMPLE/story.json",
        provider_id="gemini",
        provider_version="1.0.0",
    )


def _scene_blueprint_n8n(raw):
    """Recorded n8n scene-blueprint webhook body -> §32.2 envelope (step 13.4)."""
    document = {
        "scenes": list(raw.get("scenes") or []),
        "analysis": dict(raw.get("analysis") or {}),
        "style_spec": {"id": "cinematic", "label": "Cinematic"},
        "style_prompt": "cinematic realistic",
        "coherence_score": 0.92,
        "coherence_warnings": [],
        "coherence_metrics": {"role_mismatches": 0},
        "sfx_report": {"hint_count": 0, "hint_max": 3, "hint_min": 0, "dropped": 0},
        "total_duration": 12.5,
        "style": "cinematic",
        "scene_blueprints": [],
        "provider": "n8n",
        "generation_time": 2.5,
        "timestamp": "2026-01-01T00:00:00+00:00",
    }
    return legacy.scenes_document_to_result(
        document,
        document_ref="scenes/pm_SAMPLE/scenes.json",
        provider_id="n8n",
        provider_version="1.0.0",
    )


BUILDERS = {
    ("tts", "kokoro"): _tts_kokoro,
    ("image", "wavespeed_webhook"): _visual(
        "image", "wavespeed_webhook", "storyboard/pm_SAMPLE/storyboard.json", "1.0.0"
    ),
    ("video", "kie_ai"): _visual(
        "video", "kie_ai", "animator/pm_SAMPLE/grabber_job.json", "1.0.0"
    ),
    ("script", "random_template"): _script_random_template,
    ("script", "gemini"): _script_gemini,
    ("scene_director", "n8n"): _scene_blueprint_n8n,
}


def _drop_rotations() -> None:
    """Remove the `.bak` rotations `safe_json_write` leaves in the fixture tree."""
    for root, _dirs, files in os.walk(fixtures.fixture_root()):
        for name in files:
            if name.endswith(".bak"):
                os.unlink(os.path.join(root, name))


def main() -> int:
    for domain, provider_id in fixtures.list_boundaries():
        builder = BUILDERS.get((domain, provider_id))
        if builder is None:
            print(f"skip {domain}/{provider_id}: no builder registered")
            continue
        raw = fixtures.load_fixture(domain, provider_id, "raw_response.json")
        result = coerce_result(
            builder(raw),
            domain=domain,
            provider_id=provider_id,
            provider_version="1.0.0",
        )
        path = os.path.join(
            fixtures.fixture_dir(domain, provider_id), "expected_result.json"
        )
        safe_json_write(path, result.to_dict(), indent=2)
        print(f"wrote {domain}/{provider_id}/expected_result.json")

    print(f"wrote {fixtures.write_manifest()}")
    _drop_rotations()
    problems = fixtures.validate_fixtures()
    for problem in problems:
        print(f"PROBLEM: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
