"""Step 0.4 gate: contract freeze, provenance reproducibility, node catalogue.

Done-when for 0.4:
  * contracts.md covers every schema Phases 1–10 touch (doc review; this module
    pins the machine half),
  * Provenance carries seed / request_id / model_revision through the result
    envelope,
  * the app boots and serves the full node catalogue from
    GET /api/workflow/node-types.
"""

from __future__ import annotations

import unittest

from app import create_app
from scriptase.providers.boundary import build_provenance, invoke
from scriptase.providers.invocation import build_invocation
from scriptase.providers.results import (
    Provenance,
    ProviderResult,
    UnitResult,
    coerce_result,
    extract_reproducibility,
    validate_egress,
)


# Core production + utility nodes the catalogue must expose after the 0.2/0.3 port.
REQUIRED_NODE_TYPES = frozenset({
    "trigger.manual",
    "project.setup",
    "script.input",
    "story.generate",
    "project.existing",
    "tts.generate",
    "timing.align",
    "segment.run",
    "scenes.blueprint",
    "storyboard.generate",
    "animator.generate",
    "captions.generate",
    "music.select",
    "assemble.project",
    "timeline.project",
    "export.video",
    "workflow.output",
    "stub.input",
    "stub.output",
    "utility.set_value",
    "utility.condition",
    "utility.wait",
    "utility.merge",
})


