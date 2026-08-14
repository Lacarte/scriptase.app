"""Step 11.4: the standard provider runtime and the error boundary.

Covers contracts.md §30 (invocation context, cancellation, progress, redacted
logging), §31 (the result envelope, units, provenance, prohibited content), §33
(the one job contract and its state machine), §34 (`ProviderError`, the code
catalog, the wrapping boundary), §35 (cancellation, retry, timeout), and the
mechanical half of §36 (the egress validator).

Every scenario is driven through the hand-written `fixture_provider` package —
a provider that appears in no hardcoded list anywhere in the codebase — so the
runtime is proved against a plugin rather than against a special case.
"""

import os
import shutil
import tempfile
import unittest

from config import ROOT_DIR
from scriptase.providers import boundary, errors as E, fixtures, legacy
from scriptase.providers.domains import DomainSpec
from scriptase.providers.hub import ProviderHub
from scriptase.providers.invocation import (
    ArtifactStager,
    CancellationToken,
    ProgressReporter,
    ProviderLogger,
    build_invocation,
    domain_deadline,
    message_progress,
)
from scriptase.providers.jobs import (
    FAILED,
    JOB_CANCELLED,
    RUNNING,
    SUBMITTED,
    SUCCEEDED,
    TIMED_OUT,
    JobHandle,
    JobRecord,
    JobStatus,
    poll_interval,
    terminal_outcome,
    unknown_job_status,
)
from scriptase.providers.results import (
    PARTIAL,
    UNIT_FAILED,
    UNIT_SUCCEEDED,
    ProviderResult,
    UnitResult,
    coerce_result,
    derive_status,
    normalize_ref,
    resolve_ref,
    validate_egress,
)
from scriptase.engine.adapters.common import AdapterContext


FIXTURE_PROVIDER_BASE = os.path.join(ROOT_DIR, "tests", "fixture_providers")


def fixture_domain(base=FIXTURE_PROVIDER_BASE, domain="tts"):
    return DomainSpec(
        id=domain,
        label="Fixture domain",
        package="tests.fixture_providers",
        providers_base=base,
        default_provider="fixture_provider",
        capability_vocabulary=frozenset({
            "test_connection", "single_scene", "batch", "async_job", "cancel",
            "progress", "push_callbacks",
        }),
    )


class RuntimeCase(unittest.TestCase):
    """One temp OUTPUT_DIR, one hub over the fixture provider, per test."""

    domain = "tts"

    def setUp(self):
        self.output_dir = tempfile.mkdtemp(prefix="sts_11_4_")
        self.addCleanup(shutil.rmtree, self.output_dir, ignore_errors=True)
        self._patch_output_dir(self.output_dir)

        self.hub = ProviderHub({self.domain: fixture_domain(domain=self.domain)})
        self.provider = self.hub.get(self.domain, "fixture_provider")
        self.assertIsNotNone(self.provider, "the fixture provider must be discoverable")
        self.instance = self.hub.create(self.domain, "fixture_provider")
        self.addCleanup(self.hub.shutdown)

    def _patch_output_dir(self, path):
        """Point every module-level OUTPUT_DIR constant at the temp directory."""
        import config
        from scriptase.providers import results

        for module, name in ((config, "OUTPUT_DIR"), (results, "OUTPUT_DIR")):
            original = getattr(module, name)
            setattr(module, name, path)
            self.addCleanup(setattr, module, name, original)

    def invocation(self, scenario="sync", **overrides):
        options = {"scenario": scenario}
        options.update(overrides.pop("options", {}))
        context = AdapterContext(
            project_id=overrides.pop("project_id", "pm_ABC123"),
            execution_id="exec_1",
            node_id="node_1",
            stop_requested=overrides.pop("stop_requested", None),
            progress=overrides.pop("progress", None),
            stage_artifact=overrides.pop("stage_artifact", None),
        )
        return build_invocation(
            context,
            domain=self.domain,
            provider_id="fixture_provider",
            project_id=context.project_id,
            output_dir=os.path.join(self.output_dir, self.domain, context.project_id),
            settings={"api_key": "sk-fixture-secret-value", "mode": "sync"},
            options=options,
            **overrides,
        )

    def run_scenario(self, scenario="sync", **overrides):
        invocation = self.invocation(scenario, **overrides)
        return boundary.invoke(
            lambda inv: self.instance.invoke({"text": "hello", "voice": "af_heart"}, inv),
            invocation,
            provider_version=self.provider.version,
            contract_version=self.provider.contract_version,
        )


# -- §30.1 the invocation context -------------------------------------------


class InvocationContextTests(RuntimeCase):
    def test_collaborators_are_never_none(self):
        """A provider never writes `if stop and stop():` (§30.1)."""
        invocation = self.invocation()
        self.assertIsInstance(invocation.cancel, CancellationToken)
        self.assertIsInstance(invocation.progress, ProgressReporter)
        self.assertIsInstance(invocation.log, ProviderLogger)
        self.assertFalse(invocation.cancel.is_cancelled())
        invocation.progress(ready=1)  # must not raise without a sink

    def test_built_from_an_adapter_context(self):
        """§30.6: exactly one construction site, mapped field by field."""
        invocation = self.invocation()
        self.assertEqual(invocation.execution_id, "exec_1")
        self.assertEqual(invocation.node_id, "node_1")
        self.assertEqual(invocation.project_id, "pm_ABC123")
        self.assertEqual(invocation.attempt, 1)
        self.assertTrue(invocation.invocation_id)

    def test_legacy_route_builds_the_same_object_without_a_scheduler(self):
        invocation = build_invocation(
            None, domain="tts", provider_id="fixture_provider", project_id="pm_ABC123"
        )
        self.assertEqual(invocation.execution_id, "")
        self.assertEqual(invocation.node_id, "")
        self.assertIsInstance(invocation.cancel, CancellationToken)

    def test_deadline_defaults_come_from_the_domain(self):
        """§35.3: the platform owns the deadline, not the provider."""
        self.assertEqual(domain_deadline("tts"), 900.0)
        self.assertEqual(domain_deadline("image"), 1800.0)
        self.assertEqual(domain_deadline("video"), 7200.0)
        self.assertEqual(self.invocation().deadline, 900.0)
        self.assertEqual(self.invocation(deadline_s=5.0).deadline, 5.0)

    def test_a_retry_gets_a_new_invocation_id(self):
        """§35.2: a retried invocation is a different invocation."""
        self.assertNotEqual(
            self.invocation().invocation_id, self.invocation().invocation_id
        )


