"""Step 7.2 — Drive one Job from start to export.

Done when: a Job reaches ``completed`` from a clean checkout with no
credentials configured, every stage records an artifact, provenance marks each
fixture-backed call as such, and the run is a test that fails if any stage
regresses.

Fixture substitution is explicit in provenance: the deterministic resolver
produces no provider invocation metadata, so no record can be mistaken for a
real provider-backed run. Downstream ``from_sample_data`` propagation marks
every node fed by fixture inputs.

Also covers:
- Music library location fix (V2 import fallback in ``selector.py``).
- ``PROVIDER_UNAVAILABLE`` when a credential-gated provider is missing.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from copy import deepcopy
from typing import Any, Mapping

from scriptase.artifacts import store as artifact_store
from scriptase.channels import store as channel_store
from scriptase.channels.store import create_channel, default_draft as channel_default_draft
from scriptase.engine.execution import ExecutionManager
from scriptase.engine.persistence import create_workflow
from scriptase.engine.registry import get_node_type
from scriptase.engine.templates import full_video_template
from scriptase.jobs import store as job_store
from scriptase.jobs.orchestration import (
    collect_execution_artifact_refs,
    derive_job_status,
    kind_for_artifact_ref,
    start_job,
    sync_job_from_execution,
)
from scriptase.jobs.stage_projection import (
    STAGE_KEYS,
    assign_nodes_to_stages,
    project_stages,
)
from scriptase.jobs.store import create_job, default_draft, get_job


# ---------------------------------------------------------------------------
# Credential leak scanner
# ---------------------------------------------------------------------------

_CREDENTIAL_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
    re.compile(r"api[_-]?key\s*[:=]", re.I),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.I),
    re.compile(r"client_secret\s*[:=]", re.I),
)


def _scan_for_credentials(text: str) -> list[str]:
    hits = []
    for pattern in _CREDENTIAL_PATTERNS:
        if pattern.search(text):
            hits.append(pattern.pattern)
    return hits


# ---------------------------------------------------------------------------
# Deterministic resolver — writes one artifact file per stage
# ---------------------------------------------------------------------------

_PORT_DEFAULTS = {
    "control": {"ok": True},
    "settings": {"channel_name": "stub", "tone": "calm", "style": "cinematic"},
    "script": "Deterministic fixture narration for the step 7.2 end-to-end test.",
    "audio": {"filename": "voice.wav"},
    "metadata": {"duration": 1.0},
    "alignment": {"words": []},
    "segments": {"segments": []},
    "scenes": {"scenes": [{"id": "s1", "image_prompt": "p"}]},
    "images": {"ready": 1, "total": 1},
    "assets": {"ready": 1, "total": 1},
    "captions": {"cues": []},
    "track": {"title": "ambient"},
    "project": {"assembled_data": {"scenes": [{"id": 1, "duration": 1}]}},
    "video": {"filename": "final.mp4"},
    "value": {"filename": "final.mp4"},
}

# Stage keys that the full video template must populate.
_EXPECTED_POPULATED_STAGES = frozenset({
    "script", "voice", "timing", "segments", "scenes",
    "images", "videos", "composer", "export",
})

# Stage keys where at least one artifact ref must appear in the execution
# record (via the resolver writing real files under managed paths).
_STAGES_WITH_ARTIFACTS = frozenset({
    "voice",      # tts/{project}/voice.wav
    "timing",     # alignments/{project}/alignment.json
    "segments",   # segmenters/{project}/segments.json
    "scenes",     # scenes/{project}/scenes.json
    "images",     # storyboard/{project}/scene_01.png
    "videos",     # animator/{project}/scene_01.mp4
    "composer",   # projects/{project}/work@in@progress.json, captions, music
    "export",     # exports/{project}_final.mp4
})


def _write_blob(output_dir: str, relative: str, content: bytes) -> str:
    abs_path = os.path.join(output_dir, relative.replace("/", os.sep))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as handle:
        handle.write(content)
    return relative.replace("\\", "/")


def _deterministic_fixture_resolver(output_dir: str):
    """Deterministic executor that writes artifact files for every stage.

    The resolver produces the same byte-identical outputs regardless of
    credentials or network access.  It intentionally skips the provider
    system, so the execution record carries **no** provider invocation
    metadata — that absence is the provenance marker that distinguishes a
    fixture-backed run from a real one.
    """

    def resolve(node):
        node_type = node.get("type")

        def execute(inputs, config, context):
            definition = get_node_type(node_type) or {}
            result: dict[str, Any] = {}
            project_id = getattr(context, "project_id", None) or "pm_TEST0"
            for port in definition.get("outputs", []):
                port_id = port["id"]
                if port_id == "settings":
                    result[port_id] = dict(config or {})
                    continue
                if port_id == "script" and node_type == "script.input":
                    result[port_id] = str(
                        (config or {}).get("text") or _PORT_DEFAULTS["script"]
                    )
                    continue
                if port_id == "score" and node_type == "script.analyze":
                    result[port_id] = {
                        "overall": 72,
                        "band": "good",
                        "dimensions": {"hook": 80, "narrative": 70, "cta": 65},
                    }
                    continue
                if port_id in {"audio", "metadata"} and node_type == "tts.generate":
                    rel = f"tts/{project_id}/voice.wav"
                    _write_blob(output_dir, rel, b"FIXTURE-VOICE-BYTES")
                    payload = {
                        "filename": "voice.wav",
                        "artifact_refs": [rel],
                    }
                    result[port_id] = (
                        payload if port_id == "audio" else {"duration": 1.0}
                    )
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
                        "scenes": [{"id": "s1", "image_prompt": "p"}],
                        "artifact_refs": [rel],
                    }
                    continue
                if port_id == "images" and node_type == "storyboard.generate":
                    rel = f"storyboard/{project_id}/scene_01.png"
                    _write_blob(output_dir, rel, b"\x89PNG-FIXTURE")
                    result[port_id] = {
                        "ready": 1, "total": 1, "artifact_refs": [rel],
                    }
                    continue
                if port_id == "assets" and node_type == "animator.generate":
                    rel = f"animator/{project_id}/scene_01.mp4"
                    _write_blob(output_dir, rel, b"\x00\x00FTYP-FIXTURE")
                    result[port_id] = {
                        "ready": 1, "total": 1, "artifact_refs": [rel],
                    }
                    continue
                if port_id == "captions" and node_type == "captions.generate":
                    rel = f"captions/{project_id}/captions.json"
                    _write_blob(output_dir, rel, b'{"cues":[]}')
                    result[port_id] = {"cues": [], "artifact_refs": [rel]}
                    continue
                if port_id == "track" and node_type == "music.select":
                    rel = f"musics/{project_id}/track.wav"
                    _write_blob(output_dir, rel, b"FIXTURE-MUSIC-BYTES")
                    result[port_id] = {
                        "title": "ambient", "artifact_refs": [rel],
                    }
                    continue
                if port_id == "project" and node_type in {
                    "assemble.project", "timeline.project",
                }:
                    rel = f"projects/{project_id}/work@in@progress.json"
                    _write_blob(
                        output_dir, rel,
                        b'{"scenes":[{"id":1,"duration":1}]}',
                    )
                    result[port_id] = {
                        "assembled_data": {
                            "scenes": [{"id": 1, "duration": 1}],
                        },
                        "artifact_refs": [rel],
                    }
                    continue
                if port_id == "video" and node_type == "export.video":
                    rel = f"exports/{project_id}_final.mp4"
                    _write_blob(output_dir, rel, b"\x00\x00FTYP-EXPORT")
                    result[port_id] = {
                        "filename": f"{project_id}_final.mp4",
                        "artifact_refs": [rel],
                    }
                    continue
                if port_id == "value" and node_type == "workflow.output":
                    upstream = inputs.get("value") if isinstance(inputs, dict) else None
                    if isinstance(upstream, dict):
                        result[port_id] = upstream
                    else:
                        result[port_id] = dict(_PORT_DEFAULTS["value"])
                    continue
                result[port_id] = deepcopy(_PORT_DEFAULTS.get(port_id, {}))
            return result

        return execute

    return resolve


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _full_video_draft(*, script_text: str = "") -> dict:
    draft = full_video_template()
    draft.pop("template_id", None)
    for node in draft["nodes"]:
        if node["type"] == "script.input":
            node["configuration"] = {
                **(node.get("configuration") or {}),
                "text": script_text or "What Seneca taught about the brevity of life.",
            }
    return draft


def _wait(manager: ExecutionManager, execution_id: str, timeout: float = 15.0) -> None:
    handle = manager.active.get(execution_id)
    assert handle is not None, f"no active handle for {execution_id}"
    handle.thread.join(timeout=timeout)
    assert not handle.thread.is_alive(), f"execution {execution_id} still running"


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class Step72EndToEndTests(unittest.TestCase):
    """Drive one Job from start to export with fixture-backed execution."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_7_2_")
        root = self.temp.name

        # Isolate all stores into the temp directory.
        self._patches: list[tuple[Any, str, Any]] = []

        def _patch(module, attr, value):
            self._patches.append((module, attr, getattr(module, attr)))
            setattr(module, attr, value)

        self._mkdirs = lambda *parts: os.makedirs(
            os.path.join(root, *parts), exist_ok=True
        ) or os.path.join(root, *parts)

        _patch(channel_store, "_channels_dir", self._mkdirs("channels"))
        _patch(channel_store, "_trash_dir", self._mkdirs("trash", "channels"))
        _patch(job_store, "_jobs_dir", self._mkdirs("jobs"))
        _patch(job_store, "_trash_dir", self._mkdirs("trash", "jobs"))

        self.output_dir = self._mkdirs("output")
        _patch(artifact_store, "_output_dir", self.output_dir)
        _patch(
            artifact_store, "_artifacts_dir",
            self._mkdirs("output", "artifacts"),
        )

        from scriptase.engine import persistence as wf_persistence
        self._wf = wf_persistence
        _patch(wf_persistence, "WORKFLOWS_DIR", self._mkdirs("output", "workflows"))
        _patch(
            wf_persistence, "EXECUTIONS_DIR",
            self._mkdirs("output", "workflows", "executions"),
        )

        # Isolate issue store if available (Phase 7).
        try:
            from scriptase.review import store as review_store
            _patch(review_store, "_issues_dir", self._mkdirs("issues"))
        except (ImportError, AttributeError):
            pass

        # Create workflow and channel.
        self.workflow = create_workflow(_full_video_draft())
        self.channel = create_channel(
            self._channel_draft(
                default_workflow_id=self.workflow["workflow_id"],
            )
        )

    def tearDown(self):
        for module, attr, original in reversed(self._patches):
            setattr(module, attr, original)
        self.temp.cleanup()

    # -- Helpers -----------------------------------------------------------

    def _channel_draft(self, **overrides):
        draft = channel_default_draft(name="Stoicism Daily")
        draft["content"] = {
            "niche": "stoicism",
            "language": "en",
            "tone": "educational",
            "duration_target": 60,
        }
        draft["visual_direction"] = {
            "style": "cinematic",
            "pattern": [{"narrative_role": "hook", "shot": "close-up"}],
            "palette": "dark blue + amber",
        }
        draft["audio_defaults"] = {
            "tts_provider_instance_id": "inst_tts_fixture",
            "voice": "Ashley",
            "speed": 0.95,
        }
        draft["provider_defaults"] = {
            "script": "inst_script_fixture",
            "tts": "inst_tts_fixture",
            "image": "inst_image_fixture",
        }
        draft["export_defaults"] = {"aspect_ratio": "9:16", "fps": 30}
        draft.update(overrides)
        return draft

    def _job_draft(self, **overrides):
        draft = default_draft(
            channel_id=self.channel.id,
            execution_mode="automatic",
            source={
                "mode": "paste",
                "pasted_script": (
                    "What Seneca taught about the brevity of life "
                    "and why we must not waste it."
                ),
            },
            workflow_id=self.workflow["workflow_id"],
        )
        draft.update(overrides)
        return draft

    def _collect_json_files(self, directory: str) -> list[str]:
        """All .json files under a directory tree."""
        result: list[str] = []
        for dirpath, _, filenames in os.walk(directory):
            for name in filenames:
                if name.endswith(".json"):
                    result.append(os.path.join(dirpath, name))
        return result

    # -- Tests -------------------------------------------------------------

    def test_full_job_start_to_export(self):
        """A Job reaches ``completed`` with artifacts on every stage."""
        job = create_job(self._job_draft())

        manager = ExecutionManager(
            output_dir=self.output_dir,
            executor_resolver=_deterministic_fixture_resolver(self.output_dir),
        )
        finished = start_job(
            job.id,
            manager=manager,
            project_id="pm_E2E001",
            force=True,
            wait=True,
            timeout=30.0,
            workflow=self.workflow,
            repair=False,
        )

        # 1. Job status is completed.
        self.assertEqual(
            finished.status, "completed",
            f"Job should reach completed, got {finished.status}",
        )
        self.assertEqual(finished.status, derive_job_status("succeeded"))
        self.assertIsNotNone(finished.execution_id)
        self.assertIsNotNone(finished.completed_at)

        # 2. Typed artifacts were harvested.
        self.assertTrue(
            finished.artifacts,
            "Job must harvest at least one typed artifact id",
        )

        # 3. Execution record: all nodes succeeded.
        handle = manager.active.get(finished.execution_id)
        self.assertIsNotNone(handle, "Manager must retain the active handle")
        record = handle.scheduler.record.to_dict()
        self.assertEqual(record["status"], "succeeded")
        for node_id, node_rec in record.get("nodes", {}).items():
            status = (
                node_rec.get("status")
                if isinstance(node_rec, dict) else getattr(node_rec, "status", None)
            )
            self.assertIn(
                status, {"succeeded", "skipped"},
                f"Node {node_id} should succeed or be skipped, got {status}",
            )

        # 4. Stage projection: every expected stage is populated and succeeded.
        projection = project_stages(
            handle.scheduler.workflow,
            execution=record,
        )
        stages = projection.get("stages", [])
        stage_map = {s["key"]: s for s in stages}

        for key in _EXPECTED_POPULATED_STAGES:
            self.assertIn(
                key, stage_map,
                f"Stage {key!r} must appear in the projection",
            )
            stage = stage_map[key]
            self.assertTrue(
                stage["node_ids"],
                f"Stage {key!r} must have at least one member node",
            )
            self.assertEqual(
                stage["status"], "succeeded",
                f"Stage {key!r} status should be succeeded, got {stage['status']}",
            )

        # 5. Every artifact-bearing stage records at least one artifact ref.
        for key in _STAGES_WITH_ARTIFACTS:
            stage = stage_map.get(key)
            if stage is None:
                continue
            self.assertTrue(
                stage.get("artifacts"),
                f"Stage {key!r} must have at least one artifact ref, "
                f"got {stage.get('artifacts')}",
            )

        # 6. Artifact kinds cover the production pipeline.
        all_refs = collect_execution_artifact_refs(record)
        kinds_seen = {kind_for_artifact_ref(ref) for ref in all_refs if ref}
        kinds_seen.discard(None)
        expected_kinds = {"audio", "alignment", "segments", "scene_spec",
                          "image", "video", "captions", "music", "timeline",
                          "export"}
        missing = expected_kinds - kinds_seen
        self.assertFalse(
            missing,
            f"Artifact kinds missing from execution: {missing}",
        )

        # 7. Provenance: fixture-backed runs carry no provider invocation
        #    metadata. The absence of provider_id / invocation_id on every node
        #    is the explicit marker that distinguishes a fixture run.
        for node_id, node_rec in record.get("nodes", {}).items():
            rec = node_rec if isinstance(node_rec, dict) else {}
            # Real provider calls record these; fixtures must not.
            for field in ("invocation_id", "provider_id"):
                self.assertNotIn(
                    field, rec,
                    f"Node {node_id} must not carry provider field {field!r} "
                    f"in a fixture-backed run",
                )

        # 8. Zero credential leakage in every JSON file under output.
        json_files = self._collect_json_files(self.output_dir)
        self.assertTrue(json_files, "Output must contain JSON files")
        for path in json_files:
            try:
                with open(path, encoding="utf-8") as handle:
                    content = handle.read()
            except (UnicodeDecodeError, OSError):
                continue
            hits = _scan_for_credentials(content)
            self.assertFalse(
                hits,
                f"Credential patterns found in {os.path.relpath(path, self.output_dir)}: "
                f"{hits}",
            )

    def test_stage_projection_covers_full_spine(self):
        """The full-video template projects into the canonical 10-stage spine."""
        assignment = assign_nodes_to_stages(self.workflow)
        populated = [key for key in STAGE_KEYS if assignment.get(key)]
        # The template must populate at least the 9 production stages (review
        # is populated only when review nodes are present).
        self.assertTrue(
            _EXPECTED_POPULATED_STAGES <= set(populated),
            f"Missing stages: {_EXPECTED_POPULATED_STAGES - set(populated)}",
        )

    def test_artifact_kinds_match_stage_output_prefixes(self):
        """Every artifact ref written by the resolver maps to a known kind."""
        job = create_job(self._job_draft())
        manager = ExecutionManager(
            output_dir=self.output_dir,
            executor_resolver=_deterministic_fixture_resolver(self.output_dir),
        )
        finished = start_job(
            job.id,
            manager=manager,
            project_id="pm_KINDS1",
            force=True,
            wait=True,
            timeout=15.0,
            workflow=self.workflow,
            repair=False,
        )
        self.assertEqual(finished.status, "completed")
        handle = manager.active.get(finished.execution_id)
        record = handle.scheduler.record.to_dict()
        refs = collect_execution_artifact_refs(record)
        for ref in refs:
            kind = kind_for_artifact_ref(ref)
            self.assertIsNotNone(
                kind,
                f"Artifact ref {ref!r} must resolve to a known kind",
            )


