"""Step 16.3 — the Script-stage panel and Review integration.

Done when: a weak script surfaces a low score before TTS runs, and an
Assisted-mode Job pauses at the script checkpoint.

The first clause is two separate claims and both are tested here.
*Surfaces* is ``StageProjectionTests`` — the score has to survive the execution
record's summarizer to reach the panel at all — plus ``ReviewIntegrationTests``,
which holds the ReviewIssue the Repair Router routes back to Script.
*Before TTS runs* is ``OrderingTests``. The second clause is
``AssistedCheckpointTests``.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from scriptase.engine.models import NodeExecutionRecord
from scriptase.engine.score_snapshot import (
    SCORE_NODE_TYPE,
    score_snapshot_from_result,
)
from scriptase.engine.scheduler import _summarize, deterministic_order
from scriptase.engine.templates import full_video_template
from scriptase.jobs.execution_modes import (
    configured_checkpoint_refs,
    resolve_checkpoint_node_ids,
    resolve_execution_policy,
)
from scriptase.jobs.stage_projection import project_stages
from scriptase.modules.viral import score_script
from scriptase.review import store as issue_store
from scriptase.review.policy import route_issue
from scriptase.review.viral_gate import (
    VIRAL_CHECK_ID,
    draft_for_score,
    gate_script_score,
    threshold_from_snapshot,
    viral_threshold,
)

JOB_ID = "job_VIR163"
ANALYZE_NODE = "n_analyze"

# The same pairing step 16.1 uses to prove the scorer separates. Kept here so
# these tests fail on a *routing* regression, not on scorer drift.
STRONG_SECTIONS = {
    "hook": "Did you know the strongest bridge ever built was designed by someone who had never seen one?",
    "build": (
        "He worked from letters alone, drawing what he imagined from second-hand "
        "description. Every engineer who reviewed the plans said the span could "
        "not hold. They were wrong, and the reason why is stranger than the "
        "design itself. The material he chose had never been tested at that "
        "scale, so nobody had the data to say it would fail."
    ),
    "climax": (
        "When the first load rolled across, the deck did not flex at all. The "
        "reviewers had modelled the wrong failure entirely."
    ),
    "cta": "Follow for the story of the letter that started it.",
}

WEAK_TEXT = "This is a video. It is about a thing. The thing happened. Okay."


def _weak_score() -> dict:
    return score_script(story_text=WEAK_TEXT, target_duration=45).model_dump(mode="json")


def _strong_score() -> dict:
    return score_script(sections=STRONG_SECTIONS, target_duration=45).model_dump(
        mode="json"
    )


def _node_result(score_document: dict, **extra) -> dict:
    """The `script.analyze` output shape, as the adapter returns it."""
    payload = {
        "job_id": JOB_ID,
        "provider_id": "deterministic",
        "provider_type": "deterministic",
        "target_duration": 45,
        "score": score_document.get("score"),
        "band": score_document.get("band"),
        "threshold": None,
        "passed": None,
        "issue_ids": [],
        "viral_score": score_document,
    }
    payload.update(extra)
    return {"score": payload}


def _channel_snapshot(**thresholds) -> dict:
    return {
        "name": "Test channel",
        "review_policy": {
            "thresholds": dict(thresholds),
            "max_repairs": 3,
            "escalation": "",
            "human_checkpoints": [],
        },
    }


class IsolatedIssueStore(unittest.TestCase):
    """Redirect the ReviewIssue store at a temp root."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_viral163_")
        self.old_issues_dir = issue_store._issues_dir
        issue_store._issues_dir = os.path.join(self.temp.name, "issues")
        os.makedirs(issue_store._issues_dir, exist_ok=True)

    def tearDown(self):
        issue_store._issues_dir = self.old_issues_dir
        self.temp.cleanup()


# ---------------------------------------------------------------------------
# The threshold itself
# ---------------------------------------------------------------------------


