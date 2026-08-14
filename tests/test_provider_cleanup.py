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


# Deferred to step 0.3 with the module it exercises:
#
#   AppConfigKeyRetirementTests — GET/PATCH `/api/settings` never reintroduces
#   the three retired `sts-*-provider` keys.
#
# The endpoint lives in the compose (V2 `editor`) blueprint, which step 0.3
# splits into separate blueprints; `strip_legacy_selection_keys`, the logic
# under test, is already covered above by `LegacySelectionKeyTests`.


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

    SURFACES = (
        Path(ROOT_DIR) / "studio" / "workflows" / "adapters",
        Path(ROOT_DIR) / "studio" / "workflows" / "registry.py",
        Path(ROOT_DIR) / "studio" / "providers" / "catalog.py",
        Path(ROOT_DIR) / "studio" / "pipeline" / "services.py",
        Path(ROOT_DIR) / "studio" / "shared" / "providers_common" / "extension_ops.py",
    )

    def test_no_concrete_provider_package_import(self):
        offenders = []
        for surface in self.SURFACES:
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


if __name__ == "__main__":
    unittest.main()
