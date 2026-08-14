"""Offline scene-blueprint fixture — deterministic, credential-free.

Implements the same `generate(segments, configuration, project_id=…)` seam
`adapters/scene_director.py` dispatches through, so the real `scenes.blueprint`
node runs this provider with no adapter, registry, or component edit.

Step 5.2: consumes structured Channel ``visual_direction`` so two Channels
with different patterns produce measurably different SceneSpecs offline.
Prompt wording for the fixture image_prompt lives only in this provider package.
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
        from scriptase.modules.scene_director.providers.contract import (
            visual_direction_from_config,
        )
        from scriptase.modules.scene_director.visual_direction import (
            plan_scene_specs_from_direction,
        )
        from scriptase.shared.io_utils import safe_json_write

        all_segments = list((segments or {}).get("segments") or [])
        speech = [
            s for s in all_segments
            if not (isinstance(s, Mapping) and s.get("is_filler"))
        ]
        if not speech:
            speech = all_segments

        cfg = dict(configuration or {})
        direction = visual_direction_from_config(cfg)
        style = str(cfg.get("style") or direction.style or "cinematic")
        script = str(cfg.get("text") or cfg.get("script") or "")
        prefix = str(cfg.get("label_prefix") or "Fixture")

        specs = plan_scene_specs_from_direction(
            speech,
            direction,
            script=script,
            style_spec={"identity": {"render_mode": style}},
        )

        scenes = []
        for i, spec in enumerate(specs):
            words = spec.narration
            # Provider-owned wording: structured composition from typed inputs.
            shot = spec.camera or "medium"
            lighting = spec.lighting or ""
            palette = direction.palette or ""
            parts = [shot, f"{prefix.lower()} illustration of: {words[:80]}"]
            if lighting:
                parts.append(lighting)
            if palette:
                parts.append(f"palette {palette}")
            if style:
                parts.append(style)
            image_prompt = ", ".join(p for p in parts if p)

            row = spec.to_port_dict()
            row["title"] = f"{prefix} {i + 1}"
            row["image_prompt"] = image_prompt
            if not row.get("type_of_scene"):
                row["type_of_scene"] = "video"
            if row.get("start") is None:
                row["start"] = float(i)
            if row.get("end") is None:
                row["end"] = float(i) + 1.0
            scenes.append(row)

        if not scenes:
            # Degenerate empty input still yields one placeholder so the
            # result envelope contract (non-empty scenes) holds in edge tests.
            scenes = [{
                "index": 0,
                "title": f"{prefix} 1",
                "narrative_role": "hook",
                "type_of_scene": "video",
                "image_prompt": f"{style} illustration",
                "text_content": None,
                "start": 0.0,
                "end": 1.0,
            }]

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
            "visual_direction": direction.model_dump(mode="json"),
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
