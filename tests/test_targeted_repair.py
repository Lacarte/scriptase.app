"""Step 8.2 — Targeted repair with budgets and escalation.

Done when: an unfixable issue escalates instead of looping, and a Job that
reaches its repair budget stops with a clear reason rather than continuing
to spend.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from typing import Any

from scriptase.jobs.models import BudgetSpent
from scriptase.review import store as issue_store
from scriptase.review.models import ReviewIssue
from scriptase.review.policy import OWNER_IMAGE, OWNER_VIDEO, route_issue
from scriptase.review.repair import (
    BUDGET_EXCEEDED,
    LOW_CONFIDENCE,
    REPAIR_LIMIT_REACHED,
    SAFE_DEGRADATION,
    STATUS_REASON_BUDGET,
    STATUS_REASON_ESCALATION,
    STATUS_REASON_REPAIR_LIMIT,
    RepairDecision,
    RepairPlan,
    apply_repair_decision,
    apply_repair_plan,
    build_repair_run_request,
    decide_issue_repair,
    plan_job_repairs,
    process_job_repairs,
    resolve_repair_policy,
    resolve_target_node_id,
)


def _job(
    *,
    job_id: str = "job_AAAAAA",
    max_repairs: int = 3,
    max_generations: int | None = None,
    max_cost: float | None = None,
    generations_spent: int = 0,
    cost_spent: float = 0.0,
    confidence_floor: float = 0.5,
    safe_degradation: dict[str, str] | None = None,
    max_repairs_per_scene: int | None = None,
    workflow_id: str = "wf_test",
) -> dict[str, Any]:
    thresholds: dict[str, Any] = {"confidence_floor": confidence_floor}
    if safe_degradation is not None:
        thresholds["safe_degradation"] = safe_degradation
    if max_repairs_per_scene is not None:
        thresholds["max_repairs_per_scene"] = max_repairs_per_scene
    return {
        "id": job_id,
        "workflow_id": workflow_id,
        "channel_snapshot": {
            "review_policy": {
                "thresholds": thresholds,
                "max_repairs": max_repairs,
                "escalation": "human",
                "human_checkpoints": [],
            },
            "budget": {
                "max_generations": max_generations,
                "max_cost": max_cost,
                "currency": "USD",
            },
        },
        "budget_spent": {
            "generations": generations_spent,
            "cost": cost_spent,
        },
    }


def _issue(
    *,
    issue_id: str = "iss_AAAAAA",
    job_id: str = "job_AAAAAA",
    scene_id: str | None = "scn_AAAAAA",
    issue_type: str = "visual_mismatch",
    confidence: float = 0.9,
    attempt_count: int = 0,
    status: str = "open",
    suggested_action: str = "regenerate",
    target_node_id: str | None = "img_1",
    reason: str = "Wrong subject in still",
    repair_instruction: str = "Preserve composition; fix subject",
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "schema_version": 2,
        "job_id": job_id,
        "scene_id": scene_id,
        "target_node_id": target_node_id,
        "target_artifact_id": "art_AAAAAA",
        "issue_type": issue_type,
        "severity": "high",
        "confidence": confidence,
        "reason": reason,
        "suggested_action": suggested_action,
        "repair_instruction": repair_instruction,
        "attempt_count": attempt_count,
        "status": status,
        "check_id": None,
        "observed": {},
        "expected": {},
        "created_at": "2026-01-01T00:00:00Z",
        "resolved_at": None,
    }


def _workflow() -> dict[str, Any]:
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
            {
                "id": "vid_1",
                "type": "animator.generate",
                "type_version": 1,
                "name": "Videos",
                "position": {"x": 100, "y": 0},
                "configuration": {},
                "disabled": False,
            },
            {
                "id": "tts_1",
                "type": "tts.generate",
                "type_version": 1,
                "name": "Voice",
                "position": {"x": 50, "y": 0},
                "configuration": {},
                "disabled": False,
            },
        ],
        "edges": [],
    }


class ResolveRepairPolicyTests(unittest.TestCase):
    def test_defaults_from_empty_snapshot(self):
        policy = resolve_repair_policy({"channel_snapshot": {}})
        self.assertEqual(policy.max_repairs, 3)
        self.assertEqual(policy.confidence_floor, 0.5)
        self.assertTrue(policy.escalate_on_low_confidence)
        self.assertEqual(dict(policy.safe_degradation), {})

    def test_reads_thresholds_and_safe_degradation(self):
        job = _job(
            max_repairs=2,
            confidence_floor=0.7,
            safe_degradation={"video": "keep_still"},
            max_repairs_per_scene=4,
            max_generations=10,
        )
        policy = resolve_repair_policy(job)
        self.assertEqual(policy.max_repairs, 2)
        self.assertEqual(policy.confidence_floor, 0.7)
        self.assertEqual(policy.safe_degradation["video"], "keep_still")
        self.assertEqual(policy.max_repairs_per_scene, 4)
        self.assertEqual(policy.budget.max_generations, 10)

    def test_keep_still_shortcut_flag(self):
        job = _job()
        job["channel_snapshot"]["review_policy"]["thresholds"] = {
            "keep_still_on_video_failure": True,
        }
        policy = resolve_repair_policy(job)
        self.assertEqual(policy.safe_degradation[OWNER_VIDEO], "keep_still")


class DecideIssueRepairTests(unittest.TestCase):
    def test_admits_targeted_per_scene_repair(self):
        job = _job(max_generations=10)
        issue = _issue(scene_id="scn_SCENE1", attempt_count=0)
        decision = decide_issue_repair(issue, job, workflow=_workflow())

        self.assertEqual(decision.action, "repair")
        self.assertEqual(decision.scene_id, "scn_SCENE1")
        self.assertEqual(decision.routing.owner, OWNER_IMAGE)
        self.assertEqual(decision.target_node_type, "storyboard.generate")
        self.assertEqual(decision.target_node_id, "img_1")
        self.assertEqual(decision.attempt_count, 1)
        self.assertEqual(decision.estimated_generations, 1)
        self.assertIsNotNone(decision.run_request)
        self.assertEqual(decision.run_request["run_mode"], "retry_failed")
        self.assertEqual(decision.run_request["target_node_ids"], ["img_1"])
        self.assertEqual(
            decision.run_request["scope"]["scene_ids"], ["scn_SCENE1"]
        )
        # Smallest scope: one node, one scene — not a full-job re-run.
        self.assertEqual(decision.run_request["run_mode"], "retry_failed")
        self.assertNotEqual(decision.run_request.get("run_mode"), "full")

    def test_exhausting_attempts_escalates_instead_of_looping(self):
        """Done-when: unfixable issue escalates instead of looping."""
        job = _job(max_repairs=3, max_generations=100)
        issue = _issue(attempt_count=3, confidence=0.95)
        decision = decide_issue_repair(issue, job, workflow=_workflow())

        self.assertEqual(decision.action, "escalate")
        self.assertEqual(decision.code, REPAIR_LIMIT_REACHED)
        self.assertEqual(decision.job_status_reason, STATUS_REASON_REPAIR_LIMIT)
        self.assertIsNone(decision.run_request)
        # Re-deciding must never re-admit repair once the budget is spent.
        again = decide_issue_repair(issue, job, workflow=_workflow())
        self.assertEqual(again.action, "escalate")
        self.assertEqual(again.code, REPAIR_LIMIT_REACHED)

    def test_max_repairs_zero_escalates_immediately(self):
        job = _job(max_repairs=0, max_generations=10)
        issue = _issue(attempt_count=0)
        decision = decide_issue_repair(issue, job)
        self.assertEqual(decision.action, "escalate")
        self.assertEqual(decision.code, REPAIR_LIMIT_REACHED)

    def test_low_confidence_escalates_without_spending(self):
        job = _job(confidence_floor=0.6, max_generations=10)
        issue = _issue(confidence=0.4, attempt_count=0)
        decision = decide_issue_repair(issue, job, workflow=_workflow())
        self.assertEqual(decision.action, "escalate")
        self.assertEqual(decision.code, LOW_CONFIDENCE)
        self.assertEqual(decision.estimated_generations, 0)
        self.assertIsNone(decision.run_request)

    def test_suggested_escalate_and_accept(self):
        job = _job(max_generations=10)
        esc = decide_issue_repair(
            _issue(suggested_action="escalate"), job, workflow=_workflow()
        )
        self.assertEqual(esc.action, "escalate")
        acc = decide_issue_repair(
            _issue(suggested_action="accept"), job, workflow=_workflow()
        )
        self.assertEqual(acc.action, "accept")

    def test_terminal_issue_is_skipped(self):
        job = _job()
        decision = decide_issue_repair(
            _issue(status="resolved", attempt_count=0), job
        )
        self.assertEqual(decision.action, "skip")

    def test_job_budget_refuses_instead_of_spending(self):
        """Done-when: Job at repair budget stops with a clear reason."""
        job = _job(max_generations=2, generations_spent=2)
        issue = _issue(attempt_count=0, confidence=0.9)
        decision = decide_issue_repair(issue, job, workflow=_workflow())

        self.assertEqual(decision.action, "refuse_budget")
        self.assertEqual(decision.code, BUDGET_EXCEEDED)
        self.assertEqual(decision.job_status_reason, STATUS_REASON_BUDGET)
        self.assertIsNone(decision.run_request)

    def test_job_cost_ceiling_refuses(self):
        job = _job(max_cost=1.0, cost_spent=0.8)
        decision = decide_issue_repair(
            _issue(),
            job,
            workflow=_workflow(),
            estimated_cost=0.5,
        )
        self.assertEqual(decision.action, "refuse_budget")
        self.assertEqual(decision.code, BUDGET_EXCEEDED)

    def test_video_safe_degradation_keeps_still(self):
        job = _job(
            max_repairs=2,
            safe_degradation={"video": "keep_still"},
            max_generations=50,
        )
        issue = _issue(
            issue_type="motion_defect",
            attempt_count=2,
            target_node_id="vid_1",
            reason="Motion deformation",
        )
        decision = decide_issue_repair(issue, job, workflow=_workflow())
        self.assertEqual(decision.action, "degrade")
        self.assertEqual(decision.code, SAFE_DEGRADATION)
        self.assertEqual(decision.degradation_mode, "keep_still")
        self.assertEqual(decision.routing.owner, OWNER_VIDEO)
        self.assertIsNone(decision.run_request)

    def test_without_safe_degradation_video_escalates(self):
        job = _job(max_repairs=2, safe_degradation=None, max_generations=50)
        issue = _issue(
            issue_type="motion_defect",
            attempt_count=2,
            target_node_id="vid_1",
        )
        decision = decide_issue_repair(issue, job, workflow=_workflow())
        self.assertEqual(decision.action, "escalate")
        self.assertEqual(decision.code, REPAIR_LIMIT_REACHED)

    def test_scene_repair_cap(self):
        job = _job(
            max_repairs=5,
            max_repairs_per_scene=2,
            max_generations=50,
        )
        peers = [
            _issue(issue_id="iss_PEER01", scene_id="scn_X", attempt_count=2),
        ]
        issue = _issue(
            issue_id="iss_MAIN01",
            scene_id="scn_X",
            attempt_count=0,
        )
        decision = decide_issue_repair(
            issue, job, workflow=_workflow(), peer_issues=peers
        )
        self.assertEqual(decision.action, "escalate")
        self.assertEqual(decision.code, REPAIR_LIMIT_REACHED)

    def test_local_owner_does_not_consume_generation_budget(self):
        # Timing is free for the generation counter (step 3.5 rule).
        job = _job(max_generations=0, generations_spent=0)
        issue = _issue(
            issue_type="timing_drift",
            target_node_id=None,
            reason="Words misaligned",
        )
        decision = decide_issue_repair(issue, job)
        self.assertEqual(decision.action, "repair")
        self.assertEqual(decision.estimated_generations, 0)
        self.assertEqual(decision.target_node_type, "timing.align")


class PlanJobRepairsTests(unittest.TestCase):
    def test_budget_stop_blocks_remaining_issues(self):
        """A Job that hits budget mid-plan stops rather than continuing to spend."""
        job = _job(max_generations=1, generations_spent=0)
        issues = [
            _issue(issue_id="iss_AAA001", scene_id="scn_A"),
            _issue(issue_id="iss_AAA002", scene_id="scn_B"),
            _issue(issue_id="iss_AAA003", scene_id="scn_C"),
        ]
        plan = plan_job_repairs(job, issues=issues, workflow=_workflow())

        self.assertIsInstance(plan, RepairPlan)
        self.assertTrue(plan.stopped)
        self.assertEqual(plan.stop_code, BUDGET_EXCEEDED)
        self.assertIsNotNone(plan.stop_reason)

        actions = [d.action for d in plan.decisions]
        # First issue admits (1 generation); the rest must refuse.
        self.assertEqual(actions[0], "repair")
        self.assertTrue(all(a == "refuse_budget" for a in actions[1:]))
        # Total admitted generation estimate never exceeds the ceiling.
        admitted = sum(d.estimated_generations for d in plan.repairs)
        self.assertEqual(admitted, 1)

    def test_exhausted_issues_escalate_without_infinite_loop(self):
        job = _job(max_repairs=1, max_generations=100)
        issues = [
            _issue(issue_id="iss_EXH001", attempt_count=1),
            _issue(issue_id="iss_EXH002", attempt_count=1, scene_id="scn_B"),
        ]
        plan = plan_job_repairs(job, issues=issues, workflow=_workflow())
        self.assertEqual(len(plan.repairs), 0)
        self.assertEqual(len(plan.escalations), 2)
        for decision in plan.escalations:
            self.assertEqual(decision.code, REPAIR_LIMIT_REACHED)

    def test_skips_non_open_issues(self):
        job = _job(max_generations=10)
        issues = [
            _issue(issue_id="iss_OPEN01", status="open"),
            _issue(issue_id="iss_DONE01", status="resolved"),
        ]
        plan = plan_job_repairs(job, issues=issues, workflow=_workflow())
        self.assertEqual(len(plan.decisions), 1)
        self.assertEqual(plan.decisions[0].action, "repair")


class ApplyRepairDecisionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="scriptase-repair-")
        self._prev = issue_store._issues_dir
        issue_store._issues_dir = self._tmp

    def tearDown(self):
        issue_store._issues_dir = self._prev
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _persist(self, payload: dict[str, Any]) -> ReviewIssue:
        return issue_store.create_review_issue(
            {
                k: v
                for k, v in payload.items()
                if k not in {"id", "schema_version", "created_at", "resolved_at"}
            }
        )

    def test_apply_escalate_marks_issue_and_stops_job(self):
        doc = self._persist(_issue(attempt_count=3))
        job = _job(max_repairs=3)
        decision = decide_issue_repair(
            doc.to_document(), job, workflow=_workflow()
        )
        self.assertEqual(decision.action, "escalate")

        job_updates: list[dict[str, Any]] = []

        def _update_job(job_id: str, **kwargs):
            job_updates.append({"job_id": job_id, **kwargs})
            return None

        updated = apply_repair_decision(decision, update_job_fn=_update_job)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "escalated")
        self.assertIn("escalated", updated.reason)
        # Must not stay open — looping would re-admit an open issue.
        self.assertFalse(updated.is_open)
        self.assertEqual(len(job_updates), 1)
        self.assertEqual(job_updates[0]["status_reason"], STATUS_REASON_REPAIR_LIMIT)
        self.assertEqual(job_updates[0]["status"], "awaiting_approval")

    def test_apply_repair_advances_attempt_count(self):
        doc = self._persist(_issue(attempt_count=1))
        job = _job(max_repairs=3, max_generations=10)
        decision = decide_issue_repair(
            doc.to_document(), job, workflow=_workflow()
        )
        self.assertEqual(decision.action, "repair")
        self.assertEqual(decision.attempt_count, 2)

        updated = apply_repair_decision(decision)
        self.assertEqual(updated.status, "repairing")
        self.assertEqual(updated.attempt_count, 2)

    def test_apply_degrade_accepts_still(self):
        doc = self._persist(
            _issue(
                issue_type="motion_defect",
                attempt_count=3,
                target_node_id="vid_1",
            )
        )
        job = _job(
            max_repairs=3,
            safe_degradation={"video": "keep_still"},
            max_generations=50,
        )
        decision = decide_issue_repair(
            doc.to_document(), job, workflow=_workflow()
        )
        self.assertEqual(decision.action, "degrade")
        updated = apply_repair_decision(decision)
        self.assertEqual(updated.status, "accepted")
        self.assertIn("degraded:keep_still", updated.repair_instruction)

    def test_process_job_repairs_budget_stop_is_durable(self):
        """Full cycle: plan + apply; budget stop stamps Job and does not loop."""
        a = self._persist(_issue(scene_id="scn_A"))
        b = self._persist(_issue(scene_id="scn_B", job_id=a.job_id))
        job = _job(
            job_id=a.job_id,
            max_generations=1,
            generations_spent=0,
        )
        job_updates: list[dict[str, Any]] = []

        def _update_job(job_id: str, **kwargs):
            job_updates.append({"job_id": job_id, **kwargs})

        plan = process_job_repairs(
            job,
            issues=[a, b],
            workflow=_workflow(),
            update_job_fn=_update_job,
        )
        self.assertTrue(plan.stopped)
        self.assertEqual(plan.stop_code, BUDGET_EXCEEDED)

        # Exactly one repair admitted; Job stamped with budget reason.
        self.assertEqual(len(plan.repairs), 1)
        self.assertTrue(
            any(u.get("status_reason") == STATUS_REASON_BUDGET for u in job_updates)
        )

        # After spend is recorded, a further cycle admits nothing — clear stop.
        reloaded = [issue_store.get_issue(a.id), issue_store.get_issue(b.id)]
        job_after = dict(job)
        job_after["budget_spent"] = {"generations": 1, "cost": 0.0}
        plan_after = plan_job_repairs(
            job_after, issues=reloaded, workflow=_workflow()
        )
        self.assertEqual(len(plan_after.repairs), 0)
        for decision in plan_after.decisions:
            if decision.action not in {"skip", "escalate", "degrade", "accept"}:
                self.assertEqual(decision.action, "refuse_budget")
                self.assertEqual(decision.job_status_reason, STATUS_REASON_BUDGET)

    def test_unfixable_issue_does_not_loop_after_apply(self):
        doc = self._persist(_issue(attempt_count=3))
        job = _job(max_repairs=3, max_generations=100)
        plan = process_job_repairs(
            job, issues=[doc], workflow=_workflow(), update_job_fn=lambda *a, **k: None
        )
        self.assertEqual(len(plan.escalations), 1)
        reloaded = issue_store.get_issue(doc.id)
        self.assertEqual(reloaded.status, "escalated")
        # Next cycle sees a non-open issue → skip, never repair again.
        plan2 = plan_job_repairs(job, issues=[reloaded], workflow=_workflow())
        # escalated is terminal → filtered out of open_issues in planner
        self.assertEqual(plan2.decisions, [])


class RunRequestAndTargetTests(unittest.TestCase):
    def test_resolve_target_prefers_matching_preferred_id(self):
        routing = route_issue(_issue())
        node_id = resolve_target_node_id(
            _workflow(), routing, preferred_node_id="img_1"
        )
        self.assertEqual(node_id, "img_1")

    def test_resolve_target_falls_back_to_type(self):
        routing = route_issue(_issue(target_node_id="missing"))
        node_id = resolve_target_node_id(
            _workflow(), routing, preferred_node_id="missing"
        )
        self.assertEqual(node_id, "img_1")

    def test_build_repair_run_request_shape(self):
        body = build_repair_run_request(
            target_node_id="img_1",
            scene_id="scn_X",
            workflow_id="wf_1",
            repair_instruction="fix lighting",
            issue_id="iss_AAAAAA",
        )
        self.assertEqual(body["run_mode"], "retry_failed")
        self.assertEqual(body["scope"]["scene_ids"], ["scn_X"])
        self.assertEqual(body["scope"]["issue_id"], "iss_AAAAAA")
        self.assertEqual(body["workflow_id"], "wf_1")
        self.assertTrue(body["force"])


class DecisionSerializationTests(unittest.TestCase):
    def test_decision_to_dict_round_trip_fields(self):
        job = _job(max_generations=5)
        decision = decide_issue_repair(_issue(), job, workflow=_workflow())
        payload = decision.to_dict()
        self.assertEqual(payload["action"], "repair")
        self.assertEqual(payload["scene_id"], "scn_AAAAAA")
        self.assertIn("routing", payload)
        self.assertIsInstance(payload["routing"], dict)


if __name__ == "__main__":
    unittest.main()
