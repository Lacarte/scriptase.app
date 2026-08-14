"""Step 4.1 — Artifact library and input picker.

Done when: a Video Generator node runs standalone against a scene and image
chosen from a different Job, with the source artifacts recorded in the
resulting execution record.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from app import create_app
from scriptase.artifacts import store as artifact_store
from scriptase.artifacts.input_sources import (
    LIBRARY_JOB_ID,
    InputSourceError,
    resolve_binding,
)
from scriptase.artifacts.store import register_artifact
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.registry import get_node_type


def _wait(manager: ExecutionManager, execution_id: str, timeout: float = 8.0):
    handle = manager.active.get(execution_id)
    assert handle is not None
    handle.thread.join(timeout=timeout)
    assert not handle.thread.is_alive(), "execution did not finish in time"


def _node(node_id, node_type, configuration=None):
    definition = get_node_type(node_type) or {}
    return {
        "id": node_id,
        "type": node_type,
        "type_version": definition.get("type_version", 1),
        "name": node_id,
        "position": {"x": 0, "y": 0},
        "configuration": configuration or {},
        "disabled": False,
    }


def _workflow(nodes, edges=None):
    return {
        "schema_version": 1,
        "name": "Standalone video test",
        "description": "",
        "nodes": nodes,
        "edges": edges or [],
        "variables": {},
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "settings": {"on_error": "stop"},
        "extensions": {},
    }


class ArtifactLibraryTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_art_lib_")
        self.output_dir = os.path.join(self.temp.name, "output")
        os.makedirs(self.output_dir, exist_ok=True)

        self.old_artifacts = artifact_store._artifacts_dir
        self.old_output = artifact_store._output_dir
        artifact_store._output_dir = self.output_dir
        artifact_store._artifacts_dir = os.path.join(self.output_dir, "artifacts")
        os.makedirs(artifact_store._artifacts_dir, exist_ok=True)

        # Point config.OUTPUT_DIR at the temp root so uploads land there.
        import config
        self.old_config_output = config.OUTPUT_DIR
        config.OUTPUT_DIR = self.output_dir

        self.app = create_app(discover_providers=False)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        artifact_store._artifacts_dir = self.old_artifacts
        artifact_store._output_dir = self.old_output
        import config
        config.OUTPUT_DIR = self.old_config_output
        self.temp.cleanup()

    def _write_blob(self, relative: str, content: bytes | str) -> str:
        data = content.encode("utf-8") if isinstance(content, str) else content
        abs_path = os.path.join(self.output_dir, relative.replace("/", os.sep))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as handle:
            handle.write(data)
        return relative

    def _register_scenes(self, job_id: str, *, scene_id: str | None = None):
        payload = {
            "project_id": "pm_OTHER1",
            "scenes": [
                {
                    "index": 0,
                    "image_prompt": "a lighthouse beam over dark water",
                    "title": "Beam",
                    "segment_words": "The lamp turns.",
                    "duration": 2.0,
                }
            ],
            "total_duration": 2.0,
            "style": "cinematic",
        }
        rel = f"scenes/{job_id}/blueprint.json"
        self._write_blob(rel, json.dumps(payload))
        return register_artifact(
            job_id=job_id,
            kind="scene_spec",
            path=rel,
            scene_id=scene_id,
        )

    def _register_image(self, job_id: str, *, scene_id: str | None = "scn_AAAAAA"):
        rel = f"storyboard/{job_id}/scene_00.png"
        self._write_blob(rel, b"\x89PNG\r\n\x1a\nfake-image-bytes")
        return register_artifact(
            job_id=job_id,
            kind="image",
            path=rel,
            scene_id=scene_id,
        )


class InputSourceResolveTests(ArtifactLibraryTestBase):
    def test_resolve_job_artifact_by_id(self):
        art = self._register_scenes("job_OTHER1")
        payload, ids = resolve_binding(
            {"source": "job", "job_id": "job_OTHER1", "artifact_id": art.id},
            port_type="scenes",
        )
        self.assertEqual(ids, [art.id])
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["scenes"][0]["image_prompt"], "a lighthouse beam over dark water")
        self.assertIn(art.id, payload["artifact_ids"])

    def test_resolve_library_image_envelope(self):
        art = self._register_image("job_OTHER1")
        payload, ids = resolve_binding(
            {"source": "library", "artifact_id": art.id},
            port_type="storyboard_images",
        )
        self.assertEqual(ids, [art.id])
        self.assertEqual(payload["ready"], 1)
        self.assertEqual(payload["artifact_refs"], [art.path])
        self.assertEqual(payload["artifact_ids"], [art.id])

    def test_resolve_sample_has_no_source_artifacts(self):
        payload, ids = resolve_binding(
            {"source": "sample", "port_type": "scenes"},
            port_type="scenes",
        )
        self.assertEqual(ids, [])
        self.assertIn("scenes", payload)

    def test_run_deps_is_not_a_payload(self):
        with self.assertRaises(InputSourceError) as ctx:
            resolve_binding({"source": "run_deps"})
        self.assertEqual(ctx.exception.code, "RUN_DEPS")

    def test_current_job_requires_context(self):
        with self.assertRaises(InputSourceError) as ctx:
            resolve_binding(
                {"source": "current_job", "kind": "scene_spec"},
                port_type="scenes",
            )
        self.assertEqual(ctx.exception.code, "BAD_REQUEST")


class ArtifactLibraryApiTests(ArtifactLibraryTestBase):
    def test_list_and_get(self):
        art = self._register_scenes("job_OTHER1")
        listed = self.client.get("/api/artifacts?job_id=job_OTHER1&kind=scene_spec")
        self.assertEqual(listed.status_code, 200)
        body = listed.get_json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["artifacts"][0]["id"], art.id)
        self.assertIn("library", body["library_job_id"])

        detail = self.client.get(f"/api/artifacts/{art.id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json()["artifact"]["path"], art.path)

        payload_resp = self.client.get(
            f"/api/artifacts/{art.id}/payload?port_type=scenes"
        )
        self.assertEqual(payload_resp.status_code, 200)
        payload_body = payload_resp.get_json()
        self.assertEqual(payload_body["source_artifact_ids"], [art.id])
        self.assertIn("scenes", payload_body["payload"])

    def test_upload_registers_library_artifact(self):
        data = {
            "file": (tempfile.SpooledTemporaryFile(), "clip.png"),
        }
        # SpooledTemporaryFile needs content written.
        upload = tempfile.SpooledTemporaryFile()
        upload.write(b"\x89PNG\r\n\x1a\nupload-bytes")
        upload.seek(0)
        response = self.client.post(
            "/api/artifacts/upload",
            data={"file": (upload, "clip.png"), "kind": "image"},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        body = response.get_json()
        self.assertEqual(body["artifact"]["job_id"], LIBRARY_JOB_ID)
        self.assertEqual(body["artifact"]["kind"], "image")
        self.assertTrue(body["artifact"]["path"].startswith("library/"))

    def test_resolve_inputs_endpoint(self):
        scene = self._register_scenes("job_OTHER1")
        image = self._register_image("job_OTHER1")
        response = self.client.post(
            "/api/artifacts/resolve-inputs",
            json={
                "input_bindings": {
                    "n_animator": {
                        "scenes": {
                            "source": "job",
                            "job_id": "job_OTHER1",
                            "artifact_id": scene.id,
                            "port_type": "scenes",
                        },
                        "storyboard": {
                            "source": "library",
                            "artifact_id": image.id,
                            "port_type": "storyboard_images",
                        },
                    }
                }
            },
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        body = response.get_json()
        self.assertIn("scenes", body["input_overrides"]["n_animator"])
        self.assertIn("storyboard", body["input_overrides"]["n_animator"])
        self.assertEqual(
            set(body["source_artifact_ids"]["n_animator"]),
            {scene.id, image.id},
        )


class StandaloneVideoCrossJobTests(ArtifactLibraryTestBase):
    """Done-when: Video Generator runs standalone on another Job's scene+image."""

    def test_video_generator_standalone_records_source_artifacts(self):
        other_job = "job_OTHER1"
        scene_art = self._register_scenes(other_job)
        image_art = self._register_image(other_job)

        # Animator node only — no stubs, no edges. Inputs come from bindings.
        # Empty configuration uses schema defaults (provider option allowlists
        # are environment-dependent and not needed for this isolation test).
        workflow = _workflow([_node("n_animator", "animator.generate")])

        # Stub the adapter so we never touch a live video provider.
        captured = {}

        def fake_generate(inputs, config, context):
            captured["inputs"] = inputs
            captured["config"] = config
            return {
                "control": {"ok": True},
                "assets": {
                    "total": 1,
                    "ready": 1,
                    "errors": 0,
                    "status": "done",
                    "provider": "fixture",
                    "artifact_refs": ["animator/pm_TEST01/scene_00.mp4"],
                },
            }

        manager = ExecutionManager(output_dir=self.output_dir)

        def resolver(node):
            if node.get("type") == "animator.generate":
                return fake_generate
            raise AssertionError(f"unexpected node type {node.get('type')}")

        manager.executor_resolver = resolver

        bindings = {
            "n_animator": {
                "scenes": {
                    "source": "job",
                    "job_id": other_job,
                    "artifact_id": scene_art.id,
                },
                "storyboard": {
                    "source": "library",
                    "artifact_id": image_art.id,
                },
            }
        }

        execution_id, project_id = manager.start(
            workflow,
            run_mode="node_isolated",
            target_node_ids=["n_animator"],
            project_id="pm_TEST01",
            input_bindings=bindings,
        )
        _wait(manager, execution_id)

        record = manager.active.get(execution_id).scheduler.record.to_dict()
        self.assertEqual(record["status"], "succeeded", record)
        self.assertEqual(record["run_mode"], "node_isolated")
        self.assertEqual(record["scope_node_ids"], ["n_animator"])

        node = record["nodes"]["n_animator"]
        self.assertEqual(node["status"], "succeeded")
        source_ids = node.get("source_artifact_ids") or []
        self.assertIn(scene_art.id, source_ids)
        self.assertIn(image_art.id, source_ids)
        # Also mirrored into the inputs summary for older clients.
        summary_ids = (node.get("resolved_inputs_summary") or {}).get(
            "source_artifact_ids"
        ) or []
        self.assertIn(scene_art.id, summary_ids)
        self.assertIn(image_art.id, summary_ids)

        # Adapter actually saw the cross-job payloads.
        self.assertIn("scenes", captured["inputs"])
        self.assertEqual(
            captured["inputs"]["scenes"]["scenes"][0]["image_prompt"],
            "a lighthouse beam over dark water",
        )
        self.assertIn("storyboard", captured["inputs"])
        self.assertEqual(
            captured["inputs"]["storyboard"]["artifact_ids"],
            [image_art.id],
        )

    def test_isolated_run_rejects_missing_binding_without_stubs(self):
        from scriptase.engine.execution import ExecutionRequestError

        workflow = _workflow([_node("n_animator", "animator.generate")])
        manager = ExecutionManager(output_dir=self.output_dir)
        manager.executor_resolver = lambda node: (lambda *a, **k: {})
        with self.assertRaises(ExecutionRequestError) as ctx:
            manager.start(
                workflow,
                run_mode="node_isolated",
                target_node_ids=["n_animator"],
                project_id="pm_TEST01",
            )
        # Without stubs or bindings, isolation fails closed on required inputs.
        # prepare_snapshot may surface WORKFLOW_INVALID (require_complete) or
        # resolve_scope may raise MISSING_REQUIRED_INPUT — either is correct.
        self.assertIn(
            ctx.exception.code,
            {"MISSING_REQUIRED_INPUT", "WORKFLOW_INVALID"},
        )


if __name__ == "__main__":
    unittest.main()
