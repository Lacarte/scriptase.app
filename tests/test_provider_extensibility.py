"""Step 12.5: the no-node-edit extensibility proof and the Phase 12 gate.

contracts.md §26 asserts that adding a provider to an existing domain is one
new folder and *nothing else*. Every earlier step in Phase 12 was built on that
promise; this file is where it stops being a promise.

Three test-only provider packages, one per execution shape the platform has to
support, are discovered normally and driven through the whole chain:

    catalog → settings → selection → node validation → execution → §31 result

    tests/fixture_providers/script/fixture_document    sync document
    tests/fixture_providers/tts/fixture_artifact       sync artifact
    tests/fixture_providers/image/fixture_async   async multi-asset

They are registered by pointing a `DomainSpec.providers_base` at their folder,
the mechanism §46.3 already established for `fixture_provider`, so they never
appear in the shipped catalog. `ZeroTouchDiffTests` is the mechanical half of
the claim: it fails if any of these ids leaks outside `tests/`, and if any
shipped provider id appears in a §26 platform surface.

Deliberately *not* covered: executing the sync-artifact and async shapes
through `tts.generate` / `storyboard.generate`. Those adapters still dispatch
into `_step_tts` / `_step_storyboard`, which branch on provider id — the
branches steps 14.2, 14.3, and 15.2 own. Both shapes are executed here through
the standard runtime instead, which is the platform's own execution path, and
`test_provider_extensibility` will pick the node paths up when their owners
land. `story.generate` already dispatches generically, so the sync-document
shape is proved end to end on a real, unmodified node.
"""

import importlib
import json
import os
import shutil
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch

from flask import Flask

from config import ROOT_DIR
from scriptase.providers import providers_bp
from scriptase.providers import catalog as catalog_module
from scriptase.providers import routes as routes_module
from scriptase.providers import boundary, settings_manager
from scriptase.providers.domains import DOMAINS, DomainSpec
from scriptase.providers.hub import ProviderHub
from scriptase.providers.invocation import build_invocation
from scriptase.providers.registry import (
    AVAILABLE,
    NEEDS_CONFIGURATION,
)
from scriptase.providers.results import (
    PARTIAL,
    RESULT_VERSION,
    SUCCEEDED,
    UNIT_FAILED,
    UNIT_SUCCEEDED,
    validate_egress,
)
from scriptase.engine import options as options_module
from scriptase.engine.adapters.common import AdapterContext
from scriptase.engine.models import workflow_draft
from scriptase.engine.registry import ASYNC_OPTION_SOURCES, all_node_types
from scriptase.engine.validation import validate_workflow, validation_errors


# `providers_common.__init__` re-exports the `hub` *singleton*, which shadows
# the submodule of the same name for `from ... import` — patching the attribute
# needs the module object itself.
hub_module = importlib.import_module("scriptase.providers.hub")

FIXTURE_ROOT = os.path.join(ROOT_DIR, "tests", "fixture_providers")

# domain -> (folder, provider id). The three execution shapes.
SHAPES = {
    "script": ("script", "fixture_document"),
    "tts": ("tts", "fixture_artifact"),
    "image": ("image", "fixture_async"),
}

FIXTURE_IDS = tuple(provider_id for _folder, provider_id in SHAPES.values())

PROJECT_ID = "pm_ABC123"


def shape_spec(domain: str) -> DomainSpec:
    """A `DomainSpec` for a real domain, pointed at that domain's fixtures.

    Everything else about the domain — its label, its capability vocabulary —
    is the shipped one, so the fixtures are validated against exactly the rules
    a real provider in that domain faces.
    """
    folder, provider_id = SHAPES[domain]
    shipped = DOMAINS[domain]
    return DomainSpec(
        id=domain,
        label=shipped.label,
        package=f"tests.fixture_providers.{folder}",
        providers_base=os.path.join(FIXTURE_ROOT, folder),
        default_provider=provider_id,
        capability_vocabulary=shipped.capability_vocabulary,
        legacy_selection_key=shipped.legacy_selection_key,
    )