class CancellationTokenTests(unittest.TestCase):
    def test_raise_if_cancelled_raises_the_one_recognized_code(self):
        flag = {"stop": False}
        token = CancellationToken(lambda: flag["stop"])
        token.raise_if_cancelled()
        flag["stop"] = True
        with self.assertRaises(E.ProviderCancelled) as caught:
            token.raise_if_cancelled()
        self.assertEqual(caught.exception.code, "CANCELLED")
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(caught.exception.workflow_code, "CANCELLED")

    def test_cancellation_latches(self):
        """Monotonic: re-probing after the scheduler tears down cannot un-cancel."""
        flag = {"stop": True}
        token = CancellationToken(lambda: flag["stop"])
        self.assertTrue(token.is_cancelled())
        flag["stop"] = False
        self.assertTrue(token.is_cancelled())

    def test_callbacks_run_once_and_swallow_exceptions(self):
        calls = []
        flag = {"stop": False}
        token = CancellationToken(lambda: flag["stop"])
        token.on_cancel(lambda: calls.append("a"))
        token.on_cancel(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        flag["stop"] = True
        token.is_cancelled()
        token.is_cancelled()
        self.assertEqual(calls, ["a"])
        # Registering after the fact still fires, exactly once.
        token.on_cancel(lambda: calls.append("b"))
        self.assertEqual(calls, ["a", "b"])

    def test_a_broken_probe_does_not_fail_the_invocation(self):
        token = CancellationToken(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertFalse(token.is_cancelled())


class ProgressReporterTests(unittest.TestCase):
    def _reporter(self, **kwargs):
        events = []
        clock = {"t": 0.0}
        reporter = ProgressReporter(
            events.append, clock=lambda: clock["t"], **kwargs
        )
        return reporter, events, clock

    def test_rate_limited_to_one_event_per_second(self):
        """§30.4: without this a per-scene provider floods the SSE ring."""
        reporter, events, clock = self._reporter()
        for ready in range(1, 6):
            reporter(ready=ready, total=5)
        self.assertEqual(len(events), 1)
        clock["t"] = 1.5
        reporter(ready=5, total=5)
        self.assertEqual([event.ready for event in events], [1, 5])

    def test_the_last_value_before_a_terminal_state_is_always_emitted(self):
        reporter, events, _clock = self._reporter()
        reporter(ready=1, total=3)
        reporter(ready=2, total=3)
        reporter(ready=3, total=3, state="succeeded")
        self.assertEqual([event.ready for event in events], [1, 3])

    def test_flush_emits_the_coalesced_value(self):
        reporter, events, _clock = self._reporter()
        reporter(ready=1, total=3)
        reporter(ready=2, total=3)
        reporter.flush()
        self.assertEqual([event.ready for event in events], [1, 2])

    def test_ready_is_monotonic_and_total_is_set_once(self):
        reporter, events, clock = self._reporter()
        reporter(ready=5, total=10)
        clock["t"] = 2.0
        reporter(ready=2, total=99)
        self.assertEqual(events[-1].ready, 5)
        self.assertEqual(events[-1].total, 10)

    def test_fraction_is_clamped(self):
        reporter, events, clock = self._reporter()
        reporter(fraction=4.2)
        clock["t"] = 2.0
        reporter(fraction=-1.0)
        self.assertEqual([event.fraction for event in events], [1.0, 0.0])

    def test_a_message_is_redacted_path_stripped_and_capped(self):
        reporter, events, _clock = self._reporter(secrets={"hunter2"})
        reporter(message="wrote C:\\secret\\voice.wav for hunter2 " + "x" * 400)
        message = events[0].message
        self.assertNotIn("hunter2", message)
        self.assertNotIn("C:\\secret", message)
        self.assertIn("voice.wav", message)
        self.assertLessEqual(len(message), 200)

    def test_a_failing_sink_never_changes_the_outcome(self):
        reporter = ProgressReporter(lambda event: (_ for _ in ()).throw(RuntimeError()))
        reporter(ready=1)  # must not raise

    def test_adapter_context_progress_receives_only_a_message(self):
        """§30.6: `AdapterContext.progress` is `Callable[[str], None]`."""
        seen = []
        reporter = message_progress(seen.append)
        reporter(ready=2, total=5)
        self.assertEqual(seen, ["2/5"])


class ProviderLoggerTests(unittest.TestCase):
    def test_messages_and_fields_are_redacted(self):
        log = ProviderLogger({"domain": "tts"}, secrets={"sk-abc123def456"})
        log.warning("call failed for sk-abc123def456", api_key="sk-abc123def456")
        record = log.records[0]
        self.assertNotIn("sk-abc123def456", record["message"])
        self.assertEqual(record["fields"]["api_key"], "[REDACTED]")

    def test_internal_records_never_become_execution_record_entries(self):
        """§30.5: the boundary traceback is internal-only even at error level."""
        log = ProviderLogger()
        log.error("provider said no")
        log.internal("traceback", traceback="File ...")
        entries = log.entries()
        self.assertEqual([entry["message"] for entry in entries], ["provider said no"])

    def test_only_warning_and_error_are_eligible(self):
        log = ProviderLogger()
        log.debug("d")
        log.info("i")
        log.warning("w")
        self.assertEqual([entry["level"] for entry in log.entries()], ["warning"])


# -- §31 the result envelope -------------------------------------------------


class ResultEnvelopeTests(RuntimeCase):
    def test_sync_success(self):
        result = self.run_scenario("sync")
        self.assertEqual(result.result_version, 1)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.domain, "tts")
        self.assertEqual(result.provider_id, "fixture_provider")
        self.assertEqual(result.provider_version, "1.0.0")
        self.assertEqual(result.contract_version, 2)
        self.assertEqual(result.artifact_refs, ["tts/pm_ABC123/voice.wav"])
        self.assertEqual(result.units, [])

    def test_the_platform_overwrites_identity_so_impersonation_is_impossible(self):
        coerced = coerce_result(
            ProviderResult(domain="video", provider_id="somebody_else"),
            domain="tts",
            provider_id="fixture_provider",
        )
        self.assertEqual((coerced.domain, coerced.provider_id), ("tts", "fixture_provider"))

    def test_provenance_is_filled_by_the_platform_and_redacts_settings(self):
        """§31.3 and §36 L6: settings are input-only, provenance is the one echo."""
        result = self.run_scenario("sync")
        provenance = result.provenance.to_dict()
        self.assertEqual(provenance["provider_id"], "fixture_provider")
        # `redact_settings` is the shipped producer, and its sentinel is `***`
        # (§22.6); §31.3's `[REDACTED]` example predates that decision.
        self.assertEqual(provenance["resolved_settings_redacted"]["api_key"], "***")
        self.assertEqual(provenance["resolved_settings_redacted"]["mode"], "sync")
        self.assertNotIn("sk-fixture-secret-value", str(result.to_dict()))
        self.assertTrue(provenance["invocation_id"])
        self.assertTrue(provenance["started_at"] and provenance["finished_at"])
        # Step 0.4: reproducibility fields always present on the envelope
        # (null/empty when the provider does not surface them).
        self.assertIn("seed", provenance)
        self.assertIn("request_id", provenance)
        self.assertIn("model_revision", provenance)
        self.assertIn("provider_instance_id", provenance)

    def test_unknown_result_keys_are_dropped_not_rejected(self):
        """§31.1: a provider built against a newer build still runs here."""
        result = self.run_scenario("unknown_result_keys")
        self.assertEqual(result.status, "succeeded")
        self.assertNotIn("from_a_newer_build", result.to_dict())

    def test_a_non_object_result_is_PROVIDER_RESULT_INVALID(self):
        with self.assertRaises(E.ProviderError) as caught:
            self.run_scenario("malformed_result")
        self.assertEqual(caught.exception.code, "PROVIDER_RESULT_INVALID")
        self.assertFalse(caught.exception.retryable)

    def test_an_unsupported_result_version_is_rejected(self):
        with self.assertRaises(E.ProviderError) as caught:
            coerce_result(
                {"result_version": 99}, domain="tts", provider_id="fixture_provider"
            )
        self.assertEqual(caught.exception.code, "PROVIDER_RESULT_INVALID")

    def test_metadata_and_warning_caps(self):
        result = coerce_result(
            {
                "metadata": {f"k{i}": i for i in range(60)} | {"long": "x" * 900,
                                                              "nested": {"no": 1}},
                "warnings": [{"code": "W", "message": "y" * 900}] * 80,
            },
            domain="tts", provider_id="fixture_provider",
        )
        self.assertLessEqual(len(result.metadata), 40)
        self.assertLessEqual(len(result.warnings), 50)
        self.assertLessEqual(len(result.warnings[0]["message"]), 200)
        self.assertNotIn("nested", result.metadata)

    def test_a_warning_never_changes_status(self):
        result = ProviderResult()
        result.warn("VOICE_FALLBACK", "requested voice was unavailable")
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.warnings[0]["code"], "VOICE_FALLBACK")


