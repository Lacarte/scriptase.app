"""Step 4.3 — Attempt history and side-by-side comparison.

Done when: regenerating a scene image shows both versions side by side with
their provider instance, seed, and prompt revision.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from app import create_app
from scriptase.artifacts import store as artifact_store
from scriptase.artifacts.history import (
    compare_attempts,
    history_for_artifact,
    history_for_chain,
    list_version_chain,
)
from scriptase.artifacts.migrations import apply_migrations
from scriptase.artifacts.store import (
    get_artifact,
    register_artifact,
    versioned_relative_path,
)


class AttemptHistoryTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_hist_")
        self.output_dir = os.path.join(self.temp.name, "output")
        os.makedirs(self.output_dir, exist_ok=True)

        self.old_artifacts = artifact_store._artifacts_dir
        self.old_output = artifact_store._output_dir
        artifact_store._output_dir = self.output_dir
        artifact_store._artifacts_dir = os.path.join(self.output_dir, "artifacts")
        os.makedirs(artifact_store._artifacts_dir, exist_ok=True)

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

    def _write_blob(self, relative: str, content: bytes) -> str:
        abs_path = os.path.join(self.output_dir, relative.replace("/", os.sep))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as handle:
            handle.write(content)
        return relative

    def _register_scene_image(
        self,
        *,
        job_id: str = "job_IMG001",
        scene_id: str = "scn_AAAAAA",
        version: int,
        content: bytes,
        generation: dict | None = None,
        provenance_ref: str | None = None,
    ):
        path = versioned_relative_path(
            f"storyboard/{job_id}/{scene_id}.png", version
        )
        self._write_blob(path, content)
        return register_artifact(
            job_id=job_id,
            kind="image",
            path=path,
            scene_id=scene_id,
            provenance_ref=provenance_ref,
            generation=generation,
        )


class SceneImageRegenerateComparisonTests(AttemptHistoryTestBase):
    def test_regenerate_shows_both_versions_side_by_side(self):
        """Done-when: both versions with provider instance, seed, prompt revision."""
        v1 = self._register_scene_image(
            version=1,
            content=b"png-bytes-v1-original",
            provenance_ref="inv_v1",
            generation={
                "provider_id": "wavespeed",
                "provider_instance_id": "wavespeed_main",
                "seed": 42,
                "prompt_revision": "flux-dev@2026-01",
                "model_revision": "flux-dev@2026-01",
                "request_id": "req_aaa",
                "invocation_id": "inv_v1",
            },
        )
        v2 = self._register_scene_image(
            version=2,
            content=b"png-bytes-v2-regenerated",
            provenance_ref="inv_v2",
            generation={
                "provider_id": "wavespeed",
                "provider_instance_id": "wavespeed_fallback",
                "seed": 99,
                "prompt_revision": "flux-dev@2026-03",
                "model_revision": "flux-dev@2026-03",
                "request_id": "req_bbb",
                "invocation_id": "inv_v2",
            },
        )

        self.assertEqual(v1.version, 1)
        self.assertEqual(v2.version, 2)
        prior = get_artifact(v1.id)
        self.assertEqual(prior.superseded_by, v2.id)

        chain = list_version_chain(
            job_id="job_IMG001", kind="image", scene_id="scn_AAAAAA"
        )
        self.assertEqual([a.version for a in chain], [1, 2])

        history = history_for_artifact(v2.id)
        self.assertEqual(history["attempt_count"], 2)
        self.assertEqual(len(history["attempts"]), 2)

        left = history["attempts"][0]
        right = history["attempts"][1]
        self.assertEqual(left["version"], 1)
        self.assertEqual(right["version"], 2)
        self.assertEqual(left["provider_instance_id"], "wavespeed_main")
        self.assertEqual(left["seed"], 42)
        self.assertEqual(left["prompt_revision"], "flux-dev@2026-01")
        self.assertEqual(right["provider_instance_id"], "wavespeed_fallback")
        self.assertEqual(right["seed"], 99)
        self.assertEqual(right["prompt_revision"], "flux-dev@2026-03")

        comparison = history["comparison"]
        self.assertIsNotNone(comparison)
        self.assertTrue(comparison["same_chain"])
        self.assertEqual(comparison["left"]["artifact_id"], v1.id)
        self.assertEqual(comparison["right"]["artifact_id"], v2.id)
        self.assertEqual(
            set(comparison["changed_axes"]),
            {"provider_instance_id", "seed", "prompt_revision"},
        )
        self.assertEqual(
            comparison["axes"]["provider_instance_id"]["left"], "wavespeed_main"
        )
        self.assertEqual(
            comparison["axes"]["provider_instance_id"]["right"], "wavespeed_fallback"
        )
        self.assertEqual(comparison["axes"]["seed"]["left"], 42)
        self.assertEqual(comparison["axes"]["seed"]["right"], 99)
        self.assertEqual(
            comparison["axes"]["prompt_revision"]["left"], "flux-dev@2026-01"
        )
        self.assertEqual(
            comparison["axes"]["prompt_revision"]["right"], "flux-dev@2026-03"
        )

        # Explicit compare API mirrors the default pair.
        direct = compare_attempts(v1.id, v2.id)
        self.assertEqual(direct["left"]["version"], 1)
        self.assertEqual(direct["right"]["version"], 2)
        self.assertIn("provider_instance_id", direct["axes"])
        self.assertIn("seed", direct["axes"])
        self.assertIn("prompt_revision", direct["axes"])

    def test_model_revision_fills_prompt_revision_when_absent(self):
        art = self._register_scene_image(
            version=1,
            content=b"only-model-rev",
            generation={
                "provider_instance_id": "inst_a",
                "seed": 7,
                "model_revision": "sdxl-1.0",
            },
        )
        self.assertIsNotNone(art.generation)
        self.assertEqual(art.generation.model_revision, "sdxl-1.0")
        self.assertEqual(art.generation.prompt_revision, "sdxl-1.0")

    def test_schema_v1_migrates_to_v2_with_null_generation(self):
        migrated, changed = apply_migrations(
            {
                "id": "art_ABCDEF",
                "schema_version": 1,
                "job_id": "job_X",
                "scene_id": None,
                "kind": "image",
                "version": 1,
                "content_hash": "sha256:" + ("a" * 64),
                "path": "storyboard/x.png",
                "size_bytes": 1,
                "mime": "image/png",
                "provenance_ref": None,
                "created_at": "2026-01-01T00:00:00Z",
                "superseded_by": None,
                "from_sample_data": False,
            }
        )
        self.assertTrue(changed)
        self.assertEqual(migrated["schema_version"], 2)
        self.assertIsNone(migrated["generation"])


class AttemptHistoryApiTests(AttemptHistoryTestBase):
    def test_api_history_and_compare_for_regenerated_image(self):
        v1 = self._register_scene_image(
            version=1,
            content=b"api-v1",
            generation={
                "provider_instance_id": "inst_primary",
                "seed": 11,
                "prompt_revision": "prompt-r1",
            },
        )
        v2 = self._register_scene_image(
            version=2,
            content=b"api-v2",
            generation={
                "provider_instance_id": "inst_secondary",
                "seed": 22,
                "prompt_revision": "prompt-r2",
            },
        )

        resp = self.client.get(f"/api/artifacts/{v2.id}/history")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertEqual(body["attempt_count"], 2)
        self.assertEqual(body["attempts"][0]["provider_instance_id"], "inst_primary")
        self.assertEqual(body["attempts"][0]["seed"], 11)
        self.assertEqual(body["attempts"][0]["prompt_revision"], "prompt-r1")
        self.assertEqual(body["attempts"][1]["provider_instance_id"], "inst_secondary")
        self.assertEqual(body["attempts"][1]["seed"], 22)
        self.assertEqual(body["attempts"][1]["prompt_revision"], "prompt-r2")
        self.assertIsNotNone(body["comparison"])
        self.assertEqual(body["comparison"]["left"]["artifact_id"], v1.id)
        self.assertEqual(body["comparison"]["right"]["artifact_id"], v2.id)

        chain = self.client.get(
            "/api/artifacts/history",
            query_string={
                "job_id": "job_IMG001",
                "kind": "image",
                "scene_id": "scn_AAAAAA",
            },
        )
        self.assertEqual(chain.status_code, 200)
        chain_body = chain.get_json()
        self.assertEqual(chain_body["attempt_count"], 2)

        compare = self.client.get(
            "/api/artifacts/compare",
            query_string={"left": v1.id, "right": v2.id},
        )
        self.assertEqual(compare.status_code, 200)
        pair = compare.get_json()
        self.assertTrue(pair["same_chain"])
        self.assertEqual(
            set(pair["changed_axes"]),
            {"provider_instance_id", "seed", "prompt_revision"},
        )

    def test_api_history_empty_chain(self):
        resp = self.client.get(
            "/api/artifacts/history",
            query_string={"job_id": "job_NONE", "kind": "image"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["attempt_count"], 0)
        self.assertEqual(body["attempts"], [])
        self.assertIsNone(body["comparison"])

    def test_api_compare_requires_valid_ids(self):
        resp = self.client.get(
            "/api/artifacts/compare",
            query_string={"left": "not-an-id", "right": "art_AAAAAA"},
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