class ProviderGateCase(unittest.TestCase):
    """Isolated settings and a temp managed output directory."""

    def setUp(self):
        self.output_dir = tempfile.mkdtemp(prefix="sts_12_5_")
        self.addCleanup(shutil.rmtree, self.output_dir, ignore_errors=True)
        self._patch_output_dir(self.output_dir)

        self.settings = {
            "version": settings_manager.SETTINGS_VERSION,
            "general": {},
            "domains": {
                domain: {"selected_instance_id": None, "instances": {}}
                for domain in DOMAINS
            },
        }
        self._patch(patch.object(
            settings_manager, "load_settings",
            side_effect=lambda: deepcopy(self.settings),
        ))
        self._patch(patch.object(
            settings_manager, "save_settings", side_effect=self._save
        ))
        options_module.clear_option_cache()
        self.addCleanup(options_module.clear_option_cache)

    def _save(self, data):
        self.settings = deepcopy(data)

    def _patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def _patch_output_dir(self, path):
        """Point every module-level `OUTPUT_DIR` copy at the temp directory."""
        import config
        from scriptase.providers import results
        from scriptase.engine.adapters import common as adapter_common

        for module in (config, results, adapter_common):
            original = module.OUTPUT_DIR
            module.OUTPUT_DIR = path
            self.addCleanup(setattr, module, "OUTPUT_DIR", original)

    def stored(self, domain, provider_id, values):
        block = self.settings["domains"][domain]
        block.setdefault("instances", {})
        existing = block["instances"].get(provider_id) or {}
        block["instances"][provider_id] = {
            "type": existing.get("type") or provider_id,
            "label": existing.get("label") or provider_id,
            "settings": dict(values),
        }

    def invocation(self, domain, **overrides):
        _folder, provider_id = SHAPES[domain]
        context = AdapterContext(project_id=PROJECT_ID)
        return build_invocation(
            context,
            domain=domain,
            provider_id=provider_id,
            project_id=PROJECT_ID,
            output_dir=os.path.join(self.output_dir, domain, PROJECT_ID),
            settings=overrides.pop("settings", {}),
            options=overrides.pop("options", {}),
            **overrides,
        )


class FixtureCatalogCase(ProviderGateCase):
    """A hub over *only* the three shape fixtures.

    Used where the assertion is about the fixture itself — discovery, the
    catalog payload, the standardized result — so it reads without the seven
    shipped providers in the way.
    """

    def setUp(self):
        super().setUp()
        self.catalog = {domain: shape_spec(domain) for domain in SHAPES}
        self.hub = ProviderHub(self.catalog)
        self.hub.discover_all()
        self.addCleanup(self.hub.shutdown)
        # Every consumer resolves the hub through the module attribute at call
        # time, so one patch reaches routes, catalog, option sources, adapters,
        # and node validation alike.
        self._patch(patch.object(hub_module, "hub", self.hub))


class SharedCatalogCase(ProviderGateCase):
    """The *shipped* hub with the three fixtures added to it.

    The realistic shape of "someone installed a provider": the existing ones
    are still there, the domain defaults still resolve, and saved workflows
    still name providers this test did not write. Registration goes through a
    real discovery scan first, so the packages are validated exactly as the
    shipped ones are.
    """

    def setUp(self):
        super().setUp()
        from scriptase.providers.hub import hub as shipped

        source = ProviderHub({domain: shape_spec(domain) for domain in SHAPES})
        source.discover_all()
        self.addCleanup(source.shutdown)

        for domain, (_folder, provider_id) in SHAPES.items():
            shipped.discover(domain)
            registry = shipped.registry(domain)
            # Restore the shipped snapshot without retiring anything: the
            # instances in it are process-wide and other tests hold them.
            self.addCleanup(registry.publish, registry.snapshot)
            discovered = source.get(domain, provider_id)
            self.assertIsNotNone(discovered)
            registry.register(
                provider_id,
                discovered.module,
                discovered.manifest,
                provider_module=discovered.provider_module,
                schema_module=discovered.schema_module,
            )
        self.hub = shipped


# ---------------------------------------------------------------------------
# Discovery — the folder is the whole registration (§21.2, §26)
# ---------------------------------------------------------------------------

class DiscoveryTests(FixtureCatalogCase):
    def test_every_shape_is_discovered_with_no_registration_code(self):
        for domain, (_folder, provider_id) in SHAPES.items():
            with self.subTest(domain=domain):
                self.assertEqual(self.hub.registry(domain).list_ids(), [provider_id])
                self.assertEqual(self.hub.registry(domain).excluded(), [])

    def test_each_manifest_passes_its_own_domain_capability_vocabulary(self):
        for domain, (_folder, provider_id) in SHAPES.items():
            with self.subTest(domain=domain):
                provider = self.hub.get(domain, provider_id)
                self.assertEqual(provider.warnings, [])
                self.assertEqual(provider.contract_version, 2)
                unknown = set(provider.capabilities) - DOMAINS[domain].capability_vocabulary
                self.assertEqual(unknown, set())

    def test_an_alias_resolves_to_the_canonical_provider(self):
        provider = self.hub.get("script", "fixture-doc")
        self.assertEqual(provider.id, "fixture_document")

    def test_the_shipped_catalog_never_sees_them(self):
        """The fixtures live outside every `DomainSpec.providers_base`."""
        for domain in DOMAINS:
            shipped_base = os.path.abspath(DOMAINS[domain].providers_base)
            self.assertFalse(
                os.path.abspath(FIXTURE_ROOT).startswith(shipped_base),
                f"{domain} would discover the fixture packages",
            )

    def test_a_provider_is_constructed_lazily_and_shut_down(self):
        provider = self.hub.get("tts", "fixture_artifact")
        self.assertFalse(provider.constructed)
        instance = self.hub.create("tts", "fixture_artifact")
        self.assertTrue(provider.constructed)
        self.assertIs(instance, self.hub.create("tts", "fixture_artifact"))
        provider.shutdown()
        self.assertEqual(instance.shutdown_calls, 1)


# ---------------------------------------------------------------------------
# Catalog and API — the provider reaches the browser with no route edit
# ---------------------------------------------------------------------------