class ThresholdTests(unittest.TestCase):
    """``review_policy.thresholds`` is open by contract; parsing is not."""

    def test_unset_threshold_leaves_the_gate_off(self):
        self.assertIsNone(viral_threshold(None))
        self.assertIsNone(viral_threshold({}))
        self.assertIsNone(viral_threshold({"viral_score_min": None}))

    def test_reads_either_accepted_key(self):
        self.assertEqual(viral_threshold({"viral_score_min": 60}), 60)
        self.assertEqual(viral_threshold({"min_viral_score": 45}), 45)

    def test_coerces_the_string_a_json_form_would_post(self):
        self.assertEqual(viral_threshold({"viral_score_min": "70"}), 70)

    def test_out_of_range_and_garbage_switch_the_gate_off(self):
        # A malformed field must not gate every script against nonsense.
        self.assertIsNone(viral_threshold({"viral_score_min": 500}))
        self.assertIsNone(viral_threshold({"viral_score_min": -1}))
        self.assertIsNone(viral_threshold({"viral_score_min": "high"}))

    def test_reads_the_channel_snapshot_shape(self):
        self.assertEqual(
            threshold_from_snapshot(_channel_snapshot(viral_score_min=65)), 65
        )
        self.assertIsNone(threshold_from_snapshot(_channel_snapshot()))
        self.assertIsNone(threshold_from_snapshot({}))


# ---------------------------------------------------------------------------
# The ReviewIssue a low score raises
# ---------------------------------------------------------------------------


