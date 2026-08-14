"""Step 6.2 — optional image dependency.

Done when:
  * a workflow with no image node runs to export using a text_to_video provider
  * the image-to-video path (full_video with storyboard) still works unchanged
"""

from __future__ import annotations

import os
import tempfile
import unittest
from copy import deepcopy

from scriptase.engine.adapters import AdapterContext, AdapterError
from scriptase.engine.adapters import video as video_adapter
from scriptase.engine.registry import get_node_type
from scriptase.engine.scheduler import WorkflowScheduler
from scriptase.engine.templates import (
    full_video_template,
    serialize_templates,
    text_to_video_template,
)
from scriptase.engine.validation import validate_workflow, validation_errors
from scriptase.jobs.stage_projection import project_stages
from scriptase.modules.video.routing import (
    IMAGE_TO_VIDEO,
    TEXT_TO_VIDEO,
    VideoCapabilityError,
    required_capability_for_graph,
    resolve_motion_mode,
    storyboard_is_present,
)
from scriptase.providers.hub import ProviderHub, hub as process_hub
from scriptase.providers.selection import select_candidates


# ---------------------------------------------------------------------------
# Routing pure functions
# ---------------------------------------------------------------------------


class StoryboardPresenceTests(unittest.TestCase):
    def test_absent_when_port_missing(self):
        self.assertFalse(storyboard_is_present({"scenes": {"scenes": []}}))
        self.assertFalse(storyboard_is_present(None))
        self.assertFalse(storyboard_is_present({}))

    def test_absent_when_payload_null_or_empty(self):
        self.assertFalse(storyboard_is_present({"storyboard": None}))
        self.assertFalse(storyboard_is_present({"storyboard": {}}))

    def test_present_when_payload_connected(self):
        self.assertTrue(
            storyboard_is_present({
                "storyboard": {
                    "ready": 1,
                    "total": 1,
                    "artifact_refs": ["storyboard/x.png"],
                },
            })
        )
        self.assertTrue(storyboard_is_present({"storyboard": {"ready": 0}}))


class MotionModeResolutionTests(unittest.TestCase):
    def test_with_storyboard_prefers_image_to_video(self):
        mode = resolve_motion_mode(
            has_storyboard=True,
            capabilities={IMAGE_TO_VIDEO: True, TEXT_TO_VIDEO: True},
        )
        self.assertEqual(mode, IMAGE_TO_VIDEO)

    def test_with_storyboard_falls_back_to_text_to_video(self):
        """text_to_video-only provider may ignore stills and still run."""
        mode = resolve_motion_mode(
            has_storyboard=True,
            capabilities={TEXT_TO_VIDEO: True},
        )
        self.assertEqual(mode, TEXT_TO_VIDEO)

    def test_without_storyboard_requires_text_to_video(self):
        mode = resolve_motion_mode(
            has_storyboard=False,
            capabilities={TEXT_TO_VIDEO: True},
        )
        self.assertEqual(mode, TEXT_TO_VIDEO)

    def test_without_storyboard_rejects_image_to_video_only(self):
        with self.assertRaises(VideoCapabilityError) as ctx:
            resolve_motion_mode(
                has_storyboard=False,
                capabilities={IMAGE_TO_VIDEO: True},
            )
        self.assertEqual(ctx.exception.code, "PROVIDER_REQUEST_INVALID")
        self.assertEqual(ctx.exception.details["required_capability"], TEXT_TO_VIDEO)
        self.assertFalse(ctx.exception.details["has_storyboard"])

    def test_required_capability_for_graph(self):
        self.assertEqual(
            required_capability_for_graph(has_storyboard=True),
            IMAGE_TO_VIDEO,
        )
        self.assertEqual(
            required_capability_for_graph(has_storyboard=False),
            TEXT_TO_VIDEO,
        )


class SelectorCapabilityRoutingTests(unittest.TestCase):
    """select_candidates (step 3.3) is the query surface for step 6.2 routing."""

    @classmethod
    def setUpClass(cls):
        cls.hub = ProviderHub()
        cls.hub.discover("video")

    def test_text_to_video_query_excludes_image_only_providers(self):
        hits = select_candidates(
            "video",
            capabilities=[TEXT_TO_VIDEO],
            provider_hub=self.hub,
        )
        type_ids = {c.provider_type for c in hits}
        self.assertIn("kie_ai", type_ids)
        self.assertNotIn("grok_automa", type_ids)

    def test_image_to_video_query_excludes_text_only_providers(self):
        hits = select_candidates(
            "video",
            capabilities=[IMAGE_TO_VIDEO],
            provider_hub=self.hub,
        )
        type_ids = {c.provider_type for c in hits}
        self.assertIn("grok_automa", type_ids)
        self.assertNotIn("kie_ai", type_ids)


