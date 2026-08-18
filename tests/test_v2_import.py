"""Step 10.1: V2 project / settings / workflow import.

Done when: a V2 project imports and re-exports without manual edits, and its
saved workflows validate and run. Domain renames and settings-shape aliases
live in ``scriptase.migration.v2``.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scriptase.engine.scheduler import WorkflowScheduler
from scriptase.engine.validation import validate_workflow, validation_errors
from scriptase.migration.v2 import (
    DOMAIN_ALIASES,
    OUTPUT_LAYOUT_DIRS,
    SELECTION_ALIASES,
    SETTINGS_SHAPE,
    V2ImportError,
    export_project,
    import_project_from_zip,
    import_project_tree,
    import_settings,
    import_v2_root,
    import_workflow,
    migrate_settings_document,
    migrate_workflow_document,
    resolve_domain,
    resolve_selection,
    validate_migrated_workflow,
)
from scriptase.modules.compose.project_zip_service import (
    export_project_zip,
    import_project_zip,
)
from scriptase.providers.settings_migrations import SETTINGS_VERSION


# ---------------------------------------------------------------------------
# Fixtures — synthetic V2 documents (no live V2 tree required)
# ---------------------------------------------------------------------------


def _v2_settings_v4() -> dict:
    """Pre-rename, pre-instance-split settings (V2 shape at version 4)."""
    return {
        "version": 4,
        "general": {"auto_sync": False, "default_style": "cinematic"},
        "domains": {
            "animator": {
                "selected_provider": "grok",
                "per_provider": {
                    "grok_automa": {"duration": "6s", "mode": "video", "quality": "480p"},
                    "kie-ai": {"api_key": "", "model": "google/nano-banana"},
                },
            },
            "storyboard": {
                "selected_provider": "gemini",
                "per_provider": {
                    "gemini_ws": {"auto_type": False},
                    "webhook": {"image_model": ""},
                },
            },
            "tts": {
                "selected_provider": "kokoro",
                "per_provider": {
                    "kokoro": {"voice": "af_bella", "speed": 1},
                },
            },
            "script": {
                "selected_provider": "gemini",
                "per_provider": {},
            },
            "scene_blueprint": {
                "selected_provider": "n8n",
                "per_provider": {},
            },
        },
    }


def _v2_workflow() -> dict:
    """V2 saved workflow with v1 provider-capable node configs."""
    return {
        "schema_version": 1,
        "workflow_id": "wf_V2IMP1",
        "name": "V2 import fixture",
        "description": "Complete production-shaped graph",
        "nodes": [
            {
                "id": "n_trigger",
                "type": "trigger.manual",
                "type_version": 1,
                "name": "Trigger",
                "position": {"x": 0, "y": 0},
                "configuration": {},
                "disabled": False,
            },
            {
                "id": "n_script",
                "type": "script.input",
                "type_version": 1,
                "name": "Script",
                "position": {"x": 200, "y": 0},
                "configuration": {"text": "Hello from V2 import."},
                "disabled": False,
            },
            {
                "id": "n_tts",
                "type": "tts.generate",
                "type_version": 1,
                "name": "TTS",
                "position": {"x": 400, "y": 0},
                "configuration": {"engine": "kokoro", "voice": "af_heart", "speed": 1.0},
                "disabled": False,
            },
            {
                "id": "n_storyboard",
                "type": "storyboard.generate",
                "type_version": 1,
                "name": "Storyboard",
                "position": {"x": 600, "y": 0},
                "configuration": {
                    "provider": "webhook",
                    "prompt_prefix": "cinematic",
                    "auto_type": True,
                },
                "disabled": False,
            },
            {
                "id": "n_animator",
                "type": "animator.generate",
                "type_version": 1,
                "name": "Animator",
                "position": {"x": 800, "y": 0},
                "configuration": {
                    "provider": "grok",
                    "mode": "video",
                    "quality": "480p",
                    "duration": "6s",
                },
                "disabled": False,
            },
        ],
        "edges": [
            {
                "id": "e_t_s",
                "edge_type": "control",
                "source_node": "n_trigger",
                "source_port": "control",
                "target_node": "n_script",
                "target_port": "trigger",
            },
            {
                "id": "e_s_tts",
                "edge_type": "data",
                "source_node": "n_script",
                "source_port": "script",
                "target_node": "n_tts",
                "target_port": "script",
            },
        ],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {"on_error": "stop"},
        "extensions": {},
        "created_at": "2026-08-01T00:00:00+00:00",
        "updated_at": "2026-08-01T00:00:00+00:00",
    }


def _seed_v2_project(output_root: Path, project_id: str = "pm_V2IMP1") -> Path:
    """Write a minimal V2-shaped project tree under output_root."""
    projects = output_root / "projects" / project_id
    scenes = output_root / "scenes" / project_id
    animator = output_root / "animator" / project_id / "0"
    align = output_root / "alignments" / project_id
    tts = output_root / "tts" / project_id
    for path in (projects, scenes, animator, align, tts):
        path.mkdir(parents=True, exist_ok=True)

    project_doc = {
        "project_id": project_id,
        "project_name": "V2 Import Fixture",
        "source_folder": project_id,
        "style": "cinematic",
        "total_duration": 3.0,
        "scene_count": 1,
        "scenes": [
            {
                "id": 0,
                "scene_id": 0,
                "type": "image",
                "duration": 3.0,
                "script": "Hello from V2 import.",
                "image_url": f"/output/animator/{project_id}/0/frame.jpg",
            }
        ],
    }
    (projects / "initial.json").write_text(
        json.dumps(project_doc, indent=2), encoding="utf-8"
    )
    (scenes / "scenes.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "source_folder": project_id,
                "scenes": project_doc["scenes"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (animator / "frame.jpg").write_bytes(b"\xff\xd8\xfffake-jpeg")
    (align / "alignment.json").write_text(
        json.dumps({"words": [{"word": "Hello", "start": 0.0, "end": 0.5}]}),
        encoding="utf-8",
    )
    (tts / "audio.wav").write_bytes(b"RIFF....WAVEfmt ")
    return output_root


def _seed_v2_root(tmp: Path) -> Path:
    """Full mini V2 installation for import_v2_root."""
    root = tmp / "v2_install"
    (root / "settings").mkdir(parents=True)
    (root / "output" / "workflows").mkdir(parents=True)
    (root / "settings" / "settings.json").write_text(
        json.dumps(_v2_settings_v4(), indent=2), encoding="utf-8"
    )
    (root / "output" / "workflows" / "wf_V2IMP1.json").write_text(
        json.dumps(_v2_workflow(), indent=2), encoding="utf-8"
    )
    _seed_v2_project(root / "output", "pm_V2IMP1")
    return root


# ---------------------------------------------------------------------------
# Mapping documentation
# ---------------------------------------------------------------------------


class MappingTablesTests(unittest.TestCase):
    def test_domain_aliases_cover_the_three_renames(self):
        self.assertEqual(DOMAIN_ALIASES["scene_blueprint"], "scene_director")
        self.assertEqual(DOMAIN_ALIASES["storyboard"], "image")
        self.assertEqual(DOMAIN_ALIASES["animator"], "video")

    def test_settings_shape_aliases(self):
        self.assertEqual(SETTINGS_SHAPE["selected_provider"], "selected_instance_id")
        self.assertEqual(SETTINGS_SHAPE["per_provider"], "instances")

    def test_selection_aliases_are_domain_aware(self):
        self.assertEqual(resolve_selection("gemini", domain="image"), "gemini_ws")
        self.assertEqual(resolve_selection("gemini", domain="script"), "gemini")
        self.assertEqual(resolve_selection("webhook", domain="image"), "wavespeed_webhook")
        self.assertEqual(resolve_selection("grok", domain="video"), "grok_automa")
        self.assertEqual(resolve_selection("kie-ai", domain="video"), "kie_ai")

    def test_resolve_domain(self):
        self.assertEqual(resolve_domain("storyboard"), "image")
        self.assertEqual(resolve_domain("image"), "image")

    def test_output_layout_keeps_v2_directory_names(self):
        for name in ("tts", "scenes", "animator", "storyboard", "projects", "workflows"):
            self.assertIn(name, OUTPUT_LAYOUT_DIRS)

    def test_selection_aliases_table_exported(self):
        self.assertIn("image", SELECTION_ALIASES)
        self.assertEqual(SELECTION_ALIASES["image"]["webhook"], "wavespeed_webhook")


# ---------------------------------------------------------------------------
# Settings migration
# ---------------------------------------------------------------------------


class SettingsImportTests(unittest.TestCase):
    def test_migrate_settings_rewrites_domains_and_shape(self):
        migrated, changed = migrate_settings_document(_v2_settings_v4())
        self.assertTrue(changed)
        self.assertEqual(migrated["version"], SETTINGS_VERSION)
        domains = migrated["domains"]
        for retired in DOMAIN_ALIASES:
            self.assertNotIn(retired, domains)
        self.assertIn("scene_director", domains)
        self.assertIn("image", domains)
        self.assertIn("video", domains)
        image = domains["image"]
        self.assertEqual(image["selected_instance_id"], "gemini_ws")
        self.assertIn("instances", image)
        self.assertNotIn("selected_provider", image)
        self.assertNotIn("per_provider", image)
        # The retired Kie instance is migrated onto the prototype's Grok type.
        self.assertEqual(set(domains["video"]["instances"]), {"grok_automa"})
        self.assertEqual(domains["video"]["selected_instance_id"], "grok_automa")

    def test_import_settings_writes_dest(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "settings.json"
            migrated, changed = import_settings(
                _v2_settings_v4(), dest_path=dest, write=True
            )
            self.assertTrue(changed)
            self.assertTrue(dest.is_file())
            on_disk = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["version"], SETTINGS_VERSION)
            self.assertEqual(on_disk["domains"]["image"]["selected_instance_id"], "gemini_ws")
            # Idempotent re-import.
            again, changed_again = import_settings(on_disk, dest_path=dest, write=True)
            self.assertFalse(changed_again)
            self.assertEqual(again["version"], SETTINGS_VERSION)


# ---------------------------------------------------------------------------
# Workflow migration + run
# ---------------------------------------------------------------------------


class WorkflowImportTests(unittest.TestCase):
    def test_migrate_workflow_rewrites_v1_provider_fields(self):
        state = migrate_workflow_document(_v2_workflow())
        self.assertFalse(state.read_only)
        self.assertEqual(len(state.trail), 6)
        by_id = {n["id"]: n for n in state.document["nodes"]}
        self.assertEqual(by_id["n_tts"]["type_version"], 3)
        self.assertEqual(by_id["n_tts"]["configuration"]["provider_id"], "inworld")
        self.assertNotIn("engine", by_id["n_tts"]["configuration"])
        self.assertEqual(by_id["n_storyboard"]["configuration"]["provider_id"], "gemini_ws")
        self.assertNotIn("provider", by_id["n_storyboard"]["configuration"])
        self.assertEqual(
            by_id["n_storyboard"]["configuration"]["provider_options"]["prompt_prefix"],
            "cinematic",
        )
        self.assertEqual(by_id["n_animator"]["configuration"]["provider_id"], "grok_automa")
        self.assertEqual(validate_migrated_workflow(state.document), [])

    def test_import_workflow_persists_and_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflows_dir = Path(tmp) / "workflows"
            workflows_dir.mkdir()
            with mock.patch("scriptase.engine.persistence.WORKFLOWS_DIR", str(workflows_dir)):
                saved, original_id, trail = import_workflow(
                    _v2_workflow(), on_conflict="new_id"
                )
            self.assertEqual(original_id, "wf_V2IMP1")
            self.assertEqual(len(trail), 6)
            self.assertTrue(saved["workflow_id"].startswith("wf_"))
            self.assertEqual(
                validation_errors(validate_workflow(saved, require_identity=True)),
                [],
            )
            # Runnable: simple subgraph trigger → script.
            runnable = {
                **saved,
                "nodes": [
                    n for n in saved["nodes"] if n["id"] in {"n_trigger", "n_script"}
                ],
                "edges": [
                    e for e in saved["edges"] if e["id"] == "e_t_s"
                ],
            }
            calls: list[str] = []

            def resolver(node):
                def execute(inputs, config, context):
                    calls.append(node["id"])
                    if node["type"] == "trigger.manual":
                        return {"control": {"ok": True}}
                    if node["type"] == "script.input":
                        return {
                            "control": {"ok": True},
                            "script": config.get("text") or "x",
                        }
                    return {"control": {"ok": True}}

                return execute

            scheduler = WorkflowScheduler(
                runnable,
                project_id="pm_TEST01",
                output_dir=tmp,
                lock_root=str(Path(tmp) / "locks"),
                executor_resolver=resolver,
            )
            result = scheduler.run()
            self.assertEqual(result.status, "succeeded")
            self.assertEqual(calls, ["n_trigger", "n_script"])

    def test_persistence_import_migrates_v1_workflow(self):
        """POST /api/workflows/import path must accept raw V2 documents."""
        from scriptase.engine.persistence import import_workflow as persist_import

        with tempfile.TemporaryDirectory() as tmp:
            workflows_dir = Path(tmp) / "workflows"
            workflows_dir.mkdir()
            with mock.patch("scriptase.engine.persistence.WORKFLOWS_DIR", str(workflows_dir)):
                saved, original = persist_import(_v2_workflow(), on_conflict="new_id")
            self.assertEqual(original, "wf_V2IMP1")
            by_id = {n["id"]: n for n in saved["nodes"]}
            self.assertEqual(by_id["n_tts"]["configuration"]["provider_id"], "inworld")
            self.assertEqual(
                validation_errors(validate_workflow(saved, require_identity=True)),
                [],
            )


# ---------------------------------------------------------------------------
# Project tree + ZIP round-trip
# ---------------------------------------------------------------------------


class ProjectImportExportTests(unittest.TestCase):
    def test_project_tree_import_and_zip_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_output = tmp_path / "v2_output"
            dest_output = tmp_path / "scriptase_output"
            _seed_v2_project(source_output, "pm_V2IMP1")

            result = import_project_tree(
                source_output, "pm_V2IMP1", dest_output_dir=dest_output
            )
            self.assertEqual(result["project_id"], "pm_V2IMP1")
            self.assertGreater(result["files_copied"], 0)
            self.assertTrue(
                (dest_output / "projects" / "pm_V2IMP1" / "initial.json").is_file()
            )
            self.assertTrue(
                (dest_output / "animator" / "pm_V2IMP1" / "0" / "frame.jpg").is_file()
            )
            self.assertTrue(
                (dest_output / "tts" / "pm_V2IMP1" / "audio.wav").is_file()
            )

            # Re-export without manual edits.
            exported = export_project("pm_V2IMP1", output_dir=dest_output)
            self.assertGreater(len(exported), 0)

            # Re-import into a fresh tree (rename on conflict).
            second = import_project_from_zip(exported, dest_output_dir=dest_output)
            self.assertEqual(second.renamed_from, "pm_V2IMP1")
            self.assertTrue(second.project_id.startswith("pm_V2IMP1"))
            self.assertGreater(second.imported_files, 0)

            # Export of the renamed project also succeeds.
            exported_again = export_project(second.project_id, output_dir=dest_output)
            self.assertGreater(len(exported_again), 0)

    def test_project_zip_service_round_trip_preserves_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_v2_project(root, "pm_ZIP01")
            first = export_project_zip("pm_ZIP01", output_dir=str(root))
            # Wipe and restore.
            import shutil

            shutil.rmtree(root / "projects")
            shutil.rmtree(root / "scenes")
            shutil.rmtree(root / "animator")
            restored = import_project_zip(first.data, output_dir=str(root))
            self.assertEqual(restored.project_id, "pm_ZIP01")
            frame = root / "animator" / "pm_ZIP01" / "0" / "frame.jpg"
            self.assertTrue(frame.is_file())
            self.assertEqual(frame.read_bytes(), b"\xff\xd8\xfffake-jpeg")


# ---------------------------------------------------------------------------
# Full V2 root import
# ---------------------------------------------------------------------------


class V2RootImportTests(unittest.TestCase):
    def test_import_v2_root_settings_workflows_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            v2_root = _seed_v2_root(tmp_path)
            dest_output = tmp_path / "dest_output"
            dest_settings = tmp_path / "dest_settings" / "settings.json"

            with mock.patch(
                "scriptase.channels.presets.seed_starter_channels",
                return_value={"created": ["ch_a", "ch_b"], "skipped": [], "total_presets": 2},
            ):
                report = import_v2_root(
                    v2_root,
                    dest_output_dir=dest_output,
                    dest_settings_path=dest_settings,
                    seed_channels=True,
                )

            self.assertEqual(report.settings_version, SETTINGS_VERSION)
            self.assertTrue(report.settings_changed)
            self.assertTrue(dest_settings.is_file())
            settings = json.loads(dest_settings.read_text(encoding="utf-8"))
            self.assertIn("image", settings["domains"])
            self.assertNotIn("storyboard", settings["domains"])

            self.assertEqual(len(report.workflows), 1)
            wf_files = list((dest_output / "workflows").glob("wf_*.json"))
            self.assertEqual(len(wf_files), 1)
            saved_wf = json.loads(wf_files[0].read_text(encoding="utf-8"))
            self.assertEqual(
                validation_errors(validate_workflow(saved_wf, require_identity=True)),
                [],
            )
            tts_node = next(n for n in saved_wf["nodes"] if n["type"] == "tts.generate")
            self.assertEqual(tts_node["configuration"]["provider_id"], "inworld")

            self.assertIn("pm_V2IMP1", report.projects)
            self.assertTrue(
                (dest_output / "projects" / "pm_V2IMP1" / "initial.json").is_file()
            )
            self.assertEqual(report.channels_seeded, 2)

            # Re-export the imported project without manual edits.
            data = export_project("pm_V2IMP1", output_dir=dest_output)
            self.assertGreater(len(data), 50)


# ---------------------------------------------------------------------------
# HTTP surface (loopback)
# ---------------------------------------------------------------------------


class MigrationApiTests(unittest.TestCase):
    def setUp(self):
        from app import create_app

        self.app = create_app(discover_providers=True, start_triggers=False)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_preview_settings_and_workflow(self):
        resp = self.client.post(
            "/api/migration/v2/preview/settings",
            json={"settings": _v2_settings_v4()},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["changed"])
        self.assertEqual(body["version"], SETTINGS_VERSION)
        self.assertIn("image", body["settings"]["domains"])

        resp = self.client.post(
            "/api/migration/v2/preview/workflow",
            json={"workflow": _v2_workflow()},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["valid"])
        self.assertEqual(body["validation_errors"], [])
        self.assertEqual(len(body["migration_trail"]), 6)

    def test_workflows_import_endpoint_accepts_v2_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflows_dir = Path(tmp) / "workflows"
            workflows_dir.mkdir()
            with mock.patch(
                "scriptase.engine.persistence.WORKFLOWS_DIR", str(workflows_dir)
            ):
                resp = self.client.post(
                    "/api/workflows/import",
                    json={"workflow": _v2_workflow(), "on_conflict": "new_id"},
                )
            self.assertEqual(resp.status_code, 201, resp.get_data(as_text=True))
            body = resp.get_json()
            self.assertEqual(body["imported_from_id"], "wf_V2IMP1")
            tts = next(
                n for n in body["workflow"]["nodes"] if n["type"] == "tts.generate"
            )
            self.assertEqual(tts["configuration"]["provider_id"], "inworld")


if __name__ == "__main__":
    unittest.main()
