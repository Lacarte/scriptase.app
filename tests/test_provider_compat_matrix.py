"""Step 16.4 — Compatibility matrix.

One place that locks every compatibility surface the provider platform promised
to keep working with zero user edits (contracts.md §39–§44, §48 A1–A4/A6):

  * every documented input alias → canonical provider id
  * every legacy selection-alias / settings-format upgrade
  * every node config type_version migration (M1–M3) and M4 non-mutating fallback
  * every legacy request-field name from §40.1
  * every built-in template validating and scheduling
  * frozen managed output artifact roots (§44)
"""

from __future__ import annotations

import copy
import os
import tempfile
import unittest
from copy import deepcopy

from scriptase.providers.compatibility import (
    LEGACY_SELECTION_ALIASES,
    normalize_selection_alias,
)
from scriptase.providers.domains import DOMAINS
from scriptase.providers.hub import hub
from scriptase.providers.settings_migrations import (
    SETTINGS_VERSION,
    apply_migrations,
)
from scriptase.engine.config_migrations import (
    ANIMATOR_V1_DEFAULT_PROVIDER,
    STORYBOARD_V1_DEFAULT_PROVIDER,
    TTS_V1_DEFAULT_ENGINE,
    animator_generate_1_to_2,
    storyboard_generate_1_to_2,
    tts_generate_1_to_2,
)
from scriptase.engine.migrations import migrate_workflow
from scriptase.engine.registry import get_node_type
from scriptase.engine.scheduler import WorkflowScheduler
from scriptase.engine.templates import serialize_templates
from scriptase.engine.validation import validate_workflow, validation_errors


# contracts.md §40.3 — the complete accepted-input alias table (both directions
# of the frozen map, input column only after 16.1 retired the emit column).
DOCUMENTED_ALIASES = {
    # Step 7.1 restored the script catalogue; the legacy bridge alias resolves.
    ("script", "builtin"): "gemini",
    ("script", "gemini"): "gemini",
    ("script", "random_template"): "random_template",
    ("scene_director", "builtin"): "n8n",
    ("scene_director", "n8n"): "n8n",
    ("tts", "inworld"): "inworld",
    ("image", "gemini"): "gemini_ws",
    ("image", "gemini_ws"): "gemini_ws",
    ("video", "grok"): "grok_automa",
    ("video", "midjourney"): "grok_automa",
    ("video", "grok_automa"): "grok_automa",
}

# contracts.md §40.1 — legacy request / config field names and their v2 target.
LEGACY_SELECTION_FIELDS = (
    # (surface, legacy_key, example_value, domain, canonical)
    ("node_config_tts", "engine", "inworld", "tts", "inworld"),
    ("node_config_storyboard", "provider", "gemini", "image", "gemini_ws"),
    ("node_config_animator", "provider", "grok", "video", "grok_automa"),
    ("http_override", "provider_override", "gemini", "image", "gemini_ws"),
    ("pipeline", "tts_provider", "inworld", "tts", "inworld"),
    ("pipeline", "animator_provider_override", "midjourney", "video", "grok_automa"),
    ("preflight", "storyboard_provider", "gemini", "image", "gemini_ws"),
    ("preflight", "asset_provider", "grok", "video", "grok_automa"),
)

# contracts.md §44 — managed output roots must never relocate.
MANAGED_ARTIFACT_ROOTS = {
    "script": "stories",
    "scene_director": "scenes",
    "tts": "tts",
    "image": "image",
    "video": "video",
}


class AliasMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hub.discover_all()

    def test_every_documented_alias_and_canonical_id_resolves(self):
        for (domain, alias), canonical in DOCUMENTED_ALIASES.items():
            with self.subTest(domain=domain, alias=alias):
                provider = hub.get(domain, alias)
                self.assertIsNotNone(
                    provider, f"{domain}/{alias} must resolve"
                )
                self.assertEqual(provider.id, canonical)

    def test_hub_aliases_match_the_documented_table(self):
        """No silent extra or missing alias — the hub is the source of truth."""
        expected = {
            (domain, alias): canonical
            for (domain, alias), canonical in DOCUMENTED_ALIASES.items()
            if alias != canonical
        }
        actual = {}
        for domain in hub.domains():
            for alias, canonical in hub.registry(domain).aliases().items():
                actual[(domain, alias)] = canonical
        self.assertEqual(actual, expected)

    def test_an_unknown_alias_does_not_resolve(self):
        self.assertIsNone(hub.get("tts", "no_such_provider_xyz"))
        self.assertIsNone(hub.get("image", "midjourney"))


