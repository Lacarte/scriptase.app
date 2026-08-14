"""Step 5.1: SceneSpec contract — round-trip and adapter consumption.

Done when:
  * every SceneSpec field round-trips through the provider result envelope
  * the image and video adapters read SceneSpec rather than loose dicts
"""

from __future__ import annotations

import unittest
from unittest import mock

from pydantic import ValidationError

from scriptase.engine.adapters import image as image_adapter
from scriptase.engine.adapters import video as video_adapter
from scriptase.modules.image.providers.contract import StoryboardRequest
from scriptase.modules.scene_director.providers.base import SceneBlueprintProvider
from scriptase.modules.scene_director.providers.contract import (
    SCENESPEC_FIELDS,
    SceneBlueprintResultPayload,
    SceneItem,
    SceneSpec,
    coerce_scene_specs,
    stamp_scene_specs_from_segments,
)
from scriptase.modules.video.providers.contract import AnimatorRequest
from scriptase.providers.invocation import build_invocation
from scriptase.providers.legacy import scenes_document_to_result
from scriptase.providers.results import coerce_result


FULL_SPEC_FIELDS = {
    "scene_id": "scn_ABC123",
    "narration": "At sunrise, he finally left the village.",
    "visual_description": "Young man leaving a rural village at sunrise.",
    "image_prompt": "wide rear tracking shot, young man leaving rural village, warm sunrise, cinematic",
    "motion_prompt": "Slow tracking motion; subtle clothing movement in wind.",
    "camera": "Wide rear tracking shot.",
    "lighting": "Warm early-morning sunrise.",
    "mood": "Hopeful, reflective.",
    "continuity": "Same protagonist and clothing as previous scene.",
    "narrative_role": "hook",
    "overlay_hints": ["LEAVE"],
    "sfx_hints": ["wind_gust"],
}


class SceneSpecModelTests(unittest.TestCase):
    def test_scenespec_is_sceneitem_alias(self):
        self.assertIs(SceneItem, SceneSpec)

    def test_all_contract_fields_present(self):
        for name in SCENESPEC_FIELDS:
            self.assertTrue(hasattr(SceneSpec, "model_fields"))
            self.assertIn(name, SceneSpec.model_fields)

    def test_coerce_maps_legacy_aliases(self):
        spec = SceneSpec.coerce(
            {
                "id": "scn_LEGACY1",
                "index": 2,
                "words": "hello world",
                "prompt": "a lighthouse",
                "camera_move": "slow push-in",
                "shot_type": "wide",
                "sfx_hint": "whoosh",
                "overlay_hint": "CTA",
                "text_content": "THE SHIFT",
                "type_of_scene": "video",
                "title": "First glimpse",
            },
            position=9,
        )
        self.assertEqual(spec.scene_id, "scn_LEGACY1")
        self.assertEqual(spec.index, 2)
        self.assertEqual(spec.narration, "hello world")
        self.assertEqual(spec.image_prompt, "a lighthouse")
        self.assertEqual(spec.motion_prompt, "slow push-in")
        self.assertEqual(spec.camera, "slow push-in")
        self.assertEqual(spec.sfx_hints, ["whoosh"])
        self.assertIn("CTA", spec.overlay_hints)
        self.assertEqual(spec.type_of_scene, "video")

    def test_coerce_preserves_extras(self):
        spec = SceneSpec.coerce(
            {
                "index": 0,
                "image_prompt": "p",
                "anchor_used": True,
                "motif_used": "lighthouse",
            }
        )
        dumped = spec.model_dump()
        self.assertTrue(dumped.get("anchor_used"))
        self.assertEqual(dumped.get("motif_used"), "lighthouse")

    def test_stamp_scene_ids_from_segments(self):
        scenes = [
            {"index": 0, "image_prompt": "a"},
            {"index": 1, "image_prompt": "b", "scene_id": "scn_KEEP01"},
        ]
        segments = [
            {"index": 0, "words": "first line", "scene_id": "scn_AAA111", "is_filler": False},
            {"index": 1, "words": "second line", "scene_id": "scn_BBB222", "is_filler": False},
        ]
        stamped = stamp_scene_specs_from_segments(scenes, segments)
        self.assertEqual(stamped[0].scene_id, "scn_AAA111")
        self.assertEqual(stamped[0].narration, "first line")
        # Existing scene_id wins.
        self.assertEqual(stamped[1].scene_id, "scn_KEEP01")
        self.assertEqual(stamped[1].narration, "second line")


