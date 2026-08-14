"""Step 16.1 — Remove concrete-provider knowledge from core code.

Proves:

  * extension browser-ops resolve through the hub (no gemini/grok branch);
  * Chromium health is keyed by canonical provider id;
  * the retired app-config selection keys are stripped on read/write;
  * selection aliases live only in the compatibility module (+ manifests);
  * the allowlist scan over generic surfaces stays green.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config import ROOT_DIR
from scriptase.providers import compatibility as compat
from scriptase.providers.extension_ops import (
    health_snapshot,
    iter_extensions,
    resolve_extension,
)


class ExtensionOpsTests(unittest.TestCase):
    def test_resolves_aliases_and_canonical_ids(self):
        self.assertEqual(resolve_extension("gemini").provider_id, "gemini_ws")
        self.assertEqual(resolve_extension("gemini_ws").provider_id, "gemini_ws")
        self.assertEqual(resolve_extension("grok").provider_id, "grok_automa")
        self.assertEqual(resolve_extension("midjourney").provider_id, "grok_automa")

    def test_cloud_providers_are_not_extensions(self):
        self.assertIsNone(resolve_extension("wavespeed_direct"))
        self.assertIsNone(resolve_extension("kie_ai"))
        self.assertIsNone(resolve_extension("kokoro"))
        self.assertIsNone(resolve_extension(""))

    def test_every_shipped_extension_exposes_the_three_ops(self):
        found = {ops.provider_id: ops for ops in iter_extensions()}
        self.assertIn("gemini_ws", found)
        self.assertIn("grok_automa", found)
        for ops in found.values():
            self.assertTrue(callable(ops.is_connected))
            self.assertTrue(callable(ops.activate))
            self.assertTrue(callable(ops.focus))

    def test_health_snapshot_is_keyed_by_canonical_id(self):
        snapshot = health_snapshot()
        self.assertIn("gemini_ws", snapshot)
        self.assertIn("grok_automa", snapshot)
        for info in snapshot.values():
            self.assertIn("connected", info)
            self.assertIn("label", info)
            self.assertIn("domain", info)
        # Legacy wire labels must not be response keys.
        self.assertNotIn("gemini", snapshot)
        self.assertNotIn("grok", snapshot)


class CompatibilityModuleTests(unittest.TestCase):
    def test_selection_aliases_normalize(self):
        # Cross-domain (no domain context) — retired app-config wire spellings.
        self.assertEqual(compat.normalize_selection_alias("gemini"), "gemini_ws")
        self.assertEqual(compat.normalize_selection_alias("grok"), "grok_automa")
        self.assertEqual(compat.normalize_selection_alias("midjourney"), "grok_automa")
        self.assertEqual(compat.normalize_selection_alias("kie-ai"), "kie_ai")
        # Domain-aware: script's canonical id is also named gemini.
        self.assertEqual(
            compat.normalize_selection_alias("gemini", domain="script"), "gemini"
        )
        self.assertEqual(
            compat.normalize_selection_alias("gemini", domain="image"),
            "gemini_ws",
        )
        self.assertEqual(
            compat.normalize_selection_alias("builtin", domain="script"), "gemini"
        )
        self.assertEqual(
            compat.normalize_selection_alias("builtin", domain="scene_director"), "n8n"
        )
        # Unknown values pass through so a future plugin id is not rewritten.
        self.assertEqual(compat.normalize_selection_alias("fixture_x"), "fixture_x")
        self.assertEqual(
            compat.normalize_selection_alias("fixture_x", domain="tts"), "fixture_x"
        )

    def test_strip_removes_only_the_three_keys(self):
        user = {
            "sts-tts-provider": "inworld",
            "sts-storyboard-provider": "gemini",
            "sts-asset-provider": "grok",
            "sts-sound-enabled": True,
            "sts-default-style": "cinematic",
        }
        cleaned = compat.strip_legacy_selection_keys(user)
        self.assertEqual(
            cleaned,
            {"sts-sound-enabled": True, "sts-default-style": "cinematic"},
        )
        # Original untouched.
        self.assertIn("sts-tts-provider", user)

    def test_the_three_keys_match_domain_specs(self):
        from scriptase.providers.domains import DOMAINS

        declared = {
            spec.legacy_selection_key
            for spec in DOMAINS.values()
            if spec.legacy_selection_key
        }
        self.assertEqual(declared, set(compat.LEGACY_SELECTION_KEYS))


class AppConfigKeyRetirementTests(unittest.TestCase):
    """GET/PATCH /api/settings never reintroduces the three retired keys."""

    def setUp(self):
        from flask import Flask
        from scriptase.modules.compose.settings_routes import compose_settings_bp

        self.tmp = tempfile.mkdtemp(prefix="sts_16_1_cfg_")
        self.cfg_path = os.path.join(self.tmp, "app-config.json")
        seed = {
            "version": 2,
            "defaults": {},
            "localStorage": [],
            "user": {
                "sts-tts-provider": "inworld",
                "sts-storyboard-provider": "gemini",
                "sts-asset-provider": "grok",
                "sts-sound-enabled": True,
            },
        }
        with open(self.cfg_path, "w", encoding="utf-8") as handle:
            json.dump(seed, handle)

        app = Flask(__name__)
        app.register_blueprint(compose_settings_bp)
        self.client = app.test_client()
        self._patcher = mock.patch(
            "scriptase.modules.compose.settings_service.APP_CONFIG_PATH",
            self.cfg_path,
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_get_strips_the_three_keys(self):
        resp = self.client.get("/api/settings")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        for key in compat.LEGACY_SELECTION_KEYS:
            self.assertNotIn(key, body)
        self.assertTrue(body.get("sts-sound-enabled"))

    def test_patch_cannot_reintroduce_them(self):
        resp = self.client.patch(
            "/api/settings",
            json={"sts-tts-provider": "kokoro", "sts-sound-enabled": False},
        )
        self.assertEqual(resp.status_code, 200)
        with open(self.cfg_path, encoding="utf-8") as handle:
            stored = json.load(handle)["user"]
        self.assertNotIn("sts-tts-provider", stored)
        self.assertIs(stored.get("sts-sound-enabled"), False)


class CoreImportBoundaryTests(unittest.TestCase):
    """Core surfaces import the hub / interfaces, not concrete providers."""

    FORBIDDEN_IMPORTS = (
        "scriptase.modules.image.providers.gemini_ws",
        "scriptase.modules.video.providers.grok_automa",
        "scriptase.modules.video.providers.kie_ai",
        "scriptase.modules.tts.providers.kokoro",
        "scriptase.modules.tts.providers.inworld",
        "scriptase.modules.image.providers.wavespeed",
    )

    # V2's `studio/pipeline/services.py` is gone; its `_step_*` bodies live in
    # the per-domain service modules listed below (step 0.3).
    SURFACES = (
        Path(ROOT_DIR) / "scriptase" / "engine" / "adapters",
        Path(ROOT_DIR) / "scriptase" / "engine" / "registry.py",
        Path(ROOT_DIR) / "scriptase" / "providers" / "catalog.py",
        Path(ROOT_DIR) / "scriptase" / "modules" / "tts" / "service.py",
        Path(ROOT_DIR) / "scriptase" / "modules" / "tts" / "dispatch.py",
        Path(ROOT_DIR) / "scriptase" / "modules" / "timing" / "service.py",
        Path(ROOT_DIR) / "scriptase" / "modules" / "segmenter" / "service.py",
        Path(ROOT_DIR) / "scriptase" / "modules" / "scene_director" / "service.py",
        Path(ROOT_DIR) / "scriptase" / "modules" / "compose" / "service.py",
        Path(ROOT_DIR) / "scriptase" / "providers" / "extension_ops.py",
    )

    def test_no_concrete_provider_package_import(self):
        offenders = []
        for surface in self.SURFACES:
            if not surface.exists():
                continue
            paths = (
                [surface]
                if surface.is_file()
                else list(surface.rglob("*.py"))
            )
            for path in paths:
                text = path.read_text(encoding="utf-8")
                for forbidden in self.FORBIDDEN_IMPORTS:
                    if forbidden in text:
                        offenders.append(
                            f"{path.relative_to(ROOT_DIR)}: {forbidden}"
                        )
        self.assertEqual(offenders, [])


class RoutesBusinessLogicBoundaryTests(unittest.TestCase):
    """Step 0.3 done-when: nothing outside a package's own transport imports
    business logic from a `routes.py` / `*_routes.py`.

    Package `__init__.py` files may re-export their own blueprints; that is the
    one allowed direction (transport out). Everything else must call a service.
    """

    TRANSPORT_FILENAMES = frozenset({
        "routes.py",
        "settings_routes.py",
        "sfx_routes.py",
        "project_routes.py",
        "assemble_routes.py",
        "archive_routes.py",
        "asset_routes.py",
        "export_routes.py",
        "animation_routes.py",
    })

    def test_no_non_transport_module_imports_from_a_routes_module(self):
        import ast

        root = Path(ROOT_DIR) / "scriptase"
        offenders = []
        for path in root.rglob("*.py"):
            if path.name in self.TRANSPORT_FILENAMES:
                continue
            # Package re-export of its own blueprints is the intended pattern.
            if path.name == "__init__.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                    leaf = module.rsplit(".", 1)[-1]
                    if leaf == "routes" or leaf.endswith("_routes"):
                        # Relative re-exports inside the same package (e.g.
                        # `from .routes import X` in a sibling transport) are
                        # still forbidden outside TRANSPORT_FILENAMES.
                        offenders.append(
                            f"{path.relative_to(ROOT_DIR)}: from {module}"
                        )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        leaf = alias.name.rsplit(".", 1)[-1]
                        if leaf == "routes" or leaf.endswith("_routes"):
                            offenders.append(
                                f"{path.relative_to(ROOT_DIR)}: import {alias.name}"
                            )
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