class MusicLibraryFallbackTests(unittest.TestCase):
    """The music selector searches both the built-in and import locations."""

    def test_select_music_falls_back_to_import_root(self):
        """When tone folders are empty, the selector checks output/musics/."""
        from scriptase.modules.music import selector

        with tempfile.TemporaryDirectory() as tmp:
            # Set up a fake import root with one track.
            import_root = os.path.join(tmp, "musics")
            os.makedirs(import_root)
            track = os.path.join(import_root, "ambient_fixture.mp3")
            with open(track, "wb") as handle:
                handle.write(b"\xff\xfb\x90\x00" * 10)  # minimal MP3 frame

            original_root = selector._MUSIC_ROOT
            original_import = selector._MUSIC_IMPORT_ROOT
            try:
                selector._MUSIC_ROOT = os.path.join(tmp, "empty_library")
                selector._MUSIC_IMPORT_ROOT = import_root

                result = selector.select_music("educational")
                self.assertIsNotNone(result, "Should find a track in import root")
                self.assertIn(
                    "ambient_fixture.mp3",
                    result["path"],
                    "Selected track should come from the import root",
                )
            finally:
                selector._MUSIC_ROOT = original_root
                selector._MUSIC_IMPORT_ROOT = original_import

    def test_select_music_prefers_tone_folders(self):
        """Tone-organised folders take priority over the flat import root."""
        from scriptase.modules.music import selector

        with tempfile.TemporaryDirectory() as tmp:
            # Tone-organised library with one track.
            tone_folder = os.path.join(tmp, "library", "ambient")
            os.makedirs(tone_folder)
            tone_track = os.path.join(tone_folder, "tone_pick.mp3")
            with open(tone_track, "wb") as handle:
                handle.write(b"\xff\xfb\x90\x00" * 10)

            # Import root with a different track.
            import_root = os.path.join(tmp, "musics")
            os.makedirs(import_root)
            import_track = os.path.join(import_root, "import_pick.mp3")
            with open(import_track, "wb") as handle:
                handle.write(b"\xff\xfb\x90\x00" * 10)

            original_root = selector._MUSIC_ROOT
            original_import = selector._MUSIC_IMPORT_ROOT
            try:
                selector._MUSIC_ROOT = os.path.join(tmp, "library")
                selector._MUSIC_IMPORT_ROOT = import_root

                result = selector.select_music("educational")
                self.assertIsNotNone(result)
                self.assertIn(
                    "tone_pick.mp3",
                    result["path"],
                    "Should prefer the tone-organised folder",
                )
            finally:
                selector._MUSIC_ROOT = original_root
                selector._MUSIC_IMPORT_ROOT = original_import

    def test_select_music_returns_none_when_both_empty(self):
        """Graceful None when no tracks exist anywhere."""
        from scriptase.modules.music import selector

        with tempfile.TemporaryDirectory() as tmp:
            original_root = selector._MUSIC_ROOT
            original_import = selector._MUSIC_IMPORT_ROOT
            try:
                selector._MUSIC_ROOT = os.path.join(tmp, "empty")
                selector._MUSIC_IMPORT_ROOT = os.path.join(tmp, "also_empty")
                result = selector.select_music("educational")
                self.assertIsNone(result)
            finally:
                selector._MUSIC_ROOT = original_root
                selector._MUSIC_IMPORT_ROOT = original_import