class PartialResultTests(RuntimeCase):
    def test_partial_keeps_one_unit_per_requested_unit(self):
        """§31.5 rule 1: an unattempted unit is `skipped`, never an omission."""
        result = self.run_scenario("partial")
        self.assertEqual(result.status, PARTIAL)
        self.assertEqual([unit.unit_index for unit in result.units], [0, 1, 2])
        self.assertEqual(
            [unit.state for unit in result.units], ["succeeded", "failed", "skipped"]
        )

    def test_envelope_refs_are_the_union_of_unit_refs(self):
        """§31.5 rule 4: no unit-level ref may be missing from the envelope."""
        result = self.run_scenario("partial")
        for unit in result.units:
            for ref in unit.artifact_refs:
                self.assertIn(ref, result.artifact_refs)

    def test_all_units_failed_is_raised_never_reported_as_success(self):
        """§31.4: the rule both visual adapters enforce by hand today."""
        with self.assertRaises(E.ProviderError) as caught:
            self.run_scenario("all_units_failed")
        self.assertEqual(caught.exception.code, "PROVIDER_UNIT_FAILED")

    def test_a_failed_unit_must_carry_an_error(self):
        with self.assertRaises(E.ProviderError) as caught:
            coerce_result(
                ProviderResult(units=[UnitResult(0, UNIT_SUCCEEDED),
                                      UnitResult(1, UNIT_FAILED)]),
                domain="image", provider_id="fixture_provider",
            )
        self.assertEqual(caught.exception.code, "PROVIDER_RESULT_INVALID")

    def test_duplicate_unit_indexes_are_rejected(self):
        with self.assertRaises(E.ProviderError):
            coerce_result(
                ProviderResult(units=[UnitResult(0), UnitResult(0)]),
                domain="image", provider_id="fixture_provider",
            )

    def test_status_derivation_precedence(self):
        """§31.5 rule 3, including cancellation winning over partial success."""
        self.assertEqual(derive_status([]), "succeeded")
        self.assertEqual(derive_status([UnitResult(0, UNIT_SUCCEEDED)]), "succeeded")
        self.assertEqual(
            derive_status([UnitResult(0, UNIT_SUCCEEDED), UnitResult(1, "skipped")]),
            PARTIAL,
        )
        self.assertEqual(derive_status([UnitResult(0, UNIT_FAILED)]), "failed")
        self.assertEqual(
            derive_status([UnitResult(0, UNIT_SUCCEEDED), UnitResult(1, "cancelled")]),
            "cancelled",
        )
        self.assertEqual(
            derive_status([UnitResult(0, "cancelled"), UnitResult(1, UNIT_FAILED)]),
            "failed",
        )

    def test_a_cancelled_unit_cancels_the_invocation(self):
        with self.assertRaises(E.ProviderCancelled):
            coerce_result(
                ProviderResult(units=[UnitResult(0, UNIT_SUCCEEDED),
                                      UnitResult(1, "cancelled")]),
                domain="image", provider_id="fixture_provider",
            )


