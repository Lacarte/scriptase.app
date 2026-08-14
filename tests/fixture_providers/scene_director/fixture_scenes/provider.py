"""Offline scene-blueprint fixture — deterministic, credential-free.

Implements the same `generate(segments, configuration, project_id=…)` seam
`adapters/scenes.py` dispatches through, so the real `scenes.blueprint` node
runs this provider with no adapter, registry, or component edit.
"""

from __future__ import annotations

import os
from typing import Any, Mapping


class FixtureScenesProvider:
    """A scene_blueprint provider whose output depends only on its inputs."""

    def generate(
        self,
        segments: Mapping[str, Any],
        configuration: Mapping[str, Any],
        *,
        project_id: str,
    ) -> dict:
        import config
        from scriptase.shared.io_utils import safe_json_write

        all_segments = list((segments or {}).get("segments") or [])
        speech = [s for s in all_segments if not (isinstance(s, Mapping) and s.get("is_filler"))]
        if not speech:
            speech = all_segments
        prefix = str((configuration or {}).get("label_prefix") or "Fixture")
        style = str((configuration or {}).get("style") or "cinematic")
        scenes = []
        for i, seg in enumerate(speech):
            words = ""
            if isinstance(seg, Mapping):
                words = str(seg.get("words") or "")
            else:
                words = str(seg)
            scenes.append({
                "index": i,
                "title": f"{prefix} {i + 1}",
                "narrative_role": "hook" if i == 0 else ("cta" if i == len(speech) - 1 else "buildup"),
                "type_of_scene": "video",
                "image_prompt": f"{style} illustration of: {words[:80]}",
                "text_content": None,
                "start": float(i),
                "end": float(i) + 1.0,
            })
        document = {
            "project_id": project_id,
            "scenes": scenes,
            "style_spec": {"id": style},
            "style_prompt": style,
            "analysis": {"visual_style": style},
            "coherence_score": 1.0,
            "coherence_warnings": [],
            "coherence_metrics": {},
            "sfx_report": {"hint_count": 0, "hint_max": 3, "hint_min": 0, "dropped": 0},
            "total_duration": float(len(scenes)),
            "style": style,
            "provider": "fixture_scenes",
            "scene_blueprints": [],
        }
        path = os.path.join(config.OUTPUT_DIR, "scenes", project_id, "scenes.json")
        safe_json_write(path, document, indent=2)
        return {**document, "path": path}

    def shutdown(self) -> None:
        return None


def create() -> FixtureScenesProvider:
    return FixtureScenesProvider()


def health_check(settings: dict) -> dict:
    return {
        "status": "ok",
        "latency_ms": 0,
        "message": "Fixture scene provider is offline-only",
    }


def validate_settings(settings: dict) -> list[dict]:
    return []
