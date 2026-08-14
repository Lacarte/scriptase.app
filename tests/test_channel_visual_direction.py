"""Step 5.2: Channel visual direction feeds the Director.

Done when:
  * two Channels with different patterns produce measurably different scene
    specs from the same script
  * a scan proves no prompt text exists outside provider packages
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from scriptase.jobs.channel_settings import channel_settings_from_snapshot
from scriptase.jobs.snapshot import build_channel_snapshot
from scriptase.modules.scene_director.providers.contract import (
    SceneBlueprintRequest,
    VisualDirectionInput,
    visual_direction_from_config,
)
from scriptase.modules.scene_director.visual_direction import (
    plan_scene_specs_from_direction,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPTASE_DIR = ROOT / "scriptase"

# Markers that identify scene-director LLM system prompt text. These must
# live under a providers/ package (contracts.md §8 / product non-negotiable).
SCENE_LLM_PROMPT_MARKERS = (
    "You are a visual scene planner and prompt writer",
    "You are a visual scene prompt writer",
    "Return ONLY valid JSON. No markdown. No code fences",
)

# Directories outside which scene LLM prompts are forbidden.
_PROVIDER_PATH_PART = f"{os.sep}providers{os.sep}"


SAME_SCRIPT = (
    "You notice the pattern for the first time. "
    "Then it starts appearing everywhere around you. "
    "That is when the story shifts. "
    "Now you cannot unsee it. "
    "What else have you been missing?"
)

SAME_SEGMENTS = [
    {"index": 0, "words": "You notice the pattern for the first time."},
    {"index": 1, "words": "Then it starts appearing everywhere around you."},
    {"index": 2, "words": "That is when the story shifts."},
    {"index": 3, "words": "Now you cannot unsee it."},
    {"index": 4, "words": "What else have you been missing?"},
]

CHANNEL_A_DIRECTION = {
    "style": "cinematic",
    "pattern": [
        {"narrative_role": "hook", "shot": "extreme close-up"},
        {"narrative_role": "buildup", "shot": "medium cinematic"},
        {"narrative_role": "peak", "shot": "wide environmental"},
        {"narrative_role": "cta", "shot": "symbolic visual"},
    ],
    "palette": "teal, amber, charcoal",
    "lighting": "warm golden hour rim light",
    "camera": "slow push-in",
    "character_style": "solitary silhouetted figure",
    "continuity": "same protagonist wardrobe across all scenes",
    "negative_prompt": "text overlays, watermarks, logos",
    "references": ["ref_brand_a"],
}

CHANNEL_B_DIRECTION = {
    "style": "noir",
    "pattern": [
        {"narrative_role": "hook", "shot": "bird's-eye geometric"},
        {"narrative_role": "buildup", "shot": "over-shoulder"},
        {"narrative_role": "peak", "shot": "low-angle dutch"},
        {"narrative_role": "cta", "shot": "centered symmetrical freeze"},
    ],
    "palette": "monochrome, deep crimson",
    "lighting": "hard chiaroscuro neon spill",
    "camera": "handheld micro-jitter",
    "character_style": "faceless trenchcoat detective",
    "continuity": "rain-slick streets and single neon sign",
    "negative_prompt": "daylight, cheerful colors, crowds",
    "references": ["ref_brand_b"],
}


class VisualDirectionRequestTests(unittest.TestCase):
    def test_request_accepts_structured_visual_direction(self):
        request = SceneBlueprintRequest.from_configuration(
            {
                "script": SAME_SCRIPT,
                "style": "cinematic",
                "visual_direction": CHANNEL_A_DIRECTION,
            },
            segments=SAME_SEGMENTS,
        )
        self.assertFalse(request.visual_direction.is_empty())
        self.assertEqual(len(request.visual_direction.pattern), 4)
        self.assertEqual(
            request.visual_direction.pattern[0].shot, "extreme close-up"
        )
        self.assertEqual(request.visual_direction.palette, "teal, amber, charcoal")
        self.assertEqual(
            request.visual_direction.lighting, "warm golden hour rim light"
        )
        self.assertEqual(
            request.visual_direction.negative_prompt,
            "text overlays, watermarks, logos",
        )

    def test_free_text_pattern_is_rejected(self):
        with self.assertRaises(Exception):
            VisualDirectionInput.model_validate({
                "pattern": "just do something cinematic",
            })

    def test_from_config_reads_nested_block(self):
        direction = visual_direction_from_config({
            "visual_direction": CHANNEL_B_DIRECTION,
        })
        self.assertEqual(direction.style, "noir")
        self.assertIn("hook", direction.pattern_shot_map())
        self.assertEqual(
            direction.pattern_shot_map()["hook"], "bird's-eye geometric"
        )


class ChannelSnapshotFeedsDirectorTests(unittest.TestCase):
    def test_channel_settings_carry_structured_visual_direction(self):
        snapshot = build_channel_snapshot({
            "id": "ch_ABC123",
            "name": "Pattern A",
            "version": 1,
            "content": {"tone": "mysterious"},
            "visual_direction": CHANNEL_A_DIRECTION,
            "export_defaults": {"aspect_ratio": "9:16"},
        })
        settings = channel_settings_from_snapshot(snapshot)
        self.assertIn("visual_direction", settings)
        vd = settings["visual_direction"]
        self.assertEqual(vd["pattern"][0]["shot"], "extreme close-up")
        self.assertEqual(vd["palette"], "teal, amber, charcoal")
        self.assertEqual(vd["lighting"], "warm golden hour rim light")
        self.assertEqual(vd["continuity"], "same protagonist wardrobe across all scenes")
        self.assertEqual(vd["references"], ["ref_brand_a"])


class DifferentPatternsDifferentSpecsTests(unittest.TestCase):
    """Done-when: two Channels with different patterns → different SceneSpecs."""

    def test_offline_plan_diverges_on_pattern(self):
        specs_a = plan_scene_specs_from_direction(
            SAME_SEGMENTS, CHANNEL_A_DIRECTION, script=SAME_SCRIPT
        )
        specs_b = plan_scene_specs_from_direction(
            SAME_SEGMENTS, CHANNEL_B_DIRECTION, script=SAME_SCRIPT
        )
        self.assertEqual(len(specs_a), len(SAME_SEGMENTS))
        self.assertEqual(len(specs_b), len(SAME_SEGMENTS))
        self.assertEqual(len(specs_a), len(specs_b))

        cameras_a = [s.camera for s in specs_a]
        cameras_b = [s.camera for s in specs_b]
        self.assertNotEqual(
            cameras_a,
            cameras_b,
            "different Channel patterns must yield different camera/shot specs",
        )

        # Hook shot comes from the pattern's hook entry.
        self.assertEqual(specs_a[0].camera, "extreme close-up")
        self.assertEqual(specs_b[0].camera, "bird's-eye geometric")

        # Lighting / continuity / palette-adjacent fields also diverge.
        self.assertEqual(specs_a[0].lighting, CHANNEL_A_DIRECTION["lighting"])
        self.assertEqual(specs_b[0].lighting, CHANNEL_B_DIRECTION["lighting"])
        self.assertEqual(
            specs_a[0].continuity, CHANNEL_A_DIRECTION["continuity"]
        )
        self.assertEqual(
            specs_b[0].continuity, CHANNEL_B_DIRECTION["continuity"]
        )

        # Fingerprint: at least one §8 field differs on every scene index.
        differing = 0
        for a, b in zip(specs_a, specs_b):
            if (
                a.camera != b.camera
                or a.lighting != b.lighting
                or a.continuity != b.continuity
                or a.mood != b.mood
            ):
                differing += 1
        self.assertGreaterEqual(
            differing,
            len(specs_a),
            "every scene should carry a measurable visual-direction difference",
        )

    def test_fixture_provider_diverges_on_pattern(self):
        from tests.fixture_providers.scene_director.fixture_scenes.provider import (
            FixtureScenesProvider,
        )

        provider = FixtureScenesProvider()
        segments = {"segments": SAME_SEGMENTS}
        out_a = provider.generate(
            segments,
            {
                "style": "cinematic",
                "text": SAME_SCRIPT,
                "visual_direction": CHANNEL_A_DIRECTION,
                "label_prefix": "A",
            },
            project_id="pp_TESTA1",
        )
        out_b = provider.generate(
            segments,
            {
                "style": "noir",
                "text": SAME_SCRIPT,
                "visual_direction": CHANNEL_B_DIRECTION,
                "label_prefix": "B",
            },
            project_id="pp_TESTB1",
        )
        scenes_a = out_a["scenes"]
        scenes_b = out_b["scenes"]
        self.assertEqual(len(scenes_a), len(scenes_b))
        self.assertNotEqual(
            [s.get("camera") for s in scenes_a],
            [s.get("camera") for s in scenes_b],
        )
        self.assertNotEqual(
            [s.get("image_prompt") for s in scenes_a],
            [s.get("image_prompt") for s in scenes_b],
        )
        # Channel lighting appears in the provider-owned image_prompt wording.
        self.assertIn(
            CHANNEL_A_DIRECTION["lighting"], scenes_a[0]["image_prompt"]
        )
        self.assertIn(
            CHANNEL_B_DIRECTION["lighting"], scenes_b[0]["image_prompt"]
        )


class PromptTextLivesInProviderPackagesTests(unittest.TestCase):
    """Done-when: scan proves no scene LLM prompt text outside providers/."""

    def test_scene_llm_prompt_markers_only_under_providers(self):
        offenders: list[str] = []
        for path in SCRIPTASE_DIR.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            hits = [marker for marker in SCENE_LLM_PROMPT_MARKERS if marker in text]
            if not hits:
                continue
            rel = path.relative_to(ROOT).as_posix()
            # Must sit under a providers/ package directory.
            if _PROVIDER_PATH_PART not in str(path):
                offenders.append(f"{rel}: {hits[0]!r}")

        self.assertEqual(
            offenders,
            [],
            "scene-director LLM prompt text must live under a providers/ "
            f"package; found outside:\n  " + "\n  ".join(offenders),
        )

    def test_prompts_module_is_under_providers(self):
        prompts_path = (
            SCRIPTASE_DIR
            / "modules"
            / "scene_director"
            / "providers"
            / "prompts.py"
        )
        self.assertTrue(
            prompts_path.is_file(),
            "scene prompt builders must live at "
            "scriptase/modules/scene_director/providers/prompts.py",
        )
        legacy = (
            SCRIPTASE_DIR / "modules" / "scene_director" / "prompts.py"
        )
        self.assertFalse(
            legacy.exists(),
            "legacy scriptase/modules/scene_director/prompts.py must be removed",
        )

    def test_channel_and_job_layers_have_no_scene_llm_prompts(self):
        layers = [
            SCRIPTASE_DIR / "channels",
            SCRIPTASE_DIR / "jobs",
            SCRIPTASE_DIR / "engine" / "adapters",
        ]
        offenders: list[str] = []
        for layer in layers:
            if not layer.is_dir():
                continue
            for path in layer.rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                for marker in SCENE_LLM_PROMPT_MARKERS:
                    if marker in text:
                        offenders.append(
                            f"{path.relative_to(ROOT).as_posix()}: {marker!r}"
                        )
        self.assertEqual(
            offenders,
            [],
            "Channel/Job/adapter layers must not embed scene LLM prompts:\n  "
            + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