# -- §30.2 / §36 artifacts and egress ---------------------------------------


class ArtifactTests(RuntimeCase):
    def test_normalize_ref_produces_a_relative_posix_ref(self):
        path = os.path.join(self.output_dir, "tts", "pm_ABC123", "voice.wav")
        self.assertEqual(
            normalize_ref(path, output_dir=self.output_dir), "tts/pm_ABC123/voice.wav"
        )

    def test_a_write_outside_the_managed_directory_is_refused(self):
        with self.assertRaises(E.ProviderError) as caught:
            self.run_scenario("unmanaged_artifact")
        self.assertEqual(caught.exception.code, "PROVIDER_ARTIFACT_UNMANAGED")
        self.assertEqual(caught.exception.workflow_code, "ARTIFACT_MISSING")

    def test_a_declared_but_unproduced_artifact_is_reported(self):
        with self.assertRaises(E.ProviderError) as caught:
            self.run_scenario("missing_artifact")
        self.assertEqual(caught.exception.code, "PROVIDER_ARTIFACT_MISSING")
        self.assertEqual(
            caught.exception.details["artifacts"], ["never-written.wav"]
        )

    def test_a_staged_artifact_counts_as_produced(self):
        """Staged output lives outside its destination until the node succeeds."""
        staging = tempfile.mkdtemp(prefix="sts_stage_")
        self.addCleanup(shutil.rmtree, staging, ignore_errors=True)

        def stage(destination):
            return os.path.join(staging, os.path.basename(destination))

        result = self.run_scenario("sync", stage_artifact=stage)
        self.assertEqual(result.artifact_refs, ["tts/pm_ABC123/voice.wav"])
        self.assertFalse(os.path.exists(resolve_ref(result.artifact_refs[0],
                                                    output_dir=self.output_dir)))

    def test_resolve_ref_refuses_an_absolute_reference(self):
        with self.assertRaises(E.ProviderError):
            resolve_ref("/etc/passwd", output_dir=self.output_dir)

    def test_a_stager_records_what_it_staged(self):
        stager = ArtifactStager(None)
        returned = stager(os.path.join(self.output_dir, "a.wav"))
        self.assertTrue(stager.staged(returned))
        self.assertFalse(stager.staged(os.path.join(self.output_dir, "b.wav")))


class EgressValidatorTests(unittest.TestCase):
    """§36: enforcement is mechanical, not by review."""

    def test_absolute_paths_are_rejected(self):
        self.assertTrue(validate_egress({"path": "/var/data/x.wav"}))
        self.assertTrue(validate_egress({"path": "C:\\data\\x.wav"}))
        self.assertTrue(validate_egress({"path": "\\\\server\\share\\x.wav"}))
        self.assertEqual(validate_egress({"ref": "tts/pm_X/voice.wav"}), [])
        self.assertEqual(validate_egress({"url": "https://example.com/a/b"}), [])

    def test_sensitive_keys_are_rejected(self):
        self.assertTrue(validate_egress({"api_key": "x"}))
        self.assertTrue(validate_egress({"nested": [{"access_token": "x"}]}))

    def test_a_sensitive_key_holding_only_a_marker_is_allowed(self):
        """§31.3's `resolved_settings_redacted` keeps its original key names."""
        self.assertEqual(validate_egress({"api_key": "***"}), [])
        self.assertEqual(validate_egress({"api_key": "[REDACTED]"}), [])

    def test_bytes_and_non_json_values_are_rejected(self):
        self.assertTrue(validate_egress({"audio": b"RIFF"}))
        self.assertTrue(validate_egress({"handle": object()}))


