"""Step 3.2: instance-aware option sources and provider list.

Done when: a node can select two instances of the same provider type and each
resolves its own model and voice lists through the option-source endpoint.
"""

from __future__ import annotations

import importlib
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

from scriptase.providers import providers_bp
from scriptase.providers import catalog as catalog_module
from scriptase.providers import routes as routes_module
from scriptase.providers import domains as domains_module
from scriptase.providers import settings_manager
from scriptase.providers.hub import ProviderHub
from scriptase.engine import options as workflow_options
from scriptase.engine import workflows_bp
from scriptase.engine.options import build_context
from scriptase.engine.registry import ASYNC_OPTION_SOURCES, OptionSourceSpec

from test_provider_lifecycle import demo_spec, write_provider

hub_module = importlib.import_module("scriptase.providers.hub")


MODELS_PROVIDER = """
MODELS_BY_KEY = {
    'sk-main': [
        {'id': 'main-a', 'name': 'Main A', 'price': '0.01'},
        {'id': 'main-b', 'name': 'Main B'},
    ],
    'sk-backup': [
        {'id': 'backup-only', 'name': 'Backup Only'},
    ],
}


class Demo:
    def __init__(self):
        pass


def create():
    return Demo()


def list_models(settings):
    key = (settings or {}).get('api_key') or ''
    return list(MODELS_BY_KEY.get(key, []))


def health_check(settings):
    key = (settings or {}).get('api_key') or ''
    if not key:
        return {'status': 'fail', 'message': 'missing key'}
    return {'status': 'ok', 'latency_ms': 1.0, 'message': key}
"""

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

VOICE_SCHEMA = (
    "def settings_schema():\n"
    "    return {\n"
    "        'type': 'object',\n"
    "        'properties': {\n"
    "            'api_key': {'type': 'string', 'ui': {'type': 'password'}},\n"
    "            'voice': {\n"
    "                'type': 'string',\n"
    "                'ui': {'type': 'dropdown', 'options': ['shared']},\n"
    "            },\n"
    "        },\n"
    "        'required': ['api_key'],\n"
    "    }\n"
)


FIXTURE_SPEC = OptionSourceSpec(
    context=("domain", "provider", "instance"),
    cache="settings",
    domain="demo",
)


