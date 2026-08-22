"""Phase 1.6/1.7 workflow validation, persistence, routes, and templates."""

import json
import math
import os
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from datetime import datetime

from flask import Flask
from unittest.mock import patch

from scriptase.engine import workflows_bp
from scriptase.engine.models import workflow_draft
from scriptase.engine import persistence
from scriptase.engine.persistence import WorkflowConflict, WorkflowValidationError
from scriptase.engine.templates import serialize_templates
from scriptase.engine.registry import get_node_type
from scriptase.engine import registry
from scriptase.engine.scheduler import WorkflowScheduler
from scriptase.engine.validation import validate_workflow, validation_errors
from scriptase.engine.validation import _field_is_visible


def script_node(node_id="n_script"):
    return {
        "id": node_id,
        "type": "script.input",
        "type_version": 1,
        "name": "Script",
        "position": {"x": 0, "y": 0},
        "configuration": {"text": "A small test script."},
        "disabled": False,
    }


def draft(name="Test workflow"):
    document = workflow_draft(name=name)
    document["nodes"] = [script_node()]
    return document


class WorkflowTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sts_workflows_")
        self.old_workflows = persistence.WORKFLOWS_DIR
        self.old_trash = persistence.TRASH_DIR
        persistence.WORKFLOWS_DIR = os.path.join(self.temp.name, "workflows")
        persistence.TRASH_DIR = os.path.join(self.temp.name, "trash")
        os.makedirs(persistence.WORKFLOWS_DIR, exist_ok=True)

    def tearDown(self):
        persistence.WORKFLOWS_DIR = self.old_workflows
        persistence.TRASH_DIR = self.old_trash
        self.temp.cleanup()


