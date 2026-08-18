"""Step 3.4: secret references in the settings store.

Done when: no credential appears anywhere in the settings store, and the
egress-validation and redaction suites pass on every domain.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scriptase.providers import settings_manager
from scriptase.providers import settings_schema as ss
from scriptase.providers.errors import SECRET_REF_UNRESOLVED, ProviderError
from scriptase.providers.registry import (
    AVAILABLE,
    NEEDS_CONFIGURATION,
    ProviderInstance,
    ProviderManifest,
)
from scriptase.providers.results import validate_egress
from scriptase.providers.secrets import (
    SecretRefUnresolved,
    document_contains_plaintext_secret,
    extract_plaintext_from_document,
    extract_plaintext_from_settings,
    get_secret,
    is_secret_ref,
    load_secret_store,
    make_secret_ref,
    put_secret,
    resolve_secret_refs,
    secret_ref_id,
)
from scriptase.providers.settings_migrations import (
    SETTINGS_VERSION,
    apply_migrations,
    migrate_to_v7,
)
from scriptase.engine.redaction import collect_secrets, redact


def make_manifest(**overrides) -> ProviderManifest:
    fields = {
        "id": "alpha",
        "label": "Alpha",
        "domain": "tts",
        "kind": "cloud",
        "version": "1.0.0",
        "capabilities": {"batch": True},
        "requires": ["api_key"],
        "environment": {"api_key": "ALPHA_API_KEY"},
    }
    fields.update(overrides)
    return ProviderManifest(**fields)


def make_instance(manifest=None) -> ProviderInstance:
    module = type("ProviderModule", (), {"create": staticmethod(lambda: object())})
    return ProviderInstance("alpha", module, manifest or make_manifest())


class SecretRefWireFormTests(unittest.TestCase):
    def test_wire_form_is_the_frozen_shape(self):
        ref = make_secret_ref("s_abc")
        self.assertEqual(ref, {"$secret": "s_abc"})
        self.assertTrue(is_secret_ref(ref))
        self.assertEqual(secret_ref_id(ref), "s_abc")
        self.assertFalse(is_secret_ref({"$secret": ""}))
        self.assertFalse(is_secret_ref({"$secret": "x", "extra": 1}))
        self.assertFalse(is_secret_ref("s_abc"))


class SecretStoreIsolationTests(unittest.TestCase):
    """Each test gets its own secrets.json under a temp ROOT_DIR-like path."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sts_secrets_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.secrets_path = os.path.join(self.tmp, "secrets.json")
        self.settings_path = os.path.join(self.tmp, "settings.json")

        self._patch_paths()

    def _patch_paths(self):
        p1 = patch("scriptase.providers.secrets.SECRETS_DIR", self.tmp)
        p2 = patch("scriptase.providers.secrets.SECRETS_PATH", self.secrets_path)
        p3 = patch("scriptase.providers.settings_manager.SETTINGS_DIR", self.tmp)
        p4 = patch("scriptase.providers.settings_manager.SETTINGS_PATH", self.settings_path)
        for p in (p1, p2, p3, p4):
            p.start()
            self.addCleanup(p.stop)


class ExtractAndResolveTests(SecretStoreIsolationTests):
    def test_plaintext_is_replaced_with_a_ref_and_stored(self):
        out = extract_plaintext_from_settings({"api_key": "sk-live", "voice": "Ashley"})
        self.assertTrue(is_secret_ref(out["api_key"]))
        self.assertEqual(out["voice"], "Ashley")
        ref = secret_ref_id(out["api_key"])
        self.assertEqual(get_secret(ref), "sk-live")
        self.assertEqual(resolve_secret_refs(out)["api_key"], "sk-live")

    def test_updating_reuses_the_same_ref(self):
        first = extract_plaintext_from_settings({"api_key": "old"})
        ref = secret_ref_id(first["api_key"])
        second = extract_plaintext_from_settings(
            {"api_key": "new"}, previous=first
        )
        self.assertEqual(secret_ref_id(second["api_key"]), ref)
        self.assertEqual(get_secret(ref), "new")

    def test_clearing_a_secret_removes_the_store_entry(self):
        first = extract_plaintext_from_settings({"api_key": "sk-live"})
        ref = secret_ref_id(first["api_key"])
        second = extract_plaintext_from_settings({"api_key": ""}, previous=first)
        self.assertEqual(second["api_key"], "")
        self.assertIsNone(get_secret(ref))

    def test_document_extract_covers_every_instance(self):
        doc = {
            "version": 6,
            "domains": {
                "tts": {
                    "selected_instance_id": "inworld",
                    "instances": {
                        "inworld": {
                            "type": "inworld",
                            "label": "Inworld",
                            "settings": {"api_key": "sk-a", "voice": "A"},
                        },
                        "inworld_2": {
                            "type": "inworld",
                            "label": "Alt",
                            "settings": {"api_key": "sk-b"},
                        },
                    },
                }
            },
        }
        out = extract_plaintext_from_document(doc)
        a = out["domains"]["tts"]["instances"]["inworld"]["settings"]["api_key"]
        b = out["domains"]["tts"]["instances"]["inworld_2"]["settings"]["api_key"]
        self.assertTrue(is_secret_ref(a))
        self.assertTrue(is_secret_ref(b))
        self.assertNotEqual(secret_ref_id(a), secret_ref_id(b))
        self.assertEqual(document_contains_plaintext_secret(out), [])
        self.assertEqual(
            resolve_secret_refs(
                out["domains"]["tts"]["instances"]["inworld"]["settings"]
            )["api_key"],
            "sk-a",
        )


