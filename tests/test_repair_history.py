"""Step 8.4 — Repair history.

Done when: a repaired Job's history reconstructs the full sequence including
every superseded artifact version and the reason each repair was attempted.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import Any

from app import create_app
from scriptase.artifacts import store as artifact_store
from scriptase.artifacts.store import get_artifact, register_artifact, versioned_relative_path
from scriptase.channels import store as channel_store
from scriptase.channels.store import create_channel, default_draft as channel_default_draft
from scriptase.jobs import store as job_store
from scriptase.jobs.store import create_job, get_job, update_job
from scriptase.review import history as repair_history
from scriptase.review import store as issue_store
from scriptase.review.history import (
    REPAIR_HISTORY_SCHEMA_VERSION,
    RepairHistoryEntry,
    create_repair_history_entry,
    get_repair_history_entry,
    reconstruct_job_repair_history,
    record_repair_outcome,
)
from scriptase.review.repair import (
    RepairDecision,
    apply_repair_decision,
    decide_issue_repair,
    record_repair_attempt,
)
from scriptase.review.store import create_review_issue, get_issue


class RepairHistoryTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_rph_")
        root = self.temp.name
        self.output_dir = os.path.join(root, "output")
        os.makedirs(self.output_dir, exist_ok=True)

        # Channels + jobs.
        self.old_channels = channel_store._channels_dir
        self.old_channel_trash = channel_store._trash_dir
        channel_store._channels_dir = os.path.join(root, "channels")
        channel_store._trash_dir = os.path.join(root, "trash", "channels")
        os.makedirs(channel_store._channels_dir, exist_ok=True)

        self.old_jobs = job_store._jobs_dir
        self.old_job_trash = job_store._trash_dir
        job_store._jobs_dir = os.path.join(root, "jobs")
        job_store._trash_dir = os.path.join(root, "trash", "jobs")
        os.makedirs(job_store._jobs_dir, exist_ok=True)

        # Issues + repair history.
        self.old_issues = issue_store._issues_dir
        issue_store._issues_dir = os.path.join(root, "issues")
        os.makedirs(issue_store._issues_dir, exist_ok=True)

        self.old_history = repair_history._history_dir
        repair_history._history_dir = os.path.join(root, "repair_history")
        os.makedirs(repair_history._history_dir, exist_ok=True)

        # Artifacts.
        self.old_artifacts = artifact_store._artifacts_dir
        self.old_output = artifact_store._output_dir
        artifact_store._output_dir = self.output_dir
        artifact_store._artifacts_dir = os.path.join(self.output_dir, "artifacts")
        os.makedirs(artifact_store._artifacts_dir, exist_ok=True)

        import config

        self.old_config_output = config.OUTPUT_DIR
        config.OUTPUT_DIR = self.output_dir

        self.channel = create_channel(self._channel_draft())
        self.job = create_job(
            {
                "channel_id": self.channel.id,
                "workflow_id": "wf_test",
                "execution_mode": "manual",
                "source": {"mode": "topic", "topic": "stoicism"},
            }
        )
        # Keep the Job non-terminal so repairs can stamp status_reason freely.
        update_job(self.job.id, status="running")

        self.app = create_app(discover_providers=False)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        channel_store._channels_dir = self.old_channels
        channel_store._trash_dir = self.old_channel_trash
        job_store._jobs_dir = self.old_jobs
        job_store._trash_dir = self.old_job_trash
        issue_store._issues_dir = self.old_issues
        repair_history._history_dir = self.old_history
        artifact_store._artifacts_dir = self.old_artifacts
        artifact_store._output_dir = self.old_output
        import config

        config.OUTPUT_DIR = self.old_config_output
        self.temp.cleanup()

    def _channel_draft(self, **overrides):
        draft = channel_default_draft(name="Repair History Channel")
        draft["content"] = {
            "niche": "stoicism",
            "language": "en",
            "tone": "educational",
            "duration_target": 60,
        }
        draft["review_policy"] = {
            "thresholds": {"confidence_floor": 0.5},
            "max_repairs": 3,
            "escalation": "human",
            "human_checkpoints": [],
        }
        draft.update(overrides)
        return draft

    def _write_blob(self, relative: str, content: bytes) -> str:
        abs_path = os.path.join(self.output_dir, relative.replace("/", os.sep))
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as handle:
            handle.write(content)
        return relative

    def _register_image(
        self,
        *,
        scene_id: str = "scn_AAAAAA",
        version: int,
        content: bytes,
        generation: dict | None = None,
        provenance_ref: str | None = None,
    ):
        path = versioned_relative_path(
            f"storyboard/{self.job.id}/{scene_id}.png", version
        )
        self._write_blob(path, content)
        return register_artifact(
            job_id=self.job.id,
            kind="image",
            path=path,
            scene_id=scene_id,
            provenance_ref=provenance_ref,
            generation=generation,
        )

    def _issue(
        self,
        *,
        scene_id: str = "scn_AAAAAA",
        target_artifact_id: str | None = None,
        reason: str = "Wrong subject in still",
        repair_instruction: str = "Preserve framing; fix subject wardrobe",
        suggested_action: str = "regenerate",
        attempt_count: int = 0,
        confidence: float = 0.9,
    ):
        return create_review_issue(
            {
                "job_id": self.job.id,
                "scene_id": scene_id,
                "target_node_id": "img_1",
                "target_artifact_id": target_artifact_id,
                "issue_type": "visual_mismatch",
                "severity": "high",
                "confidence": confidence,
                "reason": reason,
                "suggested_action": suggested_action,
                "repair_instruction": repair_instruction,
                "attempt_count": attempt_count,
                "status": "open",
                "observed": {"subject": "wrong"},
                "expected": {"subject": "philosopher"},
            }
        )

    def _workflow(self) -> dict[str, Any]:
        return {
            "workflow_id": "wf_test",
            "nodes": [
                {
                    "id": "img_1",
                    "type": "storyboard.generate",
                    "type_version": 1,
                    "name": "Images",
                    "position": {"x": 0, "y": 0},
                    "configuration": {},
                    "disabled": False,
                },
            ],
        }


class RepairHistoryEntryModelTests(RepairHistoryTestBase):
    def test_create_and_load_entry(self):
        entry = create_repair_history_entry(
            job_id=self.job.id,
            issue_id="iss_AAAAAA",
            action="regenerate",
            result="resolved",
            scene_id="scn_AAAAAA",
            routed_to_node_type="storyboard.generate",
            provider_instance_id="inst_main",
            instruction="fix wardrobe",
            reason="Wrong subject in still",
            prompt_revision="flux-dev@2026-01",
            input_artifact_ids=["art_AAAAAA"],
            output_artifact_ids=["art_BBBBBB"],
            provenance_ref="inv_1",
            append_to_job=True,
        )
        self.assertTrue(entry.id.startswith("rph_"))
        self.assertEqual(entry.schema_version, REPAIR_HISTORY_SCHEMA_VERSION)

        loaded = get_repair_history_entry(entry.id)
        self.assertEqual(loaded.reason, "Wrong subject in still")
        self.assertEqual(loaded.prompt_revision, "flux-dev@2026-01")

        job = get_job(self.job.id)
        self.assertIn(entry.id, job.repair_history)


class RepairedJobSequenceTests(RepairHistoryTestBase):
    """Done-when: full sequence with superseded versions and reasons."""

    def test_reconstructs_full_sequence_with_superseded_and_reasons(self):
        # v1 — original bad still.
        v1 = self._register_image(
            version=1,
            content=b"png-v1-bad",
            provenance_ref="inv_v1",
            generation={
                "provider_id": "wavespeed",
                "provider_instance_id": "inst_primary",
                "seed": 11,
                "prompt_revision": "flux-dev@v1",
            },
        )
        issue = self._issue(
            target_artifact_id=v1.id,
            reason="Subject wardrobe does not match SceneSpec",
            repair_instruction="Keep framing; change wardrobe to navy",
        )

        job = get_job(self.job.id)
        decision = decide_issue_repair(
            issue,
            job,
            workflow=self._workflow(),
        )
        self.assertEqual(decision.action, "repair")
        apply_repair_decision(decision, mark_repairing=True)

        # v2 — repair succeeds; v1 is superseded.
        v2 = self._register_image(
            version=2,
            content=b"png-v2-fixed",
            provenance_ref="inv_v2",
            generation={
                "provider_id": "wavespeed",
                "provider_instance_id": "inst_primary",
                "seed": 22,
                "prompt_revision": "flux-dev@v2-repair",
            },
        )
        prior = get_artifact(v1.id)
        self.assertEqual(prior.superseded_by, v2.id)
        self.assertTrue(prior.is_superseded)

        entry = record_repair_attempt(
            decision,
            result="resolved",
            issue=get_issue(issue.id),
            input_artifact_ids=[v1.id],
            output_artifact_ids=[v2.id],
            provider_instance_id="inst_primary",
            prompt_revision="flux-dev@v2-repair",
            provenance_ref="inv_v2",
            reason=decision.reason,
            instruction=issue.repair_instruction,
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry.action, "regenerate")
        self.assertEqual(entry.result, "resolved")

        # Second issue on another scene — escalate (low confidence).
        issue2 = self._issue(
            scene_id="scn_BBBBBB",
            reason="Ambiguous motion defect",
            suggested_action="regenerate",
            confidence=0.1,
            repair_instruction="Unclear fix",
        )
        decision2 = decide_issue_repair(
            issue2,
            get_job(self.job.id),
            workflow=self._workflow(),
        )
        self.assertEqual(decision2.action, "escalate")
        apply_repair_decision(decision2)

        # Reconstruct.
        history = reconstruct_job_repair_history(self.job.id)
        self.assertEqual(history["job_id"], self.job.id)
        self.assertGreaterEqual(history["entry_count"], 2)

        sequence = history["sequence"]
        self.assertEqual(len(sequence), 2)

        first = sequence[0]
        self.assertEqual(first["issue_id"], issue.id)
        self.assertEqual(first["action"], "regenerate")
        self.assertEqual(first["result"], "resolved")
        # Reason for the repair attempt must be present and informative.
        self.assertTrue(first["reason"] or first["instruction"])
        blob = f"{first['reason']} {first['instruction']}".lower()
        self.assertTrue(
            "wardrobe" in blob or "targeted repair" in blob or "subject" in blob,
            msg=f"expected repair reason context, got {blob!r}",
        )
        self.assertEqual(first["prompt_revision"], "flux-dev@v2-repair")
        self.assertEqual(first["provider_instance_id"], "inst_primary")
        self.assertEqual(first["routed_to_node_type"], "storyboard.generate")

        # Superseded v1 is visible on the chain.
        self.assertIn(v1.id, first["input_artifact_ids"])
        self.assertIn(v2.id, first["output_artifact_ids"])
        chain = first["output_artifact_chains"].get(v2.id) or first[
            "input_artifact_chains"
        ].get(v1.id)
        self.assertIsNotNone(chain)
        chain_ids = {row["artifact_id"] for row in chain if "artifact_id" in row}
        self.assertIn(v1.id, chain_ids)
        self.assertIn(v2.id, chain_ids)
        superseded_ids = {
            row["artifact_id"]
            for row in first["superseded_artifact_versions"]
            if row.get("is_superseded")
        }
        self.assertIn(v1.id, superseded_ids)

        second = sequence[1]
        self.assertEqual(second["issue_id"], issue2.id)
        self.assertEqual(second["action"], "escalate")
        self.assertEqual(second["result"], "escalated")
        self.assertTrue(second["reason"])

        # Job-level flat list also carries every superseded version.
        all_superseded = {
            row["artifact_id"] for row in history["superseded_artifact_versions"]
        }
        self.assertIn(v1.id, all_superseded)

        # reasons[] is a compact reconstruction of why each repair ran.
        reasons = {row["issue_id"]: row for row in history["reasons"]}
        self.assertIn(issue.id, reasons)
        self.assertIn(issue2.id, reasons)
        self.assertTrue(reasons[issue.id]["reason"] or reasons[issue.id]["instruction"])

        # Job.repair_history order matches sequence.
        job = get_job(self.job.id)
        self.assertEqual(job.repair_history, [row["id"] for row in sequence])

    def test_api_returns_reconstructed_history(self):
        v1 = self._register_image(
            version=1,
            content=b"api-v1",
            generation={
                "provider_instance_id": "inst_a",
                "seed": 1,
                "prompt_revision": "rev-a",
            },
        )
        v2 = self._register_image(
            version=2,
            content=b"api-v2",
            generation={
                "provider_instance_id": "inst_b",
                "seed": 2,
                "prompt_revision": "rev-b",
            },
        )
        entry = create_repair_history_entry(
            job_id=self.job.id,
            issue_id="iss_API001",
            action="regenerate",
            result="resolved",
            scene_id="scn_AAAAAA",
            routed_to_node_type="storyboard.generate",
            provider_instance_id="inst_b",
            instruction="fix still",
            reason="visual mismatch on scene scn_AAAAAA",
            prompt_revision="rev-b",
            input_artifact_ids=[v1.id],
            output_artifact_ids=[v2.id],
            append_to_job=True,
        )

        response = self.client.get(f"/api/jobs/{self.job.id}/repair-history")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        body = response.get_json()
        self.assertEqual(body["entry_count"], 1)
        self.assertEqual(body["sequence"][0]["id"], entry.id)
        self.assertEqual(
            body["sequence"][0]["reason"], "visual mismatch on scene scn_AAAAAA"
        )
        superseded = {
            row["artifact_id"]
            for row in body["superseded_artifact_versions"]
            if row.get("is_superseded")
        }
        self.assertIn(v1.id, superseded)

    def test_fallback_action_records_provider_instance(self):
        issue = self._issue(reason="Primary provider timed out")
        decision = decide_issue_repair(
            issue,
            get_job(self.job.id),
            workflow=self._workflow(),
        )
        self.assertEqual(decision.action, "repair")
        apply_repair_decision(decision)

        v2 = self._register_image(
            version=1,
            content=b"fallback-bytes",
            generation={
                "provider_instance_id": "inst_fallback",
                "seed": 99,
                "prompt_revision": "fallback-rev",
            },
        )
        entry = record_repair_attempt(
            decision,
            result="resolved",
            issue=get_issue(issue.id),
            output_artifact_ids=[v2.id],
            provider_instance_id="inst_fallback",
            prompt_revision="fallback-rev",
            selection_reason="fallback_after:inst_primary",
            reason=decision.reason,
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry.action, "fallback")
        self.assertEqual(entry.provider_instance_id, "inst_fallback")
        self.assertEqual(entry.result, "resolved")


class TerminalDecisionHistoryTests(RepairHistoryTestBase):
    def test_escalate_writes_history_entry(self):
        issue = self._issue(
            reason="Low confidence visual call",
            confidence=0.1,
        )
        decision = decide_issue_repair(
            issue,
            get_job(self.job.id),
            workflow=self._workflow(),
        )
        self.assertEqual(decision.action, "escalate")
        apply_repair_decision(decision)

        history = reconstruct_job_repair_history(self.job.id)
        self.assertEqual(history["entry_count"], 1)
        row = history["sequence"][0]
        self.assertEqual(row["action"], "escalate")
        self.assertEqual(row["result"], "escalated")
        self.assertIn("confidence", row["reason"].lower())

    def test_failed_repair_records_and_reopens_issue(self):
        issue = self._issue(reason="Transient provider failure")
        decision = decide_issue_repair(
            issue,
            get_job(self.job.id),
            workflow=self._workflow(),
        )
        apply_repair_decision(decision)
        entry = record_repair_attempt(
            decision,
            result="failed",
            issue=get_issue(issue.id),
            reason=decision.reason,
        )
        self.assertEqual(entry.result, "failed")
        reopened = get_issue(issue.id)
        self.assertEqual(reopened.status, "open")


class SchemaGuardTests(unittest.TestCase):
    def test_invalid_action_rejected(self):
        with self.assertRaises(Exception):
            RepairHistoryEntry.model_validate(
                {
                    "id": "rph_AAAAAA",
                    "job_id": "job_AAAAAA",
                    "issue_id": "iss_AAAAAA",
                    "action": "explode",
                    "result": "resolved",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            )

    def test_record_outcome_skips_refuse_budget(self):
        decision = RepairDecision(
            action="refuse_budget",
            issue_id="iss_AAAAAA",
            job_id="job_AAAAAA",
            scene_id=None,
            routing=None,
            reason="budget hit",
            code="BUDGET_EXCEEDED",
        )
        self.assertIsNone(record_repair_outcome(decision))


if __name__ == "__main__":
    unittest.main()