class LeakyResultTests(RuntimeCase):
    def test_a_leaky_result_is_rejected_at_the_boundary(self):
        with self.assertRaises(E.ProviderError) as caught:
            self.run_scenario("leaky_result")
        self.assertEqual(caught.exception.code, "PROVIDER_RESULT_INVALID")


# -- §34 errors and the wrapping boundary ------------------------------------


class ProviderErrorTests(unittest.TestCase):
    def test_the_code_catalog_fixes_retryability(self):
        """§34.3: a provider may not mark an auth failure retryable."""
        self.assertFalse(E.is_retryable(E.PROVIDER_AUTH_FAILED))
        self.assertTrue(E.is_retryable(E.PROVIDER_RATE_LIMITED))
        self.assertTrue(E.is_retryable(E.PROVIDER_TIMEOUT))
        self.assertFalse(E.is_retryable(E.PROVIDER_QUOTA_EXHAUSTED))
        self.assertFalse(E.is_retryable(E.CANCELLED))

    def test_the_workflow_code_set_does_not_grow(self):
        """§34.2: PROVIDER_* codes stay in the provider layer."""
        stable = {
            "PROVIDER_UNAVAILABLE", "POLL_TIMEOUT", "CANCELLED",
            "ARTIFACT_MISSING", "NODE_EXECUTION_FAILED",
        }
        for code in E.PROVIDER_CODES:
            self.assertIn(E.workflow_code(code), stable, code)

    def test_message_is_sanitized_on_construction(self):
        error = E.ProviderError(
            E.PROVIDER_FAILED,
            "failed reading C:\\secrets\\creds.json with api_key=sk-abc123def456",
        )
        self.assertNotIn("C:\\secrets", error.message)
        self.assertNotIn("sk-abc123def456", error.message)
        self.assertIn("creds.json", error.message)

    def test_message_is_capped_at_300_characters(self):
        self.assertLessEqual(len(E.ProviderError(E.PROVIDER_FAILED, "x" * 900).message), 300)

    def test_details_are_redacted_json_only_and_size_capped(self):
        self.assertIsNone(E.ProviderError(E.PROVIDER_FAILED, "x", details=object()).details)
        self.assertEqual(
            E.ProviderError(E.PROVIDER_FAILED, "x", details={"api_key": "s"}).details,
            {"api_key": "[REDACTED]"},
        )
        oversized = E.ProviderError(
            E.PROVIDER_FAILED, "x", details={"blob": "y" * 8000}
        )
        self.assertEqual(oversized.details, {"truncated": True})

    def test_as_adapter_error_carries_the_precise_code_in_details(self):
        """§34.4: the two layers map without importing each other."""
        adapter_error = E.ProviderError(
            E.PROVIDER_AUTH_FAILED, "bad credentials", provider_id="fixture_provider"
        ).as_adapter_error()
        self.assertEqual(adapter_error.code, "NODE_EXECUTION_FAILED")
        self.assertEqual(adapter_error.details["provider_code"], "PROVIDER_AUTH_FAILED")
        self.assertIs(adapter_error.details["retryable"], False)

    def test_provider_cancelled_has_fixed_semantics(self):
        cancelled = E.ProviderCancelled()
        self.assertEqual(cancelled.code, "CANCELLED")
        self.assertFalse(cancelled.retryable)
        self.assertEqual(cancelled.as_adapter_error().code, "CANCELLED")

    def test_payload_round_trip(self):
        original = E.ProviderError(
            E.PROVIDER_RATE_LIMITED, "slow down", unit_index=3, cause_type="HTTPError"
        )
        rebuilt = E.ProviderError.from_payload(original.to_payload())
        self.assertEqual(rebuilt.to_payload(), original.to_payload())


class ExceptionBoundaryTests(RuntimeCase):
    def test_a_terminal_error_is_not_retryable(self):
        with self.assertRaises(E.ProviderError) as caught:
            self.run_scenario("terminal_error")
        self.assertEqual(caught.exception.code, "PROVIDER_AUTH_FAILED")
        self.assertFalse(caught.exception.retryable)

    def test_a_retryable_error_declares_itself(self):
        with self.assertRaises(E.ProviderError) as caught:
            self.run_scenario("retryable_error")
        self.assertEqual(caught.exception.code, "PROVIDER_RATE_LIMITED")
        self.assertTrue(caught.exception.retryable)

    def test_an_unknown_exception_never_leaks_its_text(self):
        """§34.4 rule 3 — the substantive change this step makes."""
        with self.assertRaises(E.ProviderError) as caught:
            self.run_scenario("secret_bearing_exception")
        error = caught.exception
        self.assertEqual(error.code, "PROVIDER_FAILED")
        self.assertEqual(error.cause_type, "RuntimeError")
        self.assertNotIn("sk-abc123def456", error.message)
        self.assertNotIn("C:\\secret", error.message)
        self.assertNotIn("secret", error.message.lower())
        self.assertEqual(error.message, E.generic_message("tts"))
        self.assertIsNone(error.details)

    def test_the_traceback_is_logged_internal_only(self):
        invocation = self.invocation("secret_bearing_exception")
        with self.assertRaises(E.ProviderError):
            boundary.invoke(
                lambda inv: self.instance.invoke({}, inv), invocation
            )
        internal = [r for r in invocation.log.records if r["internal"]]
        self.assertTrue(internal)
        self.assertEqual(invocation.log.entries(), [])

    def test_classification_of_common_exception_families(self):
        self.assertEqual(boundary.classify(TimeoutError()), "PROVIDER_TIMEOUT")
        self.assertEqual(boundary.classify(ConnectionError()), "PROVIDER_TRANSPORT_FAILED")
        self.assertEqual(boundary.classify(ValueError()), "PROVIDER_RESPONSE_MALFORMED")
        self.assertEqual(boundary.classify(MemoryError()), "PROVIDER_FAILED")

    def test_an_already_typed_provider_error_passes_through_unchanged(self):
        original = E.ProviderError(E.PROVIDER_QUOTA_EXHAUSTED, "out of credit")
        self.assertIs(boundary.wrap_exception(original), original)