class ResolveSettingsTests(SecretStoreIsolationTests):
    def test_resolve_settings_is_the_whole_resolution_path(self):
        stored = extract_plaintext_from_settings({"api_key": "sk-from-store"})
        instance = make_instance()
        resolved = instance.resolve_settings(stored, instance_id="alpha")
        self.assertEqual(resolved["api_key"], "sk-from-store")

    def test_env_fallback_only_applies_to_the_default_instance(self):
        instance = make_instance()
        empty = {"api_key": ""}
        with patch.dict(os.environ, {"ALPHA_API_KEY": "from-env"}, clear=False):
            default = instance.resolve_settings(empty, instance_id="alpha")
            sibling = instance.resolve_settings(empty, instance_id="alpha_2")
            omitted = instance.resolve_settings(empty)
        self.assertEqual(default["api_key"], "from-env")
        self.assertEqual(omitted["api_key"], "from-env")
        self.assertEqual(sibling["api_key"], "")

    def test_stored_ref_wins_over_environment(self):
        stored = extract_plaintext_from_settings({"api_key": "sk-stored"})
        instance = make_instance()
        with patch.dict(os.environ, {"ALPHA_API_KEY": "from-env"}, clear=False):
            resolved = instance.resolve_settings(stored, instance_id="alpha")
        self.assertEqual(resolved["api_key"], "sk-stored")

    def test_unresolved_ref_is_empty_in_soft_mode(self):
        instance = make_instance()
        dangling = {"api_key": make_secret_ref("s_missing")}
        resolved = instance.resolve_settings(dangling, instance_id="alpha")
        self.assertEqual(resolved["api_key"], "")
        self.assertEqual(instance.availability(dangling, instance_id="alpha"), NEEDS_CONFIGURATION)

    def test_strict_resolve_raises_on_missing_ref(self):
        instance = make_instance()
        dangling = {"api_key": make_secret_ref("s_missing")}
        with self.assertRaises(SecretRefUnresolved) as ctx:
            instance.resolve_settings(dangling, instance_id="alpha", strict=True)
        self.assertEqual(ctx.exception.ref, "s_missing")
        # The platform code is registered for call-time failures.
        from scriptase.providers import errors as err_mod
        self.assertEqual(SECRET_REF_UNRESOLVED, "SECRET_REF_UNRESOLVED")
        self.assertIn(SECRET_REF_UNRESOLVED, err_mod.PROVIDER_CODES)
        self.assertFalse(err_mod.is_retryable(SECRET_REF_UNRESOLVED))
        # ProviderError can carry the code for call-time failures.
        err = ProviderError(SECRET_REF_UNRESOLVED, "Secret reference could not be resolved")
        self.assertEqual(err.code, SECRET_REF_UNRESOLVED)

    def test_configured_instance_reports_available(self):
        stored = extract_plaintext_from_settings({"api_key": "sk-live"})
        instance = make_instance()
        self.assertEqual(
            instance.availability(stored, instance_id="alpha"), AVAILABLE
        )


class SettingsWritePathTests(SecretStoreIsolationTests):
    def test_set_instance_settings_never_persists_plaintext(self):
        settings_manager.set_instance_settings(
            "tts",
            "inworld",
            {"api_key": "sk-live-topsecret", "voice": "Ashley"},
            provider_type="inworld",
            label="Inworld",
        )
        on_disk = json.loads(open(self.settings_path, encoding="utf-8").read())
        stored = on_disk["domains"]["tts"]["instances"]["inworld"]["settings"]
        self.assertTrue(is_secret_ref(stored["api_key"]))
        self.assertEqual(stored["voice"], "Ashley")
        self.assertEqual(document_contains_plaintext_secret(on_disk), [])
        self.assertNotIn("sk-live-topsecret", json.dumps(on_disk))
        # Secret store holds the real value.
        self.assertEqual(
            get_secret(secret_ref_id(stored["api_key"])), "sk-live-topsecret"
        )

    def test_save_settings_extracts_whole_document(self):
        doc = settings_manager._default_settings()
        doc["domains"]["tts"]["instances"]["kokoro"] = {
            "type": "kokoro",
            "label": "kokoro",
            "settings": {"api_key": "should-not-be-inline"},
        }
        settings_manager.save_settings(doc)
        on_disk = json.loads(open(self.settings_path, encoding="utf-8").read())
        self.assertEqual(document_contains_plaintext_secret(on_disk), [])
        self.assertNotIn("should-not-be-inline", json.dumps(on_disk))