class CatalogApiTests(FixtureCatalogCase):
    def setUp(self):
        super().setUp()
        app = Flask(__name__)
        app.register_blueprint(providers_bp)
        self.client = app.test_client()
        for module in (routes_module, catalog_module):
            self._patch(patch.object(module, "hub", self.hub))
            if hasattr(module, "DOMAINS"):
                self._patch(patch.object(module, "DOMAINS", self.catalog))

    def entry(self, domain):
        payload = self.client.get("/api/providers").get_json()
        return payload["domains"][domain]

    def test_the_catalog_serves_every_fixture_from_its_manifest(self):
        entry = self.entry("script")
        (provider,) = entry["providers"]
        self.assertEqual(provider["id"], "fixture_document")
        self.assertEqual(provider["label"], "Fixture Document Generator")
        self.assertEqual(provider["version"], "2.1.0")
        self.assertIs(provider["capabilities"]["structured_sections"], True)
        self.assertTrue(provider["has_settings"])
        # `requires` is unmet, so the catalog says so without any I/O (§21.5).
        self.assertEqual(provider["availability"], NEEDS_CONFIGURATION)

    def test_the_catalog_never_carries_a_settings_value_or_an_env_name(self):
        self.stored("script", "fixture_document", {"api_key": "sk-fixture-secret"})
        payload = json.dumps(self.client.get("/api/providers").get_json())
        self.assertNotIn("sk-fixture-secret", payload)
        # `environment` is manifest-internal and never serialized (§25).
        self.assertNotIn("STS_FIXTURE_DOCUMENT_KEY", payload)

    def test_the_settings_endpoint_serves_the_schema_and_redacts_the_secret(self):
        self.stored("script", "fixture_document", {"api_key": "sk-fixture-secret"})
        data = self.client.get("/api/providers/script/fixture_document/settings").get_json()
        self.assertEqual(data["settings"]["api_key"], "***")
        self.assertIn("chapter_count", data["schema"]["properties"])
        self.assertEqual(data["schema"]["required"], ["api_key"])

    def test_saving_a_required_setting_flips_availability_to_available(self):
        resp = self.client.put(
            "/api/providers/script/fixture_document/settings",
            json={"api_key": "sk-fixture-secret", "voice_of": "chorus"},
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        (provider,) = self.entry("script")["providers"]
        self.assertEqual(provider["availability"], AVAILABLE)

    def test_the_sentinel_leaves_a_stored_secret_alone(self):
        from scriptase.providers.secrets import is_secret_ref, resolve_secret_refs

        self.client.put(
            "/api/providers/script/fixture_document/settings",
            json={"api_key": "sk-fixture-secret"},
        )
        self.client.put(
            "/api/providers/script/fixture_document/settings",
            json={"api_key": "***", "voice_of": "protagonist"},
        )
        saved = self.settings["domains"]["script"]["instances"]["fixture_document"]["settings"]
        # Step 3.4: credentials are stored as secret refs; the sentinel keeps them.
        self.assertTrue(is_secret_ref(saved["api_key"]))
        self.assertEqual(resolve_secret_refs(saved)["api_key"], "sk-fixture-secret")
        self.assertEqual(saved["voice_of"], "protagonist")

    def test_the_providers_own_validation_hook_is_served(self):
        resp = self.client.post(
            "/api/providers/script/fixture_document/validate",
            json={"api_key": "k", "chaptered": True, "epigraph": ""},
        )
        issues = resp.get_json()["issues"]
        self.assertIn(
            ("epigraph", "warning"),
            [(issue["field"], issue["severity"]) for issue in issues],
        )

    def test_a_provider_error_severity_blocks_the_save(self):
        resp = self.client.put(
            "/api/providers/image/fixture_async/settings",
            json={"endpoint_url": "http://insecure.invalid/jobs"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"]["code"], "SETTINGS_INVALID")

    def test_selection_is_a_targeted_write_of_the_canonical_id(self):
        resp = self.client.put(
            "/api/providers/script/selection", json={"provider_id": "fixture-doc"}
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        self.assertEqual(resp.get_json()["selected"], "fixture_document")
        self.assertEqual(
            self.settings["domains"]["script"]["selected_instance_id"], "fixture_document"
        )

    def test_health_comes_from_the_provider_hook(self):
        self.stored("script", "fixture_document", {"api_key": "k"})
        health = self.client.get(
            "/api/providers/script/fixture_document/health"
        ).get_json()["health"]
        self.assertEqual(health["status"], "ok")


# ---------------------------------------------------------------------------
# Option sources — the node dropdown finds it with no resolver edit
# ---------------------------------------------------------------------------

class OptionSourceTests(SharedCatalogCase):
    def test_the_provider_dropdown_offers_the_fixture_beside_the_shipped_ones(self):
        options, _context = options_module.resolve_options("script_providers")
        self.assertIn(
            {"value": "fixture_document", "label": "Fixture Document Generator"},
            options,
        )
        self.assertGreater(len(options), 1, "the shipped providers must survive")

    def test_a_provider_supplies_its_own_voices_through_its_schema(self):
        """§22.4 — declaring `ui.options` is the whole of "offer my voices"."""
        options, context = options_module.resolve_options(
            "tts_voices", {"provider": "fixture_artifact"}
        )
        self.assertEqual(context["provider"], "fixture_artifact")
        self.assertEqual(
            [option["value"] for option in options], ["fx_calm", "fx_bright"]
        )

    def test_every_source_a_provider_schema_names_accepts_its_own_context(self):
        """The invariant that would have caught the 12.4 Storyboard defect.

        `ProviderSettingsForm` sends `{domain, provider}` to every
        `ui.options_source` it renders, because the browser cannot know which
        sources want them. A source named by a provider schema but declaring an
        empty context tuple therefore answers `OPTION_CONTEXT_INVALID` and the
        dropdown renders empty — which is exactly what shipped in 12.4.
        """
        shipped = ProviderHub()
        named = set()
        for domain in DOMAINS:
            for provider in shipped.list(domain):
                schema = provider.settings_schema() or {}
                for prop in (schema.get("properties") or {}).values():
                    source = ((prop or {}).get("ui") or {}).get("options_source")
                    if isinstance(source, str):
                        named.add(source)
        self.assertTrue(named, "no provider declares a dynamic option source")
        for source in sorted(named):
            with self.subTest(source=source):
                spec = ASYNC_OPTION_SOURCES[source]
                self.assertIn("domain", spec.context)
                self.assertIn("provider", spec.context)


# ---------------------------------------------------------------------------
# Node configuration — validated against the provider, not against a list
# ---------------------------------------------------------------------------

def story_node(configuration):
    return {
        "id": "n_story",
        "type": "story.generate",
        "type_version": 1,
        "name": "Story",
        "position": {"x": 0, "y": 0},
        "configuration": configuration,
        "disabled": False,
    }


def story_document(configuration):
    document = workflow_draft(name="Extensibility probe")
    document["nodes"] = [story_node(configuration)]
    return document


class NodeConfigurationTests(SharedCatalogCase):
    def problems(self, configuration):
        return validate_workflow(story_document(configuration), require_identity=False)

    def at(self, problems, suffix):
        return [p for p in problems if (p.get("path") or "").endswith(suffix)]

    def test_a_node_configured_with_the_fixture_validates(self):
        problems = self.problems({
            "provider_id": "fixture_document",
            "provider_options": {"voice_of": "chorus", "chaptered": True,
                                 "chapter_count": 4},
        })
        self.assertEqual(validation_errors(problems), [])

    def test_the_providers_own_bounds_are_enforced_on_a_node(self):
        """The node registry has never heard of `chapter_count` (§26)."""
        problems = self.problems({
            "provider_id": "fixture_document",
            "provider_options": {"chaptered": True, "chapter_count": 99},
        })
        found = self.at(problems, "provider_options.chapter_count")
        self.assertTrue(found, problems)
        self.assertEqual(found[0]["severity"], "error")
        self.assertIn("at most 9", found[0]["message"])

    def test_an_option_the_provider_does_not_declare_is_reported_but_kept(self):
        """§22.5 — accept, warn, drop before dispatch. Never silently discard."""
        problems = self.problems({
            "provider_id": "fixture_document",
            "provider_options": {"not_a_setting": 1},
        })
        found = self.at(problems, "provider_options.not_a_setting")
        self.assertTrue(found, problems)
        self.assertEqual(found[0]["severity"], "warning")

    def test_a_credential_may_never_be_a_per_run_node_option(self):
        problems = self.problems({
            "provider_id": "fixture_document",
            "provider_options": {"api_key": "sk-typed-into-a-node"},
        })
        errors = validation_errors(problems)
        self.assertTrue(errors)
        self.assertIn("credential", errors[0]["message"])

    def test_an_uninstalled_provider_reports_only_the_provider_field(self):
        """§23.3 — the *options* half fails open, so the node stays inspectable.

        The provider field itself is a hard error, because a saved value that
        resolves to nothing has no safe execution. Everything else about the
        node still validates, and the value is preserved rather than rewritten,
        so reinstalling the provider restores the workflow untouched.
        """
        configuration = {
            "provider_id": "a_provider_from_another_install",
            "provider_options": {"whatever": True},
        }
        problems = self.problems(configuration)
        self.assertEqual(
            [p["path"] for p in validation_errors(problems)],
            ["nodes[0].configuration.provider_id"],
        )
        self.assertEqual(self.at(problems, "provider_options.whatever"), [])
        self.assertEqual(
            configuration["provider_id"], "a_provider_from_another_install"
        )

    def test_a_workflow_saved_before_the_conversion_still_validates(self):
        """M4: no `provider_id` at all, which is every pre-12.3 document."""
        problems = self.problems({"story_category": "motivation", "duration": 45})
        self.assertEqual(validation_errors(problems), [])


# ---------------------------------------------------------------------------
# Execution — the sync-document shape on a real, unmodified node
# ---------------------------------------------------------------------------

class NodeExecutionTests(SharedCatalogCase):
    def setUp(self):
        super().setUp()
        self.stored("script", "fixture_document", {
            "api_key": "sk-fixture-secret",
            "voice_of": "chorus",
            "epigraph": "from the archive",
        })

    def run_node(self, configuration, inputs=None):
        from scriptase.engine.adapters import script as story

        return story.generate(
            inputs or {},
            configuration,
            AdapterContext(project_id=PROJECT_ID),
        )

    def test_the_unmodified_node_runs_a_provider_it_has_never_heard_of(self):
        outputs = self.run_node({"provider_id": "fixture_document"})
        self.assertEqual(set(outputs), {"control", "script", "story"})
        self.assertEqual(outputs["script"], "chorus:hook\nchorus:build\nchorus:climax\nchorus:cta")

    def test_the_artifact_is_recorded_as_a_managed_relative_ref(self):
        outputs = self.run_node({"provider_id": "fixture_document"})
        (ref,) = outputs["story"]["artifact_refs"]
        self.assertEqual(ref, f"fixture_document/{PROJECT_ID}/document.json")
        self.assertTrue(os.path.isfile(os.path.join(self.output_dir, ref)))

    def test_a_per_run_option_wins_over_the_saved_setting(self):
        """§40.2 — `{**saved, **per_run}`, for every provider."""
        outputs = self.run_node({
            "provider_id": "fixture_document",
            "provider_options": {"voice_of": "narrator"},
        })
        self.assertTrue(outputs["script"].startswith("narrator:"))

    def test_a_hidden_option_never_reaches_the_provider(self):
        """§22.3 — `chapter_count` is invisible while `chaptered` is off."""
        outputs = self.run_node({
            "provider_id": "fixture_document",
            "provider_options": {"chaptered": False, "chapter_count": 7},
        })
        self.assertEqual(outputs["story"]["metadata"]["chapters"], 0)

    def test_the_credential_never_reaches_the_written_artifact(self):
        outputs = self.run_node({"provider_id": "fixture_document"})
        path = os.path.join(self.output_dir, outputs["story"]["artifact_refs"][0])
        with open(path, encoding="utf-8") as handle:
            written = handle.read()
        self.assertNotIn("sk-fixture-secret", written)
        self.assertEqual(validate_egress(json.loads(written)), [])

    def test_a_provider_that_is_not_installed_fails_the_run_rather_than_substituting(self):
        from scriptase.engine.adapters.common import AdapterError

        with self.assertRaises(AdapterError) as caught:
            self.run_node({"provider_id": "not_installed"})
        self.assertEqual(caught.exception.code, "PROVIDER_UNAVAILABLE")


# ---------------------------------------------------------------------------
# Standardized results — all three shapes through the one runtime (§31, §33)
# ---------------------------------------------------------------------------

class StandardResultTests(FixtureCatalogCase):
    def assert_envelope(self, result, domain, provider_id):
        self.assertEqual(result.result_version, RESULT_VERSION)
        self.assertEqual((result.domain, result.provider_id), (domain, provider_id))
        self.assertEqual(result.provenance.domain, domain)
        self.assertEqual(result.provenance.provider_id, provider_id)
        self.assertEqual(validate_egress(result.to_dict()), [])

    def test_the_sync_document_shape_produces_one_envelope(self):
        instance = self.hub.create("script", "fixture_document")
        invocation = self.invocation("script", options={"voice_of": "narrator"})
        result = boundary.invoke(
            lambda inv: instance.invoke({}, inv), invocation, contract_version=2
        )
        self.assert_envelope(result, "script", "fixture_document")
        self.assertEqual(result.status, SUCCEEDED)
        self.assertEqual(result.payload["story_text"].split("\n")[0], "narrator:hook")
        self.assertEqual(result.artifact_refs, [result.payload["document_ref"]])

    def test_the_sync_artifact_shape_produces_the_file_it_declares(self):
        instance = self.hub.create("tts", "fixture_artifact")
        invocation = self.invocation(
            "tts", settings={"voice": "fx_bright", "speed": 1.0, "sample_rate": 48000}
        )
        result = boundary.invoke(
            lambda inv: instance.invoke({"text": "hello there"}, inv),
            invocation,
            contract_version=2,
        )
        self.assert_envelope(result, "tts", "fixture_artifact")
        self.assertEqual(result.payload["voice"], "fx_bright")
        self.assertEqual(result.payload["sample_rate"], 48000)
        (ref,) = result.artifact_refs
        self.assertTrue(os.path.isfile(os.path.join(self.output_dir, ref)))

    def test_a_secret_in_settings_is_redacted_into_provenance_and_nowhere_else(self):
        instance = self.hub.create("tts", "fixture_artifact")
        invocation = self.invocation("tts", settings={"api_key": "sk-fixture-secret"})
        result = boundary.invoke(
            lambda inv: instance.invoke({"text": "x"}, inv), invocation, contract_version=2
        )
        payload = json.dumps(result.to_dict())
        self.assertNotIn("sk-fixture-secret", payload)
        self.assertEqual(
            result.provenance.resolved_settings_redacted["api_key"], "***"
        )

    def test_the_async_shape_reaches_a_terminal_state_through_polling(self):
        from scriptase.providers.jobs import RUNNING, terminal_outcome

        instance = self.hub.create("image", "fixture_async")
        invocation = self.invocation("image", settings={"unit_count": 3})
        handle = instance.submit({}, invocation)
        self.assertEqual(handle.correlation,
                         ("image", "fixture_async", PROJECT_ID, handle.job_id))

        first = instance.poll(handle.job_id, invocation)
        self.assertEqual(first.state, RUNNING)
        self.assertEqual((first.ready, first.total), (1, 3))

        instance.poll(handle.job_id, invocation)
        final = instance.poll(handle.job_id, invocation)
        self.assertTrue(final.terminal)
        self.assertEqual(terminal_outcome(final, domain="image"), SUCCEEDED)
        self.assertEqual([unit.state for unit in final.units], [UNIT_SUCCEEDED] * 3)
        for unit in final.units:
            (ref,) = unit.artifact_refs
            self.assertTrue(os.path.isfile(os.path.join(self.output_dir, ref)))

    def test_a_partial_job_is_reported_as_partial_not_as_success(self):
        """§31.5 — the branch an all-success fixture would never reach."""
        instance = self.hub.create("image", "fixture_async")
        invocation = self.invocation(
            "image", settings={"unit_count": 2, "fail_last_unit": True}
        )
        handle = instance.submit({}, invocation)
        instance.poll(handle.job_id, invocation)
        final = instance.poll(handle.job_id, invocation)
        self.assertEqual(final.state, PARTIAL)
        self.assertEqual(
            [unit.state for unit in final.units], [UNIT_SUCCEEDED, UNIT_FAILED]
        )
        self.assertIsNotNone(final.units[1].error)
        self.assertEqual(validate_egress(final.to_dict()), [])

    def test_a_cancelled_job_stops_at_cancelled(self):
        from scriptase.providers.jobs import JOB_CANCELLED

        instance = self.hub.create("image", "fixture_async")
        invocation = self.invocation("image", settings={"unit_count": 3})
        handle = instance.submit({}, invocation)
        instance.cancel_job(handle.job_id, invocation)
        self.assertEqual(instance.jobs[handle.job_id]["status"].state, JOB_CANCELLED)


# ---------------------------------------------------------------------------
# Templates and saved documents survive an unfamiliar catalog
# ---------------------------------------------------------------------------

class TemplateCompatibilityTests(SharedCatalogCase):
    """Installing a provider must not disturb what was already saved."""

    def test_every_built_in_template_still_validates(self):
        """`serialize_templates` validates as it builds, so reaching a list at
        all is half the assertion; the rest re-runs validation with the fixture
        catalog installed.

        `require_complete` stays off: a template deliberately leaves
        user-authored fields — Script Input text, Existing Project's id —
        blank, and completeness is not what installing a provider can break.
        """
        from scriptase.engine.templates import serialize_templates

        entries = serialize_templates()
        self.assertTrue(entries)
        for entry in entries:
            with self.subTest(template=entry["template_id"]):
                document = entry["workflow"]
                self.assertEqual(
                    validation_errors(validate_workflow(document, require_identity=False)),
                    [],
                )

    def test_a_v1_document_of_every_converted_node_migrates_and_validates(self):
        """A1: a workflow saved before the migration opens with no manual edit.

        The v1 configuration is migrated by the M1–M3 hops on load — validating
        it *before* migrating would only prove the version gate works, which is
        not the compatibility claim.
        """
        from scriptase.engine.migrations import migrate_workflow

        legacy = {
            "tts.generate": ({"engine": "kokoro", "voice": "af_heart", "speed": 1.0},
                             "kokoro"),
            "storyboard.generate": ({"provider": "gemini_ws", "aspect_ratio": "9:16",
                                     "prompt_prefix": "cinematic"}, "gemini_ws"),
            "animator.generate": ({"provider": "grok_automa", "mode": "video",
                                   "quality": "480p", "duration": "6s"}, "grok_automa"),
        }
        for node_type, (configuration, expected) in legacy.items():
            with self.subTest(node=node_type):
                document = workflow_draft(name="Legacy probe")
                document["nodes"] = [{
                    "id": "n_legacy", "type": node_type, "type_version": 1,
                    "name": node_type, "position": {"x": 0, "y": 0},
                    "configuration": configuration, "disabled": False,
                }]
                migrated = migrate_workflow(document).document
                node = migrated["nodes"][0]
                self.assertEqual(node["configuration"]["provider_id"], expected)
                problems = validate_workflow(migrated, require_identity=False)
                self.assertEqual(validation_errors(problems), [])


# ---------------------------------------------------------------------------
# The diff guard (§26) — both directions
# ---------------------------------------------------------------------------

SOURCE_ROOTS = ("studio", "frontend/src", "docs")
SOURCE_FILES = ("app.py", "config.py")
SOURCE_SUFFIXES = (".py", ".js", ".vue", ".json", ".md", ".bat", ".html", ".css")

# Every id the shipped providers answer to, canonical and legacy (§40.3).
SHIPPED_PROVIDER_IDS = (
    "kokoro", "inworld", "gemini_ws", "wavespeed_direct", "wavespeed_webhook",
    "grok_automa", "kie_ai", "gemini", "wavespeed", "kie-ai",
)

# The surfaces §26 names: adding a provider must not edit any of them.
AUDITED_SURFACES = (
    "scriptase/engine/registry.py",
    "scriptase/engine/options.py",
    "scriptase/engine/validation.py",
    "scriptase/engine/templates.py",
    "scriptase/engine/config_migrations.py",
    "scriptase/engine/adapters/common.py",
    "scriptase/engine/adapters/script.py",
    "scriptase/engine/adapters/tts.py",
    "scriptase/engine/adapters/image.py",
    "scriptase/engine/adapters/video.py",
    # Step 15.2 made this generic: `scriptase/modules/tts/dispatch.py` is now
    # the one place that resolves a TTS provider, a voice, and a `job_meta`
    # block. Domain page multi-voice and model-download still live under
    # `scriptase/modules/tts/routes.py` (local engine features of the TTS page,
    # not shared dispatch).
    #
    # V2's `pipeline/services.py` is gone. Its `_step_*` bodies live in the
    # per-domain service modules below (step 0.3). There is no
    # `scriptase.modules.pipeline` package and never will be.
    "scriptase/modules/tts/dispatch.py",
    "scriptase/modules/tts/service.py",
    "scriptase/modules/timing/service.py",
    "scriptase/modules/segmenter/service.py",
    "scriptase/modules/scene_director/service.py",
    "scriptase/modules/compose/service.py",
    "scriptase/providers/domains.py",
    "scriptase/providers/hub.py",
    "scriptase/providers/registry.py",
    "scriptase/providers/settings_manager.py",
    "scriptase/providers/compatibility.py",
    "scriptase/providers/extension_ops.py",
    "scriptase/providers/routes.py",
    "scriptase/providers/catalog.py",
    "app.py",
)

# Step 16.1: every audited surface is branch-free. Provider-id comparisons
# belong only inside a provider package.
BRANCH_FREE_SURFACES = AUDITED_SURFACES

# Every `(surface, provider id)` pair that still exists, with what it is and
# who removes it. Frozen as a *set* rather than an allowlist: a new pair fails
# the guard, and so does closing one without deleting its entry, so the record
# cannot rot into a list of excuses.
#
# `domains.py` and `config_migrations.py` are the two legitimate homes. §19.1
# makes the domain catalog the single place a default provider id is written,
# and §41.3 freezes the v1 defaults a migration has to reproduce — both would
# be *wrong* to remove. `compatibility.py` is the residual selection-alias
# table for the one-time app-config migration (step 16.1). Everything else is
# a comment, a frozen public health key, or a frozen WebSocket path string.
KNOWN_PROVIDER_LITERALS = {
    # Two explanatory comments. Harmless today; listed so a *third* one, or a
    # literal in code, cannot slip in unnoticed.
    ("scriptase/engine/registry.py", "kokoro"),
    ("scriptase/engine/registry.py", "gemini_ws"),
    ("scriptase/engine/registry.py", "gemini"),
    # A comment naming the provider 13.2 replaces the `builtin` bridge with.
    ("scriptase/engine/adapters/script.py", "gemini"),
    # §19.1 — the domain catalog is where a default provider id belongs.
    ("scriptase/providers/domains.py", "kokoro"),
    ("scriptase/providers/domains.py", "gemini_ws"),
    ("scriptase/providers/domains.py", "gemini"),
    ("scriptase/providers/domains.py", "grok_automa"),
    # §41.3 — the frozen v1 defaults M1–M3 migrate onto.
    ("scriptase/engine/config_migrations.py", "kokoro"),
    ("scriptase/engine/config_migrations.py", "wavespeed_webhook"),
    ("scriptase/engine/config_migrations.py", "wavespeed"),
    ("scriptase/engine/config_migrations.py", "grok_automa"),
    ("scriptase/engine/config_migrations.py", "gemini_ws"),
    ("scriptase/engine/config_migrations.py", "gemini"),
    # A comment about the removed C1 environment side effect.
    ("scriptase/providers/settings_manager.py", "inworld"),
    # Step 16.1 residual selection-alias table (retired app-config store only).
    # "wavespeed" is the substring of wavespeed_webhook / wavespeed_direct.
    ("scriptase/providers/compatibility.py", "gemini"),
    ("scriptase/providers/compatibility.py", "gemini_ws"),
    ("scriptase/providers/compatibility.py", "wavespeed"),
    ("scriptase/providers/compatibility.py", "wavespeed_webhook"),
    ("scriptase/providers/compatibility.py", "wavespeed_direct"),
    ("scriptase/providers/compatibility.py", "grok_automa"),
    ("scriptase/providers/compatibility.py", "kie_ai"),
    ("scriptase/providers/compatibility.py", "kie-ai"),
    # Step 6.2 — the text_to_video built-in template must pin a text_to_video
    # provider; domain default is image_to_video (grok_automa) and must not
    # be silently substituted at run time.
    ("scriptase/engine/templates.py", "kie_ai"),
    # V2's `app.py` carried two: an `/api/health` key probing Inworld package
    # availability, and a boot banner printing the frozen `…-gemini-…` /
    # `…-grok-…` WebSocket paths. Step 0.2's application factory has neither —
    # health reports version only, and extension runtimes claim their own routes
    # through `hub.bind_runtimes`. Closed rather than carried forward.
}


def source_files():
    """Every shipped source file, excluding the test tree."""
    found = []
    for entry in SOURCE_FILES:
        found.append(os.path.join(ROOT_DIR, entry))
    for root_name in SOURCE_ROOTS:
        base = os.path.join(ROOT_DIR, *root_name.split("/"))
        for directory, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in {"__pycache__", "node_modules", "dist"}]
            for name in files:
                if name.endswith(SOURCE_SUFFIXES):
                    found.append(os.path.join(directory, name))
    return found


class ZeroTouchDiffTests(unittest.TestCase):
    """The mechanical form of "adding a provider touched only its folder"."""

    def test_no_shipped_file_mentions_a_fixture_provider(self):
        """Direction 1: the three additions are folder-plus-tests, and nothing else.

        Stated as an invariant rather than as a `git diff`, so it keeps holding
        for every later commit instead of only for the one that added them.
        """
        offenders = []
        for path in source_files():
            with open(path, encoding="utf-8", errors="ignore") as handle:
                source = handle.read()
            for provider_id in FIXTURE_IDS:
                if provider_id in source:
                    offenders.append(f"{os.path.relpath(path, ROOT_DIR)}: {provider_id}")
        self.assertEqual(offenders, [])

    def test_the_zero_touch_surfaces_name_exactly_the_known_providers(self):
        """Direction 2: §26's table, asserted rather than reviewed.

        The backend counterpart of the 12.2/12.4 frontend guards. A literal id
        in one of these files is how the zero-touch promise silently breaks —
        the provider that needed the edit works, and the next one does not.
        The comparison is an equality against a frozen set, so both a new
        literal and a stale entry fail.
        """
        found = set()
        for relative in AUDITED_SURFACES:
            path = os.path.join(ROOT_DIR, *relative.split("/"))
            with open(path, encoding="utf-8") as handle:
                source = handle.read().lower()
            for provider_id in SHIPPED_PROVIDER_IDS:
                if provider_id in source:
                    found.add((relative, provider_id))
        self.assertEqual(found, KNOWN_PROVIDER_LITERALS)

    def test_no_adapter_branches_on_a_provider_id(self):
        """The substantive half: a *comparison*, not a mention (P5–P25).

        A comment costs nothing; `if provider_id == "…"` in an adapter is the
        thing that makes the next provider silently do nothing.
        """
        offenders = []
        for relative in BRANCH_FREE_SURFACES:
            path = os.path.join(ROOT_DIR, *relative.split("/"))
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().lower().splitlines()
            for number, line in enumerate(lines, 1):
                code = line.split("#", 1)[0]
                if not any(op in code for op in ("==", "!=", " in (", " in {", " in [")):
                    continue
                for provider_id in SHIPPED_PROVIDER_IDS:
                    if f"'{provider_id}'" in code or f'"{provider_id}"' in code:
                        offenders.append(f"{relative}:{number}: {provider_id}")
        self.assertEqual(offenders, [])

    def test_the_fixture_packages_carry_only_the_three_supported_files(self):
        """§19.2 — a provider package is a manifest plus two optional modules."""
        allowed = {"manifest.py", "provider.py", "settings_schema.py", "runtime.py"}
        for folder, provider_id in SHAPES.values():
            directory = os.path.join(FIXTURE_ROOT, folder, provider_id)
            present = {
                name for name in os.listdir(directory)
                if not name.startswith("__")
            }
            with self.subTest(provider=provider_id):
                self.assertTrue(present <= allowed, present - allowed)
                self.assertIn("manifest.py", present)

    def test_a_node_names_a_provider_only_through_its_domain_default(self):
        """§26's D19 resolution: node fields are provider-agnostic.

        A provider id does appear in a materialized `config_schema` — as the
        `provider` field's default — but it is *read* from `DOMAINS`, never
        written in the registry. Anywhere else is a provider-specific node
        field, which is exactly what 12.3 removed.
        """
        offenders = []
        for key, definition in all_node_types().items():
            for field in definition["config_schema"]:
                rest = {k: v for k, v in field.items() if k != "default"}
                blob = json.dumps(rest).lower()
                for provider_id in SHIPPED_PROVIDER_IDS:
                    if provider_id in blob:
                        offenders.append(f"{key}.{field['name']}: {provider_id}")
                default = field.get("default")
                if field.get("type") == "provider":
                    self.assertEqual(
                        default, DOMAINS[field["provider_domain"]].default_provider
                    )
                elif isinstance(default, str):
                    for provider_id in SHIPPED_PROVIDER_IDS:
                        if provider_id in default.lower():
                            offenders.append(f"{key}.{field['name']}: {provider_id}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