class CancellationAndTimeoutTests(RuntimeCase):
    def test_cancellation_before_dispatch_never_starts_the_provider(self):
        calls = []
        invocation = self.invocation("sync", stop_requested=lambda: True)
        with self.assertRaises(E.ProviderCancelled):
            boundary.invoke(lambda inv: calls.append(inv), invocation)
        self.assertEqual(calls, [])

    def test_a_provider_declaring_cancel_observes_the_flag(self):
        with self.assertRaises(E.ProviderCancelled):
            self.run_scenario("cancel", stop_requested=lambda: True)

    def test_cancellation_is_not_wrapped_as_a_failure(self):
        with self.assertRaises(E.ProviderCancelled) as caught:
            self.run_scenario("cancel", stop_requested=lambda: True)
        self.assertEqual(caught.exception.workflow_code, "CANCELLED")

    def test_the_deadline_raises_PROVIDER_TIMEOUT(self):
        with self.assertRaises(E.ProviderError) as caught:
            self.run_scenario("slow", deadline_s=0.05)
        self.assertEqual(caught.exception.code, "PROVIDER_TIMEOUT")
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.workflow_code, "POLL_TIMEOUT")

    def test_wait_until_prefers_cancellation_over_timeout(self):
        invocation = self.invocation("sync", stop_requested=lambda: True, deadline_s=0.0)
        with self.assertRaises(E.ProviderCancelled):
            boundary.wait_until(lambda: False, invocation=invocation, interval_s=0.01)

    def test_deadline_remaining_counts_down(self):
        clock = {"t": 0.0}
        deadline = boundary.Deadline(10.0, clock=lambda: clock["t"])
        self.assertEqual(deadline.remaining(), 10.0)
        clock["t"] = 4.0
        self.assertEqual(deadline.remaining(), 6.0)
        clock["t"] = 99.0
        self.assertTrue(deadline.expired())
        with self.assertRaises(E.ProviderError):
            deadline.check()


# -- §33 the job contract ----------------------------------------------------


class JobContractTests(RuntimeCase):
    def test_async_success_through_submit_and_poll(self):
        invocation = self.invocation("sync")
        handle = self.instance.submit({}, invocation)
        self.assertEqual(handle.correlation,
                         ("tts", "fixture_provider", "pm_ABC123", handle.job_id))
        status = self.instance.poll(handle.job_id, invocation)
        self.assertEqual(status.state, RUNNING)
        status = self.instance.poll(handle.job_id, invocation)
        self.assertEqual(status.state, SUCCEEDED)
        self.assertEqual(terminal_outcome(status), SUCCEEDED)

    def test_cancel_job_moves_to_the_cancelled_terminal_state(self):
        invocation = self.invocation("sync")
        handle = self.instance.submit({}, invocation)
        self.instance.cancel_job(handle.job_id, invocation)
        status = self.instance.jobs[handle.job_id]
        self.assertEqual(status.state, JOB_CANCELLED)
        with self.assertRaises(E.ProviderCancelled):
            terminal_outcome(status)


