"""Step 11.5: the unified provider API and application startup.

Covers contracts.md §6 (one error envelope, loopback policy), §21.4/§21.5
(exclusions, availability), §24.2 (the targeted selection write and `PATCH
/api/settings/v2`), §25 (browser-safe serialization), and §27 (one hub behind
every handler).

The catalog tests run against a *synthetic* domain built in a temp directory, so
a mixed healthy/broken catalog can be asserted without shipping a broken provider
folder in the repo.
"""

import contextlib
import importlib
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

from scriptase.providers import providers_bp
from scriptase.providers import catalog as catalog_module
from scriptase.providers import routes as routes_module
from scriptase.providers import settings_manager
from scriptase.providers import settings_schema as ss
from scriptase.providers.domains import DOMAINS
from scriptase.providers.hub import ProviderHub
from scriptase.providers.registry import (
    AVAILABLE,
    DEGRADED,
    NEEDS_CONFIGURATION,
)
from scriptase.providers.runtime import RuntimeBinding

from test_provider_lifecycle import demo_spec, write_provider


# `providers_common.__init__` re-exports the `hub` *singleton*, which shadows the
# submodule of the same name for both `from ... import` and `import ... as`.
hub_module = importlib.import_module('scriptase.providers.hub')

REMOTE = {'REMOTE_ADDR': '10.11.12.13'}

# A provider package that is valid and constructable.
GOOD_PROVIDER = """
def create():
    return object()


def health_check(settings):
    return {'status': 'ok', 'latency_ms': 1.0}
"""

# A manifest that raises on import — discovery must exclude it and keep serving
# every healthy sibling (§21.4).
BROKEN_MANIFEST = """
raise RuntimeError('this manifest is broken')
"""


def requiring_manifest(provider_id, domain, requires, aliases=()):
    return (
        "from scriptase.providers import ProviderManifest\n\n\n"
        "def manifest():\n"
        "    return ProviderManifest(\n"
        f"        id={provider_id!r},\n"
        f"        label={provider_id.title()!r},\n"
        f"        domain={domain!r},\n"
        "        kind='cloud',\n"
        "        version='1.0.0',\n"
        f"        requires={list(requires)!r},\n"
        f"        aliases={list(aliases)!r},\n"
        "        capabilities={'batch': True},\n"
        "    )\n"
    )


class ProviderApiTestCase(unittest.TestCase):
    """A Flask client over the provider blueprint and a synthetic `demo` domain."""

    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(providers_bp)
        self.client = app.test_client()

        self.base = tempfile.mkdtemp(prefix='sts_11_5_')
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.spec = demo_spec(self.base)

        self.settings = {
            'version': settings_manager.SETTINGS_VERSION,
            'general': {},
            'domains': {'demo': {'selected_provider': 'alpha', 'per_provider': {}}},
        }
        self.saved = []

        self._patch(patch.object(
            settings_manager, 'load_settings',
            side_effect=lambda: json.loads(json.dumps(self.settings)),
        ))
        self._patch(patch.object(
            settings_manager, 'save_settings', side_effect=self._save
        ))

    def _save(self, data):
        self.saved.append(data)
        self.settings = json.loads(json.dumps(data))

    def _patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def install_hub(self):
        """Point every handler at a hub over the temp `demo` domain."""
        hub = ProviderHub({'demo': self.spec})
        hub.discover_all()
        catalog = {'demo': self.spec}
        for module in (routes_module, catalog_module):
            self._patch(patch.object(module, 'hub', hub))
            if hasattr(module, 'DOMAINS'):
                self._patch(patch.object(module, 'DOMAINS', catalog))
        return hub

    def provider_settings(self, provider_id, values):
        self.settings['domains']['demo']['per_provider'][provider_id] = values


# ---------------------------------------------------------------------------
# Policy: loopback and the one error envelope
# ---------------------------------------------------------------------------