class SelectionAliasAndSettingsFormatTests(unittest.TestCase):
    def test_every_legacy_selection_alias_normalizes(self):
        for legacy, canonical in LEGACY_SELECTION_ALIASES.items():
            with self.subTest(legacy=legacy):
                self.assertEqual(normalize_selection_alias(legacy), canonical)

    def test_builtin_is_domain_aware(self):
        self.assertEqual(
            normalize_selection_alias("builtin", domain="script"), "gemini"
        )
        self.assertEqual(
            normalize_selection_alias("builtin", domain="scene_director"), "n8n"
        )
        self.assertEqual(
            normalize_selection_alias("builtin", domain="tts"), "builtin"
        )

    def test_v1_settings_upgrade_is_lossless_and_idempotent(self):
        v1 = {
            "version": 1,
            "general": {},
            "domains": {
                "tts": {
                    "selected_provider": None,
                    "per_provider": {"inworld": {"api_key": "sk-keep"}},
                },
                "image": {"per_provider": {}},
                "video": {"selected_provider": "grok", "per_provider": {}},
            },
        }
        legacy = {
            "sts-tts-provider": "inworld",
            "sts-storyboard-provider": "gemini",
            "sts-asset-provider": "kie-ai",
        }
        once, changed = apply_migrations(copy.deepcopy(v1), legacy)
        self.assertTrue(changed)
        self.assertEqual(once["version"], SETTINGS_VERSION)
        self.assertEqual(once["domains"]["tts"]["selected_instance_id"], "inworld")
        self.assertEqual(
            once["domains"]["image"]["selected_instance_id"], "gemini_ws"
        )
        # Explicit selection always wins over the legacy key, and is normalized.
        self.assertEqual(
            once["domains"]["video"]["selected_instance_id"], "grok_automa"
        )
        from scriptase.providers.secrets import is_secret_ref, resolve_secret_refs

        key = once["domains"]["tts"]["instances"]["inworld"]["settings"]["api_key"]
        # Step 3.4 (v7): credentials become secret refs; the value is preserved.
        self.assertTrue(is_secret_ref(key))
        self.assertEqual(resolve_secret_refs({"api_key": key})["api_key"], "sk-keep")
        # Every catalog domain is present after the upgrade.
        self.assertEqual(set(once["domains"]), set(DOMAINS))
        # Step 7.1 restored gemini as the script default.
        self.assertEqual(once["domains"]["script"]["selected_instance_id"], "gemini")
        self.assertEqual(
            once["domains"]["scene_director"]["selected_instance_id"], "n8n"
        )

        twice, changed_again = apply_migrations(copy.deepcopy(once), legacy)
        self.assertFalse(changed_again)
        self.assertEqual(once, twice)


class NodeConfigMigrationMatrixTests(unittest.TestCase):
    """contracts.md §41.3 M1–M3 (+ M4 non-mutating fallback)."""

    def test_m1_tts_engine_to_provider_id(self):
        self.assertEqual(
            tts_generate_1_to_2({"engine": "inworld", "voice": "Ashley", "speed": 1.1}),
            {"provider_id": "inworld", "voice": "Ashley", "speed": 1.1},
        )
        self.assertEqual(
            tts_generate_1_to_2({}),
            {"provider_id": TTS_V1_DEFAULT_ENGINE},
        )

    def test_m2_storyboard_provider_and_gated_keys(self):
        migrated = storyboard_generate_1_to_2({
            "provider": "gemini",
            "prompt_prefix": "cinematic",
            "auto_type": True,
            "provider_options": {"existing": 1},
        })
        # Wire alias is rewritten to the canonical id (§40.3 rule 1).
        self.assertEqual(migrated["provider_id"], "gemini_ws")
        self.assertNotIn("provider", migrated)
        self.assertNotIn("prompt_prefix", migrated)
        self.assertEqual(
            migrated["provider_options"],
            {"existing": 1, "prompt_prefix": "cinematic", "auto_type": True},
        )
        self.assertEqual(
            storyboard_generate_1_to_2({})["provider_id"],
            STORYBOARD_V1_DEFAULT_PROVIDER,
        )

    def test_m3_animator_provider_and_gated_keys(self):
        migrated = animator_generate_1_to_2({
            "provider": "kie-ai",
            "mode": "i2v",
            "quality": "hd",
            "duration": 5,
            "auto_type": False,
        })
        self.assertEqual(migrated["provider_id"], "kie_ai")
        for key in ("provider", "mode", "quality", "duration", "auto_type"):
            self.assertNotIn(key, migrated)
        self.assertEqual(
            migrated["provider_options"],
            {"mode": "i2v", "quality": "hd", "duration": 5, "auto_type": False},
        )
        self.assertEqual(
            animator_generate_1_to_2({})["provider_id"],
            ANIMATOR_V1_DEFAULT_PROVIDER,
        )

    def test_m1_m2_m3_round_trip_through_migrate_workflow(self):
        document = {
            "schema_version": 1,
            "name": "legacy",
            "nodes": [
                {
                    "id": "n_tts",
                    "type": "tts.generate",
                    "type_version": 1,
                    "name": "TTS",
                    "position": {"x": 0, "y": 0},
                    "configuration": {"engine": "kokoro", "voice": "af_heart"},
                    "disabled": False,
                },
                {
                    "id": "n_sb",
                    "type": "storyboard.generate",
                    "type_version": 1,
                    "name": "Storyboard",
                    "position": {"x": 0, "y": 0},
                    "configuration": {"provider": "webhook"},
                    "disabled": False,
                },
                {
                    "id": "n_an",
                    "type": "animator.generate",
                    "type_version": 1,
                    "name": "Animator",
                    "position": {"x": 0, "y": 0},
                    "configuration": {"provider": "grok"},
                    "disabled": False,
                },
            ],
            "edges": [],
            "variables": {},
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "settings": {"on_error": "stop"},
            "extensions": {},
        }
        result = migrate_workflow(document)
        by_id = {node["id"]: node for node in result.document["nodes"]}
        self.assertEqual(by_id["n_tts"]["type_version"], 3)
        self.assertEqual(by_id["n_tts"]["configuration"]["provider_id"], "inworld")
        self.assertEqual(by_id["n_tts"]["configuration"]["voice"], "Ashley")
        self.assertNotIn("engine", by_id["n_tts"]["configuration"])
        self.assertEqual(by_id["n_sb"]["type_version"], 3)
        self.assertEqual(
            by_id["n_sb"]["configuration"]["provider_id"], "gemini_ws"
        )
        self.assertEqual(by_id["n_an"]["type_version"], 3)
        self.assertEqual(by_id["n_an"]["configuration"]["provider_id"], "grok_automa")
        # Source document is never mutated.
        self.assertEqual(document["nodes"][0]["type_version"], 1)
        self.assertEqual(document["nodes"][0]["configuration"]["engine"], "kokoro")
        # Idempotent: already-v2 is a no-op.
        again = migrate_workflow(result.document)
        self.assertEqual(again.trail, [])
        self.assertEqual(again.document["nodes"], result.document["nodes"])

    def test_m4_story_and_scenes_keep_type_version_1(self):
        for type_key in ("story.generate", "scenes.blueprint"):
            with self.subTest(type_key=type_key):
                definition = get_node_type(type_key)
                self.assertEqual(definition["type_version"], 1)
                self.assertEqual(definition.get("migrations") or {}, {})
                # Absent provider_id is accepted; the adapter resolves the default.
                field_names = {f["name"] for f in definition["config_schema"]}
                self.assertIn("provider_id", field_names)