class TwoInstanceOptionSourceTests(unittest.TestCase):
    def setUp(self):
        workflow_options.clear_option_cache()
        self.addCleanup(workflow_options.clear_option_cache)

        self.base = tempfile.mkdtemp(prefix="sts_3_2_")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        write_provider(
            self.base,
            "alpha",
            domain="demo",
            manifest_body=REQUIRING_MANIFEST,
            provider_body=MODELS_PROVIDER,
            schema_body=VOICE_SCHEMA,
        )

        self.spec = demo_spec(self.base)
        self.hub = ProviderHub({"demo": self.spec})
        self.hub.discover_all()

        self.settings = {
            "version": settings_manager.SETTINGS_VERSION,
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
                            "settings": {"api_key": "sk-backup"},
                        },
                    },
                }
            },
        }

        catalog = {"demo": self.spec}
        self._patch(patch.object(hub_module, "hub", self.hub))
        self._patch(patch.object(domains_module, "DOMAINS", catalog))
        for module in (routes_module, catalog_module):
            self._patch(patch.object(module, "hub", self.hub))
            if hasattr(module, "DOMAINS"):
                self._patch(patch.object(module, "DOMAINS", catalog))
        self._patch(
            patch.object(
                settings_manager,
                "load_settings",
                side_effect=lambda: json.loads(json.dumps(self.settings)),
            )
        )
        self._patch(
            patch.object(settings_manager, "save_settings", side_effect=self._save)
        )

        # A settings-sensitive fixture that reads the instance's stored key,
        # proving two instances of one type answer differently.
        def voices_resolver(ctx):
            settings = settings_manager.get_instance_settings(
                ctx.domain, ctx.instance or ctx.provider
            )
            key = settings.get("api_key") or ""
            if key == "sk-main":
                return [
                    {"value": "main_voice", "label": "Main Voice"},
                    {"value": "shared", "label": "Shared"},
                ]
            if key == "sk-backup":
                return [
                    {"value": "backup_voice", "label": "Backup Voice"},
                ]
            return []

        self._patch(
            patch.dict(ASYNC_OPTION_SOURCES, {"fixture_voices": FIXTURE_SPEC})
        )
        self._patch(
            patch.dict(
                workflow_options._RESOLVERS, {"fixture_voices": voices_resolver}
            )
        )
        # Domain-scoped providers list for the synthetic demo domain.
        providers_spec = OptionSourceSpec(cache="settings", domain="demo")
        self._patch(
            patch.dict(ASYNC_OPTION_SOURCES, {"demo_providers": providers_spec})
        )
        self._patch(
            patch.dict(
                workflow_options._RESOLVERS,
                {"demo_providers": workflow_options._provider_options},
            )
        )

        app = Flask(__name__)
        app.register_blueprint(workflows_bp)
        app.register_blueprint(providers_bp)
        self.client = app.test_client()

    def _save(self, data):
        self.settings = json.loads(json.dumps(data))

    def _patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def fetch(self, source, query=""):
        return self.client.get(f"/api/workflow/options/{source}{query}")

    def values(self, source, query=""):
        body = self.fetch(source, query).get_json()
        return [opt["value"] for opt in body["options"]]

    def test_two_instances_resolve_different_voice_lists(self):
        main = self.values(
            "fixture_voices",
            "?domain=demo&provider=alpha&instance=alpha_main",
        )
        backup = self.values(
            "fixture_voices",
            "?domain=demo&provider=alpha&instance=alpha_backup",
        )
        self.assertEqual(main, ["main_voice", "shared"])
        self.assertEqual(backup, ["backup_voice"])
        self.assertFalse(set(main) & set(backup) - {"shared"})

    def test_instance_id_as_provider_param_still_resolves(self):
        # Nodes store instance id in provider_id; the option context may send
        # it as `provider` alone. The cache key must still distinguish them.
        main = self.values("fixture_voices", "?provider=alpha_main")
        backup = self.values("fixture_voices", "?provider=alpha_backup")
        self.assertEqual(main, ["main_voice", "shared"])
        self.assertEqual(backup, ["backup_voice"])

    def test_normalized_context_carries_instance(self):
        resp = self.fetch(
            "fixture_voices",
            "?domain=demo&instance=alpha_backup",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["context"]["provider"], "alpha")
        self.assertEqual(body["context"]["instance"], "alpha_backup")
        self.assertEqual(body["context"]["domain"], "demo")

    def test_provider_list_offers_both_instances(self):
        values = self.values("demo_providers")
        self.assertIn("alpha_main", values)
        self.assertIn("alpha_backup", values)
        labels = {
            opt["value"]: opt["label"]
            for opt in self.fetch("demo_providers").get_json()["options"]
        }
        self.assertEqual(labels["alpha_main"], "Alpha Main")
        self.assertEqual(labels["alpha_backup"], "Alpha Backup")

    def test_two_instances_resolve_different_model_lists(self):
        # list_models is keyed on instance settings (api_key).
        from scriptase.engine.options import OptionContext

        ctx_main = OptionContext(
            "fixture_models",
            FIXTURE_SPEC,
            {"domain": "demo", "provider": "alpha", "instance": "alpha_main"},
        )
        ctx_backup = OptionContext(
            "fixture_models",
            FIXTURE_SPEC,
            {"domain": "demo", "provider": "alpha", "instance": "alpha_backup"},
        )
        main_models = [
            m["id"] for m in workflow_options._provider_models(ctx_main)
        ]
        backup_models = [
            m["id"] for m in workflow_options._provider_models(ctx_backup)
        ]
        self.assertEqual(main_models, ["main-a", "main-b"])
        self.assertEqual(backup_models, ["backup-only"])

    def test_build_context_defaults_instance_from_selection(self):
        ctx = build_context("fixture_voices", {})
        self.assertEqual(ctx.provider, "alpha")
        self.assertEqual(ctx.instance, "alpha_main")


class ShippedSourceInstanceContextTests(unittest.TestCase):
    def test_tts_voices_and_image_models_accept_instance(self):
        for source in ("tts_voices", "image_models"):
            with self.subTest(source=source):
                self.assertIn("instance", ASYNC_OPTION_SOURCES[source].context)
                self.assertIn("provider", ASYNC_OPTION_SOURCES[source].context)

    def test_provider_lists_use_settings_cache(self):
        for domain in ("script", "scene_director", "tts", "image", "video"):
            with self.subTest(domain=domain):
                self.assertEqual(
                    ASYNC_OPTION_SOURCES[f"{domain}_providers"].cache,
                    "settings",
                )


if __name__ == "__main__":
    unittest.main()
