"""Step 8.3 — Fallback execution and per-unit provenance.

Done when: a primary-instance failure falls through to the next instance and
the record shows exactly which instance, seed, and model revision produced
each unit.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from scriptase.providers.errors import (
    PROVIDER_TIMEOUT,
    PROVIDER_UNIT_FAILED,
    ProviderError,
    ProviderErrorPayload,
)
from scriptase.providers.fallback import (
    FALLBACK_AFTER_PREFIX,
    effective_unit_provenance,
    format_fallback_reason,
    is_fallback_reason,
    parse_fallback_reason,
    resolve_execution_chain,
    run_with_fallback,
    selection_reason_for_index,
    stamp_unit_producer,
    stamp_units_for_attempt,
)
from scriptase.providers.results import (
    PARTIAL,
    SUCCEEDED,
    UNIT_FAILED,
    UNIT_SUCCEEDED,
    Provenance,
    ProviderResult,
    UnitResult,
)


def _unit_error(message: str = "unit failed") -> ProviderErrorPayload:
    return ProviderErrorPayload.from_error(
        ProviderError(PROVIDER_UNIT_FAILED, message, retryable=True)
    )


def _succeeded(
    index: int,
    *,
    seed: int | None = None,
    request_id: str = "",
    model_revision: str = "",
    ref: str | None = None,
) -> UnitResult:
    meta: dict = {}
    if seed is not None:
        meta["seed"] = seed
    if request_id:
        meta["request_id"] = request_id
    if model_revision:
        meta["model_revision"] = model_revision
    return UnitResult(
        unit_index=index,
        state=UNIT_SUCCEEDED,
        artifact_refs=(ref or f"unit-{index}.png",),
        metadata=meta,
        seed=seed,
        request_id=request_id,
        model_revision=model_revision,
    )


def _failed(index: int) -> UnitResult:
    return UnitResult(unit_index=index, state=UNIT_FAILED, error=_unit_error())


class SelectionReasonTests(unittest.TestCase):
    def test_format_and_parse_fallback_after(self):
        reason = format_fallback_reason("inst_main")
        self.assertEqual(reason, "fallback_after:inst_main")
        self.assertTrue(reason.startswith(FALLBACK_AFTER_PREFIX))
        self.assertEqual(parse_fallback_reason(reason), "inst_main")
        self.assertTrue(is_fallback_reason(reason))
        self.assertIsNone(parse_fallback_reason("channel"))
        self.assertFalse(is_fallback_reason("node_config"))

    def test_selection_reason_for_index(self):
        chain = ["primary", "backup", "last"]
        self.assertEqual(
            selection_reason_for_index(0, primary_reason="channel", chain=chain),
            "channel",
        )
        self.assertEqual(
            selection_reason_for_index(1, primary_reason="channel", chain=chain),
            "fallback_after:primary",
        )
        self.assertEqual(
            selection_reason_for_index(2, primary_reason="channel", chain=chain),
            "fallback_after:backup",
        )


class ResolveChainTests(unittest.TestCase):
    def test_no_policy_is_primary_only(self):
        self.assertEqual(
            resolve_execution_chain("image", primary_instance_id="inst_a"),
            ["inst_a"],
        )

    def test_policy_orders_primary_then_fallbacks(self):
        chain = resolve_execution_chain(
            "image",
            primary_instance_id="inst_main",
            fallback_policy={
                "primary": "inst_main",
                "fallbacks": ["inst_backup", "inst_last"],
            },
        )
        self.assertEqual(chain, ["inst_main", "inst_backup", "inst_last"])

    def test_node_primary_not_in_policy_is_prepended(self):
        chain = resolve_execution_chain(
            "image",
            primary_instance_id="inst_node",
            fallback_policy={
                "primary": "inst_main",
                "fallbacks": ["inst_backup"],
            },
        )
        self.assertEqual(chain, ["inst_node", "inst_main", "inst_backup"])

    def test_channel_settings_blob(self):
        chain = resolve_execution_chain(
            "image",
            primary_instance_id="alpha",
            channel_settings={
                "fallback_policies": {
                    "image": {"primary": "alpha", "fallbacks": ["beta"]},
                }
            },
        )
        self.assertEqual(chain, ["alpha", "beta"])

    def test_channel_snapshot(self):
        chain = resolve_execution_chain(
            "video",
            primary_instance_id="v1",
            channel_snapshot={
                "fallback_policies": {
                    "video": {"primary": "v1", "fallbacks": ["v2"]},
                }
            },
        )
        self.assertEqual(chain, ["v1", "v2"])


class PerUnitProvenanceTests(unittest.TestCase):
    def test_stamp_harvests_metadata_and_identity(self):
        unit = UnitResult(
            0,
            UNIT_SUCCEEDED,
            metadata={"seed": 7, "request_id": "req-7", "model_revision": "m-v2"},
        )
        stamped = stamp_unit_producer(
            unit,
            provider_id="backup_type",
            provider_instance_id="inst_backup",
            selection_reason="fallback_after:inst_main",
        )
        self.assertEqual(stamped.seed, 7)
        self.assertEqual(stamped.request_id, "req-7")
        self.assertEqual(stamped.model_revision, "m-v2")
        self.assertEqual(stamped.provider_id, "backup_type")
        self.assertEqual(stamped.provider_instance_id, "inst_backup")
        self.assertEqual(stamped.selection_reason, "fallback_after:inst_main")
        # Sparse serialization keeps the overrides.
        payload = stamped.to_dict()
        self.assertEqual(payload["seed"], 7)
        self.assertEqual(payload["selection_reason"], "fallback_after:inst_main")

    def test_effective_inherits_envelope_when_sparse_empty(self):
        envelope = Provenance(
            provider_id="main_type",
            provider_instance_id="inst_main",
            selection_reason="channel",
            seed=1,
            request_id="env-req",
            model_revision="env-model",
        )
        unit = UnitResult(0, UNIT_SUCCEEDED)
        effective = effective_unit_provenance(unit, envelope)
        self.assertEqual(effective["provider_instance_id"], "inst_main")
        self.assertEqual(effective["seed"], 1)
        self.assertEqual(effective["model_revision"], "env-model")
        self.assertEqual(effective["selection_reason"], "channel")

    def test_effective_prefers_unit_overrides(self):
        envelope = Provenance(
            provider_id="main_type",
            provider_instance_id="inst_main",
            selection_reason="channel",
            seed=1,
            model_revision="env-model",
        )
        unit = UnitResult(
            1,
            UNIT_SUCCEEDED,
            seed=99,
            model_revision="backup-model",
            provider_id="backup_type",
            provider_instance_id="inst_backup",
            selection_reason="fallback_after:inst_main",
        )
        effective = effective_unit_provenance(unit, envelope)
        self.assertEqual(effective["provider_instance_id"], "inst_backup")
        self.assertEqual(effective["seed"], 99)
        self.assertEqual(effective["model_revision"], "backup-model")
        self.assertEqual(effective["selection_reason"], "fallback_after:inst_main")


class FallbackExecutionTests(unittest.TestCase):
    def test_primary_failure_falls_through_to_backup(self):
        """Done-when: primary fails → next instance; record shows producers."""
        calls: list[tuple[str, str]] = []

        def run_one(instance_id: str, reason: str, prior):
            calls.append((instance_id, reason))
            if instance_id == "inst_main":
                raise ProviderError(
                    PROVIDER_TIMEOUT,
                    "Primary timed out",
                    retryable=True,
                    domain="image",
                    provider_id="main_type",
                )
            # Backup produces both units with distinct seeds / revisions.
            return ProviderResult(
                domain="image",
                provider_id="backup_type",
                status=SUCCEEDED,
                units=[
                    _succeeded(
                        0, seed=10, request_id="b-0", model_revision="backup-r1"
                    ),
                    _succeeded(
                        1, seed=11, request_id="b-1", model_revision="backup-r1"
                    ),
                ],
                provenance=Provenance(
                    domain="image",
                    provider_id="backup_type",
                    provider_instance_id="inst_backup",
                    selection_reason=reason,
                    seed=10,
                    model_revision="backup-r1",
                ),
            )

        record = run_with_fallback(
            domain="image",
            chain=["inst_main", "inst_backup"],
            run_one=run_one,
            multi_unit=True,
            primary_selection_reason="channel",
            resolve_type=lambda iid: (
                "main_type" if iid == "inst_main" else "backup_type"
            ),
            expected_unit_count=2,
        )

        self.assertEqual(
            calls,
            [
                ("inst_main", "channel"),
                ("inst_backup", "fallback_after:inst_main"),
            ],
        )
        self.assertEqual(record.result.status, SUCCEEDED)
        self.assertEqual(len(record.attempts), 2)
        self.assertIsNotNone(record.attempts[0].error)
        self.assertEqual(record.attempts[0].error.code, PROVIDER_TIMEOUT)

        effective = record.units_effective()
        self.assertEqual(len(effective), 2)
        for entry in effective:
            self.assertEqual(entry["provider_instance_id"], "inst_backup")
            self.assertEqual(entry["selection_reason"], "fallback_after:inst_main")
            self.assertEqual(entry["model_revision"], "backup-r1")
            self.assertIsNotNone(entry["seed"])

        # Seeds are per-unit.
        self.assertEqual(effective[0]["seed"], 10)
        self.assertEqual(effective[1]["seed"], 11)

    def test_partial_primary_reuses_success_and_fallbacks_failed_units(self):
        """Mixed run: unit 0 from primary, unit 1 from backup."""
        calls: list[str] = []

        def run_one(instance_id: str, reason: str, prior):
            calls.append(instance_id)
            if instance_id == "inst_main":
                return ProviderResult(
                    domain="image",
                    provider_id="main_type",
                    status=PARTIAL,
                    units=[
                        _succeeded(
                            0, seed=1, request_id="p-0", model_revision="main-r1"
                        ),
                        _failed(1),
                    ],
                    provenance=Provenance(
                        domain="image",
                        provider_id="main_type",
                        provider_instance_id="inst_main",
                        selection_reason=reason,
                        seed=1,
                        model_revision="main-r1",
                    ),
                )
            # Backup only re-runs the failed unit (prior already has unit 0).
            self.assertEqual(len(prior), 2)
            self.assertEqual(prior[0].state, UNIT_SUCCEEDED)
            return ProviderResult(
                domain="image",
                provider_id="backup_type",
                status=SUCCEEDED,
                units=[
                    _succeeded(
                        1, seed=2, request_id="b-1", model_revision="backup-r2"
                    ),
                ],
                provenance=Provenance(
                    domain="image",
                    provider_id="backup_type",
                    provider_instance_id="inst_backup",
                    selection_reason=reason,
                    seed=2,
                    model_revision="backup-r2",
                ),
            )

        record = run_with_fallback(
            domain="image",
            chain=["inst_main", "inst_backup"],
            run_one=run_one,
            multi_unit=True,
            primary_selection_reason="node_config",
            resolve_type=lambda iid: (
                "main_type" if iid == "inst_main" else "backup_type"
            ),
            expected_unit_count=2,
        )

        self.assertEqual(calls, ["inst_main", "inst_backup"])
        self.assertEqual(record.result.status, SUCCEEDED)
        effective = record.units_effective()
        self.assertEqual(len(effective), 2)

        # Unit 0 inherits envelope (primary).
        u0 = effective[0]
        self.assertEqual(u0["provider_instance_id"], "inst_main")
        self.assertEqual(u0["seed"], 1)
        self.assertEqual(u0["model_revision"], "main-r1")
        self.assertIn(u0["selection_reason"], {"node_config", ""})

        # Unit 1 from backup with fallback_after reason.
        u1 = effective[1]
        self.assertEqual(u1["provider_instance_id"], "inst_backup")
        self.assertEqual(u1["seed"], 2)
        self.assertEqual(u1["model_revision"], "backup-r2")
        self.assertEqual(u1["selection_reason"], "fallback_after:inst_main")

        # Sparse: fallback unit carries overrides on the envelope.
        sparse = record.result.units[1].to_dict()
        self.assertEqual(sparse["provider_instance_id"], "inst_backup")
        self.assertEqual(sparse["selection_reason"], "fallback_after:inst_main")
        self.assertEqual(sparse["seed"], 2)

    def test_single_shot_falls_through_on_raise(self):
        def run_one(instance_id: str, reason: str, prior):
            if instance_id == "tts_main":
                raise ProviderError(
                    PROVIDER_TIMEOUT,
                    "TTS primary failed",
                    retryable=True,
                    domain="tts",
                    provider_id="kokoro",
                )
            return ProviderResult(
                domain="tts",
                provider_id="inworld",
                status=SUCCEEDED,
                payload={"audio_ref": "tts/x/voice.wav"},
                metadata={"seed": 5, "model_revision": "inworld-v1", "request_id": "t1"},
                provenance=Provenance(
                    domain="tts",
                    provider_id="inworld",
                    provider_instance_id="tts_backup",
                    selection_reason=reason,
                    seed=5,
                    model_revision="inworld-v1",
                    request_id="t1",
                ),
            )

        record = run_with_fallback(
            domain="tts",
            chain=["tts_main", "tts_backup"],
            run_one=run_one,
            multi_unit=False,
            primary_selection_reason="request",
            resolve_type=lambda iid: "kokoro" if iid == "tts_main" else "inworld",
        )
        self.assertEqual(record.result.status, SUCCEEDED)
        self.assertEqual(
            record.result.provenance.selection_reason,
            "fallback_after:tts_main",
        )
        self.assertEqual(record.result.provenance.provider_instance_id, "tts_backup")
        self.assertEqual(record.result.provenance.seed, 5)
        self.assertEqual(record.result.provenance.model_revision, "inworld-v1")

    def test_exhausted_chain_raises_last_error(self):
        def run_one(instance_id: str, reason: str, prior):
            raise ProviderError(
                PROVIDER_UNIT_FAILED,
                f"{instance_id} failed",
                domain="image",
                provider_id=instance_id,
                details={"units": [_failed(0).to_dict(), _failed(1).to_dict()]},
            )

        with self.assertRaises(ProviderError) as ctx:
            run_with_fallback(
                domain="image",
                chain=["a", "b"],
                run_one=run_one,
                multi_unit=True,
                expected_unit_count=2,
            )
        self.assertEqual(ctx.exception.code, PROVIDER_UNIT_FAILED)

    def test_no_fallback_single_member_chain(self):
        def run_one(instance_id: str, reason: str, prior):
            return ProviderResult(
                domain="image",
                provider_id="only",
                status=SUCCEEDED,
                units=[_succeeded(0, seed=3, model_revision="only-r")],
                provenance=Provenance(
                    provider_id="only",
                    provider_instance_id="only",
                    selection_reason=reason,
                    seed=3,
                    model_revision="only-r",
                ),
            )

        record = run_with_fallback(
            domain="image",
            chain=["only"],
            run_one=run_one,
            multi_unit=True,
            primary_selection_reason="default",
            expected_unit_count=1,
        )
        self.assertEqual(record.result.status, SUCCEEDED)
        self.assertEqual(len(record.attempts), 1)
        effective = record.units_effective()
        self.assertEqual(effective[0]["provider_instance_id"], "only")
        self.assertEqual(effective[0]["seed"], 3)


class StampBatchTests(unittest.TestCase):
    def test_stamp_units_for_attempt_only_indices(self):
        units = [_succeeded(0, seed=1), _succeeded(1, seed=2)]
        stamped = stamp_units_for_attempt(
            units,
            provider_id="t",
            provider_instance_id="i",
            selection_reason="fallback_after:p",
            only_indices={1},
            stamp_identity=True,
        )
        self.assertEqual(stamped[0].provider_instance_id, "")
        self.assertEqual(stamped[1].provider_instance_id, "i")
        self.assertEqual(stamped[1].selection_reason, "fallback_after:p")


if __name__ == "__main__":
    unittest.main()