class JobTypeTests(unittest.TestCase):
    def test_the_two_duplicate_definitions_are_now_one(self):
        """§14.6/§33.1: both `base.py` modules re-export the shared types."""
        from scriptase.modules.video.providers import base as animator_base
        from scriptase.providers import jobs
        from scriptase.modules.image.providers import base as storyboard_base

        for name in ("JobHandle", "JobStatus", "SceneResult"):
            self.assertIs(getattr(storyboard_base, name), getattr(jobs, name), name)
            self.assertIs(getattr(animator_base, name), getattr(jobs, name), name)
        # `SceneResult`'s image/video split is gone: one media-neutral shape.
        self.assertIs(jobs.SceneResult, UnitResult)

    def test_a_job_id_must_match_the_frozen_pattern(self):
        JobHandle(job_id="job.1:a-b_c")
        with self.assertRaises(E.ProviderError):
            JobHandle(job_id="not ok!")
        with self.assertRaises(E.ProviderError):
            JobHandle(job_id="x" * 129)

    def test_the_handle_carries_identity_only(self):
        """§33.1: live state on a frozen handle would go stale immediately."""
        self.assertNotIn("state", JobHandle(job_id="a").to_dict())
        self.assertNotIn("status", JobHandle(job_id="a").to_dict())

    def test_state_is_a_closed_vocabulary(self):
        with self.assertRaises(E.ProviderError):
            JobStatus(job_id="a", state="processing")

    def test_transitions_are_monotonic(self):
        status = JobStatus(job_id="a", state=SUBMITTED, total=3)
        status = status.advance(state=RUNNING, ready=1)
        status = status.advance(ready=0)
        self.assertEqual(status.ready, 1)
        status = status.advance(total=99)
        self.assertEqual(status.total, 3)
        terminal = status.advance(state=SUCCEEDED)
        with self.assertRaises(E.ProviderError):
            terminal.advance(state=RUNNING)

    def test_every_terminal_state_maps_to_one_invocation_outcome(self):
        """§33.2: sync and async providers are indistinguishable to callers."""
        self.assertEqual(terminal_outcome(JobStatus("a", SUCCEEDED)), SUCCEEDED)
        self.assertEqual(terminal_outcome(JobStatus("a", PARTIAL)), PARTIAL)
        with self.assertRaises(E.ProviderCancelled):
            terminal_outcome(JobStatus("a", JOB_CANCELLED))
        with self.assertRaises(E.ProviderError) as timed_out:
            terminal_outcome(JobStatus("a", TIMED_OUT))
        self.assertEqual(timed_out.exception.code, "PROVIDER_TIMEOUT")
        with self.assertRaises(E.ProviderError) as failed:
            terminal_outcome(JobStatus("a", FAILED))
        self.assertEqual(failed.exception.workflow_code, "NODE_EXECUTION_FAILED")

    def test_a_non_terminal_job_has_no_outcome(self):
        with self.assertRaises(E.ProviderError):
            terminal_outcome(JobStatus("a", RUNNING))

    def test_zero_produced_units_can_never_be_succeeded(self):
        status = JobStatus(
            "a", SUCCEEDED,
            units=(UnitResult(0, UNIT_FAILED, error=_error()),
                   UnitResult(1, UNIT_FAILED, error=_error())),
        )
        with self.assertRaises(E.ProviderError) as caught:
            terminal_outcome(status)
        self.assertEqual(caught.exception.code, "PROVIDER_UNIT_FAILED")

    def test_a_failed_status_always_carries_an_error(self):
        self.assertIsNotNone(JobStatus("a", FAILED).error)

    def test_an_unknown_job_fails_instead_of_waiting_out_the_deadline(self):
        status = unknown_job_status("a")
        self.assertEqual(status.state, FAILED)
        self.assertEqual(status.error.code, "PROVIDER_NOT_FOUND")

    def test_timed_out_preserves_already_terminal_units_as_diagnostics(self):
        """§35.3: the current code raises a bare RuntimeError with no partial data."""
        status = JobStatus(
            "a", TIMED_OUT, ready=1, total=3,
            units=(UnitResult(0, UNIT_SUCCEEDED, artifact_refs=("a/0.png",)),),
        )
        with self.assertRaises(E.ProviderError) as caught:
            terminal_outcome(status)
        self.assertEqual(caught.exception.details["ready"], 1)
        self.assertEqual(len(caught.exception.details["units"]), 1)

    def test_a_message_is_sanitized(self):
        status = JobStatus("a", RUNNING, message="reading C:\\secret\\job.json")
        self.assertNotIn("C:\\secret", status.message)

    def test_job_records_round_trip_for_persistence(self):
        """§33.4: a job handle survives a process restart."""
        record = JobRecord(
            handle=JobHandle("job-1", "image", "gemini_ws", "pm_ABC123"),
            status=JobStatus("job-1", RUNNING, ready=1, total=3),
        )
        rebuilt = JobRecord.from_dict(record.to_dict())
        self.assertEqual(rebuilt.to_dict(), record.to_dict())
        self.assertEqual(validate_egress(record.to_dict()), [])

    def test_poll_cadence_matches_todays_values(self):
        self.assertEqual(poll_interval("image"), 10.0)
        self.assertEqual(poll_interval("video"), 10.0)
        self.assertEqual(poll_interval("image", push=True), 60.0)


def _error():
    return E.ProviderErrorPayload.from_error(
        E.ProviderError(E.PROVIDER_UNIT_FAILED, "unit failed")
    )


# -- §46 the provider fixture layer ------------------------------------------


class ProviderFixtureTests(unittest.TestCase):
    def test_the_committed_fixture_set_is_frozen_and_sanitized(self):
        """§46.4: an accidental edit fails here rather than changing meaning."""
        self.assertEqual(fixtures.validate_fixtures(), [])

    def test_every_recorded_boundary_has_all_three_files(self):
        boundaries = fixtures.list_boundaries()
        self.assertTrue(boundaries)
        for domain, provider_id in boundaries:
            for name in fixtures.FIXTURE_FILES:
                with self.subTest(boundary=f"{domain}/{provider_id}", file=name):
                    self.assertIsNotNone(
                        fixtures.load_fixture(domain, provider_id, name)
                    )

    def test_the_sanitation_validator_catches_what_it_must(self):
        self.assertTrue(fixtures.validate_sanitation({"p": "C:\\Users\\me\\x.json"}))
        self.assertTrue(fixtures.validate_sanitation({"k": "sk-abcdefgh12345678"}))
        self.assertTrue(fixtures.validate_sanitation({"account_id": "acct_1"}))
        self.assertTrue(fixtures.validate_sanitation({"ts": "2025-07-04T11:22:33Z"}))
        self.assertEqual(fixtures.validate_sanitation({"ts": "2026-01-01T00:00:00Z"}), [])
        # A recorded response may keep its managed /output URL and its synthetic
        # remote URL — that is exactly the code the egress rule must exercise.
        self.assertEqual(
            fixtures.validate_sanitation({"local_path": "/output/storyboard/p/0/i.png"}),
            [],
        )

    def test_expected_results_are_egress_clean_but_raw_responses_need_not_be(self):
        raw = fixtures.load_fixture("image", "wavespeed_webhook", "raw_response.json")
        expected = fixtures.load_fixture(
            "image", "wavespeed_webhook", "expected_result.json"
        )
        self.assertTrue(validate_egress(raw), "the raw response keeps its /output URLs")
        self.assertEqual(validate_egress(expected), [])