class ReviewIntegrationTests(IsolatedIssueStore):
    """A weak script becomes a durable issue the Repair Router owns."""

    def test_weak_script_below_threshold_drafts_an_issue(self):
        draft = draft_for_score(
            _weak_score(), job_id=JOB_ID, threshold=60, target_node_id=ANALYZE_NODE
        )
        self.assertIsNotNone(draft)
        self.assertEqual(draft.issue_type, "script_defect")
        self.assertEqual(draft.check_id, VIRAL_CHECK_ID)
        self.assertEqual(draft.suggested_action, "re-prompt")
        self.assertEqual(draft.target_node_id, ANALYZE_NODE)
        self.assertEqual(draft.expected, {"min_score": 60})
        self.assertLess(draft.observed["score"], 60)

    def test_strong_script_above_threshold_drafts_nothing(self):
        strong = _strong_score()
        self.assertGreaterEqual(strong["score"], 60)
        self.assertIsNone(
            draft_for_score(strong, job_id=JOB_ID, threshold=60, target_node_id=ANALYZE_NODE)
        )

    def test_the_issue_routes_back_to_script(self):
        """The whole point: a weak hook is the Script node's problem."""
        draft = draft_for_score(
            _weak_score(), job_id=JOB_ID, threshold=60, target_node_id=ANALYZE_NODE
        )
        routing = route_issue(draft)
        self.assertEqual(routing.owner, "script")
        self.assertEqual(routing.stage_key, "script")
        self.assertIn("script.input", routing.node_types)
        self.assertIn("story.generate", routing.node_types)

    def test_routing_does_not_rely_on_the_issue_type_default(self):
        """``check_id`` alone must reach Script, so a future re-reading of
        ``script_defect`` cannot silently orphan the analyzer's findings."""
        routing = route_issue({"check_id": VIRAL_CHECK_ID, "issue_type": None})
        self.assertEqual(routing.owner, "script")
        self.assertEqual(routing.source, "check_id")

    def test_severity_scales_with_the_deficit(self):
        weak = _weak_score()
        # Barely under the bar is not the same finding as far under it.
        near = draft_for_score(weak, job_id=JOB_ID, threshold=weak["score"] + 1)
        far = draft_for_score(weak, job_id=JOB_ID, threshold=min(100, weak["score"] + 40))
        self.assertEqual(near.severity, "low")
        self.assertEqual(far.severity, "high")

    def test_never_critical_so_automatic_mode_keeps_running(self):
        """``should_pause_for_escalation`` stops an unattended Job on critical.
        A soft content judgement is not grounds to do that."""
        for threshold in (10, 40, 70, 100):
            draft = draft_for_score(_weak_score(), job_id=JOB_ID, threshold=threshold)
            if draft is not None:
                self.assertNotEqual(draft.severity, "critical")

    def test_repair_instruction_names_the_weak_dimensions_without_repeating(self):
        draft = draft_for_score(_weak_score(), job_id=JOB_ID, threshold=60)
        instruction = draft.repair_instruction
        self.assertIn("hook", instruction)
        # Bounded by the model, and deduped so one dimension's repeated code
        # does not eat the budget.
        self.assertLessEqual(len(instruction), 500)
        self.assertEqual(instruction.count("hook_missing"), 1)

    def test_reasons_stay_structured_codes_never_free_text(self):
        draft = draft_for_score(_weak_score(), job_id=JOB_ID, threshold=60)
        for entry in draft.observed["weak_dimensions"]:
            for code in entry["reasons"]:
                self.assertRegex(code, r"^[a-z0-9_]+$")

    def test_a_payload_the_frozen_contract_rejects_raises_nothing(self):
        """A scorer bug must not be reported as a defect in the script."""
        self.assertIsNone(draft_for_score({"score": "high"}, job_id=JOB_ID, threshold=60))
        self.assertIsNone(draft_for_score({}, job_id=JOB_ID, threshold=60))
        self.assertIsNone(draft_for_score(None, job_id=JOB_ID, threshold=60))

    def test_gate_persists_the_issue_and_reports_the_verdict(self):
        verdict = gate_script_score(
            _weak_score(), job_id=JOB_ID, target_node_id=ANALYZE_NODE, threshold=60
        )
        self.assertEqual(verdict["threshold"], 60)
        self.assertIs(verdict["passed"], False)
        self.assertEqual(len(verdict["issue_ids"]), 1)

        stored = issue_store.get_issue(verdict["issue_ids"][0])
        self.assertEqual(stored.job_id, JOB_ID)
        self.assertEqual(stored.check_id, VIRAL_CHECK_ID)
        self.assertEqual(stored.status, "open")

    def test_rescoring_reuses_the_open_issue(self):
        """A second pass must not reset attempt_count, or ``max_repairs``
        stops being enforceable and the repair loop never terminates."""
        first = gate_script_score(
            _weak_score(), job_id=JOB_ID, target_node_id=ANALYZE_NODE, threshold=60
        )
        second = gate_script_score(
            _weak_score(), job_id=JOB_ID, target_node_id=ANALYZE_NODE, threshold=60
        )
        self.assertEqual(first["issue_ids"], second["issue_ids"])
        self.assertEqual(len(issue_store.list_issues(job_id=JOB_ID)), 1)

    def test_a_repaired_script_that_now_passes_closes_its_issue(self):
        """Without this the Script stage keeps reporting a defect that the
        repair already fixed — ``emit_review_issues`` only ever reuses."""
        raised = gate_script_score(
            _weak_score(), job_id=JOB_ID, target_node_id=ANALYZE_NODE, threshold=60
        )
        issue_id = raised["issue_ids"][0]

        verdict = gate_script_score(
            _strong_score(), job_id=JOB_ID, target_node_id=ANALYZE_NODE, threshold=60
        )
        self.assertIs(verdict["passed"], True)
        self.assertEqual(issue_store.get_issue(issue_id).status, "resolved")
        self.assertEqual(issue_store.list_issues(job_id=JOB_ID, open_only=True), [])

    def test_an_unreadable_payload_is_unmeasured_and_closes_nothing(self):
        """A scorer bug must not clear a finding the script really earned."""
        raised = gate_script_score(
            _weak_score(), job_id=JOB_ID, target_node_id=ANALYZE_NODE, threshold=60
        )
        issue_id = raised["issue_ids"][0]

        verdict = gate_script_score(
            {"score": "not a number"},
            job_id=JOB_ID,
            target_node_id=ANALYZE_NODE,
            threshold=60,
        )
        self.assertIsNone(verdict["passed"])
        self.assertEqual(verdict["issue_ids"], [])
        self.assertEqual(issue_store.get_issue(issue_id).status, "open")

    def test_no_threshold_means_not_measured_rather_than_passed(self):
        verdict = gate_script_score(
            _weak_score(), job_id=JOB_ID, target_node_id=ANALYZE_NODE, threshold=None
        )
        self.assertIsNone(verdict["threshold"])
        self.assertIsNone(verdict["passed"])
        self.assertEqual(verdict["issue_ids"], [])
        self.assertEqual(issue_store.list_issues(job_id=JOB_ID), [])

    def test_a_run_with_no_job_writes_nothing(self):
        """ReviewIssues are Job-keyed; a canvas run has no Job to key against."""
        verdict = gate_script_score(_weak_score(), job_id="", threshold=60)
        self.assertEqual(verdict["issue_ids"], [])
        self.assertEqual(issue_store.list_issues(job_id=JOB_ID), [])


# ---------------------------------------------------------------------------
# Surviving the execution record
# ---------------------------------------------------------------------------