# ---------------------------------------------------------------------------
# Adapter gate
# ---------------------------------------------------------------------------


class VideoAdapterCapabilityGateTests(unittest.TestCase):
    def setUp(self):
        self.ctx = AdapterContext(project_id="pm_ABC123")
        self.scenes = {
            "scenes": [
                {
                    "index": 0,
                    "id": "scn_AAAAAA",
                    "image_prompt": "a quiet harbor at dusk",
                    "motion_prompt": "slow pan across the water",
                }
            ]
        }
        # Ensure shipped video providers are discoverable.
        process_hub.discover("video")

    def test_text_to_video_without_storyboard_runs(self):
        """No image node: kie_ai (text_to_video) is accepted and executes."""
        import scriptase.engine.adapters.video as mod

        captured: dict = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return {"total": 1, "ready": 1, "errors": 0}

        original = mod.run_manifest_job
        mod.run_manifest_job = fake_run
        try:
            result = video_adapter.generate(
                {"scenes": self.scenes},
                {"provider_id": "kie_ai"},
                self.ctx,
            )
        finally:
            mod.run_manifest_job = original

        self.assertEqual(result["assets"]["ready"], 1)
        self.assertEqual(result["assets"]["provider"], "kie_ai")
        self.assertEqual(result["assets"]["motion_mode"], TEXT_TO_VIDEO)
        self.assertEqual(captured.get("options", {}).get("motion_mode"), TEXT_TO_VIDEO)

    def test_image_to_video_without_storyboard_fails_clearly(self):
        """grok_automa is image_to_video-only; no storyboard must not run."""
        with self.assertRaises(AdapterError) as ctx:
            video_adapter.generate(
                {"scenes": self.scenes},
                {"provider_id": "grok_automa"},
                self.ctx,
            )
        self.assertEqual(ctx.exception.code, "PROVIDER_REQUEST_INVALID")
        self.assertIn("text_to_video", ctx.exception.message)
        self.assertFalse(ctx.exception.details.get("has_storyboard"))

    def test_image_to_video_with_storyboard_still_runs(self):
        """Default path: storyboard connected + grok_automa → image_to_video."""
        import scriptase.engine.adapters.video as mod
        from config import OUTPUT_DIR
        from PIL import Image

        captured: dict = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return {"total": 1, "ready": 1, "errors": 0}

        # Step 7.4 image gate requires a real still on disk before video runs.
        ref = "storyboard/pm_ABC123/0/image.png"
        abs_path = os.path.join(OUTPUT_DIR, *ref.split("/"))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        Image.new("RGB", (90, 160), (20, 40, 80)).save(abs_path, format="PNG")

        original = mod.run_manifest_job
        mod.run_manifest_job = fake_run
        try:
            result = video_adapter.generate(
                {
                    "scenes": self.scenes,
                    "storyboard": {
                        "ready": 1,
                        "total": 1,
                        "artifact_refs": [ref],
                    },
                },
                {"provider_id": "grok_automa", "aspect_ratio": "9:16"},
                self.ctx,
            )
        finally:
            mod.run_manifest_job = original
            try:
                os.remove(abs_path)
            except OSError:
                pass

        self.assertEqual(result["assets"]["ready"], 1)
        self.assertEqual(result["assets"]["provider"], "grok_automa")
        self.assertEqual(result["assets"]["motion_mode"], IMAGE_TO_VIDEO)
        self.assertEqual(captured.get("options", {}).get("motion_mode"), IMAGE_TO_VIDEO)


# ---------------------------------------------------------------------------
# Template + end-to-end export
# ---------------------------------------------------------------------------


def _write_blob(output_dir: str, relative: str, content: bytes) -> str:
    abs_path = os.path.join(output_dir, relative.replace("/", os.sep))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as handle:
        handle.write(content)
    return relative.replace("\\", "/")


