"""Step 9.3 — Cost accounting and reporting.

Done when: a completed Job reports accumulated generation count and cost per
stage and per provider instance, reconciling with its provenance records.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from scriptase.engine.cost_snapshot import cost_snapshot_from_result
from scriptase.jobs.cost import (
    CostRecord,
    accumulate_spend,
    budget_spent_from_execution,
    build_channel_cost_report,
    build_cost_report,
    convert_amount,
    extract_cost_records_from_execution,
)
from scriptase.jobs.models import BudgetSpent, Job, JobSource
from scriptase.providers.boundary import build_provenance
from scriptase.providers.invocation import build_invocation
from scriptase.providers.results import (
    Provenance,
    ProviderResult,
    extract_cost,
)


def _job(
    *,
    job_id: str = "job_COST01",
    channel_id: str = "ch_COST01",
    generations: int = 0,
    cost: float = 0.0,
    currency: str = "USD",
    max_cost: float | None = None,
    max_generations: int | None = None,
    execution_id: str | None = "exec_cost_1",
) -> Job:
    return Job(
        id=job_id,
        channel_id=channel_id,
        channel_snapshot={
            "id": channel_id,
            "name": "Cost Channel",
            "budget": {
                "max_generations": max_generations,
                "max_cost": max_cost,
                "currency": currency,
            },
        },
        workflow_id="wf_COST01",
        execution_mode="automatic",
        source=JobSource(mode="topic", topic="cost accounting"),
        status="completed",
        budget_spent=BudgetSpent(generations=generations, cost=cost),
        execution_id=execution_id,
        created_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:05:00+00:00",
    )


def _workflow() -> dict:
    return {
        "workflow_id": "wf_COST01",
        "name": "Cost workflow",
        "nodes": [
            {"id": "n_script", "type": "story.generate", "name": "Script"},
            {"id": "n_tts", "type": "tts.generate", "name": "Voice"},
            {"id": "n_img", "type": "storyboard.generate", "name": "Images"},
            {"id": "n_music", "type": "music.select", "name": "Music"},
        ],
        "edges": [
            {
                "id": "e1",
                "source_node": "n_script",
                "source_port": "script",
                "target_node": "n_tts",
                "target_port": "script",
            },
            {
                "id": "e2",
                "source_node": "n_tts",
                "source_port": "audio",
                "target_node": "n_img",
                "target_port": "audio",
            },
        ],
    }


def _execution_with_costs() -> dict:
    return {
        "execution_id": "exec_cost_1",
        "workflow_id": "wf_COST01",
        "status": "succeeded",
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:05:00+00:00",
        "workflow_snapshot": _workflow(),
        "nodes": {
            "n_script": {
                "status": "succeeded",
                "cache": {"hit": False},
                "cost": {
                    "amount": "0.02",
                    "currency": "USD",
                    "unit_count": 500,
                    "unit": "tokens",
                    "provider_instance_id": "script_main",
                    "provider_id": "openrouter",
                    "generations": 1,
                    "cache_hit": False,
                    "invocation_id": "inv_script",
                },
            },
            "n_tts": {
                "status": "succeeded",
                "cache": {"hit": False},
                "cost": {
                    "amount": "0.10",
                    "currency": "USD",
                    "unit_count": 1,
                    "unit": "audio",
                    "provider_instance_id": "tts_main",
                    "provider_id": "inworld",
                    "generations": 1,
                    "cache_hit": False,
                    "invocation_id": "inv_tts",
                },
            },
            "n_img": {
                "status": "succeeded",
                "cache": {"hit": False},
                "cost": {
                    "amount": "0.40",
                    "currency": "EUR",
                    "unit_count": 4,
                    "unit": "images",
                    "provider_instance_id": "img_main",
                    "provider_id": "wavespeed_direct",
                    "generations": 1,
                    "cache_hit": False,
                    "invocation_id": "inv_img",
                },
            },
            "n_music": {
                "status": "succeeded",
                "cache": {"hit": False},
                # Local service — no cost snapshot.
            },
        },
    }


class ExtractCostTests(unittest.TestCase):
    def test_extract_cost_from_metadata(self):
        block = extract_cost(
            metadata={
                "cost": {
                    "amount": "1.25",
                    "currency": "eur",
                    "unit_count": 3,
                    "unit": "images",
                }
            }
        )
        self.assertIsNotNone(block)
        self.assertEqual(block["amount"], "1.25")
        self.assertEqual(block["currency"], "EUR")
        self.assertEqual(block["unit_count"], 3.0)
        self.assertEqual(block["unit"], "images")

    def test_extract_cost_never_invents(self):
        self.assertIsNone(extract_cost(metadata={}))
        self.assertIsNone(extract_cost(metadata={"cost": {"currency": "USD"}}))

    def test_build_provenance_harvests_cost(self):
        invocation = build_invocation(
            None,
            domain="image",
            provider_id="wavespeed_direct",
            project_id="pm_COST1",
            settings={},
            options={},
        )
        result = ProviderResult(
            metadata={
                "cost": {
                    "amount": 0.05,
                    "currency": "USD",
                    "unit_count": 1,
                    "unit": "images",
                }
            }
        )
        provenance = build_provenance(
            invocation,
            result=result,
            provider_instance_id="img_main",
        )
        self.assertIsNotNone(provenance.cost)
        self.assertEqual(provenance.cost["currency"], "USD")
        self.assertEqual(float(provenance.cost["amount"]), 0.05)


class CostSnapshotTests(unittest.TestCase):
    def test_snapshot_from_nested_provenance(self):
        result = {
            "control": {"ok": True},
            "media": {
                "provenance": {
                    "invocation_id": "inv_1",
                    "provider_id": "wavespeed_direct",
                    "provider_instance_id": "img_main",
                    "cache_hit": False,
                    "cost": {
                        "amount": "0.12",
                        "currency": "USD",
                        "unit_count": 1,
                        "unit": "images",
                    },
                }
            },
        }
        snap = cost_snapshot_from_result(
            result, cache_hit=False, is_provider_node=True
        )
        self.assertIsNotNone(snap)
        self.assertEqual(snap["amount"], "0.12")
        self.assertEqual(snap["provider_instance_id"], "img_main")
        self.assertEqual(snap["generations"], 1)

    def test_cache_hit_zero_generations(self):
        result = {
            "provenance": {
                "provider_instance_id": "tts_main",
                "provider_id": "inworld",
                "cache_hit": True,
                "cost": {"amount": "0.10", "currency": "USD"},
            }
        }
        snap = cost_snapshot_from_result(
            result, cache_hit=True, is_provider_node=True
        )
        self.assertEqual(snap["generations"], 0)
        self.assertTrue(snap["cache_hit"])


class CostRecordExtractionTests(unittest.TestCase):
    def test_extracts_per_provider_node(self):
        job = _job()
        execution = _execution_with_costs()
        records = extract_cost_records_from_execution(job, execution)
        self.assertEqual(len(records), 3)
        instances = {r.provider_instance_id for r in records}
        self.assertEqual(instances, {"script_main", "tts_main", "img_main"})

    def test_stage_assignment(self):
        job = _job()
        records = extract_cost_records_from_execution(
            job, _execution_with_costs()
        )
        by_node = {r.node_id: r.stage_key for r in records}
        self.assertEqual(by_node["n_script"], "script")
        self.assertEqual(by_node["n_tts"], "voice")
        self.assertEqual(by_node["n_img"], "images")

    def test_legacy_provider_node_without_snapshot_counts_generation(self):
        job = _job()
        execution = {
            "execution_id": "exec_legacy",
            "workflow_snapshot": _workflow(),
            "nodes": {
                "n_tts": {
                    "status": "succeeded",
                    "cache": {"hit": False},
                }
            },
        }
        records = extract_cost_records_from_execution(job, execution)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].generations, 1)
        self.assertIsNone(records[0].amount)


class AccumulateAndReportTests(unittest.TestCase):
    def test_accumulate_converts_currency_at_report_time(self):
        records = [
            CostRecord(
                job_id="job_COST01",
                node_id="a",
                provider_instance_id="img_main",
                amount="1.00",
                currency="EUR",
                generations=1,
            ),
            CostRecord(
                job_id="job_COST01",
                node_id="b",
                provider_instance_id="tts_main",
                amount="0.50",
                currency="USD",
                generations=1,
            ),
        ]
        # EUR 1.00 * 1.08 + USD 0.50 = 1.58
        spent = accumulate_spend(records, currency="USD")
        self.assertEqual(spent.generations, 2)
        self.assertAlmostEqual(spent.cost, 1.58, places=4)

    def test_convert_same_currency_is_identity(self):
        self.assertEqual(convert_amount(2.5, from_currency="USD", to_currency="USD"), 2.5)

    def test_report_by_stage_and_instance_reconciles(self):
        # Pre-compute the expected converted total so budget_spent matches.
        records_preview = extract_cost_records_from_execution(
            _job(), _execution_with_costs()
        )
        spent = accumulate_spend(records_preview, currency="USD")
        job = _job(generations=spent.generations, cost=spent.cost)
        execution = _execution_with_costs()

        report = build_cost_report(job, execution=execution)
        self.assertEqual(report["totals"]["generations"], 3)
        # 0.02 + 0.10 + 0.40*1.08 = 0.552
        self.assertAlmostEqual(report["totals"]["cost"], 0.552, places=4)

        self.assertIn("script", report["by_stage"])
        self.assertIn("voice", report["by_stage"])
        self.assertIn("images", report["by_stage"])
        self.assertEqual(report["by_stage"]["script"]["generations"], 1)
        self.assertEqual(report["by_stage"]["voice"]["generations"], 1)
        self.assertEqual(report["by_stage"]["images"]["generations"], 1)

        self.assertIn("script_main", report["by_provider_instance"])
        self.assertIn("tts_main", report["by_provider_instance"])
        self.assertIn("img_main", report["by_provider_instance"])

        self.assertTrue(report["reconcile"]["ok"])
        self.assertEqual(len(report["records"]), 3)

    def test_report_flags_unreconciled_when_stored_differs(self):
        job = _job(generations=0, cost=0.0)
        report = build_cost_report(job, execution=_execution_with_costs())
        self.assertFalse(report["reconcile"]["ok"])
        self.assertEqual(report["reconcile"]["computed"]["generations"], 3)
        self.assertEqual(report["reconcile"]["stored"]["generations"], 0)

    def test_channel_rollup(self):
        jobs = [
            _job(job_id="job_COST01", generations=2, cost=1.0),
            _job(job_id="job_COST02", generations=3, cost=2.5),
        ]
        # Second job needs a valid id shape.
        jobs[1] = _job(job_id="job_COST02", generations=3, cost=2.5)
        report = build_channel_cost_report("ch_COST01", jobs)
        self.assertEqual(report["totals"]["generations"], 5)
        self.assertAlmostEqual(report["totals"]["cost"], 3.5)
        self.assertEqual(report["totals"]["job_count"], 2)


class SyncBudgetSpentTests(unittest.TestCase):
    def test_budget_spent_from_execution(self):
        job = _job(generations=0, cost=0.0)
        spent, records = budget_spent_from_execution(
            job, _execution_with_costs()
        )
        self.assertEqual(len(records), 3)
        self.assertEqual(spent.generations, 3)
        self.assertGreater(spent.cost, 0)

    def test_apply_job_spend_persists(self):
        from scriptase.jobs import store as job_store
        from scriptase.jobs.cost import apply_job_spend_from_execution
        from scriptase.channels import store as channel_store

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = os.path.join(tmp, "jobs")
            channels_dir = os.path.join(tmp, "channels")
            os.makedirs(jobs_dir)
            os.makedirs(channels_dir)
            with mock.patch.object(job_store, "_jobs_dir", jobs_dir), mock.patch.object(
                job_store, "_trash_dir", os.path.join(tmp, "trash")
            ), mock.patch.object(
                channel_store, "_channels_dir", channels_dir
            ), mock.patch.object(
                channel_store, "_trash_dir", os.path.join(tmp, "ctrash")
            ):
                channel = channel_store.create_channel(
                    {"name": "Cost Ch", "budget": {"currency": "USD"}}
                )
                job = job_store.create_job(
                    {
                        "channel_id": channel.id,
                        "workflow_id": "wf_COST01",
                        "execution_mode": "manual",
                        "source": {"mode": "topic", "topic": "x"},
                    }
                )
                job = job_store.update_job(
                    job.id,
                    status="completed",
                    execution_id="exec_cost_1",
                    completed_at="2026-01-01T00:05:00+00:00",
                    allow_terminal=True,
                )
                updated, records = apply_job_spend_from_execution(
                    job.id,
                    _execution_with_costs(),
                    allow_terminal=True,
                )
                self.assertEqual(updated.budget_spent.generations, 3)
                self.assertAlmostEqual(updated.budget_spent.cost, 0.552, places=4)
                self.assertEqual(len(records), 3)

                # Idempotent re-apply does not double-count.
                updated2, _ = apply_job_spend_from_execution(
                    job.id,
                    _execution_with_costs(),
                    allow_terminal=True,
                )
                self.assertEqual(updated2.budget_spent.generations, 3)


class CostApiTests(unittest.TestCase):
    def test_job_cost_endpoint(self):
        from app import create_app
        from scriptase.jobs import store as job_store
        from scriptase.channels import store as channel_store
        from scriptase.jobs.cost import apply_job_spend_from_execution
        from scriptase.engine import persistence as eng_persist

        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = os.path.join(tmp, "jobs")
            channels_dir = os.path.join(tmp, "channels")
            exec_dir = os.path.join(tmp, "executions")
            os.makedirs(jobs_dir)
            os.makedirs(channels_dir)
            os.makedirs(exec_dir)

            with mock.patch.object(job_store, "_jobs_dir", jobs_dir), mock.patch.object(
                job_store, "_trash_dir", os.path.join(tmp, "trash")
            ), mock.patch.object(
                channel_store, "_channels_dir", channels_dir
            ), mock.patch.object(
                channel_store, "_trash_dir", os.path.join(tmp, "ctrash")
            ):
                app = create_app(discover_providers=False, start_triggers=False)
                client = app.test_client()

                channel = channel_store.create_channel(
                    {"name": "API Cost", "budget": {"currency": "USD"}}
                )
                job = job_store.create_job(
                    {
                        "channel_id": channel.id,
                        "workflow_id": "wf_COST01",
                        "execution_mode": "manual",
                        "source": {"mode": "topic", "topic": "api"},
                    }
                )
                execution = _execution_with_costs()
                execution["execution_id"] = "exec_api_1"

                # Persist a minimal execution document if the store expects one.
                job = job_store.update_job(
                    job.id,
                    status="completed",
                    execution_id="exec_api_1",
                    completed_at="2026-01-01T00:05:00+00:00",
                    allow_terminal=True,
                )
                apply_job_spend_from_execution(
                    job.id, execution, allow_terminal=True
                )

                with mock.patch(
                    "scriptase.jobs.routes.load_execution",
                    return_value=execution,
                ), mock.patch(
                    "scriptase.jobs.orchestration._load_execution_record",
                    return_value=execution,
                ):
                    resp = client.get(f"/api/jobs/{job.id}/cost")
                self.assertEqual(resp.status_code, 200)
                body = resp.get_json()
                self.assertIn("cost", body)
                cost = body["cost"]
                self.assertEqual(cost["totals"]["generations"], 3)
                self.assertTrue(cost["reconcile"]["ok"])
                self.assertIn("by_stage", cost)
                self.assertIn("by_provider_instance", cost)

                # Channel rollup
                ch_resp = client.get(f"/api/channels/{channel.id}/cost")
                self.assertEqual(ch_resp.status_code, 200)
                ch_body = ch_resp.get_json()
                self.assertEqual(ch_body["cost"]["totals"]["generations"], 3)


if __name__ == "__main__":
    unittest.main()