class ValidationTests(unittest.TestCase):
    def test_error_policies_are_capability_gated_and_bounded(self):
        document = draft()
        document["nodes"][0]["on_error"] = {
            "policy": "retry", "max_attempts": 11, "delay_ms": -1, "backoff_multiplier": 0.5,
        }
        problems = validation_errors(validate_workflow(document, require_identity=False))
        messages = [problem["message"] for problem in problems]
        self.assertTrue(any("not supported" in message for message in messages))
        self.assertTrue(any("1 to 10" in message for message in messages))
        self.assertTrue(any("0 to 60000" in message for message in messages))

    def test_explicit_error_control_output_is_a_valid_edge(self):
        document = draft()
        document["nodes"].extend([
            {
                "id": "n_tts", "type": "tts.generate", "type_version": 4, "name": "TTS",
                "position": {"x": 200, "y": 0}, "configuration": {}, "disabled": False,
                "on_error": {"policy": "continue_error"},
            },
            {
                "id": "n_recover", "type": "project.setup", "type_version": 1, "name": "Recover",
                "position": {"x": 400, "y": 0}, "configuration": {}, "disabled": False,
            },
        ])
        document["edges"] = [
            {"id": "e_data", "source_node": "n_script", "source_port": "script",
             "target_node": "n_tts", "target_port": "script", "edge_type": "data"},
            {"id": "e_error", "source_node": "n_tts", "source_port": "error",
             "target_node": "n_recover", "target_port": "trigger", "edge_type": "control"},
        ]
        self.assertEqual(validation_errors(validate_workflow(document, require_identity=False)), [])

    def test_conditional_field_visibility_matches_inspector_rules(self):
        field = {"display_options": {"show": {"enabled": [True]}}}
        self.assertFalse(_field_is_visible(field, {"enabled": False}))
        self.assertTrue(_field_is_visible(field, {"enabled": True}))
        hidden = {"display_options": {"hide": {"mode": ["auto"]}}}
        self.assertFalse(_field_is_visible(hidden, {"mode": "auto"}))
        self.assertTrue(_field_is_visible(hidden, {"mode": "manual"}))

    def test_valid_draft_has_only_missing_input_warnings_when_incomplete(self):
        document = draft()
        problems = validate_workflow(document, require_identity=False)
        self.assertEqual(validation_errors(problems), [])

    def test_rejects_unknown_fields_types_cycles_and_dynamic_mismatch(self):
        document = draft()
        document["surprise"] = True
        document["nodes"].append({
            "id": "n_output", "type": "workflow.output", "type_version": 1,
            "name": "Output", "position": {"x": 200, "y": 0},
            "configuration": {"port_type": "audio_file", "label": ""}, "disabled": False,
        })
        document["edges"] = [
            {"id": "e_bad", "source_node": "n_script", "source_port": "script",
             "target_node": "n_output", "target_port": "value", "edge_type": "data"},
        ]
        codes = {problem["code"] for problem in validation_errors(
            validate_workflow(document, require_identity=False)
        )}
        self.assertIn("WORKFLOW_INVALID", codes)
        self.assertIn("PORT_TYPE_MISMATCH", codes)

    def test_built_in_templates_are_typed_valid_and_schedulable(self):
        templates = serialize_templates()
        self.assertEqual([item["template_id"] for item in templates], [
            "full_video",
            "narration_only",
            "storyboard_only",
            "reexport_existing_project",
        ])

        def resolver(node):
            def execute(inputs, config, context):
                return {
                    port["id"]: ({"ok": True} if port["type"] == "control" else {})
                    for port in get_node_type(node["type"])["outputs"]
                }
            return execute

        with tempfile.TemporaryDirectory(prefix="sts_template_runs_") as root:
            for item in templates:
                workflow = deepcopy(item["workflow"])
                problems = validate_workflow(
                    workflow, require_identity=False, require_complete=False
                )
                self.assertEqual(validation_errors(problems), [], item["template_id"])
                workflow.update({
                    "workflow_id": "wf_ABC123",
                    "created_at": "2026-08-04T12:00:00Z",
                    "updated_at": "2026-08-04T12:00:00Z",
                })
                for node in workflow["nodes"]:
                    if node["type"] == "script.input":
                        node["configuration"]["text"] = "A small template execution test."
                    elif node["type"] == "project.existing":
                        node["configuration"]["project_id"] = "pm_ABC123"
                result = WorkflowScheduler(
                    workflow,
                    project_id="pm_ABC123",
                    lock_root=os.path.join(root, "locks"),
                    output_dir=root,
                    executor_resolver=resolver,
                ).run()
                self.assertEqual(result.status, "succeeded", item["template_id"])

        self.assertTrue(any(
            problem["severity"] == "warning"
            for problem in validate_workflow(
                templates[0]["workflow"], require_identity=False, require_complete=False
            )
        ))

    def test_rejects_non_finite_numbers_and_excessive_nesting(self):
        non_finite = draft()
        non_finite["viewport"]["x"] = math.nan
        problems = validation_errors(validate_workflow(non_finite, require_identity=False))
        self.assertIn("finite", problems[0]["message"])

        nested = draft()
        value = {}
        nested["extensions"] = value
        for _ in range(20):
            value["child"] = {}
            value = value["child"]
        problems = validation_errors(validate_workflow(nested, require_identity=False))
        self.assertIn("nesting depth", problems[0]["message"])

    def test_rejects_oversized_variables_and_bad_extensions(self):
        oversized = draft()
        oversized["variables"] = {"value": "x" * (64 * 1024)}
        problems = validation_errors(validate_workflow(oversized, require_identity=False))
        self.assertTrue(any(problem.get("path") == "variables" for problem in problems))

        populated = draft()
        populated["variables"] = {"future": True}
        problems = validation_errors(validate_workflow(populated, require_identity=False))
        self.assertFalse(any(problem.get("path") == "variables" for problem in problems))

        bad_extensions = draft()
        bad_extensions["extensions"] = []
        problems = validation_errors(validate_workflow(bad_extensions, require_identity=False))
        self.assertTrue(any(problem.get("path") == "extensions" for problem in problems))

    def test_persisted_identity_requires_timezone_aware_timestamps(self):
        document = draft()
        document.update({
            "workflow_id": "wf_ABC123",
            "created_at": "2026-08-04T12:00:00",
            "updated_at": "not-a-timestamp",
        })
        problems = validation_errors(validate_workflow(document))
        timestamp_paths = {problem.get("path") for problem in problems}
        self.assertEqual(timestamp_paths & {"created_at", "updated_at"}, {"created_at", "updated_at"})


