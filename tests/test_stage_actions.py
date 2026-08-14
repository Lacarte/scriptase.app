"""Step 2.4 — Step detail panel actions map onto existing run modes.

Done when: each action on a step produces the same execution record a
canvas-initiated run would, proven by a test comparing both records field by
field.

Guards:
- No new execution path (only ported run modes)
- Primary target prefers assemble over captions in Composer
- Provider capability is metadata; -P never appears in stage names
- Inspect actions do not start runs
"""

from __future__ import annotations

import time
import unittest

from scriptase.engine.execution import ExecutionManager
from scriptase.engine.scheduler import calculate_scope
from scriptase.engine.templates import full_video_template
from scriptase.jobs.stage_actions import (
    ACTION_RUN_MODES,
    EXECUTABLE_STAGE_ACTIONS,
    STAGE_ACTIONS,
    StageActionError,
    action_requires_provider,
    build_stage_run_request,
    is_executable_action,
    is_side_branch_type,
    normalize_execution_record_for_compare,
    run_mode_for_action,
    stage_for_key,
    stage_primary_target,
)
from scriptase.jobs.stage_projection import project_stages


def _full_video(*, script_text: str = "Hello from the step detail panel.") -> dict:
    draft = full_video_template()
    draft.pop("template_id", None)
    for node in draft["nodes"]:
        if node["type"] == "script.input":
            node["configuration"] = {
                **(node.get("configuration") or {}),
                "text": script_text,
            }
    return draft


