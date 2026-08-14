"""Cost accounting and reporting (step 9.3 / contracts.md §12.1).

Enforcement landed in 3.5 (pre-flight). This module is the accounting half:

* Lift :class:`CostRecord` rows from execution node cost snapshots (and
  therefore from provenance stamped at generation time).
* Accumulate generation count and cost onto ``Job.budget_spent``.
* Report totals, per-stage, and per-provider-instance breakdowns.
* Convert currencies only at report time — never on ingest.

A completed Job's report reconciles with its provenance-backed cost records:
``budget_spent`` equals the sum of those records after sync.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scriptase.jobs.budget import PROVIDER_NODE_TYPES, budget_from_job, spent_from_job
from scriptase.jobs.models import BudgetSpent, Job
from scriptase.jobs.stage_projection import (
    PRIMARY_STAGE_BY_TYPE,
    STAGE_KEYS,
    assign_nodes_to_stages,
)
from scriptase.providers.results import extract_cost
from scriptase.shared.io_utils import now_iso

# Default FX rates expressed as "units of report currency per 1 unit of code".
# Used only at report time. Callers may supply their own rates map.
DEFAULT_REPORT_CURRENCY = "USD"
DEFAULT_FX_RATES: dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "JPY": 0.0067,
    "CNY": 0.14,
    "AUD": 0.65,
    "CAD": 0.73,
}


# ---------------------------------------------------------------------------
# CostRecord (contracts.md §12.1)
# ---------------------------------------------------------------------------


class CostRecord(BaseModel):
    """One generation's cost as recorded from provenance (contracts.md §12.1)."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = ""
    execution_id: str = ""
    node_id: str = ""
    unit_index: int | None = None
    provider_instance_id: str = ""
    provider_id: str = ""
    amount: str | None = None  # decimal as reported; null when provider silent
    currency: str = "USD"
    unit_count: float | None = None
    unit: str | None = None
    generations: int = Field(default=1, ge=0)
    stage_key: str | None = None
    cache_hit: bool = False
    invocation_id: str = ""
    recorded_at: str = ""

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, value: Any) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value).strip()
        if not text:
            return None
        try:
            float(text)
        except (TypeError, ValueError):
            return None
        return text

    @field_validator("currency", mode="before")
    @classmethod
    def _currency(cls, value: Any) -> str:
        text = str(value or "USD").strip().upper() or "USD"
        return text[:8]

    @field_validator("generations", mode="before")
    @classmethod
    def _generations(cls, value: Any) -> int:
        if value is None:
            return 1
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 1

    def amount_float(self) -> float:
        if self.amount is None:
            return 0.0
        try:
            return float(self.amount)
        except (TypeError, ValueError):
            return 0.0

    def to_public(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Currency conversion (report time only)
# ---------------------------------------------------------------------------


def convert_amount(
    amount: float,
    *,
    from_currency: str,
    to_currency: str = DEFAULT_REPORT_CURRENCY,
    rates: Mapping[str, float] | None = None,
) -> float:
    """Convert *amount* from *from_currency* into *to_currency* using *rates*.

    Rates are ``units of USD (or report base) per 1 unit of code``. Missing
    currencies are treated as 1.0 when codes match, else left unconverted
    (returned as-is) so a report never invents a rate.
    """
    src = (from_currency or DEFAULT_REPORT_CURRENCY).strip().upper()
    dst = (to_currency or DEFAULT_REPORT_CURRENCY).strip().upper()
    if src == dst:
        return float(amount)
    table = dict(DEFAULT_FX_RATES)
    if rates:
        for key, value in rates.items():
            try:
                table[str(key).strip().upper()] = float(value)
            except (TypeError, ValueError):
                continue
    src_rate = table.get(src)
    dst_rate = table.get(dst)
    if src_rate is None or dst_rate is None or src_rate == 0:
        # Unknown pair: do not invent. Caller sees the raw amount.
        return float(amount)
    # Convert src → base (USD) → dst: amount * src_rate / dst_rate
    # With rates as "USD per 1 unit", EUR 1.08 means 1 EUR = 1.08 USD.
    return float(amount) * float(src_rate) / float(dst_rate)


def amount_in_currency(
    record: CostRecord,
    *,
    currency: str = DEFAULT_REPORT_CURRENCY,
    rates: Mapping[str, float] | None = None,
) -> float:
    return convert_amount(
        record.amount_float(),
        from_currency=record.currency,
        to_currency=currency,
        rates=rates,
    )


# ---------------------------------------------------------------------------
# Extraction from execution records
# ---------------------------------------------------------------------------


def _stage_for_node(
    node_id: str,
    node_type: str,
    *,
    assignment: Mapping[str, list[str]] | None = None,
) -> str | None:
    if assignment:
        for stage_key, members in assignment.items():
            if node_id in members:
                return stage_key
    return PRIMARY_STAGE_BY_TYPE.get(node_type)


def _nodes_by_id(workflow: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(workflow, Mapping):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for node in workflow.get("nodes") or []:
        if isinstance(node, Mapping) and node.get("id"):
            out[str(node["id"])] = dict(node)
    return out


def cost_record_from_snapshot(
    snapshot: Mapping[str, Any],
    *,
    job_id: str = "",
    execution_id: str = "",
    node_id: str = "",
    stage_key: str | None = None,
    recorded_at: str | None = None,
) -> CostRecord:
    """Build a CostRecord from a node cost snapshot (or provenance cost block)."""
    amount = snapshot.get("amount")
    currency = snapshot.get("currency") or "USD"
    # Accept a nested cost block if present.
    nested = snapshot.get("cost")
    if isinstance(nested, Mapping) and amount is None:
        block = extract_cost(cost=nested)
        if block:
            amount = block.get("amount")
            currency = block.get("currency") or currency
            unit_count = block.get("unit_count")
            unit = block.get("unit")
        else:
            unit_count = snapshot.get("unit_count")
            unit = snapshot.get("unit")
    else:
        unit_count = snapshot.get("unit_count")
        unit = snapshot.get("unit")

    generations = snapshot.get("generations")
    if generations is None:
        generations = 0 if snapshot.get("cache_hit") else 1

    return CostRecord(
        job_id=job_id,
        execution_id=execution_id,
        node_id=node_id,
        unit_index=snapshot.get("unit_index"),
        provider_instance_id=str(
            snapshot.get("provider_instance_id") or ""
        ).strip(),
        provider_id=str(snapshot.get("provider_id") or "").strip(),
        amount=amount,
        currency=str(currency or "USD"),
        unit_count=unit_count if unit_count is not None else None,
        unit=str(unit).strip() if unit not in (None, "") else None,
        generations=int(generations or 0),
        stage_key=stage_key,
        cache_hit=bool(snapshot.get("cache_hit")),
        invocation_id=str(snapshot.get("invocation_id") or "").strip(),
        recorded_at=recorded_at or now_iso(),
    )


def extract_cost_records_from_execution(
    job: Job | Mapping[str, Any],
    execution: Mapping[str, Any] | None,
    *,
    workflow: Mapping[str, Any] | None = None,
) -> list[CostRecord]:
    """Lift CostRecords from an execution's node cost snapshots / provenance.

    Only succeeded (or partially succeeded) nodes with a cost snapshot or a
    provider node type contribute. Cache hits appear with ``generations=0``.
    """
    if not isinstance(execution, Mapping):
        return []

    job_id = job.id if isinstance(job, Job) else str((job or {}).get("id") or "")
    execution_id = str(execution.get("execution_id") or "")
    workflow_doc = workflow
    if workflow_doc is None:
        snap = execution.get("workflow_snapshot")
        workflow_doc = snap if isinstance(snap, Mapping) else None

    nodes_meta = _nodes_by_id(workflow_doc)
    assignment: dict[str, list[str]] | None = None
    if isinstance(workflow_doc, Mapping):
        try:
            assignment = assign_nodes_to_stages(workflow_doc)
        except Exception:
            assignment = None

    node_records = execution.get("nodes") if isinstance(execution.get("nodes"), Mapping) else {}
    finished_at = str(execution.get("finished_at") or execution.get("started_at") or "") or now_iso()
    records: list[CostRecord] = []

    for node_id, raw in node_records.items():
        if not isinstance(raw, Mapping):
            continue
        status = str(raw.get("status") or "")
        if status not in {"succeeded", "awaiting_approval"}:
            # awaiting_approval has produced outputs (checkpoint after success).
            continue

        node = nodes_meta.get(str(node_id)) or {}
        node_type = str(node.get("type") or "")
        stage_key = _stage_for_node(str(node_id), node_type, assignment=assignment)

        snapshot = raw.get("cost") if isinstance(raw.get("cost"), Mapping) else None
        if snapshot is None:
            # Fallback: try to recover from outputs_summary.provenance (lossy).
            summary = raw.get("outputs_summary")
            recovered = _recover_snapshot_from_summary(summary, node_type=node_type)
            if recovered is None:
                # Provider node with no snapshot still counts as one generation
                # when it succeeded without a cache hit (legacy records).
                cache = raw.get("cache") if isinstance(raw.get("cache"), Mapping) else {}
                cache_hit = bool(cache.get("hit"))
                if node_type in PROVIDER_NODE_TYPES and not cache_hit:
                    recovered = {
                        "generations": 1,
                        "cache_hit": False,
                        "provider_instance_id": "",
                    }
                else:
                    continue
            snapshot = recovered

        records.append(
            cost_record_from_snapshot(
                snapshot,
                job_id=job_id,
                execution_id=execution_id,
                node_id=str(node_id),
                stage_key=stage_key,
                recorded_at=finished_at,
            )
        )

    records.sort(key=lambda r: (r.stage_key or "", r.node_id, r.unit_index or -1))
    return records


def _recover_snapshot_from_summary(
    summary: Any,
    *,
    node_type: str = "",
) -> dict[str, Any] | None:
    """Best-effort recovery when older records lack the cost field.

    ``_summarize`` preserves numbers/bools and truncates strings to char counts,
    so amount strings are lost. Generation count can still be inferred for
    provider nodes.
    """
    if not isinstance(summary, Mapping):
        return None
    # Walk for a nested provenance-ish block.
    stack: list[Any] = [summary]
    seen = 0
    while stack and seen < 50:
        seen += 1
        cur = stack.pop()
        if not isinstance(cur, Mapping):
            continue
        if "provider_instance_id" in cur or "invocation_id" in cur or "cost" in cur:
            cache_hit = bool(cur.get("cache_hit"))
            amount = cur.get("amount")
            # Summarized strings become {chars: N}; skip those.
            if isinstance(amount, Mapping):
                amount = None
            currency = cur.get("currency")
            if isinstance(currency, Mapping):
                currency = "USD"
            instance = cur.get("provider_instance_id")
            if isinstance(instance, Mapping):
                instance = ""
            return {
                "amount": amount if isinstance(amount, (int, float, str)) else None,
                "currency": currency if isinstance(currency, str) else "USD",
                "provider_instance_id": instance if isinstance(instance, str) else "",
                "generations": 0 if cache_hit else (1 if node_type in PROVIDER_NODE_TYPES else 0),
                "cache_hit": cache_hit,
            }
        for child in cur.values():
            if isinstance(child, Mapping):
                stack.append(child)
            elif isinstance(child, list):
                stack.extend(item for item in child[:5] if isinstance(item, Mapping))
    return None


# ---------------------------------------------------------------------------
# Accumulation
# ---------------------------------------------------------------------------


def accumulate_spend(
    records: Sequence[CostRecord],
    *,
    currency: str = DEFAULT_REPORT_CURRENCY,
    rates: Mapping[str, float] | None = None,
) -> BudgetSpent:
    """Sum generation count and cost (converted to *currency*) from records."""
    generations = 0
    cost = 0.0
    for record in records:
        generations += int(record.generations or 0)
        cost += amount_in_currency(record, currency=currency, rates=rates)
    return BudgetSpent(generations=generations, cost=round(cost, 6))


def budget_spent_from_execution(
    job: Job | Mapping[str, Any],
    execution: Mapping[str, Any] | None,
    *,
    workflow: Mapping[str, Any] | None = None,
    rates: Mapping[str, float] | None = None,
) -> tuple[BudgetSpent, list[CostRecord]]:
    """Compute the Job's running spend from its linked execution."""
    budget = budget_from_job(job)
    report_currency = budget.currency or DEFAULT_REPORT_CURRENCY
    records = extract_cost_records_from_execution(
        job, execution, workflow=workflow
    )
    spent = accumulate_spend(records, currency=report_currency, rates=rates)
    return spent, records


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _empty_bucket() -> dict[str, Any]:
    return {
        "generations": 0,
        "cost": 0.0,
        "cost_by_currency": {},
        "record_count": 0,
    }


def _add_to_bucket(
    bucket: dict[str, Any],
    record: CostRecord,
    *,
    report_currency: str,
    rates: Mapping[str, float] | None,
) -> None:
    bucket["generations"] = int(bucket["generations"]) + int(record.generations or 0)
    converted = amount_in_currency(record, currency=report_currency, rates=rates)
    bucket["cost"] = round(float(bucket["cost"]) + converted, 6)
    bucket["record_count"] = int(bucket["record_count"]) + 1
    if record.amount is not None:
        raw_map = bucket.setdefault("cost_by_currency", {})
        code = record.currency or report_currency
        raw_map[code] = round(float(raw_map.get(code) or 0.0) + record.amount_float(), 6)


def build_cost_report(
    job: Job | Mapping[str, Any],
    *,
    execution: Mapping[str, Any] | None = None,
    workflow: Mapping[str, Any] | None = None,
    records: Sequence[CostRecord] | None = None,
    rates: Mapping[str, float] | None = None,
    report_currency: str | None = None,
) -> dict[str, Any]:
    """Full Job cost report: totals, by stage, by provider instance, reconcile.

    When *records* is omitted they are extracted from *execution*. Currency
    conversion uses *rates* (or defaults) and only affects the aggregated
    ``cost`` fields — each record keeps its reported amount/currency.
    """
    if isinstance(job, Job):
        job_id = job.id
        channel_id = job.channel_id
        execution_id = job.execution_id
        stored_spent = job.budget_spent
    else:
        job_id = str((job or {}).get("id") or "")
        channel_id = str((job or {}).get("channel_id") or "")
        execution_id = (job or {}).get("execution_id")
        stored_spent = spent_from_job(job)

    budget = budget_from_job(job)
    currency = (
        report_currency
        or budget.currency
        or DEFAULT_REPORT_CURRENCY
    ).strip().upper() or DEFAULT_REPORT_CURRENCY

    if records is None:
        records = extract_cost_records_from_execution(
            job, execution, workflow=workflow
        )
    else:
        records = list(records)

    totals = _empty_bucket()
    by_stage: dict[str, dict[str, Any]] = {
        key: _empty_bucket() for key in STAGE_KEYS
    }
    by_instance: dict[str, dict[str, Any]] = {}

    for record in records:
        _add_to_bucket(totals, record, report_currency=currency, rates=rates)
        stage = record.stage_key or "unknown"
        if stage not in by_stage:
            by_stage[stage] = _empty_bucket()
        _add_to_bucket(by_stage[stage], record, report_currency=currency, rates=rates)

        instance_key = record.provider_instance_id or record.provider_id or "unknown"
        if instance_key not in by_instance:
            by_instance[instance_key] = _empty_bucket()
            by_instance[instance_key]["provider_instance_id"] = (
                record.provider_instance_id or None
            )
            by_instance[instance_key]["provider_id"] = record.provider_id or None
        _add_to_bucket(
            by_instance[instance_key], record, report_currency=currency, rates=rates
        )

    computed = BudgetSpent(
        generations=int(totals["generations"]),
        cost=float(totals["cost"]),
    )
    stored = BudgetSpent(
        generations=int(stored_spent.generations),
        cost=float(stored_spent.cost),
    )
    # Reconcile: computed from provenance records vs Job.budget_spent.
    # Floats compared at 1e-6; generations exact.
    generations_match = computed.generations == stored.generations
    cost_match = abs(computed.cost - stored.cost) < 1e-6
    reconciled = generations_match and cost_match

    ceiling = {
        "max_generations": budget.max_generations,
        "max_cost": budget.max_cost,
        "currency": budget.currency or currency,
    }

    return {
        "job_id": job_id,
        "channel_id": channel_id,
        "execution_id": execution_id,
        "currency": currency,
        "totals": {
            "generations": computed.generations,
            "cost": computed.cost,
            "cost_by_currency": totals.get("cost_by_currency") or {},
            "record_count": totals["record_count"],
        },
        "budget_spent": stored.model_dump(mode="json"),
        "budget": ceiling,
        "by_stage": {
            key: value
            for key, value in by_stage.items()
            if value["record_count"] > 0 or value["generations"] > 0
        },
        "by_provider_instance": by_instance,
        "records": [r.to_public() for r in records],
        "reconcile": {
            "ok": reconciled,
            "computed": computed.model_dump(mode="json"),
            "stored": stored.model_dump(mode="json"),
            "generations_match": generations_match,
            "cost_match": cost_match,
        },
    }


def build_channel_cost_report(
    channel_id: str,
    jobs: Sequence[Job | Mapping[str, Any]],
    *,
    rates: Mapping[str, float] | None = None,
    report_currency: str | None = None,
) -> dict[str, Any]:
    """Roll up cost across every Job for a Channel."""
    currency = (report_currency or DEFAULT_REPORT_CURRENCY).strip().upper()
    totals = _empty_bucket()
    job_summaries: list[dict[str, Any]] = []

    for job in jobs:
        if isinstance(job, Job):
            jid = job.id
            status = job.status
            spent = job.budget_spent
            ch = job.channel_id
        else:
            jid = str((job or {}).get("id") or "")
            status = str((job or {}).get("status") or "")
            spent = spent_from_job(job)
            ch = str((job or {}).get("channel_id") or "")
        if ch and channel_id and ch != channel_id:
            continue
        # Prefer stored budget_spent (already accumulated); no execution load.
        totals["generations"] = int(totals["generations"]) + int(spent.generations)
        totals["cost"] = round(float(totals["cost"]) + float(spent.cost), 6)
        totals["record_count"] = int(totals["record_count"]) + 1
        job_summaries.append({
            "job_id": jid,
            "status": status,
            "generations": int(spent.generations),
            "cost": float(spent.cost),
        })

    return {
        "channel_id": channel_id,
        "currency": currency,
        "totals": {
            "generations": int(totals["generations"]),
            "cost": float(totals["cost"]),
            "job_count": int(totals["record_count"]),
        },
        "jobs": job_summaries,
    }


def apply_job_spend_from_execution(
    job_id: str,
    execution: Mapping[str, Any] | None,
    *,
    workflow: Mapping[str, Any] | None = None,
    rates: Mapping[str, float] | None = None,
    allow_terminal: bool = True,
) -> tuple[Job, list[CostRecord]]:
    """Recompute and persist ``budget_spent`` from the linked execution.

    Idempotent: always overwrites with the provenance-derived total so a
    partial sync cannot double-count. Returns the updated Job and records.
    """
    from scriptase.jobs.store import get_job, update_job

    job = get_job(job_id)
    spent, records = budget_spent_from_execution(
        job, execution, workflow=workflow, rates=rates
    )
    # Only write when values change to avoid needless document churn.
    current = job.budget_spent
    if (
        int(current.generations) != int(spent.generations)
        or abs(float(current.cost) - float(spent.cost)) >= 1e-9
    ):
        job = update_job(
            job.id,
            budget_spent=spent,
            allow_terminal=allow_terminal or job.is_terminal,
        )
    return job, records


__all__ = [
    "DEFAULT_FX_RATES",
    "DEFAULT_REPORT_CURRENCY",
    "CostRecord",
    "accumulate_spend",
    "amount_in_currency",
    "apply_job_spend_from_execution",
    "budget_spent_from_execution",
    "build_channel_cost_report",
    "build_cost_report",
    "convert_amount",
    "cost_record_from_snapshot",
    "extract_cost_records_from_execution",
]