class PersistenceTests(WorkflowTestBase):
    def test_load_applies_two_hop_node_migration_and_resave_persists_it(self):
        definition = get_node_type("script.input")
        definition["type_version"] = 3
        definition["migrations"] = {
            1: lambda config: {"body": config["text"]},
            2: lambda config: {"text": config["body"] + " (migrated)"},
        }
        document = draft()
        document.update({
            "workflow_id": "wf_ABC123",
            "created_at": "2026-08-05T12:00:00+00:00",
            "updated_at": "2026-08-05T12:00:00+00:00",
        })
        path = os.path.join(persistence.WORKFLOWS_DIR, "wf_ABC123.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)

        with patch.dict(registry._NODE_TYPES, {"script.input": definition}):
            state = persistence.load_workflow_state("wf_ABC123")
            self.assertFalse(state.read_only)
            self.assertEqual(state.document["nodes"][0]["type_version"], 3)
            self.assertEqual(
                state.document["nodes"][0]["configuration"]["text"],
                "A small test script. (migrated)",
            )
            self.assertEqual(
                [(item["from_version"], item["to_version"]) for item in state.trail],
                [(1, 2), (2, 3)],
            )
            # Loading is non-destructive; Save is the explicit persistence point.
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["nodes"][0]["type_version"], 1)

            saved = persistence.update_workflow(
                "wf_ABC123",
                state.document,
                expected_updated_at=state.document["updated_at"],
            )
            self.assertEqual(saved["nodes"][0]["type_version"], 3)
            self.assertEqual(
                len(saved["extensions"]["type_version_migrations"]), 2
            )

    def test_create_load_update_list_and_soft_delete(self):
        created = persistence.create_workflow(draft())
        self.assertRegex(created["workflow_id"], r"^wf_[A-Z0-9]{6}$")
        loaded = persistence.load_workflow(created["workflow_id"])
        self.assertEqual(loaded, created)

        changed = dict(loaded)
        changed["name"] = "Renamed"
        updated = persistence.update_workflow(
            created["workflow_id"], changed, expected_updated_at=created["updated_at"]
        )
        self.assertEqual(updated["name"], "Renamed")
        items, total = persistence.list_workflows()
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["workflow_id"], created["workflow_id"])

        persistence.delete_workflow(
            created["workflow_id"], expected_updated_at=updated["updated_at"]
        )
        self.assertFalse(os.path.exists(os.path.join(
            persistence.WORKFLOWS_DIR, f"{created['workflow_id']}.json"
        )))
        trash = os.path.join(persistence.TRASH_DIR, "workflows")
        self.assertEqual(len(os.listdir(trash)), 2)  # JSON + atomic-write backup.

    def test_conflict_and_invalid_id_are_rejected(self):
        created = persistence.create_workflow(draft())
        with self.assertRaises(WorkflowConflict):
            persistence.update_workflow(
                created["workflow_id"], created, expected_updated_at="stale"
            )
        with self.assertRaises(ValueError):
            persistence.load_workflow("../../escape")

    def test_invalid_document_is_not_written(self):
        bad = draft()
        bad["nodes"][0]["configuration"]["text"] = 123
        with self.assertRaises(WorkflowValidationError):
            persistence.create_workflow(bad)
        self.assertEqual(os.listdir(persistence.WORKFLOWS_DIR), [])

    def test_import_allocates_a_new_id(self):
        created = persistence.create_workflow(draft())
        imported, original_id = persistence.import_workflow(created)
        self.assertEqual(original_id, created["workflow_id"])
        self.assertNotEqual(imported["workflow_id"], created["workflow_id"])

    def test_import_rejects_a_malformed_source_id(self):
        document = draft()
        document["workflow_id"] = "../../escape"
        with self.assertRaises(WorkflowValidationError):
            persistence.import_workflow(document)

    def test_interleaved_writers_serialize_and_keep_the_conflict_signal(self):
        """Step 6.2: two writers holding the same token — one wins, one conflicts."""
        created = persistence.create_workflow(draft())
        workflow_id = created["workflow_id"]

        original_load = persistence.load_workflow
        section_guard = threading.Lock()
        section = {"active": 0, "max": 0}

        def slow_load(target_id):
            with section_guard:
                section["active"] += 1
                section["max"] = max(section["max"], section["active"])
            try:
                document = original_load(target_id)
                time.sleep(0.2)  # Without locking both writers overlap here.
                return document
            finally:
                with section_guard:
                    section["active"] -= 1

        outcomes = {}

        def writer(label):
            changed = dict(created)
            changed["name"] = f"Writer {label}"
            try:
                outcomes[label] = persistence.update_workflow(
                    workflow_id, changed, expected_updated_at=created["updated_at"]
                )
            except WorkflowConflict:
                outcomes[label] = "conflict"

        persistence.load_workflow = slow_load
        try:
            threads = [
                threading.Thread(target=writer, args=(label,)) for label in ("a", "b")
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
        finally:
            persistence.load_workflow = original_load

        self.assertEqual(section["max"], 1)  # Single writer in the critical section.
        winners = [value for value in outcomes.values() if isinstance(value, dict)]
        self.assertEqual(len(winners), 1)
        self.assertEqual(list(outcomes.values()).count("conflict"), 1)
        stored = persistence.load_workflow(workflow_id)  # Parses and validates.
        self.assertEqual(stored, winners[0])

    def test_updated_at_is_strictly_monotonic_within_the_same_instant(self):
        frozen = "2026-08-05T12:00:00.000000+00:00"
        original_now = persistence.now_iso
        persistence.now_iso = lambda: frozen
        try:
            created = persistence.create_workflow(draft())
            first = persistence.update_workflow(
                created["workflow_id"], dict(created, name="First"),
                expected_updated_at=created["updated_at"],
            )
            second = persistence.update_workflow(
                created["workflow_id"], dict(first, name="Second"),
                expected_updated_at=first["updated_at"],
            )
        finally:
            persistence.now_iso = original_now
        stamps = [created["updated_at"], first["updated_at"], second["updated_at"]]
        self.assertEqual(len(set(stamps)), 3)
        parsed = [datetime.fromisoformat(stamp) for stamp in stamps]
        self.assertLess(parsed[0], parsed[1])
        self.assertLess(parsed[1], parsed[2])

    def test_trash_removes_the_backup_resurrection_path(self):
        created = persistence.create_workflow(draft())
        updated = persistence.update_workflow(
            created["workflow_id"], dict(created, name="Renamed"),
            expected_updated_at=created["updated_at"],
        )
        backup = os.path.join(
            persistence.WORKFLOWS_DIR, f"{created['workflow_id']}.json.bak"
        )
        self.assertTrue(os.path.isfile(backup))
        persistence.delete_workflow(
            created["workflow_id"], expected_updated_at=updated["updated_at"]
        )
        remnants = [
            name for name in os.listdir(persistence.WORKFLOWS_DIR)
            if name.startswith(created["workflow_id"])
        ]
        self.assertEqual(remnants, [])  # No .bak left to resurrect from.
        with self.assertRaises(persistence.WorkflowNotFound):
            persistence.load_workflow(created["workflow_id"])
        with self.assertRaises(persistence.WorkflowNotFound):
            persistence.delete_workflow(created["workflow_id"])

    def test_delete_works_on_a_workflow_that_no_longer_parses(self):
        created = persistence.create_workflow(draft())
        path = os.path.join(persistence.WORKFLOWS_DIR, f"{created['workflow_id']}.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")
        persistence.delete_workflow(created["workflow_id"], expected_updated_at="anything")
        self.assertFalse(os.path.exists(path))
        trash = os.path.join(persistence.TRASH_DIR, "workflows")
        self.assertEqual(len(os.listdir(trash)), 1)


class DefaultWorkflowSeedTests(WorkflowTestBase):
    """Step 12.2 — a fresh install opens on a runnable Full Video graph."""

    def _marker(self):
        return os.path.join(
            persistence.WORKFLOWS_DIR, persistence.DEFAULT_WORKFLOW_MARKER
        )

    def test_fresh_install_is_seeded_with_a_complete_full_video_workflow(self):
        seeded = persistence.ensure_default_workflow()
        self.assertIsNotNone(seeded)
        self.assertEqual(seeded["name"], "Full Video")
        self.assertNotIn("template_id", seeded)

        template = next(
            item["workflow"] for item in serialize_templates()
            if item["template_id"] == persistence.DEFAULT_WORKFLOW_TEMPLATE_ID
        )
        self.assertEqual(
            [node["type"] for node in seeded["nodes"]],
            [node["type"] for node in template["nodes"]],
        )

        # Production's dropdown reads the same list the builder does.
        items, total = persistence.list_workflows()
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["workflow_id"], seeded["workflow_id"])
        # Runnability of the template itself is covered by
        # test_built_in_templates_are_typed_valid_and_schedulable; here the
        # point is that the seeded copy survives the persistence round trip.
        self.assertEqual(persistence.load_workflow(seeded["workflow_id"]), seeded)

    def test_seeding_is_a_once_per_installation_event(self):
        seeded = persistence.ensure_default_workflow()
        self.assertTrue(os.path.exists(self._marker()))
        self.assertIsNone(persistence.ensure_default_workflow())
        self.assertEqual(persistence.list_workflows()[1], 1)

        # A user who deletes every workflow must not have one resurrected.
        persistence.delete_workflow(seeded["workflow_id"])
        self.assertIsNone(persistence.ensure_default_workflow())
        self.assertEqual(persistence.list_workflows()[1], 0)

    def test_an_existing_store_is_never_seeded(self):
        created = persistence.create_workflow(draft())
        self.assertIsNone(persistence.ensure_default_workflow())
        items, total = persistence.list_workflows()
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["workflow_id"], created["workflow_id"])