class ScoreSnapshotTests(unittest.TestCase):
    """The reason a dedicated record field exists at all."""

    def test_outputs_summary_destroys_the_breakdown(self):
        """This is the failure the snapshot answers. If ``_summarize`` ever
        starts preserving the payload, delete the field — do not keep both."""
        summarized = _summarize(_node_result(_weak_score()))
        score = summarized["score"]
        # The band survives only as a character count …
        self.assertEqual(set(score["band"]), {"chars"})
        # … and every dimension is flattened past the depth limit, so not one
        # id, sub-score or reason code is left to render.
        dimensions = score["viral_score"]["dimensions"]
        self.assertEqual(dimensions["count"], 6)
        self.assertEqual(dimensions["items"], [{"type": "dict"}] * 3)

    def test_snapshot_preserves_band_and_every_dimension(self):
        snapshot = score_snapshot_from_result(
            _node_result(_weak_score()), node_type=SCORE_NODE_TYPE
        )
        self.assertEqual(snapshot["band"], "poor")
        self.assertEqual(
            [d["id"] for d in snapshot["dimensions"]],
            ["hook", "opening_line", "pacing", "open_loops", "cta", "balance"],
        )
        for dimension in snapshot["dimensions"]:
            for reason in dimension["reasons"]:
                self.assertIn(reason["impact"], {"positive", "negative"})

    def test_only_the_analyzer_produces_one(self):
        result = _node_result(_weak_score())
        self.assertIsNone(score_snapshot_from_result(result, node_type="tts.generate"))
        self.assertIsNone(score_snapshot_from_result(result, node_type=None))

    def test_gate_fields_are_present_together_or_not_at_all(self):
        ungated = score_snapshot_from_result(
            _node_result(_weak_score()), node_type=SCORE_NODE_TYPE
        )
        self.assertNotIn("threshold", ungated)
        self.assertNotIn("passed", ungated)

        gated = score_snapshot_from_result(
            _node_result(_weak_score(), threshold=60, passed=False),
            node_type=SCORE_NODE_TYPE,
        )
        self.assertEqual(gated["threshold"], 60)
        self.assertIs(gated["passed"], False)

    def test_a_result_with_no_score_records_nothing(self):
        """An empty field beats a zero the panel would render as a verdict."""
        self.assertIsNone(
            score_snapshot_from_result({"score": {}}, node_type=SCORE_NODE_TYPE)
        )
        self.assertIsNone(
            score_snapshot_from_result({}, node_type=SCORE_NODE_TYPE)
        )


# ---------------------------------------------------------------------------
# Reaching the Production panel
# ---------------------------------------------------------------------------


class StageProjectionTests(unittest.TestCase):
    """``stage.score`` is what the Script panel renders."""

    def _execution(self, **record_kwargs) -> dict:
        return {
            "nodes": {
                ANALYZE_NODE: NodeExecutionRecord(
                    status="succeeded", **record_kwargs
                ).__dict__,
            }
        }

    def test_score_lands_on_the_script_stage(self):
        snapshot = score_snapshot_from_result(
            _node_result(_weak_score(), threshold=60, passed=False),
            node_type=SCORE_NODE_TYPE,
        )
        projection = project_stages(
            full_video_template(), execution=self._execution(score=snapshot)
        )
        stages = {stage["key"]: stage for stage in projection["stages"]}
        self.assertEqual(stages["script"]["score"]["score"], snapshot["score"])
        self.assertEqual(stages["script"]["score"]["band"], "poor")
        self.assertIs(stages["script"]["score"]["passed"], False)

    def test_every_other_stage_carries_a_typed_none(self):
        """The panel branches on a value, never on a missing key."""
        projection = project_stages(full_video_template())
        for stage in projection["stages"]:
            self.assertIn("score", stage)
            self.assertIsNone(stage["score"])

    def test_an_unrun_analyzer_leaves_the_stage_score_empty(self):
        projection = project_stages(full_video_template(), execution=self._execution())
        stages = {stage["key"]: stage for stage in projection["stages"]}
        self.assertIsNone(stages["script"]["score"])


class OrderingTests(unittest.TestCase):
    """"Before TTS runs" is a scheduling claim, not a layout one."""

    def test_the_analyzer_is_scheduled_before_tts(self):
        template = full_video_template()
        order = deterministic_order(template)
        self.assertLess(order.index(ANALYZE_NODE), order.index("n_tts"))

    def test_the_analyzer_sits_on_the_script_stage(self):
        projection = project_stages(full_video_template())
        stages = {stage["key"]: stage for stage in projection["stages"]}
        self.assertIn(ANALYZE_NODE, stages["script"]["node_ids"])
        for key, stage in stages.items():
            if key != "script":
                self.assertNotIn(ANALYZE_NODE, stage["node_ids"])


# ---------------------------------------------------------------------------
# The Assisted-mode pause
# ---------------------------------------------------------------------------