def _wait(manager: ExecutionManager, execution_id: str, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    handle = None
    while time.time() < deadline:
        handle = manager.active.get(execution_id)
        if handle is not None and handle.thread is not None:
            break
        time.sleep(0.01)
    assert handle is not None, f"execution {execution_id} never became active"
    handle.thread.join(timeout=timeout)
    # Record may still be finishing persistence; poll status.
    while time.time() < deadline:
        record = handle.scheduler.record.to_dict()
        if record.get("status") in {"succeeded", "failed", "cancelled", "partial"}:
            return record
        time.sleep(0.02)
    return handle.scheduler.record.to_dict()


def _stub_chain() -> dict:
    """Tiny linear workflow of stubs so runs complete without providers."""
    return {
        "schema_version": 1,
        "name": "Stage action stub chain",
        "description": "",
        "nodes": [
            {
                "id": "sample",
                "type": "stub.input",
                "type_version": 1,
                "name": "Sample",
                "position": {"x": 0, "y": 0},
                "configuration": {
                    "port_type": "generic_json",
                    "payload": {"answer": 42},
                },
                "disabled": False,
            },
            {
                "id": "viewer",
                "type": "stub.output",
                "type_version": 1,
                "name": "Viewer",
                "position": {"x": 200, "y": 0},
                "configuration": {"port_type": "generic_json"},
                "disabled": False,
            },
            {
                "id": "viewer_b",
                "type": "stub.output",
                "type_version": 1,
                "name": "Viewer B",
                "position": {"x": 400, "y": 0},
                "configuration": {"port_type": "generic_json"},
                "disabled": False,
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source_node": "sample",
                "source_port": "value",
                "target_node": "viewer",
                "target_port": "value",
                "edge_type": "data",
            },
            {
                "id": "e2",
                "source_node": "viewer",
                "source_port": "value",
                "target_node": "viewer_b",
                "target_port": "value",
                "edge_type": "data",
            },
        ],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {"on_error": "stop"},
        "extensions": {},
    }


class StageActionMappingTests(unittest.TestCase):
    def test_executable_actions_map_to_ported_run_modes(self):
        expected = {
            "run": "node_with_deps",
            "test": "node_isolated",
            "regenerate": "retry_failed",
            "run_from_here": "from_node",
        }
        self.assertEqual(ACTION_RUN_MODES, expected)
        for action, mode in expected.items():
            self.assertTrue(is_executable_action(action))
            self.assertEqual(run_mode_for_action(action), mode)

    def test_inspect_actions_do_not_start_runs(self):
        for action in ("view_input", "view_output", "provider", "history", "approve"):
            self.assertFalse(is_executable_action(action))
            with self.assertRaises(StageActionError):
                run_mode_for_action(action)

    def test_unknown_action_rejected(self):
        with self.assertRaises(StageActionError):
            run_mode_for_action("explode")

    def test_stage_actions_catalog_covers_section_18(self):
        # §18: Run, Test, Regenerate, Run From Here, View Input, View Output,
        # Provider, History, Approve.
        self.assertEqual(
            set(STAGE_ACTIONS),
            {
                "run",
                "test",
                "regenerate",
                "run_from_here",
                "view_input",
                "view_output",
                "provider",
                "history",
                "approve",
            },
        )
        self.assertEqual(
            set(EXECUTABLE_STAGE_ACTIONS),
            {"run", "test", "regenerate", "run_from_here"},
        )


class StagePrimaryTargetTests(unittest.TestCase):
    def test_voice_stage_targets_tts_node(self):
        workflow = _full_video()
        stage = stage_for_key(workflow, "voice")
        self.assertIn("n_tts", stage["node_ids"])
        self.assertEqual(stage_primary_target(stage, workflow), "n_tts")

    def test_composer_prefers_assemble_over_captions(self):
        workflow = _full_video()
        stage = stage_for_key(workflow, "composer")
        self.assertGreaterEqual(len(stage["node_ids"]), 2)
        target = stage_primary_target(stage, workflow)
        # Find the type of the chosen target — must be primary, not side branch.
        node = next(n for n in workflow["nodes"] if n["id"] == target)
        self.assertFalse(is_side_branch_type(node["type"]))
        self.assertEqual(node["type"], "assemble.project")

    def test_empty_stage_raises(self):
        with self.assertRaises(StageActionError):
            stage_primary_target({"key": "review", "node_ids": []}, _full_video())


class StageRunRequestTests(unittest.TestCase):
    def test_build_request_matches_canvas_shape(self):
        workflow = _full_video()
        workflow["workflow_id"] = "wf_TEST01"
        stage = stage_for_key(workflow, "voice")
        body = build_stage_run_request("run", stage, workflow)
        self.assertEqual(
            body,
            {
                "workflow_id": "wf_TEST01",
                "run_mode": "node_with_deps",
                "target_node_ids": ["n_tts"],
                "force": False,
            },
        )

    def test_draft_request_embeds_workflow_document(self):
        workflow = _full_video()
        stage = stage_for_key(workflow, "script")
        body = build_stage_run_request("test", stage, workflow)
        self.assertNotIn("workflow_id", body)
        self.assertIn("workflow", body)
        self.assertEqual(body["run_mode"], "node_isolated")
        self.assertEqual(body["target_node_ids"], ["n_script"])

    def test_each_action_scope_matches_canvas_calculate_scope(self):
        """Production and canvas must expand to the same scope for every action."""
        workflow = _full_video()
        stage = stage_for_key(workflow, "timing")
        target = stage_primary_target(stage, workflow)
        for action, mode in ACTION_RUN_MODES.items():
            body = build_stage_run_request(action, stage, workflow)
            # Canvas would call calculate_scope with the same mode + targets.
            canvas_scope = calculate_scope(
                workflow, body["run_mode"], body["target_node_ids"]
            )
            production_scope = calculate_scope(workflow, mode, [target])
            self.assertEqual(
                canvas_scope,
                production_scope,
                msg=f"scope mismatch for action={action!r} mode={mode!r}",
            )
            self.assertEqual(body["run_mode"], mode)
            self.assertEqual(body["target_node_ids"], [target])


class ProviderCapabilityTests(unittest.TestCase):
    def test_provider_required_only_for_capable_executable_actions(self):
        capable = {
            "key": "voice",
            "provider_capable": True,
            "node_ids": ["n_tts"],
        }
        local = {
            "key": "timing",
            "provider_capable": False,
            "node_ids": ["n_align"],
        }
        self.assertTrue(action_requires_provider("run", capable))
        self.assertFalse(action_requires_provider("run", local))
        self.assertFalse(action_requires_provider("view_input", capable))
        self.assertFalse(action_requires_provider("provider", capable))

    def test_projection_labels_never_contain_dash_p(self):
        projection = project_stages(_full_video())
        for stage in projection["stages"]:
            self.assertNotIn("-P", stage["label"])
            self.assertNotIn("-P", stage["key"])


class ProductionCanvasRecordParityTests(unittest.TestCase):
    """Done-when: Production action and canvas run produce equal records."""

    def test_each_executable_action_matches_canvas_record_field_by_field(self):
        # Use stub nodes so the run completes offline without providers.
        # Stage action mapping is tested above against full_video; here we
        # prove the *engine path* is identical by starting two runs with the
        # body Production would build vs the body the canvas would send.
        workflow = _stub_chain()
        # Synthetic stage pointing at viewer (the "primary" processing node).
        stage = {
            "key": "export",
            "label": "Export",
            "node_ids": ["viewer"],
            "provider_capable": False,
        }

        for action in sorted(EXECUTABLE_STAGE_ACTIONS):
            with self.subTest(action=action):
                production_body = build_stage_run_request(
                    action, stage, workflow, force=False
                )
                # Canvas-initiated: same mode + same target, no Production helper.
                canvas_body = {
                    "run_mode": ACTION_RUN_MODES[action],
                    "target_node_ids": ["viewer"],
                    "force": False,
                    "workflow": workflow,
                }
                self.assertEqual(
                    {
                        "run_mode": production_body["run_mode"],
                        "target_node_ids": production_body["target_node_ids"],
                        "force": production_body["force"],
                    },
                    {
                        "run_mode": canvas_body["run_mode"],
                        "target_node_ids": canvas_body["target_node_ids"],
                        "force": canvas_body["force"],
                    },
                    msg="request bodies must match before either run starts",
                )

                # Force must be False so cache behaviour is comparable; use
                # separate managers so queue isolation is clean.
                prod_mgr = ExecutionManager(output_dir=self._tmp())
                canvas_mgr = ExecutionManager(output_dir=self._tmp())

                prod_id, _ = prod_mgr.start(
                    workflow,
                    run_mode=production_body["run_mode"],
                    target_node_ids=list(production_body["target_node_ids"]),
                    force=False,
                    source="manual",
                )
                canvas_id, _ = canvas_mgr.start(
                    workflow,
                    run_mode=canvas_body["run_mode"],
                    target_node_ids=list(canvas_body["target_node_ids"]),
                    force=False,
                    source="manual",
                )
                prod_record = _wait(prod_mgr, prod_id)
                canvas_record = _wait(canvas_mgr, canvas_id)

                prod_norm = normalize_execution_record_for_compare(prod_record)
                canvas_norm = normalize_execution_record_for_compare(canvas_record)
                self.assertEqual(
                    prod_norm,
                    canvas_norm,
                    msg=(
                        f"execution records diverged for action={action!r}\n"
                        f"production={prod_norm!r}\ncanvas={canvas_norm!r}"
                    ),
                )
                # Both must have actually run the expected mode/scope.
                self.assertEqual(prod_norm["run_mode"], ACTION_RUN_MODES[action])
                self.assertIn("viewer", prod_norm["scope_node_ids"])

    def test_full_video_action_requests_match_canvas_for_every_stage(self):
        """For every occupied Production stage, each action's request equals
        what the canvas would POST for the same primary node + mode."""
        workflow = _full_video()
        workflow["workflow_id"] = "wf_ABC123"
        projection = project_stages(workflow)
        for stage in projection["stages"]:
            if not stage["node_ids"]:
                continue
            target = stage_primary_target(stage, workflow)
            for action, mode in ACTION_RUN_MODES.items():
                production = build_stage_run_request(
                    action, stage, workflow, workflow_id="wf_ABC123"
                )
                canvas = {
                    "workflow_id": "wf_ABC123",
                    "run_mode": mode,
                    "target_node_ids": [target],
                    "force": False,
                }
                self.assertEqual(
                    production,
                    canvas,
                    msg=f"stage={stage['key']!r} action={action!r}",
                )

    _dirs: list = []

    def _tmp(self) -> str:
        import tempfile

        path = tempfile.mkdtemp(prefix="stage-actions-")
        self._dirs.append(path)
        return path

    @classmethod
    def tearDownClass(cls):
        import shutil

        for path in cls._dirs:
            shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