class RouteTests(WorkflowTestBase):
    def setUp(self):
        super().setUp()
        app = Flask(__name__)
        app.register_blueprint(workflows_bp)
        self.client = app.test_client()

    def test_crud_import_export_and_templates(self):
        response = self.client.post("/api/workflows", json={"workflow": draft()})
        self.assertEqual(response.status_code, 201)
        workflow = response.get_json()["workflow"]
        workflow_id = workflow["workflow_id"]

        self.assertEqual(self.client.get("/api/workflows").status_code, 200)
        self.assertEqual(self.client.get(f"/api/workflows/{workflow_id}").status_code, 200)
        exported = self.client.get(f"/api/workflows/{workflow_id}/export")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("attachment", exported.headers["Content-Disposition"])
        self.assertEqual(self.client.get("/api/workflow/templates").status_code, 200)

        workflow["name"] = "Updated"
        updated = self.client.put(f"/api/workflows/{workflow_id}", json={
            "workflow": workflow,
            "expected_updated_at": workflow["updated_at"],
        })
        self.assertEqual(updated.status_code, 200)
        workflow = updated.get_json()["workflow"]

        imported = self.client.post("/api/workflows/import", json={"workflow": workflow})
        self.assertEqual(imported.status_code, 201)
        self.assertNotEqual(imported.get_json()["workflow"]["workflow_id"], workflow_id)

        deleted = self.client.delete(f"/api/workflows/{workflow_id}", json={
            "expected_updated_at": workflow["updated_at"],
        })
        self.assertEqual(deleted.status_code, 200)

    def test_hand_corrupted_workflow_can_be_trashed_via_the_api(self):
        response = self.client.post("/api/workflows", json={"workflow": draft()})
        workflow = response.get_json()["workflow"]
        workflow_id = workflow["workflow_id"]
        workflow["name"] = "Updated"
        updated = self.client.put(f"/api/workflows/{workflow_id}", json={
            "workflow": workflow,
            "expected_updated_at": workflow["updated_at"],
        })
        self.assertEqual(updated.status_code, 200)  # Rotates a .bak alongside.

        path = os.path.join(persistence.WORKFLOWS_DIR, f"{workflow_id}.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{ hand-corrupted, no longer parses")

        deleted = self.client.delete(f"/api/workflows/{workflow_id}", json={})
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.get_json()["deleted"])

        # Neither the primary nor the .bak survives to resurrect the workflow.
        gone = self.client.get(f"/api/workflows/{workflow_id}")
        self.assertEqual(gone.status_code, 404)
        trash = os.path.join(persistence.TRASH_DIR, "workflows")
        self.assertEqual(len(os.listdir(trash)), 2)  # Corrupt JSON + its .bak.

    def test_validation_conflict_and_loopback_errors_use_envelope(self):
        bad = draft()
        bad["nodes"][0]["type"] = "unknown.node"
        response = self.client.post("/api/workflows", json={"workflow": bad})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "WORKFLOW_INVALID")

        denied = self.client.get(
            "/api/workflows", environ_overrides={"REMOTE_ADDR": "10.1.2.3"}
        )
        self.assertEqual(denied.status_code, 403)
        self.assertIn("error", denied.get_json())

    def test_future_node_version_opens_read_only_with_visible_metadata(self):
        document = draft()
        document.update({
            "workflow_id": "wf_FUTURE",
            "created_at": "2026-08-05T12:00:00+00:00",
            "updated_at": "2026-08-05T12:00:00+00:00",
        })
        document["nodes"][0]["type_version"] = 99
        document["nodes"][0]["configuration"] = {"future_field": True}
        path = os.path.join(persistence.WORKFLOWS_DIR, "wf_FUTURE.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)

        opened = self.client.get("/api/workflows/wf_FUTURE")
        self.assertEqual(opened.status_code, 200)
        payload = opened.get_json()
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["warnings"][0]["code"], "FUTURE_NODE_VERSION")
        self.assertEqual(payload["workflow"]["nodes"][0]["configuration"], {"future_field": True})

        update = self.client.put("/api/workflows/wf_FUTURE", json={
            "workflow": payload["workflow"],
            "expected_updated_at": payload["workflow"]["updated_at"],
        })
        self.assertEqual(update.status_code, 409)
        self.assertEqual(update.get_json()["error"]["code"], "WORKFLOW_READ_ONLY")


if __name__ == "__main__":
    unittest.main()