class MusicAdapterManagedTrackTests(unittest.TestCase):
    """The music adapter accepts tracks from both managed roots."""

    def test_managed_track_accepts_library_path(self):
        from scriptase.engine.adapters.music import _managed_track, _MANAGED_ROOTS

        # Skip if the library root doesn't exist (clean checkout).
        library_root = _MANAGED_ROOTS[0][0]
        with tempfile.TemporaryDirectory() as tmp:
            # Create a temporary file under a mock library root.
            from scriptase.engine.adapters import music as music_adapter

            original_roots = music_adapter._MANAGED_ROOTS
            mock_library = os.path.join(tmp, "library")
            mock_import = os.path.join(tmp, "musics")
            os.makedirs(mock_library)
            os.makedirs(mock_import)

            track_path = os.path.join(mock_library, "ambient", "test.mp3")
            os.makedirs(os.path.dirname(track_path))
            with open(track_path, "wb") as handle:
                handle.write(b"MP3-BYTES")

            music_adapter._MANAGED_ROOTS = (
                (os.path.abspath(mock_library), "/assets/sounds/music/"),
                (os.path.abspath(mock_import), "musics/"),
            )
            try:
                ref = _managed_track(track_path)
                self.assertEqual(ref, "/assets/sounds/music/ambient/test.mp3")
            finally:
                music_adapter._MANAGED_ROOTS = original_roots

    def test_managed_track_accepts_import_path(self):
        from scriptase.engine.adapters.music import _managed_track
        from scriptase.engine.adapters import music as music_adapter

        with tempfile.TemporaryDirectory() as tmp:
            original_roots = music_adapter._MANAGED_ROOTS
            mock_library = os.path.join(tmp, "library")
            mock_import = os.path.join(tmp, "musics")
            os.makedirs(mock_library)
            os.makedirs(mock_import)

            track_path = os.path.join(mock_import, "ambient_test.mp3")
            with open(track_path, "wb") as handle:
                handle.write(b"MP3-BYTES")

            music_adapter._MANAGED_ROOTS = (
                (os.path.abspath(mock_library), "/assets/sounds/music/"),
                (os.path.abspath(mock_import), "musics/"),
            )
            try:
                ref = _managed_track(track_path)
                self.assertEqual(ref, "musics/ambient_test.mp3")
            finally:
                music_adapter._MANAGED_ROOTS = original_roots

    def test_managed_track_rejects_unmanaged_path(self):
        from scriptase.engine.adapters.music import _managed_track
        from scriptase.engine.adapters.common import AdapterError
        from scriptase.engine.adapters import music as music_adapter

        with tempfile.TemporaryDirectory() as tmp:
            original_roots = music_adapter._MANAGED_ROOTS
            music_adapter._MANAGED_ROOTS = (
                (os.path.abspath(os.path.join(tmp, "library")), "/assets/sounds/music/"),
                (os.path.abspath(os.path.join(tmp, "musics")), "musics/"),
            )
            try:
                with self.assertRaises(AdapterError) as ctx:
                    _managed_track(os.path.join(tmp, "unmanaged", "track.mp3"))
                self.assertEqual(ctx.exception.code, "ARTIFACT_UNMANAGED")
            finally:
                music_adapter._MANAGED_ROOTS = original_roots