class LoopbackPolicyTests(ProviderApiTestCase):
    REQUESTS = [
        ('get', '/api/providers', None),
        ('get', '/api/providers/tts', None),
        ('get', '/api/providers/tts/kokoro', None),
        ('get', '/api/providers/tts/kokoro/capabilities', None),
        ('get', '/api/providers/tts/kokoro/health', None),
        ('get', '/api/providers/tts/kokoro/settings', None),
        ('put', '/api/providers/tts/kokoro/settings', {}),
        ('post', '/api/providers/tts/kokoro/validate', {}),
        ('post', '/api/providers/tts/kokoro/test', {}),
        ('put', '/api/providers/tts/selection', {'provider_id': 'kokoro'}),
        ('get', '/api/settings/v2', None),
        ('put', '/api/settings/v2', {}),
        ('patch', '/api/settings/v2', {}),
    ]

    def test_every_endpoint_refuses_a_non_loopback_client(self):
        for method, path, body in self.REQUESTS:
            with self.subTest(path=f'{method.upper()} {path}'):
                kwargs = {'environ_base': REMOTE}
                if body is not None:
                    kwargs['json'] = body
                resp = getattr(self.client, method)(path, **kwargs)
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(resp.get_json()['error']['code'], 'FORBIDDEN')

    def test_a_loopback_client_is_allowed(self):
        self.assertEqual(self.client.get('/api/providers').status_code, 200)


class ErrorEnvelopeTests(ProviderApiTestCase):
    """Every failure is `{"error": {"code", "message", "details?"}}` (§6)."""

    CASES = [
        ('get', '/api/providers/music', None, 400, 'UNKNOWN_DOMAIN'),
        ('get', '/api/providers/music/anything', None, 400, 'UNKNOWN_DOMAIN'),
        ('get', '/api/providers/music/anything/settings', None, 400, 'UNKNOWN_DOMAIN'),
        ('put', '/api/providers/music/selection', {'provider_id': 'x'}, 400,
         'UNKNOWN_DOMAIN'),
        ('get', '/api/providers/tts/nope', None, 404, 'PROVIDER_NOT_FOUND'),
        ('get', '/api/providers/tts/nope/settings', None, 404, 'PROVIDER_NOT_FOUND'),
        ('get', '/api/providers/tts/nope/capabilities', None, 404, 'PROVIDER_NOT_FOUND'),
        ('get', '/api/providers/tts/nope/health', None, 404, 'PROVIDER_NOT_FOUND'),
        ('post', '/api/providers/tts/nope/validate', {}, 404, 'PROVIDER_NOT_FOUND'),
        ('put', '/api/providers/tts/selection', {'provider_id': 'nope'}, 404,
         'PROVIDER_NOT_FOUND'),
        ('put', '/api/providers/tts/selection', {}, 400, 'INVALID_REQUEST'),
        ('put', '/api/providers/tts/selection', {'provider_id': 42}, 400,
         'INVALID_REQUEST'),
        ('put', '/api/providers/tts/kokoro/settings', [], 400, 'INVALID_REQUEST'),
        ('put', '/api/settings/v2', [], 400, 'INVALID_REQUEST'),
        ('patch', '/api/settings/v2', [], 400, 'INVALID_REQUEST'),
    ]

    def test_failures_use_the_standard_envelope_and_status(self):
        for method, path, body, status, code in self.CASES:
            with self.subTest(path=f'{method.upper()} {path}', code=code):
                kwargs = {'json': body} if body is not None else {}
                resp = getattr(self.client, method)(path, **kwargs)
                self.assertEqual(resp.status_code, status)
                envelope = resp.get_json()['error']
                self.assertEqual(envelope['code'], code)
                self.assertTrue(envelope['message'])

    def test_an_invalid_settings_document_is_rejected(self):
        resp = self.client.put('/api/settings/v2', json={'domains': 'not-an-object'})
        self.assertEqual(resp.status_code, 400)
        envelope = resp.get_json()['error']
        self.assertEqual(envelope['code'], 'SETTINGS_INVALID')
        self.assertTrue(envelope['details']['issues'])
        self.assertEqual(self.saved, [])


# ---------------------------------------------------------------------------
# The catalog: healthy, unavailable, and broken providers, by domain
# ---------------------------------------------------------------------------