class SceneSpecEnvelopeRoundTripTests(unittest.TestCase):
    """Every §8 field survives the provider result envelope."""

    def _full_document(self) -> dict:
        scene = {
            **FULL_SPEC_FIELDS,
            "index": 0,
            "start": 0.0,
            "end": 3.5,
            "type_of_scene": "video",
            "title": "Departure",
            "text_content": None,
            "anchor_used": True,
        }
        return {
            "scenes": [scene],
            "style_spec": {"id": "cinematic"},
            "style_prompt": "cinematic realistic",
            "analysis": {"mood": "hopeful"},
            "coherence_score": 0.91,
            "coherence_warnings": [],
            "coherence_metrics": {"role_mismatches": 0},
            "sfx_report": {"hint_count": 1, "hint_max": 3, "hint_min": 0, "dropped": 0},
            "total_duration": 3.5,
            "provider": "fixture_scenes",
            "scene_blueprints": [{"index": 0, "narrative_role": "hook"}],
            "style": "cinematic",
        }

    def test_payload_from_mapping_round_trips_all_fields(self):
        payload = SceneBlueprintResultPayload.from_mapping(self._full_document())
        self.assertEqual(len(payload.scenes), 1)
        scene = payload.scenes[0]
        for name, expected in FULL_SPEC_FIELDS.items():
            self.assertEqual(getattr(scene, name), expected, msg=name)

        dumped = payload.model_dump(mode="python")
        port = payload.scenes_as_dicts()[0]
        for name, expected in FULL_SPEC_FIELDS.items():
            self.assertEqual(dumped["scenes"][0][name], expected, msg=f"dump:{name}")
            self.assertEqual(port[name], expected, msg=f"port:{name}")

        # Re-coerce the dumped scenes and prove nothing was lost.
        again = SceneBlueprintResultPayload.from_mapping(dumped)
        for name, expected in FULL_SPEC_FIELDS.items():
            self.assertEqual(getattr(again.scenes[0], name), expected, msg=f"again:{name}")

    def test_provider_invoke_envelope_round_trips(self):
        document = self._full_document()
        path = "scenes/pm_SAMPLE/scenes.json"

        class FullSpecProvider(SceneBlueprintProvider):
            def generate(self, segments, configuration, *, project_id):
                return {**document, "path": path, "project_id": project_id}

        invocation = build_invocation(
            None,
            domain="scene_director",
            provider_id="fixture_scenes",
            project_id="pm_SAMPLE",
            output_dir=".",
            settings={},
            options={},
        )
        # normalize_ref requires a path under OUTPUT_DIR — stub it.
        with mock.patch(
            "scriptase.providers.results.normalize_ref",
            return_value=path,
        ):
            result = FullSpecProvider().invoke(
                {
                    "script": "At sunrise",
                    "segments": [{"index": 0, "words": "At sunrise"}],
                },
                invocation,
            )

        # invoke() returns a ProviderResult whose payload is the envelope body.
        payload = result.payload if hasattr(result, "payload") else result
        if not isinstance(payload, dict):
            payload = dict(payload)
        scenes = payload["scenes"]
        self.assertEqual(len(scenes), 1)
        for name, expected in FULL_SPEC_FIELDS.items():
            self.assertEqual(scenes[0][name], expected, msg=f"envelope:{name}")

        # Envelope itself re-validates as the frozen payload.
        reloaded = SceneBlueprintResultPayload.from_mapping(payload)
        for name, expected in FULL_SPEC_FIELDS.items():
            self.assertEqual(getattr(reloaded.scenes[0], name), expected)

        # And survives the shared coerce_result boundary.
        envelope = coerce_result(
            result,
            domain="scene_director",
            provider_id="fixture_scenes",
        )
        self.assertEqual(envelope.status, "succeeded")
        for name, expected in FULL_SPEC_FIELDS.items():
            self.assertEqual(
                envelope.payload["scenes"][0][name],
                expected,
                msg=f"coerced:{name}",
            )

    def test_legacy_document_helper_round_trips(self):
        result = scenes_document_to_result(
            self._full_document(),
            document_ref="scenes/pm_SAMPLE/scenes.json",
            provider_id="n8n",
        )
        scenes = result.payload["scenes"]
        for name, expected in FULL_SPEC_FIELDS.items():
            self.assertEqual(scenes[0][name], expected, msg=name)