def _stub_resolver(output_dir: str, *, seen: list | None = None):
    """Deterministic executor that writes export bytes without real providers."""

    def resolve(node):
        node_type = node.get("type")
        node_id = node.get("id")

        def execute(inputs, config, context):
            if seen is not None:
                seen.append({
                    "node_id": node_id,
                    "type": node_type,
                    "config": dict(config or {}),
                    "input_ports": sorted(inputs.keys()) if isinstance(inputs, dict) else [],
                })
            definition = get_node_type(node_type) or {}
            result = {}
            project_id = getattr(context, "project_id", None) or "pm_TEST0"
            for port in definition.get("outputs", []):
                port_id = port["id"]
                if port_id == "control":
                    result[port_id] = {"ok": True}
                    continue
                if port_id == "settings":
                    result[port_id] = dict(config or {})
                    continue
                if port_id == "script" and node_type == "script.input":
                    result[port_id] = str(
                        (config or {}).get("text") or "Stub narration."
                    )
                    continue
                if port_id in {"audio", "metadata"} and node_type == "tts.generate":
                    rel = f"tts/{project_id}/voice.wav"
                    _write_blob(output_dir, rel, b"VOICE")
                    result[port_id] = (
                        {"filename": "voice.wav", "artifact_refs": [rel]}
                        if port_id == "audio"
                        else {"duration": 1.0}
                    )
                    continue
                if port_id == "video" and node_type == "export.video":
                    rel = f"exports/{project_id}_final.mp4"
                    _write_blob(output_dir, rel, b"EXPORT-BYTES")
                    result[port_id] = {
                        "filename": f"{project_id}_final.mp4",
                        "artifact_refs": [rel],
                    }
                    continue
                if port_id == "value" and node_type == "workflow.output":
                    upstream = inputs.get("value") if isinstance(inputs, dict) else None
                    result[port_id] = (
                        upstream if isinstance(upstream, dict) else {"filename": "final.mp4"}
                    )
                    continue
                if port_id == "project" and node_type in {
                    "assemble.project",
                    "timeline.project",
                }:
                    rel = f"projects/{project_id}/work@in@progress.json"
                    _write_blob(output_dir, rel, b'{"scenes":[{"id":1,"duration":1}]}')
                    result[port_id] = {
                        "assembled_data": {"scenes": [{"id": 1, "duration": 1}]},
                        "artifact_refs": [rel],
                    }
                    continue
                if port_id == "images" and node_type == "storyboard.generate":
                    rel = f"storyboard/{project_id}/scene_01.png"
                    _write_blob(output_dir, rel, b"IMAGE")
                    result[port_id] = {
                        "ready": 1,
                        "total": 1,
                        "artifact_refs": [rel],
                    }
                    continue
                if port_id == "assets" and node_type == "animator.generate":
                    rel = f"animator/{project_id}/scene_01.mp4"
                    _write_blob(output_dir, rel, b"VIDEO")
                    # Mirror the capability gate so the e2e path proves the
                    # graph shape is legal for the selected provider.
                    has_sb = "storyboard" in (inputs or {})
                    provider = str(
                        (config or {}).get("provider_id") or "grok_automa"
                    )
                    package = process_hub.get("video", provider)
                    caps = dict(package.capabilities) if package else {}
                    mode = resolve_motion_mode(
                        has_storyboard=has_sb, capabilities=caps
                    )
                    result[port_id] = {
                        "ready": 1,
                        "total": 1,
                        "artifact_refs": [rel],
                        "provider": provider,
                        "motion_mode": mode,
                    }
                    continue
                if port_id == "alignment" and node_type == "timing.align":
                    rel = f"alignments/{project_id}/alignment.json"
                    _write_blob(output_dir, rel, b'{"words":[]}')
                    result[port_id] = {"words": [], "artifact_refs": [rel]}
                    continue
                if port_id == "segments" and node_type == "segment.run":
                    rel = f"segmenters/{project_id}/segments.json"
                    _write_blob(output_dir, rel, b'{"segments":[]}')
                    result[port_id] = {"segments": [], "artifact_refs": [rel]}
                    continue
                if port_id == "scenes" and node_type == "scenes.blueprint":
                    rel = f"scenes/{project_id}/scenes.json"
                    _write_blob(output_dir, rel, b'{"scenes":[{"id":"s1"}]}')
                    result[port_id] = {
                        "scenes": [{
                            "index": 0,
                            "id": "scn_AAAAAA",
                            "image_prompt": "p",
                            "motion_prompt": "m",
                        }],
                        "artifact_refs": [rel],
                    }
                    continue
                if port_id == "captions" and node_type == "captions.generate":
                    result[port_id] = {"cues": []}
                    continue
                if port_id == "track" and node_type == "music.select":
                    result[port_id] = {"title": "ambient"}
                    continue
                result[port_id] = {}
            return result

        return execute

    return resolve


def _prepare_draft(template_fn, *, script: str = "A short narration for the test.") -> dict:
    draft = template_fn()
    draft.pop("template_id", None)
    for node in draft["nodes"]:
        if node.get("type") == "script.input":
            node.setdefault("configuration", {})["text"] = script
    draft.update({
        "workflow_id": "wf_TEST01",
        "created_at": "2026-08-14T12:00:00Z",
        "updated_at": "2026-08-14T12:00:00Z",
    })
    return draft


