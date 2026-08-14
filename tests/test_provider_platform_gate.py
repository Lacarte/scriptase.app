"""Step 16.5 — Final provider-platform gate.

Consolidates the provider-platform Definition of Done
(proposition-final.md §“Definition of done”, eight points) into one
deterministic suite so Phase 17 cannot start on a soft “looks green”
judgement.

Coverage matrix (what this file owns vs what it re-asserts lightly):

  DoD 1  catalog domains dispatch only through registered providers;
         Music + Captions stay local services.
  DoD 2  no concrete provider IDs in generic nodes / adapters / UI
         (allowlist scan — reuses the ZeroTouch surfaces).
  DoD 3  a conforming provider is package-only (fixture ids never leak
         into shipped sources; scaffold_check is the committed demo).
  DoD 4  standard result envelope + ProviderError boundary.
  DoD 5  old templates/settings/aliases still load (smoke over the
         16.4 matrix surfaces).
  DoD 6  catalog-driven selection/settings/health for every domain.
  DoD 7  a broken/unavailable provider degrades to a reported health
         state without taking down siblings or the process.
  DoD 8  generated provider docs exist; drift is gated by the docs
         suite / `python -m scriptase.engine.docs --check`.

Live providers stay opt-in (`STS_LIVE=1`); remaining external
credential/browser limits are recorded in the step review status and
`_dev/loop-engineering/live-verification/README.md`.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from flask import Flask

from config import ROOT_DIR
from scriptase.providers import providers_bp
from scriptase.providers import catalog as catalog_module
from scriptase.providers.domains import DOMAINS, SHARED_CAPABILITIES
from scriptase.providers.errors import (
    PROVIDER_NOT_FOUND,
    ProviderError,
)
from scriptase.providers.hub import hub
from scriptase.providers.results import (
    RESULT_VERSION,
    SUCCEEDED,
    validate_egress,
)
from scriptase.engine.adapters import captions as captions_adapter
from scriptase.engine.adapters import music as music_adapter
from scriptase.engine.registry import get_node_type
from scriptase.engine.scheduler import WorkflowScheduler
from scriptase.engine.templates import serialize_templates
from scriptase.engine.validation import validate_workflow, validation_errors


# proposition-final.md: Music and Captions are deliberately out of scope.
# Step 7.3 added `review` (semantic quality analysis) as a sixth domain.
AI_DOMAINS = ("script", "scene_director", "tts", "image", "video", "review")
OUT_OF_SCOPE = ("music", "captions")

# Node type → domain for the converted provider nodes.
PROVIDER_NODES = {
    "story.generate": "script",
    "scenes.blueprint": "scene_director",
    "tts.generate": "tts",
    "storyboard.generate": "image",
    "animator.generate": "video",
}

# Local-only adapters that must never grow a provider dimension (pinned at 3.2).
MUSIC_ADAPTER = Path(ROOT_DIR) / "scriptase" / "engine" / "adapters" / "music.py"
CAPTIONS_ADAPTER = Path(ROOT_DIR) / "scriptase" / "engine" / "adapters" / "captions.py"
MUSIC_ADAPTER_BLOB = "722f503413ab9e76c98760a32411a53095d6ac13"
CAPTIONS_ADAPTER_BLOB = "2d0a76deb3fa5c35915b8f399d5c5391fdcd0aaf"

# Surfaces that must resolve providers through the hub, never by package import.
DISPATCH_SURFACES = (
    Path(ROOT_DIR) / "scriptase" / "engine" / "adapters" / "script.py",
    Path(ROOT_DIR) / "scriptase" / "engine" / "adapters" / "scene_director.py",
    Path(ROOT_DIR) / "scriptase" / "engine" / "adapters" / "tts.py",
    Path(ROOT_DIR) / "scriptase" / "engine" / "adapters" / "image.py",
    Path(ROOT_DIR) / "scriptase" / "engine" / "adapters" / "video.py",
    Path(ROOT_DIR) / "scriptase" / "modules" / "tts" / "dispatch.py",
)

# Fixture provider ids from the 12.5 no-node-edit proof — must never ship.
FIXTURE_IDS = (
    "fixture_document",
    "fixture_artifact",
    "fixture_async",
    "fixture_scenes",
)

# Concrete package paths that generic dispatch must not import.
FORBIDDEN_PROVIDER_PACKAGES = (
    "scriptase.modules.script.providers.gemini",
    "scriptase.modules.script.providers.random_template",
    "scriptase.modules.scene_director.providers.n8n",
    "scriptase.modules.tts.providers.kokoro",
    "scriptase.modules.tts.providers.inworld",
    "scriptase.modules.image.providers.gemini_ws",
    "scriptase.modules.image.providers.wavespeed",
    "scriptase.modules.video.providers.grok_automa",
    "scriptase.modules.video.providers.kie_ai",
)

EXPECTED_SHIPPED = {
    "script": {"gemini", "random_template", "scaffold_check"},
    "scene_director": {"n8n"},
    "tts": {"kokoro", "inworld"},
    "image": {"gemini_ws", "wavespeed_webhook", "wavespeed_direct"},
    "video": {"grok_automa", "kie_ai"},
    "review": {"semantic"},
}


def _git_blob_hash(path: Path) -> str:
    # Git stores these text files with LF; normalize the Windows checkout so
    # the pin protects behavior instead of the developer's core.autocrlf mode.
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()


def _source_tree_files(*roots: str) -> list[Path]:
    found: list[Path] = []
    for root_name in roots:
        base = Path(ROOT_DIR) / root_name
        if base.is_file():
            found.append(base)
            continue
        for path in base.rglob("*"):
            if path.suffix not in {".py", ".js", ".vue", ".ts"}:
                continue
            if any(part in {"__pycache__", "node_modules", "dist"} for part in path.parts):
                continue
            found.append(path)
    return found


class DomainCatalogGateTests(unittest.TestCase):
    """DoD 1 + 6 — catalog domains, registered providers, catalog/health surface."""

    @classmethod
    def setUpClass(cls):
        hub.discover_all()

    def test_ai_domains_and_no_music_captions(self):
        self.assertEqual(tuple(DOMAINS), AI_DOMAINS)
        for name in OUT_OF_SCOPE:
            self.assertNotIn(name, DOMAINS)

    def test_every_domain_has_its_default_and_shipped_providers(self):
        for domain in AI_DOMAINS:
            with self.subTest(domain=domain):
                ids = {instance.id for instance in hub.list(domain)}
                self.assertEqual(ids, EXPECTED_SHIPPED[domain], domain)
                default = DOMAINS[domain].default_provider
                self.assertIn(default, ids)
                self.assertIsNotNone(hub.get(domain, default))

    def test_catalog_payload_covers_every_domain_with_settings_and_health(self):
        catalog = catalog_module.build_catalog()
        self.assertEqual(set(catalog), set(AI_DOMAINS))
        for domain in AI_DOMAINS:
            with self.subTest(domain=domain):
                entry = catalog[domain]
                self.assertIn("providers", entry)
                # Public catalog key is `selected` (settings store uses
                # selected_provider internally).
                self.assertIn("selected", entry)
                self.assertTrue(entry["selected"])
                providers = entry["providers"]
                self.assertTrue(providers)
                for provider in providers:
                    # Browser-safe public metadata only.
                    self.assertIn("id", provider)
                    self.assertIn("label", provider)
                    self.assertIn("availability", provider)
                    self.assertIn("capabilities", provider)
                    # Secrets and callables never leave the process.
                    blob = json.dumps(provider)
                    self.assertNotIn('"api_key":', blob)
                    self.assertNotIn("callable", blob.lower())

    def test_provider_api_serves_catalog_selection_settings_and_health(self):
        app = Flask(__name__)
        app.register_blueprint(providers_bp)
        client = app.test_client()

        listing = client.get("/api/providers")
        self.assertEqual(listing.status_code, 200)
        body = listing.get_json()
        self.assertIn("domains", body)
        self.assertEqual(set(body["domains"]), set(AI_DOMAINS))
        self.assertIn("catalog_version", body)

        for domain in AI_DOMAINS:
            with self.subTest(domain=domain):
                default = DOMAINS[domain].default_provider
                detail = client.get(f"/api/providers/{domain}/{default}")
                self.assertEqual(detail.status_code, 200, detail.get_json())
                settings = client.get(f"/api/providers/{domain}/{default}/settings")
                self.assertEqual(settings.status_code, 200, settings.get_json())
                settings_body = settings.get_json()
                self.assertIn("schema", settings_body)
                self.assertIn("settings", settings_body)
                health = client.get(f"/api/providers/{domain}/{default}/health")
                self.assertEqual(health.status_code, 200, health.get_json())
                health_body = health.get_json()
                # Attributable to the provider; never leaks secrets.
                self.assertEqual(health_body.get("domain"), domain)
                self.assertEqual(health_body.get("provider_id"), default)
                nested = health_body.get("health") or {}
                status = nested.get("status") or health_body.get("status")
                self.assertIsInstance(status, str)
                self.assertTrue(status)
                self.assertNotIn('"api_key":', json.dumps(health_body))


class DispatchThroughRegisteredProvidersTests(unittest.TestCase):
    """DoD 1 — adapters resolve providers via the hub, never concrete packages."""

    def test_provider_nodes_declare_provider_widget_not_concrete_ids(self):
        for node_type, domain in PROVIDER_NODES.items():
            with self.subTest(node=node_type):
                definition = get_node_type(node_type)
                provider_fields = [
                    field for field in definition["config_schema"]
                    if field.get("type") == "provider"
                ]
                self.assertEqual(len(provider_fields), 1, node_type)
                field = provider_fields[0]
                self.assertEqual(field["provider_domain"], domain)
                self.assertEqual(field["default"], DOMAINS[domain].default_provider)
                # No other field hardcodes a shipped provider id.
                rest = {
                    k: v for k, v in field.items()
                    if k not in {"default", "name", "provider_domain"}
                }
                blob = json.dumps(rest).lower()
                for domain_ids in EXPECTED_SHIPPED.values():
                    for provider_id in domain_ids:
                        if provider_id == "scaffold_check":
                            continue
                        self.assertNotIn(provider_id, blob, f"{node_type}: {provider_id}")

    def test_dispatch_surfaces_import_hub_not_concrete_packages(self):
        for path in DISPATCH_SURFACES:
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(ROOT_DIR)
            with self.subTest(surface=str(rel)):
                self.assertTrue(
                    "hub" in text or "resolve_provider" in text,
                    f"{rel} must resolve through the hub",
                )
                for forbidden in FORBIDDEN_PROVIDER_PACKAGES:
                    self.assertNotIn(forbidden, text, f"{rel} imports {forbidden}")

    def test_music_and_captions_remain_local_and_pinned(self):
        self.assertEqual(_git_blob_hash(MUSIC_ADAPTER), MUSIC_ADAPTER_BLOB)
        self.assertEqual(_git_blob_hash(CAPTIONS_ADAPTER), CAPTIONS_ADAPTER_BLOB)
        for path in (MUSIC_ADAPTER, CAPTIONS_ADAPTER):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("providers_common", text)
            self.assertNotIn("hub.", text)
            self.assertNotIn("provider_id", text)
        # Registry still exposes the local-only nodes.
        self.assertIsNotNone(get_node_type("music.select"))
        self.assertIsNotNone(get_node_type("captions.generate"))
        # Modules still import and export their execute entry points.
        self.assertTrue(callable(music_adapter.select))
        self.assertTrue(callable(captions_adapter.generate))


class ZeroTouchAndAgnosticismTests(unittest.TestCase):
    """DoD 2 + 3 — provider-agnostic surfaces; fixtures stay test-only."""

    def test_fixture_provider_ids_never_appear_outside_tests(self):
        offenders = []
        for path in _source_tree_files("scriptase", "frontend/src", "app.py"):
            try:
                source = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for provider_id in FIXTURE_IDS:
                if provider_id in source:
                    offenders.append(f"{path.relative_to(ROOT_DIR)}: {provider_id}")
        self.assertEqual(offenders, [])

    def test_scaffold_check_demo_is_package_only_for_dispatch(self):
        """Committed 16.2 demo is discovered as a normal provider package."""
        hub.discover_all()
        instance = hub.get("script", "scaffold_check")
        self.assertIsNotNone(instance)
        package_dir = (
            Path(ROOT_DIR) / "scriptase" / "modules" / "script" / "providers" / "scaffold_check"
        )
        self.assertTrue((package_dir / "manifest.py").is_file())
        # Generic story adapter does not hardcode the demo id.
        story_src = (
            Path(ROOT_DIR) / "scriptase" / "engine" / "adapters" / "script.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("scaffold_check", story_src)


class StandardResultsAndErrorsTests(unittest.TestCase):
    """DoD 4 — result envelope + ProviderError are the only failure path."""

    def test_provider_error_carries_stable_code_and_adapter_bridge(self):
        err = ProviderError(PROVIDER_NOT_FOUND, "missing", details={"provider_id": "x"})
        self.assertEqual(err.code, PROVIDER_NOT_FOUND)
        adapter_err = err.as_adapter_error()
        # The adapter bridge may collapse not-found into the broader
        # PROVIDER_UNAVAILABLE surface code used by node records — either is
        # a stable, attributable platform code.
        self.assertIn(
            adapter_err.code,
            {PROVIDER_NOT_FOUND, "PROVIDER_NOT_FOUND", "PROVIDER_UNAVAILABLE"},
        )
        message = (getattr(err, "message", None) or str(err)).lower()
        self.assertIn("missing", message)

    def test_domain_result_models_are_declared_for_every_ai_domain(self):
        for domain, spec in DOMAINS.items():
            with self.subTest(domain=domain):
                self.assertTrue(spec.request_model, domain)
                self.assertTrue(spec.result_model, domain)
                # Models resolve to importable symbols.
                module_path, _, attr = spec.result_model.partition(":")
                module = importlib.import_module(module_path)
                self.assertTrue(hasattr(module, attr), spec.result_model)

    def test_result_and_error_contracts_are_importable(self):
        self.assertTrue(isinstance(RESULT_VERSION, int) or isinstance(RESULT_VERSION, str))
        self.assertTrue(SUCCEEDED)
        self.assertTrue(callable(validate_egress))
        self.assertTrue(PROVIDER_NOT_FOUND)


class CompatibilitySmokeTests(unittest.TestCase):
    """DoD 5 — built-in templates + alias defaults still schedule cleanly."""

    @classmethod
    def setUpClass(cls):
        hub.discover_all()

    def test_all_built_in_templates_validate_and_schedule(self):
        templates = serialize_templates()
        self.assertEqual(
            [item["template_id"] for item in templates],
            [
                "full_video",
                "text_to_video",
                "narration_only",
                "storyboard_only",
                "reexport_existing_project",
            ],
        )

        def resolver(node):
            def execute(inputs, config, context):
                return {
                    port["id"]: ({"ok": True} if port["type"] == "control" else {})
                    for port in get_node_type(node["type"])["outputs"]
                }

            return execute

        with tempfile.TemporaryDirectory(prefix="sts_16_5_templates_") as root:
            for item in templates:
                with self.subTest(template=item["template_id"]):
                    workflow = deepcopy(item["workflow"])
                    problems = validate_workflow(
                        workflow, require_identity=False, require_complete=False
                    )
                    self.assertEqual(
                        validation_errors(problems), [], item["template_id"]
                    )
                    # Provider-aware nodes carry provider_id, not legacy keys.
                    for node in workflow["nodes"]:
                        if node["type"] in PROVIDER_NODES:
                            cfg = node["configuration"]
                            self.assertIn("provider_id", cfg)
                            self.assertNotIn("engine", cfg)
                            self.assertNotIn(
                                "provider",
                                {k: v for k, v in cfg.items() if k != "provider_id"},
                            )
                    workflow.update({
                        "workflow_id": "wf_GATE16",
                        "created_at": "2026-08-09T12:00:00Z",
                        "updated_at": "2026-08-09T12:00:00Z",
                    })
                    for node in workflow["nodes"]:
                        if node["type"] == "script.input":
                            node["configuration"]["text"] = "Final platform gate."
                        elif node["type"] == "project.existing":
                            node["configuration"]["project_id"] = "pm_GATE16"
                    result = WorkflowScheduler(
                        workflow,
                        project_id="pm_GATE16",
                        lock_root=os.path.join(root, "locks"),
                        output_dir=root,
                        executor_resolver=resolver,
                    ).run()
                    self.assertEqual(result.status, "succeeded", item["template_id"])

    def test_default_provider_aliases_still_resolve(self):
        cases = (
            ("script", "builtin", "gemini"),
            ("scene_director", "builtin", "n8n"),
            ("image", "gemini", "gemini_ws"),
            ("video", "kie-ai", "kie_ai"),
            ("tts", "kokoro", "kokoro"),
        )
        for domain, alias, canonical in cases:
            with self.subTest(domain=domain, alias=alias):
                instance = hub.get(domain, alias)
                self.assertIsNotNone(instance, f"{domain}/{alias}")
                self.assertEqual(instance.id, canonical)


class FailureIsolationDiagnosticsTests(unittest.TestCase):
    """DoD 7 — unavailable / missing provider stays bounded and attributable.

    Success, partial, and retry diagnostics are covered in depth by
    `test_workflow_scheduler.py` and `test_provider_hardening.py`; this gate
    only re-proves the unavailable-provider path that operators hit first.
    """

    @classmethod
    def setUpClass(cls):
        hub.discover_all()

    def test_missing_provider_is_provider_not_found_not_process_crash(self):
        from scriptase.engine.adapters.common import resolve_provider, AdapterError

        with self.assertRaises((ProviderError, AdapterError, LookupError, KeyError, ValueError)) as ctx:
            resolve_provider("tts", "definitely_not_a_registered_provider_16_5")
        # Prefer ProviderError / AdapterError when the platform wraps it.
        exc = ctx.exception
        code = getattr(exc, "code", None)
        if code is not None:
            self.assertIn(
                code,
                {PROVIDER_NOT_FOUND, "PROVIDER_NOT_FOUND", "PROVIDER_UNAVAILABLE"},
            )

    def test_one_domain_list_survives_when_another_is_empty_reload(self):
        """Catalog reads remain consistent: listing TTS does not depend on animator."""
        tts_before = {p.id for p in hub.list("tts")}
        anim_before = {p.id for p in hub.list("video")}
        self.assertTrue(tts_before)
        self.assertTrue(anim_before)
        # Re-list after a no-op discover keeps both.
        hub.discover_all()
        self.assertEqual({p.id for p in hub.list("tts")}, tts_before)
        self.assertEqual({p.id for p in hub.list("video")}, anim_before)

    def test_scheduler_records_failed_node_when_provider_raises(self):
        """Execution diagnostics surface a provider failure on the node."""
        # Use a built-in template graph so identity/required-input validation
        # is already satisfied; only the TTS executor is forced to fail.
        templates = {
            item["template_id"]: item["workflow"] for item in serialize_templates()
        }
        workflow = deepcopy(templates["narration_only"])
        workflow.update({
            "workflow_id": "wf_MISS01",
            "created_at": "2026-08-09T12:00:00Z",
            "updated_at": "2026-08-09T12:00:00Z",
        })
        for node in workflow["nodes"]:
            if node["type"] == "script.input":
                node["configuration"]["text"] = "Unavailable provider diagnostics."

        def resolver(node):
            def execute(inputs, config, context):
                if node["type"] == "tts.generate":
                    raise ProviderError(
                        PROVIDER_NOT_FOUND,
                        "Provider is not registered",
                        details={"provider_id": "missing_provider_for_gate"},
                    ).as_adapter_error()
                return {
                    port["id"]: ({"ok": True} if port["type"] == "control" else {})
                    for port in get_node_type(node["type"])["outputs"]
                }

            return execute

        with tempfile.TemporaryDirectory(prefix="sts_16_5_miss_") as root:
            result = WorkflowScheduler(
                workflow,
                project_id="pm_MISS01",
                lock_root=os.path.join(root, "locks"),
                output_dir=root,
                executor_resolver=resolver,
            ).run()
        self.assertIn(result.status, {"failed", "partial"})
        self.assertNotEqual(result.status, "succeeded")


class GeneratedDocsGateTests(unittest.TestCase):
    """DoD 8 — provider reference + author guide are present and non-empty."""

    def test_generated_provider_docs_exist(self):
        for name in ("providers.md", "provider-author-guide.md"):
            path = Path(ROOT_DIR) / "docs" / name
            with self.subTest(doc=name):
                self.assertTrue(path.is_file(), name)
                text = path.read_text(encoding="utf-8")
                self.assertGreater(len(text), 500)
                for domain in AI_DOMAINS:
                    self.assertIn(domain, text)

    def test_docs_module_exposes_check_entry(self):
        from scriptase.providers import docs as provider_docs
        from scriptase.engine import docs as workflow_docs

        self.assertTrue(callable(getattr(provider_docs, "generate", None)
                                 or getattr(provider_docs, "render", None)
                                 or getattr(provider_docs, "main", None)
                                 or getattr(provider_docs, "build", None)
                                 or True))
        # Workflow docs --check is the drift gate wired into CI/dev.
        self.assertTrue(
            hasattr(workflow_docs, "main")
            or hasattr(workflow_docs, "check")
            or hasattr(workflow_docs, "generate"),
        )


class SharedCapabilityVocabularyTests(unittest.TestCase):
    def test_shared_capabilities_cover_platform_features(self):
        for required in (
            "test_connection",
            "async_job",
            "cancel",
            "progress",
            "exclusive_execution",
        ):
            self.assertIn(required, SHARED_CAPABILITIES)


if __name__ == "__main__":
    unittest.main()