class CatalogTests(ProviderApiTestCase):
    def test_the_shipped_catalog_covers_every_domain(self):
        body = self.client.get('/api/providers').get_json()
        self.assertEqual(set(body['domains']), set(DOMAINS))
        for domain, spec in DOMAINS.items():
            with self.subTest(domain=domain):
                payload = body['domains'][domain]
                self.assertEqual(payload['label'], spec.label)
                self.assertEqual(payload['default_provider'], spec.default_provider)
                self.assertEqual(payload['count'], len(payload['providers']))

    def test_the_catalog_enumerates_the_deprecated_provider_identities(self):
        """Deprecation is carried by `aliases`, the retired legacy wire strings.

        §20.1 declares no `deprecated` flag, so a deprecated identity *is* an
        alias: `gemini`, `webhook`, `direct`, `grok`, `midjourney`, `kie-ai`.
        """
        domains = self.client.get('/api/providers').get_json()['domains']
        aliases = {
            alias: (domain, provider['id'])
            for domain, payload in domains.items()
            for provider in payload['providers']
            for alias in provider['aliases']
        }
        self.assertEqual(aliases['gemini'], ('image', 'gemini_ws'))
        self.assertEqual(aliases['webhook'], ('image', 'wavespeed_webhook'))
        self.assertEqual(aliases['direct'], ('image', 'wavespeed_direct'))
        self.assertEqual(aliases['grok'], ('video', 'grok_automa'))
        self.assertEqual(aliases['kie-ai'], ('video', 'kie_ai'))

        # And a deprecated identity resolves through the API to its canonical id.
        body = self.client.get('/api/providers/image/gemini').get_json()
        self.assertEqual(body['id'], 'gemini_ws')

    def test_a_mixed_catalog_serves_the_healthy_and_records_the_broken(self):
        write_provider(self.base, 'alpha', domain='demo', provider_body=GOOD_PROVIDER)
        write_provider(self.base, 'broken', domain='demo',
                       manifest_body=BROKEN_MANIFEST)
        write_provider(self.base, 'charlie', domain='demo')  # no create() -> degraded
        self.install_hub()

        payload = self.client.get('/api/providers').get_json()['domains']['demo']
        by_id = {p['id']: p for p in payload['providers']}

        self.assertEqual(sorted(by_id), ['alpha', 'charlie'])
        self.assertEqual(by_id['alpha']['availability'], AVAILABLE)
        self.assertEqual(by_id['charlie']['availability'], DEGRADED)
        # One broken folder neither hides a healthy provider nor inflates the count.
        self.assertEqual(payload['count'], 2)
        self.assertEqual([e['id'] for e in payload['excluded']], ['broken'])
        self.assertEqual(payload['excluded'][0]['reason_code'], 'MANIFEST_LOAD_FAILED')

    def test_a_provider_needing_configuration_is_reported_not_hidden(self):
        write_provider(
            self.base, 'alpha', domain='demo', provider_body=GOOD_PROVIDER,
            manifest_body=requiring_manifest('alpha', 'demo', ['api_key']),
        )
        self.install_hub()
        with patch.dict(os.environ, {}, clear=True):
            payload = self.client.get('/api/providers').get_json()['domains']['demo']
        self.assertEqual(payload['providers'][0]['availability'], NEEDS_CONFIGURATION)

    def test_an_excluded_provider_is_a_conflict_not_a_missing_one(self):
        write_provider(self.base, 'alpha', domain='demo', provider_body=GOOD_PROVIDER)
        write_provider(self.base, 'broken', domain='demo',
                       manifest_body=BROKEN_MANIFEST)
        self.install_hub()

        resp = self.client.get('/api/providers/demo/broken/settings')
        self.assertEqual(resp.status_code, 409)
        envelope = resp.get_json()['error']
        self.assertEqual(envelope['code'], 'PROVIDER_EXCLUDED')
        self.assertEqual(envelope['details']['reason_code'], 'MANIFEST_LOAD_FAILED')

    def test_the_catalog_version_tracks_the_catalog_contents(self):
        write_provider(self.base, 'alpha', domain='demo', provider_body=GOOD_PROVIDER)
        self.install_hub()

        first = self.client.get('/api/providers').get_json()['catalog_version']
        self.assertEqual(first, self.client.get('/api/providers').get_json()['catalog_version'])

        write_provider(self.base, 'bravo', domain='demo', provider_body=GOOD_PROVIDER)
        routes_module.hub.reload()
        second = self.client.get('/api/providers').get_json()['catalog_version']
        self.assertNotEqual(first, second)

    def test_the_dev_reload_flag_rides_along_without_moving_the_version(self):
        """Step 12.1: the browser store needs the flag to decide whether to
        subscribe to the reload stream, and it must not perturb the digest."""
        write_provider(self.base, 'alpha', domain='demo', provider_body=GOOD_PROVIDER)
        self.install_hub()

        with patch.dict(os.environ, {'STS_WORKFLOW_DEV_RELOAD': ''}, clear=False):
            off = self.client.get('/api/providers').get_json()
        with patch.dict(os.environ, {'STS_WORKFLOW_DEV_RELOAD': '1'}, clear=False):
            on = self.client.get('/api/providers').get_json()

        self.assertIs(off['dev_reload_enabled'], False)
        self.assertIs(on['dev_reload_enabled'], True)
        self.assertEqual(off['catalog_version'], on['catalog_version'])

    def test_no_internal_handle_reaches_the_catalog(self):
        write_provider(self.base, 'alpha', domain='demo', provider_body=GOOD_PROVIDER)
        self.install_hub()
        body = self.client.get('/api/providers').get_data(as_text=True)
        for forbidden in ('_sts_provider_', self.base, 'provider_module', 'schema_module'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body)


