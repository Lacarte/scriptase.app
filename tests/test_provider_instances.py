"""Step 3.1: split provider type from provider instance.

Done when:
  * two instances of one provider type hold independent settings, availability,
    and health state
  * a V2 settings file migrates forward with its selection intact
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from flask import Flask

from scriptase.providers import providers_bp
from scriptase.providers import catalog as catalog_module
from scriptase.providers import routes as routes_module
from scriptase.providers import settings_manager
from scriptase.providers.concurrency import exclusive_lock
from scriptase.providers.domains import DOMAINS
from scriptase.providers.hub import ProviderHub
from scriptase.providers.registry import (
    AVAILABLE,
    NEEDS_CONFIGURATION,
)
from scriptase.providers.settings_migrations import (
    SETTINGS_VERSION,
    apply_migrations,
)

from test_provider_lifecycle import demo_spec, write_provider


REQUIRING_MANIFEST = """
from scriptase.providers import ProviderManifest


def manifest():
    return ProviderManifest(
        id='alpha',
        label='Alpha',
        domain='demo',
        kind='cloud',
        version='1.0.0',
        requires=['api_key'],
        capabilities={'batch': True},
    )
"""

FACTORY_PROVIDER = """
class Demo:
    instances = 0
    def __init__(self):
        Demo.instances += 1


def create():
    return Demo()


def health_check(settings):
    key = (settings or {}).get('api_key') or ''
    if not key:
        return {'status': 'fail', 'message': 'missing key'}
    return {'status': 'ok', 'latency_ms': 1.0, 'message': key}