class TextToVideoTemplateTests(unittest.TestCase):
    def test_template_has_no_storyboard_node(self):
        draft = text_to_video_template()
        types = [n["type"] for n in draft["nodes"]]
        self.assertNotIn("storyboard.generate", types)
        self.assertIn("animator.generate", types)
        self.assertIn("export.video", types)
        self.assertIn("scenes.blueprint", types)

    def test_template_wires_scenes_directly_to_animator(self):
        draft = text_to_video_template()
        edges = draft["edges"]
        self.assertTrue(
            any(
                e["source_node"] == "n_scenes"
                and e["target_node"] == "n_animator"
                and e["target_port"] == "scenes"
                for e in edges
            )
        )
        self.assertFalse(
            any(e.get("target_port") == "storyboard" for e in edges)
        )

    def test_template_selects_text_to_video_provider(self):
        draft = text_to_video_template()
        animator = next(
            n for n in draft["nodes"] if n["type"] == "animator.generate"
        )
        self.assertEqual(animator["configuration"].get("provider_id"), "kie_ai")

    def test_template_validates(self):
        draft = text_to_video_template()
        draft.pop("template_id", None)
        problems = validate_workflow(
            draft, require_identity=False, require_complete=False
        )
        self.assertEqual(validation_errors(problems), [])

    def test_template_is_serialized_with_builtins(self):
        ids = [item["template_id"] for item in serialize_templates()]
        self.assertIn("text_to_video", ids)
        self.assertIn("full_video", ids)

    def test_projection_has_no_image_members(self):
        projection = project_stages(text_to_video_template())
        assignment = {s["key"]: s for s in projection["stages"]}
        # Images may appear as an empty spine gap, but never with members.
        if "images" in assignment:
            self.assertEqual(assignment["images"]["node_ids"], [])
        self.assertIn("videos", assignment)
        self.assertEqual(assignment["videos"]["node_ids"], ["n_animator"])
        self.assertIn("export", assignment)


class FullVideoPathUnchangedTests(unittest.TestCase):
    def test_full_video_still_has_storyboard_edge(self):
        draft = full_video_template()
        types = [n["type"] for n in draft["nodes"]]
        self.assertIn("storyboard.generate", types)
        self.assertTrue(
            any(
                e["source_node"] == "n_storyboard"
                and e["target_node"] == "n_animator"
                and e["target_port"] == "storyboard"
                for e in draft["edges"]
            )
        )

    def test_full_video_runs_to_export_with_image_to_video(self):
        process_hub.discover("video")
        seen: list[dict] = []
        with tempfile.TemporaryDirectory(prefix="sts_6_2_i2v_") as root:
            draft = _prepare_draft(full_video_template)
            result = WorkflowScheduler(
                draft,
                project_id="pm_I2V001",
                lock_root=os.path.join(root, "locks"),
                output_dir=root,
                executor_resolver=_stub_resolver(root, seen=seen),
            ).run()
            self.assertEqual(result.status, "succeeded")

            animator_calls = [c for c in seen if c["type"] == "animator.generate"]
            self.assertEqual(len(animator_calls), 1)
            self.assertIn("storyboard", animator_calls[0]["input_ports"])
            self.assertIn("scenes", animator_calls[0]["input_ports"])
            self.assertTrue(any(c["type"] == "storyboard.generate" for c in seen))
            self.assertTrue(any(c["type"] == "export.video" for c in seen))

            export_path = os.path.join(root, "exports", "pm_I2V001_final.mp4")
            self.assertTrue(os.path.isfile(export_path))


class TextToVideoEndToEndTests(unittest.TestCase):
    def test_no_image_node_runs_to_export_with_text_to_video(self):
        """Done-when: workflow with no image node reaches export via t2v."""
        process_hub.discover("video")
        seen: list[dict] = []
        with tempfile.TemporaryDirectory(prefix="sts_6_2_t2v_") as root:
            draft = _prepare_draft(text_to_video_template)
            self.assertFalse(
                any(n["type"] == "storyboard.generate" for n in draft["nodes"])
            )

            result = WorkflowScheduler(
                draft,
                project_id="pm_T2V001",
                lock_root=os.path.join(root, "locks"),
                output_dir=root,
                executor_resolver=_stub_resolver(root, seen=seen),
            ).run()
            self.assertEqual(result.status, "succeeded")

            # Storyboard never executed.
            self.assertFalse(
                any(c["type"] == "storyboard.generate" for c in seen)
            )

            animator_calls = [c for c in seen if c["type"] == "animator.generate"]
            self.assertEqual(len(animator_calls), 1)
            self.assertNotIn("storyboard", animator_calls[0]["input_ports"])
            self.assertIn("scenes", animator_calls[0]["input_ports"])
            self.assertEqual(
                animator_calls[0]["config"].get("provider_id"),
                "kie_ai",
            )

            self.assertTrue(any(c["type"] == "export.video" for c in seen))
            self.assertTrue(any(c["type"] == "workflow.output" for c in seen))

            export_path = os.path.join(root, "exports", "pm_T2V001_final.mp4")
            self.assertTrue(os.path.isfile(export_path), export_path)


if __name__ == "__main__":
    unittest.main()