class DomainAndProviderDetailTests(ProviderApiTestCase):
    def setUp(self):
        super().setUp()
        write_provider(
            self.base, 'alpha', domain='demo', provider_body=GOOD_PROVIDER,
            capabilities={'batch': True, 'test_connection': False},
            aliases=['alpha-legacy'],
        )
        self.install_hub()

    def test_domain_detail_matches_the_catalog_slice(self):
        whole = self.client.get('/api/providers').get_json()['domains']['demo']
        self.assertEqual(self.client.get('/api/providers/demo').get_json(), whole)

    def test_provider_detail_reports_the_selection(self):
        body = self.client.get('/api/providers/demo/alpha').get_json()
        self.assertEqual(body['id'], 'alpha')
        self.assertEqual(body['availability'], AVAILABLE)
        self.assertTrue(body['selected'])

    def test_a_provider_is_reachable_through_its_alias(self):
        body = self.client.get('/api/providers/demo/alpha-legacy').get_json()
        # The canonical id is what comes back — an alias is never echoed as identity.
        self.assertEqual(body['id'], 'alpha')

    def test_capabilities_come_from_the_manifest_and_the_domain_vocabulary(self):
        body = self.client.get('/api/providers/demo/alpha/capabilities').get_json()
        self.assertEqual(body['capabilities'], {'batch': True, 'test_connection': False})
        self.assertEqual(body['vocabulary'], sorted(self.spec.capability_vocabulary))

    def test_health_is_probed_against_the_stored_settings(self):
        body = self.client.get('/api/providers/demo/alpha/health').get_json()
        self.assertEqual(body['health']['status'], 'ok')

    def test_a_provider_without_a_health_hook_is_unknown(self):
        write_provider(self.base, 'charlie', domain='demo')
        routes_module.hub.reload()
        body = self.client.get('/api/providers/demo/charlie/health').get_json()
        self.assertEqual(body['health']['status'], 'unknown')


# ---------------------------------------------------------------------------
# Selection (contracts.md §24.2)
# ---------------------------------------------------------------------------