class ImageVideoAdapterSceneSpecTests(unittest.TestCase):
    """Image and video adapters read SceneSpec rather than loose dicts."""

    def test_storyboard_from_scene_specs_uses_image_prompt(self):
        specs = coerce_scene_specs([
            {
                "scene_id": "scn_IMG001",
                "index": 3,
                "image_prompt": "still of a lighthouse",
                "motion_prompt": "camera orbits the lighthouse",
            },
            {
                # No image prompt — skipped.
                "index": 4,
                "motion_prompt": "only motion",
            },
        ])
        request = StoryboardRequest.from_scene_specs(specs)
        self.assertEqual(len(request.scenes), 1)
        self.assertEqual(request.scenes[0].index, 3)
        self.assertEqual(request.scenes[0].prompt, "still of a lighthouse")

    def test_animator_from_scene_specs_prefers_motion_prompt(self):
        specs = coerce_scene_specs([
            {
                "scene_id": "scn_VID001",
                "index": 1,
                "image_prompt": "still of a lighthouse",
                "motion_prompt": "slow orbit around the lighthouse",
                "reference_ref": "storyboard/pm_X/scene_1.png",
            }
        ])
        request = AnimatorRequest.from_scene_specs(specs)
        self.assertEqual(len(request.scenes), 1)
        self.assertEqual(request.scenes[0].prompt, "slow orbit around the lighthouse")
        self.assertEqual(
            request.scenes[0].reference_ref,
            "storyboard/pm_X/scene_1.png",
        )

    def test_animator_falls_back_to_image_prompt(self):
        specs = coerce_scene_specs([
            {"index": 0, "image_prompt": "a windy ridge"},
        ])
        request = AnimatorRequest.from_scene_specs(specs)
        self.assertEqual(request.scenes[0].prompt, "a windy ridge")

    def test_image_adapter_coerces_scenespec_before_request(self):
        captured = {}

        def fake_run_manifest_job(**kwargs):
            captured["request"] = kwargs["request"]
            return {"total": 1, "ready": 1, "errors": 0, "scene_statuses": {}}

        with mock.patch.object(image_adapter, "run_manifest_job", side_effect=fake_run_manifest_job), \
             mock.patch.object(image_adapter, "resolve_provider", return_value=object()), \
             mock.patch.object(image_adapter, "_resolved_settings", return_value={}), \
             mock.patch.object(image_adapter, "_canonical_provider_id", return_value="fixture"), \
             mock.patch.object(image_adapter, "provider_id", return_value="fixture"):
            result = image_adapter._step_storyboard(
                {
                    "scenes": [
                        {
                            **FULL_SPEC_FIELDS,
                            "index": 0,
                        }
                    ]
                },
                {"aspect_ratio": "9:16", "style": "cinematic"},
                "pm_TEST",
                mock.Mock(project_id="pm_TEST"),
            )

        self.assertEqual(result["ready"], 1)
        request = captured["request"]
        self.assertIsInstance(request, StoryboardRequest)
        self.assertEqual(request.scenes[0].prompt, FULL_SPEC_FIELDS["image_prompt"])

    def test_video_adapter_coerces_scenespec_before_request(self):
        captured = {}

        def fake_run_manifest_job(**kwargs):
            captured["request"] = kwargs["request"]
            return {"total": 1, "ready": 1, "errors": 0}

        with mock.patch.object(video_adapter, "run_manifest_job", side_effect=fake_run_manifest_job), \
             mock.patch.object(video_adapter, "resolve_provider", return_value=object()), \
             mock.patch.object(video_adapter, "_resolved_settings", return_value={}), \
             mock.patch.object(video_adapter, "_canonical_provider_id", return_value="fixture"), \
             mock.patch.object(video_adapter, "provider_id", return_value="fixture"):
            result = video_adapter._step_assets(
                {
                    "scenes": [
                        {
                            **FULL_SPEC_FIELDS,
                            "index": 0,
                        }
                    ]
                },
                {"aspect_ratio": "9:16", "mode": "video"},
                "pm_TEST",
                mock.Mock(project_id="pm_TEST"),
            )

        self.assertEqual(result["ready"], 1)
        request = captured["request"]
        self.assertIsInstance(request, AnimatorRequest)
        self.assertEqual(request.scenes[0].prompt, FULL_SPEC_FIELDS["motion_prompt"])

    def test_empty_scenes_raise_validation(self):
        with self.assertRaises(ValidationError):
            StoryboardRequest.from_scene_specs(
                coerce_scene_specs([{"index": 0, "narration": "no prompt"}])
            )
        with self.assertRaises(ValidationError):
            AnimatorRequest.from_scene_specs(
                coerce_scene_specs([{"index": 0, "narration": "no prompt"}])
            )


if __name__ == "__main__":
    unittest.main()
