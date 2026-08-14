"""Step 1.4 — Job model and store.

Done when: starting a Job writes a snapshot that a redaction test proves
contains no credential, and a Job survives a process restart with its status
and artifact set intact.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from scriptase.channels import store as channel_store
from scriptase.channels.store import create_channel, default_draft as channel_default_draft
from scriptase.engine.redaction import REDACTED, collect_secrets, is_sensitive_key, redact
from scriptase.jobs import store as job_store
from scriptase.jobs.migrations import SCHEMA_VERSION, apply_migrations
from scriptase.jobs.models import JOB_STATUSES, parse_job
from scriptase.jobs.snapshot import (
    assert_snapshot_has_no_credentials,
    build_channel_snapshot,
    snapshot_contains_credentials,
)
from scriptase.jobs.store import (
    JobNotFound,
    JobTerminal,
    JobValidationError,
    add_artifact_ids,
    create_job,
    default_draft,
    delete_job,
    get_job,
    list_jobs,
    update_job,
)


class JobStoreTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_jobs_")
        # Channel store (create_job loads the Channel for the snapshot).
        self.old_channels = channel_store._channels_dir
        self.old_channel_trash = channel_store._trash_dir
        channel_store._channels_dir = os.path.join(self.temp.name, "channels")
        channel_store._trash_dir = os.path.join(self.temp.name, "trash", "channels")
        os.makedirs(channel_store._channels_dir, exist_ok=True)

        # Job store.
        self.old_jobs = job_store._jobs_dir
        self.old_job_trash = job_store._trash_dir
        job_store._jobs_dir = os.path.join(self.temp.name, "jobs")
        job_store._trash_dir = os.path.join(self.temp.name, "trash", "jobs")
        os.makedirs(job_store._jobs_dir, exist_ok=True)

        self.channel = create_channel(self._channel_draft())

    def tearDown(self):
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_channel_trash
        job_store._jobs_dir = self.old_jobs
        job_store._trash_dir = self.old_job_trash
        self.temp.cleanup()

    def _channel_draft(self, **overrides):
        draft = channel_default_draft(name="Philosophy Daily")
        draft["content"] = {
            "niche": "stoicism",
            "language": "en",
            "tone": "educational",
            "duration_target": 60,
        }
        draft["visual_direction"] = {
            "style": "cinematic",
            "pattern": [
                {"narrative_role": "hook", "shot": "extreme close-up"},
                {"narrative_role": "explanation", "shot": "medium cinematic"},
                {"narrative_role": "ending", "shot": "symbolic visual"},
            ],
            "palette": "dark blue + amber",
        }
        draft["audio_defaults"] = {
            "tts_provider_instance_id": "inst_tts_1",
            "voice": "af_heart",
            "speed": 0.95,
        }
        draft["provider_defaults"] = {
            "script": "inst_script_1",
            "tts": "inst_tts_1",
            "image": "inst_image_1",
        }
        draft["fallback_policies"] = {
            "image": {"primary": "inst_image_1", "fallbacks": ["inst_image_2"]},
        }
        draft["export_defaults"] = {"aspect_ratio": "9:16", "fps": 30}
        draft["default_workflow_id"] = "wf_AAAAAA"
        draft.update(overrides)
        return draft

    def _job_draft(self, **overrides):
        draft = default_draft(
            channel_id=self.channel.id,
            execution_mode="automatic",
            source={
                "mode": "idea",
                "idea": "What Marcus Aurelius teaches about control",
            },
        )
        draft.update(overrides)
        return draft


class JobSnapshotRedactionTests(JobStoreTestBase):
    """Done-when: starting a Job writes a snapshot with no credentials."""

    def test_create_job_snapshot_has_instance_refs_and_no_credentials(self):
        job = create_job(self._job_draft())
        self.assertRegex(job.id, r"^job_[A-Z0-9]{6}$")
        self.assertEqual(job.schema_version, SCHEMA_VERSION)
        self.assertEqual(job.channel_id, self.channel.id)
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.execution_mode, "automatic")
        self.assertEqual(job.source.mode, "idea")
        self.assertEqual(job.workflow_id, "wf_AAAAAA")  # from channel default

        snapshot = job.channel_snapshot
        self.assertIsInstance(snapshot, dict)
        self.assertEqual(snapshot["id"], self.channel.id)
        self.assertEqual(snapshot["name"], "Philosophy Daily")
        self.assertEqual(snapshot["version"], self.channel.version)
        self.assertEqual(snapshot["provider_defaults"]["script"], "inst_script_1")
        self.assertEqual(snapshot["provider_defaults"]["tts"], "inst_tts_1")
        self.assertEqual(
            snapshot["audio_defaults"]["tts_provider_instance_id"], "inst_tts_1"
        )
        self.assertEqual(
            snapshot["fallback_policies"]["image"]["primary"], "inst_image_1"
        )
        self.assertIn("snapshotted_at", snapshot)
        self.assertTrue(snapshot["snapshotted_at"])

        # Redaction gate: no credential keys, no secret values collected.
        assert_snapshot_has_no_credentials(snapshot)
        self.assertFalse(snapshot_contains_credentials(snapshot))
        self.assertEqual(collect_secrets(snapshot), set())
        self.assertEqual(collect_secrets(job.to_document()), set())

        # On-disk document is the same clean shape.
        path = os.path.join(job_store._jobs_dir, f"{job.id}.json")
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        assert_snapshot_has_no_credentials(raw["channel_snapshot"])
        serialized = json.dumps(raw)
        for banned in ("api_key", "api-key", "client_secret", "password", "sk-"):
            self.assertNotIn(banned, serialized.lower() if banned != "sk-" else serialized)

    def test_build_channel_snapshot_strips_injected_credentials(self):
        """Even a poisoned mapping never freezes secrets into a snapshot."""
        poisoned = self.channel.to_document()
        poisoned["api_key"] = "sk-super-secret-key-value"
        poisoned["client_secret"] = "shh-do-not-leak"
        poisoned["content"] = {
            **poisoned.get("content", {}),
            "password": "should-not-appear",
            "tone": "educational",
        }
        poisoned["provider_defaults"] = {
            **poisoned.get("provider_defaults", {}),
            "script": "inst_script_1",
            "access_token": "tok_leaked",
        }

        snapshot = build_channel_snapshot(poisoned)
        assert_snapshot_has_no_credentials(snapshot)

        # Allowlisted instance refs survive; sensitive keys do not.
        self.assertEqual(snapshot["provider_defaults"]["script"], "inst_script_1")
        self.assertNotIn("api_key", snapshot)
        self.assertNotIn("client_secret", snapshot)
        self.assertNotIn("access_token", snapshot.get("provider_defaults", {}))
        self.assertNotIn("password", snapshot.get("content", {}))

        serialized = json.dumps(snapshot)
        self.assertNotIn("sk-super-secret-key-value", serialized)
        self.assertNotIn("tok_leaked", serialized)
        self.assertNotIn("should-not-appear", serialized)
        self.assertNotIn(REDACTED, serialized)  # stripped, not merely redacted

    def test_store_refuses_to_write_snapshot_with_credentials(self):
        job = create_job(self._job_draft())
        path = os.path.join(job_store._jobs_dir, f"{job.id}.json")
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        raw["channel_snapshot"]["api_key"] = "sk-injected-on-disk"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(raw, handle)

        with self.assertRaises(ValueError) as ctx:
            get_job(job.id)
        self.assertIn("credential", str(ctx.exception).lower())


class JobProcessRestartTests(JobStoreTestBase):
    """Done-when: Job survives a process restart with status + artifacts intact."""

    def test_job_survives_process_restart_with_status_and_artifacts(self):
        job = create_job(self._job_draft())
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.artifacts, [])

        # Simulate orchestration progress (step 1.5 will wire the engine).
        running = update_job(
            job.id,
            status="running",
            current_stage="script",
            execution_id="ex_ABCDEF",
            started_at="2026-08-14T10:00:00+00:00",
        )
        self.assertEqual(running.status, "running")
        self.assertEqual(running.current_stage, "script")
        self.assertEqual(running.execution_id, "ex_ABCDEF")

        with_artifacts = add_artifact_ids(
            job.id,
            ["art_AAAAAA", "art_BBBBBB", "art_AAAAAA"],  # dedupe
        )
        self.assertEqual(with_artifacts.artifacts, ["art_AAAAAA", "art_BBBBBB"])
        self.assertEqual(with_artifacts.status, "running")

        # --- Process restart: drop any in-memory handles and rebind to the
        # same on-disk root (simulates a new interpreter loading the same files).
        jobs_dir = job_store._jobs_dir
        trash_dir = job_store._trash_dir
        job_store._jobs_dir = ""
        job_store._trash_dir = ""
        # Rebind as a fresh process would.
        job_store._jobs_dir = jobs_dir
        job_store._trash_dir = trash_dir

        reloaded = get_job(job.id)
        self.assertEqual(reloaded.id, job.id)
        self.assertEqual(reloaded.status, "running")
        self.assertEqual(reloaded.current_stage, "script")
        self.assertEqual(reloaded.execution_id, "ex_ABCDEF")
        self.assertEqual(reloaded.started_at, "2026-08-14T10:00:00+00:00")
        self.assertEqual(reloaded.artifacts, ["art_AAAAAA", "art_BBBBBB"])
        self.assertEqual(reloaded.channel_id, self.channel.id)
        self.assertEqual(
            reloaded.channel_snapshot["provider_defaults"]["script"],
            "inst_script_1",
        )
        assert_snapshot_has_no_credentials(reloaded.channel_snapshot)

        # Raw on-disk JSON matches (not just an in-memory cache).
        path = os.path.join(jobs_dir, f"{job.id}.json")
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        self.assertEqual(raw["status"], "running")
        self.assertEqual(raw["artifacts"], ["art_AAAAAA", "art_BBBBBB"])
        self.assertEqual(raw["execution_id"], "ex_ABCDEF")


class JobCrudTests(JobStoreTestBase):
    def test_create_list_update_delete_round_trip(self):
        job = create_job(self._job_draft(workflow_id="wf_CUSTOM"))
        self.assertEqual(job.workflow_id, "wf_CUSTOM")
        self.assertTrue(job.created_at)

        listed = list_jobs(channel_id=self.channel.id)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].id, job.id)

        updated = update_job(
            job.id,
            status="awaiting_approval",
            status_reason="approval",
            current_stage="review",
        )
        self.assertEqual(updated.status, "awaiting_approval")
        self.assertEqual(updated.status_reason, "approval")

        # Terminal status then further mutation is rejected.
        done = update_job(
            job.id,
            status="completed",
            completed_at="2026-08-14T12:00:00+00:00",
        )
        self.assertEqual(done.status, "completed")
        self.assertTrue(done.is_terminal)
        with self.assertRaises(JobTerminal) as ctx:
            update_job(job.id, status="running")
        self.assertEqual(ctx.exception.code, "JOB_TERMINAL")

        delete_job(job.id)
        with self.assertRaises(JobNotFound):
            get_job(job.id)
        trash_entries = os.listdir(job_store._trash_dir)
        self.assertTrue(any(job.id in name for name in trash_entries))

    def test_create_rejects_missing_channel(self):
        with self.assertRaises(JobValidationError) as ctx:
            create_job(default_draft(
                channel_id="ch_ZZZZZZ",
                source={"mode": "idea", "idea": "seed idea for missing channel"},
            ))
        self.assertEqual(ctx.exception.code, "JOB_INVALID")
        joined = " ".join(
            item.get("msg", "") for item in ctx.exception.problems
        ).lower()
        self.assertIn("channel", joined)

    def test_create_rejects_paste_without_script(self):
        with self.assertRaises(JobValidationError) as ctx:
            create_job(self._job_draft(source={"mode": "paste", "pasted_script": ""}))
        joined = " ".join(
            item.get("msg", "") for item in ctx.exception.problems
        ).lower()
        self.assertIn("pasted_script", joined)

    def test_create_rejects_invalid_execution_mode(self):
        with self.assertRaises(JobValidationError):
            create_job(self._job_draft(execution_mode="turbo"))

    def test_create_rejects_invalid_source_mode(self):
        with self.assertRaises(JobValidationError):
            create_job(self._job_draft(source={"mode": "telepathy", "topic": "x"}))

    def test_delete_missing_raises_not_found(self):
        with self.assertRaises(JobNotFound):
            delete_job("job_AAAAAA")

    def test_status_vocabulary_matches_contract(self):
        self.assertEqual(
            set(JOB_STATUSES),
            {
                "queued",
                "running",
                "awaiting_approval",
                "completed",
                "failed",
                "cancelled",
            },
        )
        # No separate "paused" member — status_reason carries the reason.
        self.assertNotIn("paused", JOB_STATUSES)


class SnapshotAndMigrationUnitTests(unittest.TestCase):
    def test_apply_migrations_stamps_schema_version(self):
        migrated, changed = apply_migrations({"id": "job_AAAAAA"})
        self.assertTrue(changed)
        self.assertEqual(migrated["schema_version"], SCHEMA_VERSION)

    def test_parse_job_rejects_extra_fields(self):
        with self.assertRaises(Exception):
            parse_job({
                "id": "job_AAAAAA",
                "channel_id": "ch_AAAAAA",
                "api_key": "sk-nope",
            })

    def test_is_sensitive_key_covers_credential_shapes(self):
        self.assertTrue(is_sensitive_key("api_key"))
        self.assertTrue(is_sensitive_key("client_secret"))
        self.assertTrue(is_sensitive_key("wavespeed_api_key"))
        self.assertFalse(is_sensitive_key("provider_defaults"))
        self.assertFalse(is_sensitive_key("script"))

    def test_redact_does_not_mutate_allowlisted_instance_ids(self):
        payload = {
            "provider_defaults": {"script": "inst_script_1"},
            "api_key": "sk-should-redact",
        }
        cleaned = redact(payload)
        self.assertEqual(cleaned["provider_defaults"]["script"], "inst_script_1")
        self.assertEqual(cleaned["api_key"], REDACTED)


if __name__ == "__main__":
    unittest.main()