class MigrationV7Tests(SecretStoreIsolationTests):
    def test_v7_rewrites_plaintext_credentials_to_refs(self):
        data = {
            "version": 6,
            "general": {},
            "domains": {
                "tts": {
                    "selected_instance_id": "inworld",
                    "instances": {
                        "inworld": {
                            "type": "inworld",
                            "label": "inworld",
                            "settings": {"api_key": "sk-migrate-me", "voice": "A"},
                        }
                    },
                }
            },
        }
        migrated = migrate_to_v7(data, {})
        key = migrated["domains"]["tts"]["instances"]["inworld"]["settings"]["api_key"]
        self.assertTrue(is_secret_ref(key))
        self.assertEqual(get_secret(secret_ref_id(key)), "sk-migrate-me")
        self.assertEqual(document_contains_plaintext_secret(migrated), [])

    def test_apply_migrations_reaches_v7(self):
        data = {
            "version": 6,
            "domains": {
                "tts": {
                    "selected_instance_id": "inworld",
                    "instances": {
                        "inworld": {
                            "type": "inworld",
                            "label": "inworld",
                            "settings": {"api_key": "sk-v7"},
                        }
                    },
                }
            },
        }
        migrated, changed = apply_migrations(data, {})
        self.assertTrue(changed)
        self.assertEqual(migrated["version"], SETTINGS_VERSION)
        # v7 introduced secret refs; v8 backfills catalog domains (step 7.3).
        self.assertGreaterEqual(SETTINGS_VERSION, 7)
        key = migrated["domains"]["tts"]["instances"]["inworld"]["settings"]["api_key"]
        self.assertTrue(is_secret_ref(key))


class RedactionSimplifiesTests(SecretStoreIsolationTests):
    def test_a_secret_ref_is_not_collected_as_a_secret_value(self):
        ref = make_secret_ref("s_opaque")
        found = collect_secrets({"api_key": ref, "nested": {"token": ref}})
        self.assertEqual(found, set())

    def test_redaction_still_serves_the_sentinel_for_secret_fields(self):
        stored = extract_plaintext_from_settings(
            {"api_key": "sk-live", "voice": "Ashley"}
        )
        redacted = ss.redact(stored)
        self.assertEqual(redacted["api_key"], ss.REDACTION_SENTINEL)
        self.assertEqual(redacted["voice"], "Ashley")
        # The ref id itself never leaves as a credential.
        self.assertNotIn("sk-live", json.dumps(redacted))

    def test_engine_redact_leaves_refs_alone_and_scrubs_plaintext(self):
        payload = {
            "settings": {"api_key": make_secret_ref("s_x"), "note": "ok"},
            "leaky": {"api_key": "sk-plaintext"},
        }
        cleaned = redact(payload)
        self.assertEqual(cleaned["settings"]["api_key"], make_secret_ref("s_x"))
        self.assertEqual(cleaned["leaky"]["api_key"], "[REDACTED]")

    def test_sentinel_patch_preserves_the_stored_ref(self):
        previous = extract_plaintext_from_settings({"api_key": "sk-live", "voice": "A"})
        merged = ss.apply_settings_patch(
            previous,
            {"api_key": ss.REDACTION_SENTINEL, "voice": "B"},
        )
        self.assertEqual(merged["api_key"], previous["api_key"])
        self.assertEqual(merged["voice"], "B")
        self.assertEqual(
            resolve_secret_refs(merged)["api_key"], "sk-live"
        )


class EgressAndDomainsTests(SecretStoreIsolationTests):
    """Done-when: egress + redaction clean across domains with secret refs."""

    DOMAINS = ("script", "scene_director", "tts", "image", "video")

    def test_settings_store_has_no_inline_credentials_for_any_domain(self):
        doc = settings_manager._default_settings()
        for domain in self.DOMAINS:
            block = doc["domains"][domain]
            iid = block["selected_instance_id"]
            if iid is None:
                continue
            block["instances"][iid]["settings"] = {
                "api_key": f"sk-{domain}-secret",
                "bearer_token": f"tok-{domain}",
            }
        settings_manager.save_settings(doc)
        on_disk = json.loads(open(self.settings_path, encoding="utf-8").read())
        leaks = document_contains_plaintext_secret(on_disk)
        self.assertEqual(leaks, [], msg=f"plaintext leaks: {leaks}")
        blob = json.dumps(on_disk)
        for domain in self.DOMAINS:
            self.assertNotIn(f"sk-{domain}-secret", blob)
            self.assertNotIn(f"tok-{domain}", blob)

        # Redacted document is egress-clean and contains no resolved secret.
        redacted = settings_manager.redact_settings(on_disk)
        self.assertEqual(validate_egress(redacted), [])
        self.assertNotIn("sk-", json.dumps(redacted))

        # Resolved settings for each domain still yield the real key in-process.
        for domain in self.DOMAINS:
            iid = on_disk["domains"][domain]["selected_instance_id"]
            if iid is None:
                continue
            stored = on_disk["domains"][domain]["instances"][iid]["settings"]
            resolved = resolve_secret_refs(stored)
            self.assertEqual(resolved["api_key"], f"sk-{domain}-secret")
            # And the resolved bag is never written back.
            self.assertTrue(is_secret_ref(stored["api_key"]))


if __name__ == "__main__":
    unittest.main()