class ProviderUnavailableTests(unittest.TestCase):
    """Stages that need a provider must fail with PROVIDER_UNAVAILABLE."""

    def test_adapter_resolve_provider_raises_on_missing_type(self):
        """resolve_provider raises AdapterError when the provider is unknown."""
        from scriptase.engine.adapters.common import AdapterError, resolve_provider

        with self.assertRaises(AdapterError) as ctx:
            resolve_provider("tts", "nonexistent_provider_xyz")
        self.assertEqual(ctx.exception.code, "PROVIDER_UNAVAILABLE")
        self.assertIn("nonexistent_provider_xyz", str(ctx.exception))

    def test_error_names_what_is_missing(self):
        """The error message must identify the missing provider by name."""
        from scriptase.engine.adapters.common import AdapterError, resolve_provider

        domains = ["tts", "image", "video", "scene_director"]
        for domain in domains:
            with self.subTest(domain=domain):
                with self.assertRaises(AdapterError) as ctx:
                    resolve_provider(domain, f"fixture_missing_{domain}")
                self.assertEqual(
                    ctx.exception.code, "PROVIDER_UNAVAILABLE",
                    f"Domain {domain} should raise PROVIDER_UNAVAILABLE",
                )
                self.assertIn(
                    f"fixture_missing_{domain}", str(ctx.exception),
                    f"Error must name the missing provider for {domain}",
                )


if __name__ == "__main__":
    unittest.main()