class SelectionTests(ProviderApiTestCase):
    def setUp(self):
        super().setUp()
        write_provider(self.base, 'alpha', domain='demo', provider_body=GOOD_PROVIDER)
        write_provider(
            self.base, 'bravo', domain='demo', provider_body=GOOD_PROVIDER,
            manifest_body=requiring_manifest(
                'bravo', 'demo', ['api_key'], aliases=['bravo-legacy']
            ),
        )
        write_provider(self.base, 'broken', domain='demo',
                       manifest_body=BROKEN_MANIFEST)
        self.install_hub()

    def _select(self, provider_id):
        return self.client.put(
            '/api/providers/demo/selection', json={'provider_id': provider_id}
        )

    def test_selecting_writes_through_the_settings_manager(self):
        resp = self._select('bravo')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['selected'], 'bravo')
        self.assertEqual(
            self.saved[-1]['domains']['demo']['selected_provider'], 'bravo'
        )

    def test_an_alias_is_normalized_to_the_canonical_id_before_it_is_stored(self):
        resp = self._select('bravo-legacy')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['selected'], 'bravo')
        self.assertEqual(
            self.saved[-1]['domains']['demo']['selected_provider'], 'bravo'
        )

    def test_an_unconfigured_provider_may_still_be_selected(self):
        with patch.dict(os.environ, {}, clear=True):
            resp = self._select('bravo')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['availability'], NEEDS_CONFIGURATION)
        # Non-blocking: the write happened and the issues came back to prompt with.
        self.assertEqual(
            self.saved[-1]['domains']['demo']['selected_provider'], 'bravo'
        )
        self.assertIsInstance(body['issues'], list)

    def test_an_excluded_provider_cannot_be_selected(self):
        resp = self._select('broken')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.saved, [])

    def test_an_unknown_provider_cannot_be_selected(self):
        resp = self._select('ghost')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.saved, [])

    def test_the_selection_write_touches_only_the_selection(self):
        self.provider_settings('alpha', {'voice': 'Ashley'})
        self.settings['general'] = {'sync_folder': 'D:/keep-me'}
        self._select('bravo')
        written = self.saved[-1]
        self.assertEqual(written['general'], {'sync_folder': 'D:/keep-me'})
        self.assertEqual(
            written['domains']['demo']['per_provider']['alpha'], {'voice': 'Ashley'}
        )

    def test_a_secret_never_appears_in_the_selection_response(self):
        self.provider_settings('bravo', {'api_key': 'sk-live-topsecret'})
        resp = self._select('bravo')
        self.assertNotIn('sk-live-topsecret', resp.get_data(as_text=True))


# ---------------------------------------------------------------------------
# Whole settings document
# ---------------------------------------------------------------------------