class AssistedCheckpointTests(unittest.TestCase):
    """A Channel that asked for a score bar asked to see the misses."""

    def test_assisted_gains_the_script_checkpoint_when_a_threshold_is_set(self):
        refs = configured_checkpoint_refs(
            "assisted", human_checkpoints=["review"], script_gate=True
        )
        self.assertEqual(refs[0], "script")

    def test_assisted_without_a_threshold_is_unchanged(self):
        self.assertEqual(
            configured_checkpoint_refs("assisted", human_checkpoints=["review"]),
            ["review"],
        )
        self.assertEqual(configured_checkpoint_refs("assisted"), [])

    def test_a_checkpoint_list_that_already_covers_script_is_not_duplicated(self):
        for ref in ("script", "script_approval", "story", "script.input"):
            refs = configured_checkpoint_refs(
                "assisted", human_checkpoints=[ref], script_gate=True
            )
            self.assertEqual(refs, [ref], msg=ref)

    def test_automatic_never_gains_a_pause(self):
        """Unattended by definition — a soft judgement cannot stop it."""
        self.assertEqual(
            configured_checkpoint_refs("automatic", human_checkpoints=[], script_gate=True),
            [],
        )

    def test_manual_already_stops_at_script(self):
        refs = configured_checkpoint_refs("manual", script_gate=True)
        self.assertIn("script", refs)

    def test_an_assisted_job_pauses_at_the_script_node(self):
        """End to end: Channel threshold → policy → resolved graph node id."""
        template = full_video_template()
        job = {
            "execution_mode": "assisted",
            "channel_snapshot": _channel_snapshot(viral_score_min=60),
        }
        policy = resolve_execution_policy(job, template)
        self.assertEqual(policy.mode, "assisted")
        self.assertIn("script", policy.checkpoint_refs)
        self.assertIn("n_script", policy.checkpoint_node_ids)

    def test_the_same_job_without_a_threshold_runs_straight_through(self):
        template = full_video_template()
        job = {
            "execution_mode": "assisted",
            "channel_snapshot": _channel_snapshot(),
        }
        policy = resolve_execution_policy(job, template)
        self.assertEqual(policy.checkpoint_node_ids, ())

    def test_the_resolved_checkpoint_is_the_script_node_not_the_analyzer(self):
        """Approving the *score* is meaningless; the script is what a human
        accepts or rejects."""
        node_ids = resolve_checkpoint_node_ids(full_video_template(), ["script"])
        self.assertEqual(node_ids, ["n_script"])


# ---------------------------------------------------------------------------
# The done-when clause, end to end
# ---------------------------------------------------------------------------