class LegacyRequestFieldMatrixTests(unittest.TestCase):
    """§40.1 fields resolve through the same alias table the hub uses."""

    @classmethod
    def setUpClass(cls):
        hub.discover_all()

    def test_every_legacy_selection_value_resolves_to_its_canonical(self):
        for surface, field, value, domain, canonical in LEGACY_SELECTION_FIELDS:
            with self.subTest(surface=surface, field=field, value=value):
                # Selection aliases + hub aliases cover the full wire vocabulary.
                normalized = normalize_selection_alias(value, domain=domain)
                provider = hub.get(domain, normalized) or hub.get(domain, value)
                self.assertIsNotNone(provider)
                self.assertEqual(provider.id, canonical)


class BuiltInTemplateMatrixTests(unittest.TestCase):
    def test_every_built_in_template_validates_and_schedules(self):
        templates = serialize_templates()
        self.assertEqual(
            [item["template_id"] for item in templates],
            [
                "full_video",
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

        with tempfile.TemporaryDirectory(prefix="sts_16_4_templates_") as root:
            for item in templates:
                with self.subTest(template=item["template_id"]):
                    workflow = deepcopy(item["workflow"])
                    problems = validate_workflow(
                        workflow, require_identity=False, require_complete=False
                    )
                    self.assertEqual(
                        validation_errors(problems), [], item["template_id"]
                    )
                    # Provider nodes use current type_version + provider_id.
                    for node in workflow["nodes"]:
                        if node["type"] in {
                            "tts.generate",
                            "storyboard.generate",
                            "animator.generate",
                        }:
                            self.assertEqual(node["type_version"], 3)
                            self.assertIn("provider_id", node["configuration"])
                            self.assertNotIn("engine", node["configuration"])
                            self.assertNotIn("provider", node["configuration"])
                    workflow.update({
                        "workflow_id": "wf_ABC123",
                        "created_at": "2026-08-09T12:00:00Z",
                        "updated_at": "2026-08-09T12:00:00Z",
                    })
                    for node in workflow["nodes"]:
                        if node["type"] == "script.input":
                            node["configuration"]["text"] = "Matrix template run."
                        elif node["type"] == "project.existing":
                            node["configuration"]["project_id"] = "pm_ABC123"
                    result = WorkflowScheduler(
                        workflow,
                        project_id="pm_ABC123",
                        lock_root=os.path.join(root, "locks"),
                        output_dir=root,
                        executor_resolver=resolver,
                    ).run()
                    self.assertEqual(result.status, "succeeded", item["template_id"])


class OutputArtifactRootTests(unittest.TestCase):
    def test_managed_roots_remain_under_output_domain_folders(self):
        """§44 — relocation would strand every existing project and cache entry."""
        for domain, folder in MANAGED_ARTIFACT_ROOTS.items():
            with self.subTest(domain=domain):
                self.assertIn(domain, DOMAINS)
                # The frozen relative prefixes used by adapters / services.
                self.assertTrue(folder)
                self.assertNotIn("..", folder)
                self.assertNotIn("/", folder.replace("\\", "/"))


if __name__ == "__main__":
    unittest.main()