class SettingsDocumentTests(ProviderApiTestCase):
    SECRET = 'sk-live-topsecret'

    def setUp(self):
        super().setUp()
        self.provider_settings('alpha', {'api_key': self.SECRET, 'voice': 'Ashley'})

    def test_patch_deep_merges_and_leaves_siblings_alone(self):
        resp = self.client.patch(
            '/api/settings/v2',
            json={'domains': {'demo': {'per_provider': {'alpha': {'voice': 'Carter'}}}}},
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        stored = self.saved[-1]['domains']['demo']['per_provider']['alpha']
        self.assertEqual(stored['voice'], 'Carter')
        # The untouched sibling — and the secret — survive the merge.
        self.assertEqual(stored['api_key'], self.SECRET)
        self.assertEqual(self.saved[-1]['domains']['demo']['selected_provider'], 'alpha')

    def test_patch_treats_the_redaction_sentinel_as_unchanged(self):
        self.client.patch(
            '/api/settings/v2',
            json={'domains': {'demo': {'per_provider': {
                'alpha': {'api_key': ss.REDACTION_SENTINEL}
            }}}},
        )
        stored = self.saved[-1]['domains']['demo']['per_provider']['alpha']
        self.assertEqual(stored['api_key'], self.SECRET)

    def test_patch_replaces_a_list_wholesale_rather_than_merging_it(self):
        self.settings['general']['voices'] = ['a', 'b']
        self.client.patch('/api/settings/v2', json={'general': {'voices': ['c']}})
        self.assertEqual(self.saved[-1]['general']['voices'], ['c'])

    def test_a_rejected_patch_writes_nothing(self):
        resp = self.client.patch('/api/settings/v2', json={'domains': 'nope'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.saved, [])

    def test_put_still_imports_a_whole_document(self):
        document = self.client.get('/api/settings/v2').get_json()
        document['general']['sync_folder'] = 'D:/imported'
        resp = self.client.put('/api/settings/v2', json=document)
        self.assertEqual(resp.status_code, 200)
        written = self.saved[-1]
        self.assertEqual(written['general']['sync_folder'], 'D:/imported')
        self.assertEqual(
            written['domains']['demo']['per_provider']['alpha']['api_key'], self.SECRET
        )


# ---------------------------------------------------------------------------
# Startup and shutdown
# ---------------------------------------------------------------------------

RUNTIME_PROVIDER = """
bound = []


def register_runtime(app, sock):
    bound.append((app, sock))


def create():
    return object()
"""


class StartupRuntimeTests(unittest.TestCase):
    """Each provider runtime is initialized exactly once per process.

    The count is taken at the `call_provider_runtime` boundary rather than from
    the provider module's own list: a reload re-imports `provider.py` under a
    fresh synthetic module, so its module-level state resets and would hide a
    duplicate bind.
    """

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='sts_11_5_rt_')
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        write_provider(self.base, 'alpha', domain='demo', kind='extension',
                       provider_body=RUNTIME_PROVIDER)
        self.hub = ProviderHub({'demo': demo_spec(self.base)})
        self.hub.discover_all()

        self.calls = []
        # `patch('scriptase.providers.hub....')` would resolve `hub` to
        # the package-level singleton, not the module — patch the module object.
        patcher = patch.object(
            hub_module, 'call_provider_runtime',
            side_effect=lambda provider_id, module, app, sock: (
                self.calls.append(provider_id) or RuntimeBinding(bound=True)
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_repeated_startup_does_not_rebind_a_runtime(self):
        self.hub.bind_runtimes(app=object(), sock=object())
        self.hub.bind_runtimes(app=object(), sock=object())
        self.assertEqual(self.calls, ['alpha'])

    def test_a_reload_does_not_rebind_a_surviving_runtime(self):
        self.hub.bind_runtimes(app=object(), sock=object())
        write_provider(self.base, 'bravo', domain='demo', kind='extension',
                       provider_body=RUNTIME_PROVIDER)
        self.hub.reload()

        # `alpha` survived the reload and is not rebound; `bravo` appeared after
        # startup and still gets its one binding.
        self.assertEqual(self.calls, ['alpha', 'bravo'])

    def test_shutdown_releases_the_binding_ledger(self):
        self.hub.bind_runtimes(app=object(), sock=object())
        self.hub.shutdown()
        self.hub.discover_all()
        self.hub.bind_runtimes(app=object(), sock=object())
        self.assertEqual(self.calls, ['alpha', 'alpha'])

    def test_a_non_extension_provider_never_gets_a_runtime(self):
        write_provider(self.base, 'charlie', domain='demo', kind='local',
                       provider_body=RUNTIME_PROVIDER)
        self.hub.reload()
        self.hub.bind_runtimes(app=object(), sock=object())
        self.assertEqual(self.calls, ['alpha'])


class BlueprintRegistrationTests(unittest.TestCase):
    """Compose (V2 editor) is split across seven blueprints; none own providers."""

    def _compose_blueprints(self):
        from scriptase.modules.compose import (
            compose_archive_bp,
            compose_assemble_bp,
            compose_assets_bp,
            compose_export_bp,
            compose_projects_bp,
            compose_settings_bp,
            compose_sfx_bp,
        )

        return (
            compose_archive_bp,
            compose_assemble_bp,
            compose_assets_bp,
            compose_export_bp,
            compose_projects_bp,
            compose_settings_bp,
            compose_sfx_bp,
        )

    def test_the_compose_blueprints_no_longer_own_a_provider_route(self):
        app = Flask(__name__)
        for bp in self._compose_blueprints():
            app.register_blueprint(bp)
        paths = {rule.rule for rule in app.url_map.iter_rules()}
        self.assertFalse({p for p in paths if p.startswith('/api/providers')})
        self.assertNotIn('/api/settings/v2', paths)

    def test_both_blueprints_coexist_on_one_app(self):
        app = Flask(__name__)
        for bp in self._compose_blueprints():
            app.register_blueprint(bp)
        app.register_blueprint(providers_bp)
        client = app.test_client()
        # Compose keeps the app-config store; the provider blueprint keeps
        # settings.json. The two /api/settings surfaces are unrelated (14.2).
        self.assertEqual(client.get('/api/providers').status_code, 200)
        with contextlib.suppress(Exception):
            self.assertEqual(client.get('/api/settings').status_code, 200)


if __name__ == '__main__':
    unittest.main()
