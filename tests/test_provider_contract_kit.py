"""Step 16.2: reusable provider contract-test kit (suites + fakes)."""

from __future__ import annotations

import unittest

from scriptase.providers.contract_tests import (
    AsyncMultiAssetContractSuite,
    FakeAsyncMultiAssetProvider,
    FakeSyncArtifactProvider,
    FakeSyncDocumentProvider,
    SyncArtifactContractSuite,
    SyncDocumentContractSuite,
    assert_egress_clean,
    assert_health_shape,
    assert_manifest_v2,
    assert_settings_schema,
    run_suite_methods,
)
from scriptase.providers.registry import ProviderManifest
from scriptase.providers.results import ProviderResult


def test_assert_manifest_v2_accepts_contract_v2_shape():
    manifest = ProviderManifest(
        id="kit_demo",
        label="Kit demo",
        domain="script",
        kind="local",
        version="1.0.0",
        contract_version=2,
        capabilities={"test_connection": True, "offline": True},
        description="Offline kit demo.",
    )
    assert_manifest_v2(manifest, folder_id="kit_demo", domain="script")


def test_assert_manifest_v2_rejects_contract_v1():
    manifest = ProviderManifest(
        id="kit_demo",
        label="Kit demo",
        domain="script",
        kind="local",
        version="1.0.0",
        contract_version=1,
        capabilities={},
    )
    try:
        assert_manifest_v2(manifest, folder_id="kit_demo", domain="script")
    except AssertionError as exc:
        assert "contract_version=2" in str(exc)
    else:
        raise AssertionError("expected contract_version=1 to fail the v2 helper")


def test_assert_settings_schema_and_health_shapes():
    assert_settings_schema(None)
    assert_settings_schema({
        "type": "object",
        "properties": {"api_key": {"type": "string"}},
        "required": ["api_key"],
    })
    assert_health_shape({"status": "ok", "message": "ready", "latency_ms": 1})


def test_sync_document_suite_passes_on_fake():
    run_suite_methods(SyncDocumentContractSuite)


def test_sync_artifact_suite_passes_on_fake():
    run_suite_methods(SyncArtifactContractSuite)


def test_async_multi_asset_suite_passes_on_fake():
    run_suite_methods(AsyncMultiAssetContractSuite)


def test_fake_async_partial_path():
    class PartialSuite(AsyncMultiAssetContractSuite):
        def make_provider(self):
            return FakeAsyncMultiAssetProvider(fail_last=True)

        def test_submit_poll_reaches_terminal_success(self):
            # Replace the success case with the partial path.
            import os
            from scriptase.providers.invocation import build_invocation
            from scriptase.providers.results import PARTIAL

            out = os.path.join(self.output_root, self.domain, self.project_id)
            os.makedirs(out, exist_ok=True)
            invocation = build_invocation(
                None,
                domain=self.domain,
                provider_id=self.provider_id,
                project_id=self.project_id,
                output_dir=out,
                settings={},
                options={"unit_count": 2},
            )
            handle = self.provider.submit(self.sample_request(), invocation)
            status = None
            for _ in range(4):
                status = self.provider.poll(handle.job_id, invocation)
                if status.state in {PARTIAL, "succeeded", "failed"}:
                    break
            assert status is not None
            assert status.state == PARTIAL

    run_suite_methods(PartialSuite)


def test_fake_providers_shut_down_idempotently():
    for provider in (
        FakeSyncDocumentProvider(),
        FakeSyncArtifactProvider(),
        FakeAsyncMultiAssetProvider(),
    ):
        provider.shutdown()
        provider.shutdown()
        assert provider.shutdown_calls == 2


def test_assert_egress_clean_on_empty_envelope():
    assert_egress_clean(ProviderResult(payload={"ok": True}, artifact_refs=[]))


class UnittestStyleSuiteSmoke(SyncDocumentContractSuite, unittest.TestCase):
    """Prove the mixin still works under unittest.TestCase."""

    def make_provider(self):
        return FakeSyncDocumentProvider(prefix="unittest")
