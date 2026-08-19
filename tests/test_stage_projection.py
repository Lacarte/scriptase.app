"""Step 2.2 — Stage projection, derived from the graph.

Done when: the default workflow projects to Script, Voice, Timing, Segments,
Scenes, Images, Videos, Review, Composer, Export, and adding a parallel
caption branch changes the graph without adding a step.

Also locks: projection is computed from the graph (no frontend step array),
side branches collapse into the merge stage, ``-P`` never appears in stage
names, and stage status derives from member node execution records.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from copy import deepcopy

from app import create_app
from scriptase.engine import persistence as workflow_persistence
from scriptase.engine.persistence import create_workflow
from scriptase.engine.templates import (
    full_video_template,
    narration_only_template,
    storyboard_only_template,
)
from scriptase.jobs.stage_projection import (
    PRIMARY_STAGE_BY_TYPE,
    SIDE_BRANCH_STAGE_BY_TYPE,
    STAGE_CATALOG,
    StageProjectionError,
    assign_nodes_to_stages,
    default_stage_labels,
    project_stages,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_LABELS = [
    "Script",
    "Voice",
    "Timing",
    "Segments",
    "Scenes",
    "Images",
    "Videos",
    "Review",
    "Assembly",
    "Export",
]


def _full_video_draft(*, script_text: str = "Placeholder narration.") -> dict:
    draft = full_video_template()
    draft.pop("template_id", None)
    for node in draft["nodes"]:
        if node["type"] == "script.input":
            node["configuration"] = {
                **(node.get("configuration") or {}),
                "text": script_text,
            }
    return draft


def _strip_caption_branch(workflow: dict) -> dict:
    """Remove the captions node and every edge that touches it."""
    doc = deepcopy(workflow)
    caption_ids = {
        n["id"] for n in doc["nodes"] if n.get("type") == "captions.generate"
    }
    doc["nodes"] = [n for n in doc["nodes"] if n["id"] not in caption_ids]
    doc["edges"] = [
        e
        for e in doc["edges"]
        if e.get("source_node") not in caption_ids
        and e.get("target_node") not in caption_ids
    ]
    return doc


def _add_extra_caption(workflow: dict) -> dict:
    """Add a second parallel caption generator into the same merge stage."""
    doc = deepcopy(workflow)
    # Align → captions2 → assemble (parallel to existing captions).
    doc["nodes"].append({
        "id": "n_captions_b",
        "type": "captions.generate",
        "type_version": 1,
        "name": "Captions B",
        "position": {"x": 1280, "y": 700},
        "configuration": {
            "preset_id": "bold_popup",
            "words_per_group": 3,
            "enabled": True,
        },
        "disabled": False,
    })
    doc["edges"].append({
        "id": "e_align_captions_b",
        "source_node": "n_align",
        "source_port": "alignment",
        "target_node": "n_captions_b",
        "target_port": "alignment",
        "edge_type": "data",
    })
    # assemble.project already accepts captions; a second captions edge is
    # rejected by single-value inputs. Fold into compose via a second data
    # path by attaching only to alignment — collapse-to-merge still walks to
    # assemble through any existing captions→assemble path... actually with
    # no outbound edge this node has no merge target. Wire it into assemble
    # by first removing the original captions→assemble edge? Better: the
    # side-branch map assigns captions.generate → composer directly, so no
    # merge walk is required.
    return doc


# ---------------------------------------------------------------------------
# Core projection
# ---------------------------------------------------------------------------


class DefaultWorkflowProjectionTests(unittest.TestCase):
    """Done when: default workflow → the ten Production stages."""

    def test_catalog_labels_match_contract(self):
        self.assertEqual(default_stage_labels(), DEFAULT_LABELS)
        self.assertEqual([s["label"] for s in STAGE_CATALOG], DEFAULT_LABELS)

    def test_full_video_projects_to_default_spine(self):
        projection = project_stages(full_video_template())
        labels = [s["label"] for s in projection["stages"]]
        self.assertEqual(labels, DEFAULT_LABELS)

        keys = [s["key"] for s in projection["stages"]]
        self.assertEqual(
            keys,
            [
                "script",
                "voice",
                "timing",
                "segments",
                "scenes",
                "images",
                "videos",
                "review",
                "composer",
                "export",
            ],
        )

    def test_full_video_ordinals_are_contiguous(self):
        stages = project_stages(full_video_template())["stages"]
        self.assertEqual([s["ordinal"] for s in stages], list(range(len(stages))))

    def test_review_is_present_even_without_review_nodes(self):
        """Spine gap fill keeps Review between Videos and Composer (Phase 7)."""
        assignment = assign_nodes_to_stages(full_video_template())
        self.assertEqual(assignment["review"], [])
        stages = project_stages(full_video_template())["stages"]
        review = next(s for s in stages if s["key"] == "review")
        self.assertEqual(review["node_ids"], [])
        self.assertEqual(review["status"], "idle")
        self.assertFalse(review["provider_capable"])

    def test_primary_nodes_land_in_expected_stages(self):
        assignment = assign_nodes_to_stages(full_video_template())
        # Step 16.2 put the virality analyzer on the Script stage rather than a
        # stage of its own — a verdict about the script, not a step after it.
        self.assertEqual(assignment["script"], ["n_script", "n_analyze"])
        self.assertEqual(assignment["voice"], ["n_tts"])
        self.assertEqual(assignment["timing"], ["n_align"])
        self.assertEqual(assignment["segments"], ["n_segment"])
        self.assertEqual(assignment["scenes"], ["n_scenes"])
        self.assertEqual(assignment["images"], ["n_storyboard"])
        self.assertEqual(assignment["videos"], ["n_animator"])
        self.assertEqual(assignment["composer"], ["n_captions", "n_music", "n_assemble", "n_timeline"])
        self.assertEqual(assignment["export"], ["n_export"])

    def test_infrastructure_nodes_are_excluded(self):
        assignment = assign_nodes_to_stages(full_video_template())
        all_ids = [nid for members in assignment.values() for nid in members]
        self.assertNotIn("n_trigger", all_ids)
        self.assertNotIn("n_setup", all_ids)
        self.assertNotIn("n_output", all_ids)

    def test_no_minus_p_in_stage_names(self):
        for stage in project_stages(full_video_template())["stages"]:
            self.assertNotIn("-P", stage["label"])
            self.assertNotIn("-P", stage["key"])
            self.assertNotIn(" -P", stage["label"])


class SideBranchCollapseTests(unittest.TestCase):
    """Done when: adding a parallel caption branch changes the graph without adding a step."""

    def test_captions_are_side_branch_mapped_to_composer(self):
        self.assertEqual(SIDE_BRANCH_STAGE_BY_TYPE["captions.generate"], "composer")
        self.assertEqual(SIDE_BRANCH_STAGE_BY_TYPE["music.select"], "composer")

    def test_removing_captions_does_not_remove_a_stage(self):
        with_captions = project_stages(full_video_template())
        without = project_stages(_strip_caption_branch(full_video_template()))
        self.assertEqual(
            [s["label"] for s in with_captions["stages"]],
            [s["label"] for s in without["stages"]],
        )
        # Node membership changes; stage count does not.
        composer_with = next(s for s in with_captions["stages"] if s["key"] == "composer")
        composer_without = next(s for s in without["stages"] if s["key"] == "composer")
        self.assertIn("n_captions", composer_with["node_ids"])
        self.assertNotIn("n_captions", composer_without["node_ids"])

    def test_adding_parallel_caption_does_not_add_a_step(self):
        base = full_video_template()
        with_extra = _add_extra_caption(base)
        self.assertEqual(len(with_extra["nodes"]), len(base["nodes"]) + 1)

        base_proj = project_stages(base)
        extra_proj = project_stages(with_extra)
        self.assertEqual(
            [s["label"] for s in base_proj["stages"]],
            [s["label"] for s in extra_proj["stages"]],
        )
        composer = next(s for s in extra_proj["stages"] if s["key"] == "composer")
        self.assertIn("n_captions", composer["node_ids"])
        self.assertIn("n_captions_b", composer["node_ids"])

    def test_music_collapses_into_composer(self):
        assignment = assign_nodes_to_stages(full_video_template())
        self.assertIn("n_music", assignment["composer"])
        # Music never opens its own stage.
        labels = [s["label"] for s in project_stages(full_video_template())["stages"]]
        self.assertNotIn("Music", labels)
        self.assertNotIn("Captions", labels)


class PartialWorkflowProjectionTests(unittest.TestCase):
    def test_narration_only_is_script_and_voice(self):
        projection = project_stages(narration_only_template())
        labels = [s["label"] for s in projection["stages"]]
        self.assertEqual(labels, ["Script", "Voice"])
        # No empty Review gap — the spine only spans occupied range.
        self.assertNotIn("Review", labels)

    def test_storyboard_only_stops_at_images(self):
        projection = project_stages(storyboard_only_template())
        labels = [s["label"] for s in projection["stages"]]
        self.assertEqual(
            labels,
            ["Script", "Voice", "Timing", "Segments", "Scenes", "Images"],
        )

    def test_empty_workflow_raises(self):
        with self.assertRaises(StageProjectionError) as ctx:
            project_stages({"nodes": [], "edges": []})
        self.assertEqual(ctx.exception.code, "STAGE_PROJECTION_INVALID")

    def test_fill_spine_gaps_can_be_disabled(self):
        # Without gap fill, Review is omitted when it has no member nodes.
        projection = project_stages(full_video_template(), fill_spine_gaps=False)
        labels = [s["label"] for s in projection["stages"]]
        self.assertNotIn("Review", labels)
        self.assertIn("Videos", labels)
        self.assertIn("Assembly", labels)


class ProviderCapabilityTests(unittest.TestCase):
    def test_provider_capable_stages_flagged(self):
        stages = {s["key"]: s for s in project_stages(full_video_template())["stages"]}
        self.assertTrue(stages["voice"]["provider_capable"])
        self.assertTrue(stages["scenes"]["provider_capable"])
        self.assertTrue(stages["images"]["provider_capable"])
        self.assertTrue(stages["videos"]["provider_capable"])
        # Script pastes text (script.input, no provider), but step 16.2 put
        # the provider-capable analyzer on the same stage, so the stage as a
        # whole is capable and reports the analyzer's binding.
        self.assertTrue(stages["script"]["provider_capable"])
        self.assertEqual(
            stages["script"]["active_provider_instance_id"], "deterministic"
        )
        self.assertFalse(stages["timing"]["provider_capable"])
        self.assertFalse(stages["segments"]["provider_capable"])
        self.assertFalse(stages["composer"]["provider_capable"])
        self.assertFalse(stages["export"]["provider_capable"])

    def test_story_generate_makes_script_provider_capable(self):
        draft = {
            "nodes": [
                {
                    "id": "n_story",
                    "type": "story.generate",
                    "type_version": 1,
                    "name": "Story",
                    "position": {"x": 0, "y": 0},
                    "configuration": {"provider_id": "gemini"},
                    "disabled": False,
                },
            ],
            "edges": [],
        }
        stages = project_stages(draft)["stages"]
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["key"], "script")
        self.assertTrue(stages[0]["provider_capable"])
        self.assertEqual(stages[0]["active_provider_instance_id"], "gemini")

    def test_primary_mapping_covers_shipped_media_types(self):
        for type_key in (
            "script.input",
            "story.generate",
            "tts.generate",
            "timing.align",
            "segment.run",
            "scenes.blueprint",
            "storyboard.generate",
            "animator.generate",
            "assemble.project",
            "export.video",
        ):
            self.assertIn(type_key, PRIMARY_STAGE_BY_TYPE)


class StatusDerivationTests(unittest.TestCase):
    def test_status_derives_from_member_node_records(self):
        workflow = full_video_template()
        execution = {
            "nodes": {
                "n_script": {"status": "succeeded", "artifact_refs": ["stories/x.json"]},
                "n_tts": {"status": "running", "artifact_refs": []},
                "n_align": {"status": "idle"},
            }
        }
        stages = {s["key"]: s for s in project_stages(workflow, execution=execution)["stages"]}
        self.assertEqual(stages["script"]["status"], "succeeded")
        self.assertEqual(stages["voice"]["status"], "running")
        self.assertEqual(stages["timing"]["status"], "idle")
        self.assertEqual(stages["script"]["artifacts"], ["stories/x.json"])

    def test_failed_beats_running(self):
        workflow = full_video_template()
        execution = {
            "nodes": {
                "n_captions": {"status": "succeeded"},
                "n_music": {"status": "failed"},
                "n_assemble": {"status": "running"},
                "n_timeline": {"status": "idle"},
            }
        }
        stages = {s["key"]: s for s in project_stages(workflow, execution=execution)["stages"]}
        self.assertEqual(stages["composer"]["status"], "failed")

    def test_empty_stage_is_idle(self):
        stages = {s["key"]: s for s in project_stages(full_video_template())["stages"]}
        self.assertEqual(stages["review"]["status"], "idle")
        self.assertEqual(stages["review"]["artifacts"], [])
        self.assertEqual(stages["review"]["issues"], [])


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


class StageProjectionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_stages_")
        root = self.temp.name
        self.old_workflows = workflow_persistence.WORKFLOWS_DIR
        self.old_executions = workflow_persistence.EXECUTIONS_DIR
        workflow_persistence.WORKFLOWS_DIR = os.path.join(root, "workflows")
        workflow_persistence.EXECUTIONS_DIR = os.path.join(root, "executions")
        os.makedirs(workflow_persistence.EXECUTIONS_DIR, exist_ok=True)

        self.app = create_app(discover_providers=False)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.workflow = create_workflow(_full_video_draft())

    def tearDown(self):
        workflow_persistence.WORKFLOWS_DIR = self.old_workflows
        workflow_persistence.EXECUTIONS_DIR = self.old_executions
        self.temp.cleanup()

    def test_get_workflow_stages(self):
        response = self.client.get(
            f"/api/workflows/{self.workflow['workflow_id']}/stages"
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        projection = body["projection"]
        self.assertEqual(projection["workflow_id"], self.workflow["workflow_id"])
        labels = [s["label"] for s in projection["stages"]]
        self.assertEqual(labels, DEFAULT_LABELS)

    def test_get_workflow_stages_summary(self):
        response = self.client.get(
            f"/api/workflows/{self.workflow['workflow_id']}/stages?summary=1"
        )
        self.assertEqual(response.status_code, 200)
        projection = response.get_json()["projection"]
        self.assertEqual(projection["stage_count"], 10)
        self.assertIn("node_count", projection["stages"][0])
        self.assertNotIn("node_ids", projection["stages"][0])

    def test_get_missing_workflow(self):
        response = self.client.get("/api/workflows/wf_ZZZZZZ/stages")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "NOT_FOUND")

    def test_post_inline_workflow_stages(self):
        response = self.client.post(
            "/api/workflow/stages",
            json={"workflow": full_video_template()},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        labels = [s["label"] for s in response.get_json()["projection"]["stages"]]
        self.assertEqual(labels, DEFAULT_LABELS)

    def test_post_bare_workflow_body(self):
        response = self.client.post(
            "/api/workflow/stages",
            json=narration_only_template(),
        )
        self.assertEqual(response.status_code, 200)
        labels = [s["label"] for s in response.get_json()["projection"]["stages"]]
        self.assertEqual(labels, ["Script", "Voice"])

    def test_post_empty_nodes_returns_stage_projection_invalid(self):
        response = self.client.post(
            "/api/workflow/stages",
            json={"nodes": [], "edges": []},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.get_json()["error"]["code"], "STAGE_PROJECTION_INVALID"
        )

    def test_stage_shape_matches_contract(self):
        response = self.client.get(
            f"/api/workflows/{self.workflow['workflow_id']}/stages"
        )
        stage = response.get_json()["projection"]["stages"][0]
        for field in (
            "key",
            "label",
            "ordinal",
            "node_ids",
            "status",
            "provider_capable",
            "active_provider_instance_id",
            "artifacts",
            "issues",
        ):
            self.assertIn(field, stage)


if __name__ == "__main__":
    unittest.main()