class EndToEndTests(unittest.TestCase):
    """Nothing in the chain stubbed out.

    Every other test here holds one link. This one runs the real
    ``script.analyze`` adapter inside the real Full Video graph against a real
    Job whose Channel sets a real threshold, and asserts what the step
    promises: the score is on the Script stage and the issue it raised belongs
    to Script — both before TTS has produced anything.
    """

    def setUp(self):
        from scriptase.channels import store as channel_store
        from scriptase.jobs import store as job_store

        self.channel_store = channel_store
        self.job_store = job_store
        self.temp = tempfile.TemporaryDirectory(prefix="scriptase_viral163_e2e_")
        root = self.temp.name

        self.old = {
            "issues": issue_store._issues_dir,
            "jobs": job_store._jobs_dir,
            "jobs_trash": job_store._trash_dir,
            "channels": channel_store._channels_dir,
            "channels_trash": channel_store._trash_dir,
        }
        issue_store._issues_dir = os.path.join(root, "issues")
        job_store._jobs_dir = os.path.join(root, "jobs")
        job_store._trash_dir = os.path.join(root, "trash", "jobs")
        channel_store._channels_dir = os.path.join(root, "channels")
        channel_store._trash_dir = os.path.join(root, "trash", "channels")
        for path in (
            issue_store._issues_dir,
            job_store._jobs_dir,
            channel_store._channels_dir,
        ):
            os.makedirs(path, exist_ok=True)

    def tearDown(self):
        issue_store._issues_dir = self.old["issues"]
        self.job_store._jobs_dir = self.old["jobs"]
        self.job_store._trash_dir = self.old["jobs_trash"]
        self.channel_store._channels_dir = self.old["channels"]
        self.channel_store._trash_dir = self.old["channels_trash"]
        self.temp.cleanup()

    def _job_with_threshold(self, minimum: int) -> str:
        draft = self.channel_store.default_draft(name="Virality channel")
        draft["review_policy"]["thresholds"] = {"viral_score_min": minimum}
        channel = self.channel_store.create_channel(draft)
        job = self.job_store.create_job(
            self.job_store.default_draft(
                channel_id=channel.id,
                execution_mode="assisted",
                source={"mode": "paste", "pasted_script": WEAK_TEXT},
            )
        )
        return job.id

    def _run(self, job_id: str):
        """Run the graph for real, stubbing only the nodes that would spend."""
        from copy import deepcopy

        from scriptase.engine.adapters import viral as viral_adapter
        from scriptase.engine.registry import get_node_type
        from scriptase.engine.scheduler import WorkflowScheduler

        draft = deepcopy(full_video_template())
        draft.pop("template_id", None)
        draft["workflow_id"] = "wf_VIR163"
        draft["created_at"] = "2026-08-16T00:00:00Z"
        draft["updated_at"] = "2026-08-16T00:00:00Z"
        draft["extensions"] = {"job_id": job_id}
        for node in draft["nodes"]:
            if node["type"] == "script.input":
                node["configuration"]["text"] = WEAK_TEXT

        def resolver(node):
            if node["type"] == SCORE_NODE_TYPE:
                return viral_adapter.analyze
            if node["type"] == "script.input":
                return lambda inputs, config, context: {
                    "script": config.get("text") or "",
                    "control": {"ok": True},
                }

            def execute(inputs, config, context):
                return {
                    port["id"]: ({"ok": True} if port["type"] == "control" else {})
                    for port in get_node_type(node["type"])["outputs"]
                }

            return execute

        with tempfile.TemporaryDirectory(prefix="sts_16_3_") as output_root:
            scheduler = WorkflowScheduler(
                draft,
                project_id="pm_VIR163",
                output_dir=output_root,
                executor_resolver=resolver,
            )
            return draft, scheduler.run()

    def test_a_weak_script_surfaces_a_low_score_before_tts_runs(self):
        job_id = self._job_with_threshold(60)
        workflow, record = self._run(job_id)

        self.assertEqual(record.node_statuses[ANALYZE_NODE], "succeeded")

        # The verdict survived the execution record …
        execution = record.execution_record
        snapshot = execution["nodes"][ANALYZE_NODE]["score"]
        self.assertIsNotNone(snapshot)
        self.assertLess(snapshot["score"], 60)
        self.assertEqual(snapshot["threshold"], 60)
        self.assertIs(snapshot["passed"], False)
        self.assertEqual(len(snapshot["dimensions"]), 6)

        # … and reaches the Script stage the panel renders.
        projection = project_stages(workflow, execution=execution, job_id=job_id)
        script_stage = next(s for s in projection["stages"] if s["key"] == "script")
        self.assertEqual(script_stage["score"]["score"], snapshot["score"])
        self.assertEqual(script_stage["score"]["band"], snapshot["band"])

        # The issue is on the Script stage, and it is the analyzer's.
        self.assertEqual(len(script_stage["issues"]), 1)
        issue = issue_store.get_issue(script_stage["issues"][0])
        self.assertEqual(issue.check_id, VIRAL_CHECK_ID)
        self.assertEqual(issue.job_id, job_id)
        self.assertEqual(route_issue(issue).owner, "script")

        # "Before TTS runs": the analyzer is scheduled ahead of it, so the
        # verdict is on record before the first expensive node is reached.
        order = deterministic_order(workflow)
        self.assertLess(order.index(ANALYZE_NODE), order.index("n_tts"))

    def test_a_script_that_clears_the_bar_raises_nothing(self):
        # 0 is a real bar that everything clears — proving the gate stays
        # quiet when it passes, not merely when the key is unset.
        job_id = self._job_with_threshold(0)
        _workflow, record = self._run(job_id)

        snapshot = record.execution_record["nodes"][ANALYZE_NODE]["score"]
        self.assertEqual(snapshot["threshold"], 0)
        self.assertIs(snapshot["passed"], True)
        self.assertEqual(issue_store.list_issues(job_id=job_id), [])

    def test_an_assisted_job_with_a_threshold_pauses_at_script(self):
        from scriptase.jobs.execution_modes import apply_execution_policy_to_workflow

        job_id = self._job_with_threshold(60)
        job = self.job_store.get_job(job_id)
        prepared = apply_execution_policy_to_workflow(full_video_template(), job)
        self.assertEqual(prepared["extensions"]["approval_checkpoints"], ["n_script"])
        self.assertEqual(prepared["extensions"]["execution_mode"], "assisted")


if __name__ == "__main__":
    unittest.main()