class ProvenanceReproducibilityTests(unittest.TestCase):
    """seed / request_id / model_revision ride the result envelope."""

    def test_provenance_dict_carries_reproducibility_fields(self):
        provenance = Provenance(
            provider_id="wavespeed_direct",
            seed=42,
            request_id="req_abc",
            model_revision="flux-dev@2026-01",
        )
        payload = provenance.to_dict()
        self.assertEqual(payload["seed"], 42)
        self.assertEqual(payload["request_id"], "req_abc")
        self.assertEqual(payload["model_revision"], "flux-dev@2026-01")
        self.assertIn("provider_instance_id", payload)
        self.assertIn("cost", payload)
        # Egress-clean by construction.
        self.assertEqual(validate_egress({"provenance": payload}), [])

    def test_extract_reproducibility_from_metadata_and_options(self):
        harvested = extract_reproducibility(
            metadata={
                "seed": "7",
                "request_id": "upstream-99",
                "model": "inworld-tts-1.5-max",
            },
            options={"seed": 99},  # metadata wins when present
        )
        self.assertEqual(harvested["seed"], 7)
        self.assertEqual(harvested["request_id"], "upstream-99")
        self.assertEqual(harvested["model_revision"], "inworld-tts-1.5-max")

    def test_extract_never_invents_values(self):
        harvested = extract_reproducibility(metadata={}, options={})
        self.assertIsNone(harvested["seed"])
        self.assertEqual(harvested["request_id"], "")
        self.assertEqual(harvested["model_revision"], "")

    def test_coerce_result_round_trips_provenance_reproducibility(self):
        envelope = coerce_result(
            {
                "status": "succeeded",
                "payload": {"ok": True},
                "metadata": {
                    "seed": 11,
                    "request_id": "rid-1",
                    "model_revision": "m@1",
                },
                "provenance": {
                    "seed": 11,
                    "request_id": "rid-1",
                    "model_revision": "m@1",
                    "provider_id": "fixture",
                },
            },
            domain="tts",
            provider_id="fixture",
        )
        prov = envelope.provenance.to_dict()
        self.assertEqual(prov["seed"], 11)
        self.assertEqual(prov["request_id"], "rid-1")
        self.assertEqual(prov["model_revision"], "m@1")
        # Envelope carries provenance intact.
        full = envelope.to_dict()
        self.assertEqual(full["provenance"]["seed"], 11)
        self.assertEqual(full["provenance"]["request_id"], "rid-1")
        self.assertEqual(full["provenance"]["model_revision"], "m@1")

    def test_build_provenance_harvests_from_result_metadata(self):
        invocation = build_invocation(
            None,
            domain="image",
            provider_id="wavespeed_direct",
            project_id="pm_TEST1",
            settings={"api_key": "sk-secret"},
            options={"seed": 3},
        )
        result = ProviderResult(
            metadata={
                "seed": 3,
                "request_id": "ws-req-1",
                "model_revision": "flux-1",
            }
        )
        provenance = build_provenance(
            invocation,
            result=result,
            provider_version="1.0.0",
            contract_version=2,
        )
        self.assertEqual(provenance.seed, 3)
        self.assertEqual(provenance.request_id, "ws-req-1")
        self.assertEqual(provenance.model_revision, "flux-1")
        self.assertEqual(provenance.provider_id, "wavespeed_direct")
        # Secret stays redacted.
        self.assertEqual(
            provenance.resolved_settings_redacted.get("api_key"), "***"
        )
        self.assertNotIn("sk-secret", str(provenance.to_dict()))

    def test_invoke_puts_reproducibility_on_the_envelope(self):
        invocation = build_invocation(
            None,
            domain="tts",
            provider_id="fixture",
            project_id="pm_TEST2",
            settings={},
            options={"seed": 99},
        )

        def call(_invocation):
            return ProviderResult(
                payload={"audio_ref": "tts/pm_TEST2/voice.wav"},
                artifact_refs=[],
                metadata={
                    "seed": 99,
                    "request_id": "call-1",
                    "model": "fixture-tts",
                },
            )

        result = invoke(
            call,
            invocation,
            provider_version="1.0.0",
            contract_version=2,
            verify_artifacts=False,
        )
        self.assertEqual(result.provenance.seed, 99)
        self.assertEqual(result.provenance.request_id, "call-1")
        self.assertEqual(result.provenance.model_revision, "fixture-tts")
        envelope = result.to_dict()
        self.assertEqual(envelope["provenance"]["seed"], 99)
        self.assertEqual(envelope["provenance"]["request_id"], "call-1")
        self.assertEqual(envelope["provenance"]["model_revision"], "fixture-tts")

    def test_unit_result_sparse_reproducibility_overrides(self):
        """Per-unit overrides are frozen for 8.3; absent means inherit envelope."""
        plain = UnitResult(0).to_dict()
        self.assertNotIn("seed", plain)
        self.assertNotIn("request_id", plain)
        self.assertNotIn("model_revision", plain)

        override = UnitResult(
            1,
            seed=5,
            request_id="u-1",
            model_revision="m-b",
            provider_id="backup",
            selection_reason="fallback_after:inst_main",
        ).to_dict()
        self.assertEqual(override["seed"], 5)
        self.assertEqual(override["request_id"], "u-1")
        self.assertEqual(override["model_revision"], "m-b")
        self.assertEqual(override["provider_id"], "backup")
        self.assertEqual(override["selection_reason"], "fallback_after:inst_main")

        restored = UnitResult.from_dict(override)
        self.assertEqual(restored.seed, 5)
        self.assertEqual(restored.provider_id, "backup")


class NodeCatalogueGateTests(unittest.TestCase):
    """App boots and serves the full node catalogue."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app(discover_providers=True)
        cls.client = cls.app.test_client()

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["status"], "ok")

    def test_node_types_catalogue(self):
        response = self.client.get("/api/workflow/node-types")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertIn("registry_version", body)
        self.assertIn("port_types", body)
        self.assertIn("node_types", body)
        node_types = body["node_types"]
        self.assertIsInstance(node_types, dict)
        missing = sorted(REQUIRED_NODE_TYPES - set(node_types))
        self.assertEqual(missing, [], f"node catalogue missing types: {missing}")
        # No executor internals leak to the browser.
        for type_key, definition in node_types.items():
            self.assertNotIn("executor", definition, type_key)
            self.assertNotIn("module", definition.get("config_schema") or {}, type_key)


if __name__ == "__main__":
    unittest.main()