class LegacyEnvelopeDiffTests(unittest.TestCase):
    """The recorded legacy payloads must reach the envelope field for field."""

    def _rebuild(self, domain, provider_id, builder):
        raw = fixtures.load_fixture(domain, provider_id, "raw_response.json")
        result = coerce_result(
            builder(raw), domain=domain, provider_id=provider_id, provider_version="1.0.0"
        )
        expected = fixtures.load_fixture(domain, provider_id, "expected_result.json")
        return result.to_dict(), expected

    def test_tts_legacy_metadata_matches_the_recorded_envelope(self):
        produced, expected = self._rebuild("tts", "kokoro", lambda raw: (
            legacy.tts_metadata_to_result(
                raw,
                audio_ref="tts/pm_SAMPLE/voice.wav",
                manifest_ref="tts/pm_SAMPLE/tts.json",
                provider_id="kokoro",
                provider_version="1.0.0",
            )
        ))
        self.assertEqual(produced, expected)

    def test_every_legacy_tts_key_is_accounted_for(self):
        """Nothing is silently lost: each key is payload, metadata, or approved."""
        raw = fixtures.load_fixture("tts", "kokoro", "raw_response.json")
        envelope = fixtures.load_fixture("tts", "kokoro", "expected_result.json")
        carried = set(envelope["payload"]) | set(envelope["metadata"])
        for key in raw:
            with self.subTest(key=key):
                if key in legacy.TTS_DROPPED_KEYS:
                    # `wav_path` is the §36 L7 absolute path, deprecated with an
                    # owner; `job_meta` is superseded by `provenance` (D39).
                    self.assertIn(key, {"wav_path", "job_meta"})
                    continue
                self.assertIn(key, carried)
        self.assertEqual(
            envelope["provenance"]["resolved_settings_redacted"],
            raw["job_meta"]["resolved_settings_redacted"],
        )

    def test_visual_manifests_match_the_recorded_envelopes(self):
        for domain, provider_id, manifest_ref in (
            ("image", "wavespeed_webhook", "storyboard/pm_SAMPLE/storyboard.json"),
            ("video", "kie_ai", "animator/pm_SAMPLE/grabber_job.json"),
        ):
            with self.subTest(domain=domain):
                produced, expected = self._rebuild(
                    domain, provider_id,
                    lambda raw, d=domain, p=provider_id, m=manifest_ref: (
                        legacy.visual_manifest_to_result(
                            raw, domain=d, provider_id=p, manifest_ref=m,
                            provider_version="1.0.0",
                        )
                    ),
                )
                self.assertEqual(produced, expected)

    def test_remote_urls_never_cross_into_a_result(self):
        """§36 L9: the downloaded file is the output, not the CDN link."""
        for domain, provider_id in (
            ("image", "wavespeed_webhook"), ("video", "kie_ai")
        ):
            with self.subTest(domain=domain):
                raw = fixtures.load_fixture(domain, provider_id, "raw_response.json")
                envelope = fixtures.load_fixture(
                    domain, provider_id, "expected_result.json"
                )
                self.assertIn("cdn.example.invalid", str(raw))
                self.assertNotIn("cdn.example.invalid", str(envelope))
                self.assertNotIn("scene_statuses", str(envelope))

    def test_a_raw_exception_string_becomes_a_bounded_unit_error(self):
        """§31.5 rule 6 / §36 L3: closes the `"error": str(e)` leak."""
        units = legacy.storyboard_manifest_to_units({
            "scene_statuses": {
                "0": {"status": "error",
                      "error": "boom at C:\\projects\\out.png api_key=sk-abc123def456"},
            }
        })
        payload = units[0].error.to_dict()
        self.assertEqual(payload["code"], "PROVIDER_UNIT_FAILED")
        self.assertNotIn("C:\\projects", payload["message"])
        self.assertNotIn("sk-abc123def456", payload["message"])
        self.assertEqual(validate_egress(units[0].to_dict()), [])

    def test_the_abc_tts_result_maps_onto_the_payload(self):
        """§32.3: `audio_path` (absolute) becomes `audio_ref` (relative)."""
        from scriptase.modules.tts.providers.base import TTSResult

        payload = legacy.tts_result_to_payload(
            TTSResult(
                audio_path=os.path.join("C:", "out", "voice.wav"),
                duration_seconds=8.0,
                sample_rate=24000,
                metadata={"voice": "af_heart", "characters_billed": 42},
            ),
            audio_ref="tts/pm_SAMPLE/voice.wav",
        )
        self.assertEqual(payload["audio_ref"], "tts/pm_SAMPLE/voice.wav")
        self.assertNotIn("audio_path", payload)
        self.assertEqual(validate_egress(payload), [])

    def test_the_legacy_job_status_maps_onto_the_closed_vocabulary(self):
        """§33.1: provider-defined strings become one state machine."""
        class Legacy:
            def __init__(self, status, error=None):
                self.job_id = "job-1"
                self.status = status
                self.progress = 0.5
                self.message = None
                self.result = None
                self.error = error

        cases = {
            "pending": SUBMITTED, "processing": RUNNING, "complete": SUCCEEDED,
            "done": SUCCEEDED, "failed": FAILED, "cancelled": JOB_CANCELLED,
            "something-nobody-defined": RUNNING,
        }
        for raw, expected in cases.items():
            with self.subTest(status=raw):
                self.assertEqual(legacy.job_status_from_legacy(Legacy(raw)).state, expected)

        with_error = legacy.job_status_from_legacy(Legacy("failed", error="boom"))
        self.assertEqual(with_error.error.code, "PROVIDER_UNIT_FAILED")


if __name__ == "__main__":
    unittest.main()
