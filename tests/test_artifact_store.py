"""Step 1.2 — Artifact model, content-addressed store, and versioning.

Done when: regenerating any artifact produces a new immutable version with the
prior one still resolvable and marked superseded, and the engine's
cache-integrity tests pass unchanged.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from pydantic import ValidationError

from scriptase.artifacts import store as artifact_store
from scriptase.artifacts.migrations import SCHEMA_VERSION, apply_migrations
from scriptase.artifacts.models import (
    ARTIFACT_KINDS,
    Artifact,
    normalize_managed_path,
    parse_artifact,
    validation_problems,
)
from scriptase.artifacts.resolve import (
    artifact_ids_for_payload,
    resolve_ref,
    with_artifact_ids,
)
from scriptase.artifacts.store import (
    ArtifactMissing,
    ArtifactNotFound,
    ArtifactSuperseded,
    ArtifactValidationError,
    absolute_path,
    active_artifact,
    find_by_content_hash,
    get_artifact,
    list_artifacts,
    register_artifact,
    register_from_refs,
    verify_integrity,
    versioned_relative_path,
)


class ArtifactStoreTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_artifacts_")
        self.old_artifacts = artifact_store._artifacts_dir
        self.old_output = artifact_store._output_dir
        self.output_dir = os.path.join(self.temp.name, "output")
        artifact_store._output_dir = self.output_dir
        artifact_store._artifacts_dir = os.path.join(self.output_dir, "artifacts")
        os.makedirs(os.path.join(self.output_dir, "storyboard"), exist_ok=True)
        os.makedirs(artifact_store._artifacts_dir, exist_ok=True)

    def tearDown(self):
        artifact_store._artifacts_dir = self.old_artifacts
        artifact_store._output_dir = self.old_output
        self.temp.cleanup()

    def _write_blob(self, relative: str, content: bytes) -> str:
        abs_path = os.path.join(self.output_dir, relative.replace("/", os.sep))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as handle:
            handle.write(content)
        return relative


class ArtifactRegisterAndSupersedeTests(ArtifactStoreTestBase):
    def test_regenerate_produces_immutable_version_prior_still_resolvable(self):
        """Done-when: regenerate → v2, prior resolvable and marked superseded."""
        path_v1 = versioned_relative_path("storyboard/pm_TEST/scene_01.png", 1)
        path_v2 = versioned_relative_path("storyboard/pm_TEST/scene_01.png", 2)
        self.assertEqual(path_v1, "storyboard/pm_TEST/scene_01_v1.png")
        self.assertEqual(path_v2, "storyboard/pm_TEST/scene_01_v2.png")

        self._write_blob(path_v1, b"image-bytes-v1")
        first = register_artifact(
            job_id="job_TEST01",
            kind="image",
            path=path_v1,
            scene_id="scn_AAAAAA",
            provenance_ref="inv_first",
        )
        self.assertRegex(first.id, r"^art_[A-Z0-9]{6}$")
        self.assertEqual(first.version, 1)
        self.assertEqual(first.schema_version, SCHEMA_VERSION)
        self.assertEqual(first.kind, "image")
        self.assertEqual(first.job_id, "job_TEST01")
        self.assertEqual(first.scene_id, "scn_AAAAAA")
        self.assertEqual(first.path, path_v1)
        self.assertIsNone(first.superseded_by)
        self.assertTrue(first.content_hash.startswith("sha256:"))
        self.assertEqual(first.size_bytes, len(b"image-bytes-v1"))
        self.assertEqual(first.provenance_ref, "inv_first")
        self.assertTrue(first.created_at)

        # On-disk index document is valid JSON.
        index_path = os.path.join(artifact_store._artifacts_dir, f"{first.id}.json")
        self.assertTrue(os.path.isfile(index_path))
        with open(index_path, encoding="utf-8") as handle:
            raw = json.load(handle)
        self.assertEqual(raw["id"], first.id)
        self.assertEqual(raw["version"], 1)
        self.assertIsNone(raw["superseded_by"])

        # Regenerating writes a new additive path and registers version 2.
        self._write_blob(path_v2, b"image-bytes-v2-repaired")
        second = register_artifact(
            job_id="job_TEST01",
            kind="image",
            path=path_v2,
            scene_id="scn_AAAAAA",
            provenance_ref="inv_repair",
        )
        self.assertNotEqual(second.id, first.id)
        self.assertEqual(second.version, 2)
        self.assertEqual(second.path, path_v2)
        self.assertIsNone(second.superseded_by)
        self.assertEqual(second.provenance_ref, "inv_repair")
        self.assertNotEqual(second.content_hash, first.content_hash)

        # Prior version is still resolvable by id and marked superseded.
        prior = get_artifact(first.id)
        self.assertEqual(prior.superseded_by, second.id)
        self.assertTrue(prior.is_superseded)
        self.assertEqual(prior.path, path_v1)
        self.assertEqual(prior.content_hash, first.content_hash)
        self.assertEqual(prior.version, 1)

        # Prior blob is still on disk (additive paths).
        self.assertTrue(os.path.isfile(absolute_path(prior)))
        self.assertTrue(os.path.isfile(absolute_path(second)))

        # Integrity of both versions still verifies.
        self.assertTrue(verify_integrity(prior)["ok"])
        self.assertTrue(verify_integrity(second)["ok"])

        # Active tip is version 2.
        tip = active_artifact("job_TEST01", "image", scene_id="scn_AAAAAA")
        self.assertIsNotNone(tip)
        self.assertEqual(tip.id, second.id)
        self.assertEqual(tip.version, 2)

        # require_active surfaces ARTIFACT_SUPERSEDED for the prior version.
        with self.assertRaises(ArtifactSuperseded) as ctx:
            get_artifact(first.id, require_active=True)
        self.assertEqual(ctx.exception.code, "ARTIFACT_SUPERSEDED")
        self.assertEqual(ctx.exception.superseded_by, second.id)

        # History lists both versions.
        history = list_artifacts(
            job_id="job_TEST01",
            scene_id="scn_AAAAAA",
            kind="image",
            include_superseded=True,
        )
        self.assertEqual({item.version for item in history}, {1, 2})

        active_only = list_artifacts(
            job_id="job_TEST01",
            scene_id="scn_AAAAAA",
            kind="image",
            include_superseded=False,
        )
        self.assertEqual(len(active_only), 1)
        self.assertEqual(active_only[0].id, second.id)

    def test_third_regeneration_chains_superseded_by(self):
        paths = []
        arts = []
        for version in (1, 2, 3):
            rel = versioned_relative_path("storyboard/pm_TEST/scene.png", version)
            self._write_blob(rel, f"bytes-v{version}".encode())
            art = register_artifact(
                job_id="job_CHAIN",
                kind="image",
                path=rel,
                scene_id="scn_BBBBBB",
            )
            paths.append(rel)
            arts.append(art)

        self.assertEqual([a.version for a in arts], [1, 2, 3])
        v1 = get_artifact(arts[0].id)
        v2 = get_artifact(arts[1].id)
        v3 = get_artifact(arts[2].id)
        self.assertEqual(v1.superseded_by, v2.id)
        self.assertEqual(v2.superseded_by, v3.id)
        self.assertIsNone(v3.superseded_by)
        # All three still resolvable.
        for art in arts:
            loaded = get_artifact(art.id)
            self.assertEqual(loaded.id, art.id)
            self.assertTrue(verify_integrity(loaded)["ok"])


class ContentAddressedAndResolverTests(ArtifactStoreTestBase):
    def test_content_hash_index_finds_artifact(self):
        rel = "tts/pm_TEST/voice.wav"
        self._write_blob(rel, b"RIFF....WAVEfmt ")
        art = register_artifact(job_id="job_HASH", kind="audio", path=rel)
        found = find_by_content_hash(art.content_hash)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].id, art.id)
        # Bare hex also works.
        found_bare = find_by_content_hash(art.content_digest)
        self.assertEqual(found_bare[0].id, art.id)

    def test_resolver_maps_relative_ref_and_art_id(self):
        rel = "captions/pm_TEST/captions.json"
        self._write_blob(rel, b'{"cues":[]}')
        art = register_artifact(job_id="job_RES", kind="captions", path=rel)

        by_path = resolve_ref(rel)
        self.assertIsNotNone(by_path)
        self.assertEqual(by_path.id, art.id)

        by_id = resolve_ref(art.id)
        self.assertIsNotNone(by_id)
        self.assertEqual(by_id.id, art.id)

        self.assertIsNone(resolve_ref("storyboard/nope.png"))
        self.assertIsNone(resolve_ref("art_ZZZZZZ"))

    def test_with_artifact_ids_leaves_refs_intact(self):
        rel = "exports/pm_TEST/final.mp4"
        self._write_blob(rel, b"\x00\x00\x00 ftyp")
        art = register_artifact(job_id="job_IDS", kind="export", path=rel)
        payload = {"artifact_refs": [rel], "filename": "final.mp4"}
        enriched = with_artifact_ids(payload)
        self.assertEqual(enriched["artifact_refs"], [rel])
        self.assertEqual(enriched["artifact_ids"], [art.id])
        self.assertEqual(artifact_ids_for_payload(payload), [art.id])

    def test_register_from_refs(self):
        refs = ["music/track_a.wav", "music/track_b.wav"]
        for ref in refs:
            self._write_blob(ref, b"music-bytes-" + ref.encode())
        # Each register is a separate (job, scene, kind) tip — same kind without
        # scene still versions. Use distinct kinds via one job+kind chain:
        # register_from_refs creates sequential versions for the same chain.
        arts = register_from_refs(job_id="job_REFS", kind="music", refs=refs)
        self.assertEqual(len(arts), 2)
        self.assertEqual(arts[0].version, 1)
        self.assertEqual(arts[1].version, 2)
        self.assertEqual(get_artifact(arts[0].id).superseded_by, arts[1].id)


class ValidationAndPathTests(ArtifactStoreTestBase):
    def test_absolute_path_rejected(self):
        with self.assertRaises(ArtifactValidationError) as ctx:
            register_artifact(
                job_id="job_ABS",
                kind="image",
                path=r"C:\Users\evil\image.png",
            )
        self.assertEqual(ctx.exception.code, "ARTIFACT_UNMANAGED")

    def test_missing_blob_raises(self):
        with self.assertRaises(ArtifactMissing):
            register_artifact(
                job_id="job_MISS",
                kind="image",
                path="storyboard/missing.png",
            )

    def test_empty_blob_raises(self):
        self._write_blob("storyboard/empty.png", b"")
        with self.assertRaises(ArtifactMissing):
            register_artifact(
                job_id="job_EMPTY",
                kind="image",
                path="storyboard/empty.png",
            )

    def test_unknown_kind_rejected(self):
        self._write_blob("storyboard/x.png", b"data")
        with self.assertRaises(ArtifactValidationError):
            register_artifact(job_id="job_K", kind="thumbnail", path="storyboard/x.png")

    def test_path_traversal_rejected(self):
        with self.assertRaises((ArtifactValidationError, ValueError)):
            normalize_managed_path("../secrets.txt")
        with self.assertRaises(ArtifactValidationError):
            register_artifact(
                job_id="job_TRAV",
                kind="script",
                path="stories/../../settings/settings.json",
            )

    def test_model_rejects_absolute_path_on_parse(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_artifact({
                "id": "art_AAAAAA",
                "job_id": "job_X",
                "kind": "image",
                "version": 1,
                "content_hash": "sha256:" + ("a" * 64),
                "path": "/etc/passwd",
                "size_bytes": 1,
            })
        problems = validation_problems(ctx.exception)
        self.assertTrue(any("path" in item.get("loc", []) for item in problems))

    def test_all_contract_kinds_accepted(self):
        for kind in ARTIFACT_KINDS:
            rel = f"misc/{kind}.bin"
            self._write_blob(rel, f"payload-{kind}".encode())
            art = register_artifact(
                job_id=f"job_{kind[:4].upper()}",
                kind=kind,
                path=rel,
            )
            self.assertEqual(art.kind, kind)

    def test_get_missing_raises_not_found(self):
        with self.assertRaises(ArtifactNotFound) as ctx:
            get_artifact("art_ZZZZZZ")
        self.assertEqual(ctx.exception.code, "ARTIFACT_NOT_FOUND")

    def test_integrity_detects_tamper(self):
        rel = "storyboard/tamper.png"
        self._write_blob(rel, b"original")
        art = register_artifact(job_id="job_TAMP", kind="image", path=rel)
        abs_path = absolute_path(art)
        with open(abs_path, "wb") as handle:
            handle.write(b"tampered!")
        result = verify_integrity(art)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "artifact_integrity_failed")


class MigrationTests(ArtifactStoreTestBase):
    def test_missing_schema_version_stamped_on_load(self):
        rel = "scripts/story.json"
        self._write_blob(rel, b'{"title":"x"}')
        created = register_artifact(job_id="job_MIG", kind="script", path=rel)
        path = os.path.join(artifact_store._artifacts_dir, f"{created.id}.json")
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        raw.pop("schema_version", None)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(raw, handle)

        loaded = get_artifact(created.id)
        self.assertEqual(loaded.schema_version, SCHEMA_VERSION)
        self.assertEqual(loaded.version, 1)

    def test_apply_migrations_idempotent(self):
        doc = {
            "id": "art_AAAAAA",
            "job_id": "job_X",
            "kind": "script",
            "version": 1,
            "content_hash": "sha256:" + ("b" * 64),
            "path": "stories/x.json",
            "size_bytes": 1,
            "schema_version": SCHEMA_VERSION,
        }
        migrated, changed = apply_migrations(doc)
        self.assertFalse(changed)
        self.assertEqual(migrated["schema_version"], SCHEMA_VERSION)

    def test_round_trip_through_model(self):
        rel = "alignments/pm_TEST/align.json"
        self._write_blob(rel, b'{"words":[]}')
        created = register_artifact(job_id="job_RT", kind="alignment", path=rel)
        restored = Artifact.model_validate(created.to_document())
        self.assertEqual(restored.to_document(), created.to_document())


class VersionedPathHelperTests(unittest.TestCase):
    def test_versioned_relative_path_shapes(self):
        self.assertEqual(
            versioned_relative_path("storyboard/pm_X/scene.png", 1),
            "storyboard/pm_X/scene_v1.png",
        )
        self.assertEqual(
            versioned_relative_path("exports/final", 3),
            "exports/final_v3",
        )


if __name__ == "__main__":
    unittest.main()