"""


class InstanceSettingsMigrationTests(unittest.TestCase):
    def test_v5_settings_become_instances_with_selection_intact(self):
        v5 = {
            "version": 5,
            "general": {},
            "domains": {
                "tts": {
                    "selected_provider": "inworld",
                    "per_provider": {
                        "inworld": {"api_key": "sk-keep", "voice": "Ashley"},
                        "kokoro": {"voice": "af_bella"},
                    },
                },
                "image": {
                    "selected_provider": "gemini_ws",
                    "per_provider": {},
                },
            },
        }
        migrated, changed = apply_migrations(json.loads(json.dumps(v5)), {})
        self.assertTrue(changed)
        self.assertEqual(migrated["version"], SETTINGS_VERSION)

        from scriptase.providers.secrets import is_secret_ref, resolve_secret_refs

        tts = migrated["domains"]["tts"]
        self.assertEqual(tts["selected_instance_id"], "inworld")
        self.assertNotIn("selected_provider", tts)
        self.assertNotIn("per_provider", tts)
        inworld = tts["instances"]["inworld"]
        self.assertEqual(inworld["type"], "inworld")
        # v14 gives the default instance its friendly settings-page label.
        self.assertEqual(inworld["label"], "Voice Generator")
        self.assertEqual(inworld["settings"]["voice"], "Ashley")
        # Step 3.4 (v7): credentials become secret refs.
        self.assertTrue(is_secret_ref(inworld["settings"]["api_key"]))
        self.assertEqual(
            resolve_secret_refs(inworld["settings"]),
            {"api_key": "sk-keep", "voice": "Ashley"},
        )
        self.assertNotIn("kokoro", tts["instances"])

        image = migrated["domains"]["image"]
        self.assertEqual(image["selected_instance_id"], "gemini_ws")
        self.assertEqual(
            image["instances"]["gemini_ws"]["type"], "gemini_ws"
        )

        # Idempotent on the post-3.1 shape.
        again, changed_again = apply_migrations(json.loads(json.dumps(migrated)), {})
        self.assertFalse(changed_again)
        self.assertEqual(migrated, again)

    def test_v1_file_still_migrates_selection_through_to_v6(self):
        v1 = {
            "version": 1,
            "general": {},
            "domains": {
                "tts": {
                    "selected_provider": None,
                    "per_provider": {"inworld": {"api_key": "sk"}},
                },
            },
        }
        legacy = {"sts-tts-provider": "inworld"}
        migrated, _ = apply_migrations(json.loads(json.dumps(v1)), legacy)
        from scriptase.providers.secrets import is_secret_ref, resolve_secret_refs

        self.assertEqual(migrated["version"], SETTINGS_VERSION)
        self.assertEqual(
            migrated["domains"]["tts"]["selected_instance_id"], "inworld"
        )
        key = migrated["domains"]["tts"]["instances"]["inworld"]["settings"]["api_key"]
        self.assertTrue(is_secret_ref(key))
        self.assertEqual(resolve_secret_refs({"api_key": key})["api_key"], "sk")


class TwoInstancesIndependenceTests(unittest.TestCase):
    """Two instances of one type hold independent settings / availability / health."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="sts_3_1_")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.spec = demo_spec(self.base)
        write_provider(
            self.base,
            "alpha",
            manifest_body=REQUIRING_MANIFEST,
            provider_body=FACTORY_PROVIDER,
        )
        self.hub = ProviderHub({"demo": self.spec})
        self.hub.discover_all()

        self.settings = {
            "version": SETTINGS_VERSION,
            "general": {},
            "domains": {
                "demo": {
                    "selected_instance_id": "alpha_main",
                    "instances": {
                        "alpha_main": {
                            "type": "alpha",
                            "label": "Alpha Main",
                            "settings": {"api_key": "sk-main"},
                        },
                        "alpha_backup": {
                            "type": "alpha",
                            "label": "Alpha Backup",
                            "settings": {},
                        },
                    },
                }
            },
        }
        self.saved = []

        def load():
            return json.loads(json.dumps(self.settings))

        def save(data):
            self.saved.append(data)
            self.settings = json.loads(json.dumps(data))

        for attr, value in (
            ("load_settings", load),
            ("save_settings", save),
        ):
            patcher = patch.object(settings_manager, attr, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.provider = self.hub.get("demo", "alpha")
        self.assertIsNotNone(self.provider)

    def test_settings_are_independent(self):
        from scriptase.providers.secrets import is_secret_ref, resolve_secret_refs

        main = settings_manager.get_instance_settings("demo", "alpha_main")
        backup = settings_manager.get_instance_settings("demo", "alpha_backup")
        self.assertEqual(resolve_secret_refs(main), {"api_key": "sk-main"})
        self.assertEqual(backup, {})

        settings_manager.set_instance_settings(
            "demo",
            "alpha_backup",
            {"api_key": "sk-backup"},
            provider_type="alpha",
            label="Alpha Backup",
        )
        self.assertEqual(
            resolve_secret_refs(
                settings_manager.get_instance_settings("demo", "alpha_main")
            ),
            {"api_key": "sk-main"},
        )
        backup_after = settings_manager.get_instance_settings("demo", "alpha_backup")
        # Step 3.4: writes materialise credentials as secret refs.
        self.assertTrue(is_secret_ref(backup_after["api_key"]))
        self.assertEqual(resolve_secret_refs(backup_after), {"api_key": "sk-backup"})

    def test_availability_is_independent(self):
        main_settings = settings_manager.get_instance_settings("demo", "alpha_main")
        backup_settings = settings_manager.get_instance_settings("demo", "alpha_backup")
        self.assertEqual(
            self.provider.availability(main_settings, instance_id="alpha_main"),
            AVAILABLE,
        )
        self.assertEqual(
            self.provider.availability(backup_settings, instance_id="alpha_backup"),
            NEEDS_CONFIGURATION,
        )

    def test_health_is_independent(self):
        main = self.provider.health_check(
            settings_manager.get_instance_settings("demo", "alpha_main")
        )
        backup = self.provider.health_check(
            settings_manager.get_instance_settings("demo", "alpha_backup")
        )
        self.assertEqual(main.status, "ok")
        self.assertEqual(main.message, "sk-main")
        self.assertEqual(backup.status, "fail")

    def test_construction_is_memoized_per_instance(self):
        first_main = self.provider.create("alpha_main")
        second_main = self.provider.create("alpha_main")
        backup = self.provider.create("alpha_backup")
        self.assertIs(first_main, second_main)
        self.assertIsNot(first_main, backup)
        self.assertEqual(type(first_main).instances, 2)

    def test_hub_create_accepts_instance_id(self):
        a = self.hub.create("demo", "alpha", instance_id="alpha_main")
        b = self.hub.create("demo", "alpha", instance_id="alpha_backup")
        self.assertIsNot(a, b)

    def test_exclusive_lock_is_per_instance(self):
        lock_main = exclusive_lock("demo", "alpha", "alpha_main")
        lock_backup = exclusive_lock("demo", "alpha", "alpha_backup")
        lock_main_again = exclusive_lock("demo", "alpha", "alpha_main")
        self.assertIs(lock_main, lock_main_again)
        self.assertIsNot(lock_main, lock_backup)

        held = []
        barrier = threading.Barrier(2)

        def grab(lock, slot):
            with lock:
                held.append(slot)
                barrier.wait()

        t1 = threading.Thread(target=grab, args=(lock_main, "main"))
        t2 = threading.Thread(target=grab, args=(lock_backup, "backup"))
        t1.start()
        t2.start()
        t1.join(timeout=2)
        t2.join(timeout=2)
        self.assertEqual(sorted(held), ["backup", "main"])


class InstanceApiTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(providers_bp)
        self.client = app.test_client()

        self.base = tempfile.mkdtemp(prefix="sts_3_1_api_")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.spec = demo_spec(self.base)
        write_provider(
            self.base,
            "alpha",
            manifest_body=REQUIRING_MANIFEST,
            provider_body=FACTORY_PROVIDER,
        )

        self.settings = {
            "version": SETTINGS_VERSION,
            "general": {},
            "domains": {
                "demo": {
                    "selected_instance_id": "alpha",
                    "instances": {
                        "alpha": {
                            "type": "alpha",
                            "label": "Alpha",
                            "settings": {"api_key": "sk-main"},
                        }
                    },
                }
            },
        }
        self.saved = []

        def load():
            return json.loads(json.dumps(self.settings))

        def save(data):
            self.saved.append(data)
            self.settings = json.loads(json.dumps(data))

        for attr, value in (
            ("load_settings", load),
            ("save_settings", save),
        ):
            patcher = patch.object(settings_manager, attr, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)

        hub = ProviderHub({"demo": self.spec})
        hub.discover_all()
        catalog = {"demo": self.spec}
        for module in (routes_module, catalog_module):
            patcher = patch.object(module, "hub", hub)
            patcher.start()
            self.addCleanup(patcher.stop)
            if hasattr(module, "DOMAINS"):
                patcher = patch.object(module, "DOMAINS", catalog)
                patcher.start()
                self.addCleanup(patcher.stop)

    def test_create_second_instance_and_probe_independently(self):
        created = self.client.post(
            "/api/providers/demo/instances",
            json={
                "provider_type": "alpha",
                "label": "Alpha Backup",
                "settings": {},
            },
        )
        self.assertEqual(created.status_code, 201, created.get_data(as_text=True))
        body = created.get_json()
        backup_id = body["instance_id"]
        self.assertNotEqual(backup_id, "alpha")
        self.assertEqual(body["provider_type"], "alpha")

        main_health = self.client.get("/api/providers/demo/instances/alpha/health")
        backup_health = self.client.get(
            f"/api/providers/demo/instances/{backup_id}/health"
        )
        self.assertEqual(main_health.status_code, 200)
        self.assertEqual(backup_health.status_code, 200)
        self.assertEqual(main_health.get_json()["health"]["status"], "ok")
        self.assertEqual(backup_health.get_json()["health"]["status"], "fail")

        # Type-scoped path still addresses the default instance.
        type_health = self.client.get("/api/providers/demo/alpha/health")
        self.assertEqual(type_health.get_json()["instance_id"], "alpha")
        self.assertEqual(type_health.get_json()["health"]["status"], "ok")

    def test_selection_accepts_instance_id(self):
        self.client.post(
            "/api/providers/demo/instances",
            json={"provider_type": "alpha", "instance_id": "alpha_backup", "settings": {}},
        )
        resp = self.client.put(
            "/api/providers/demo/selection",
            json={"instance_id": "alpha_backup"},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload["selected_instance_id"], "alpha_backup")
        self.assertEqual(payload["provider_type"], "alpha")
        self.assertEqual(
            self.settings["domains"]["demo"]["selected_instance_id"],
            "alpha_backup",
        )

    def test_catalog_lists_instances(self):
        self.client.post(
            "/api/providers/demo/instances",
            json={"provider_type": "alpha", "instance_id": "alpha_backup", "settings": {}},
        )
        resp = self.client.get("/api/providers")
        self.assertEqual(resp.status_code, 200)
        domain = resp.get_json()["domains"]["demo"]
        instance_ids = {entry["instance_id"] for entry in domain["instances"]}
        self.assertIn("alpha", instance_ids)
        self.assertIn("alpha_backup", instance_ids)
        self.assertEqual(domain["selected_instance_id"], "alpha")


class DefaultSettingsShapeTests(unittest.TestCase):
    def test_defaults_use_instances(self):
        defaults = settings_manager._default_settings()
        self.assertEqual(defaults["version"], SETTINGS_VERSION)
        for domain_id, spec in DOMAINS.items():
            block = defaults["domains"][domain_id]
            self.assertEqual(block["selected_instance_id"], spec.default_provider)
            if spec.default_provider is None:
                self.assertEqual(block["instances"], {})
            else:
                self.assertIn(spec.default_provider, block["instances"])
                self.assertEqual(
                    block["instances"][spec.default_provider]["type"],
                    spec.default_provider,
                )
            self.assertNotIn("selected_provider", block)
            self.assertNotIn("per_provider", block)


if __name__ == "__main__":
    unittest.main()
