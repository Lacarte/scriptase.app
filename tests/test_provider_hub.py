"""Step 11.1: domain catalog, provider hub, and the shared domain binding.

Covers contracts.md §19.1 (catalog is data), §21.2 (deterministic discovery order),
§21.3 (duplicate ids), §21.4 (broken-provider isolation), and §27 (hub surface).
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scriptase.providers import settings_manager
from scriptase.providers.domains import DOMAINS, DomainSpec, get_domain
from scriptase.providers.hub import ProviderHub, bind_domain, hub
from scriptase.providers.registry import ProviderManifest, ProviderRegistry


MANIFEST_TEMPLATE = """
from scriptase.providers import ProviderManifest


def manifest():
    return ProviderManifest(
        id={id!r},
        label={label!r},
        domain={domain!r},
        kind='local',
        version='1.0.0',
        capabilities={{'batch': True}},
    )
"""


def _write_provider(base, provider_id, domain='tts', label=None, body=None):
    folder = os.path.join(base, provider_id)
    os.makedirs(folder, exist_ok=True)
    source = body if body is not None else MANIFEST_TEMPLATE.format(
        id=provider_id, label=label or provider_id.title(), domain=domain
    )
    with open(os.path.join(folder, 'manifest.py'), 'w', encoding='utf-8') as handle:
        handle.write(source)
    return folder


class DomainCatalogTests(unittest.TestCase):
    def test_catalog_declares_exactly_five_domains_in_order(self):
        self.assertEqual(
            list(DOMAINS),
            ['script', 'scene_director', 'tts', 'image', 'video'],
        )

    def test_every_spec_is_complete(self):
        for domain_id, spec in DOMAINS.items():
            self.assertEqual(spec.id, domain_id)
            self.assertTrue(spec.label)
            self.assertTrue(spec.package.startswith('scriptase.modules.'))
            self.assertTrue(os.path.isabs(spec.providers_base))
            self.assertTrue(spec.default_provider)
            self.assertIn('test_connection', spec.capability_vocabulary)

    def test_get_domain_rejects_unknown(self):
        with self.assertRaises(ValueError):
            get_domain('music')


class SingleSourceOfDomainTruthTests(unittest.TestCase):
    """The three previously hardcoded domain sets must all derive from DOMAINS."""

    def test_registry_valid_domains_is_the_catalog(self):
        self.assertEqual(ProviderRegistry.VALID_DOMAINS, frozenset(DOMAINS))

    def test_default_settings_are_generated_from_the_catalog(self):
        defaults = settings_manager._default_settings()
        self.assertEqual(list(defaults['domains']), list(DOMAINS))
        for domain_id, spec in DOMAINS.items():
            self.assertEqual(
                defaults['domains'][domain_id]['selected_provider'], spec.default_provider
            )
            self.assertEqual(defaults['domains'][domain_id]['per_provider'], {})

    def test_validate_settings_accepts_every_catalog_domain(self):
        issues = settings_manager.validate_settings(settings_manager._default_settings())
        self.assertEqual(issues, [])

    def test_validate_settings_warns_on_unknown_domain(self):
        data = settings_manager._default_settings()
        data['domains']['music'] = {'selected_provider': None, 'per_provider': {}}
        issues = settings_manager.validate_settings(data)
        self.assertEqual(
            [i['field'] for i in issues if i['severity'] == 'warning'], ['domains.music']
        )


class HubSurfaceTests(unittest.TestCase):
    def test_domains_follow_catalog_order(self):
        self.assertEqual(hub.domains(), list(DOMAINS))

    def test_registry_is_created_once_per_domain(self):
        first = hub.registry('tts')
        self.assertIs(first, hub.registry('tts'))
        self.assertEqual(first.domain, 'tts')

    def test_unknown_domain_fails_deterministically(self):
        with self.assertRaises(ValueError):
            hub.registry('music')
        self.assertIsNone(hub.get('music', 'anything'))
        self.assertEqual(hub.list('music'), [])

    def test_catalog_serializes_every_domain(self):
        payload = hub.catalog(selected={'tts': 'kokoro'})
        self.assertEqual(list(payload), list(DOMAINS))
        self.assertEqual(payload['tts']['selected'], 'kokoro')
        self.assertIsNone(payload['video']['selected'])
        self.assertEqual(
            [p['id'] for p in payload['script']['providers']],
            # Discovery order is sorted folder names; scaffold_check is the
            # step-16.2 demo package (folder drop, no hub/registry edit).
            ['gemini', 'random_template', 'scaffold_check'],
        )
        self.assertEqual([p['id'] for p in payload['scene_director']['providers']], ['n8n'])

    def test_shipped_domains_resolve_their_providers(self):
        self.assertIsNotNone(hub.get('tts', 'kokoro'))
        self.assertIsNotNone(hub.get('image', 'gemini_ws'))
        self.assertIsNotNone(hub.get('video', 'kie_ai'))
        self.assertIsNone(hub.get('tts', 'no_such_provider'))


class CompatibilityFacadeTests(unittest.TestCase):
    """Existing per-module imports must keep working (contracts.md §17.1)."""

    def test_tts_package_exposes_the_hub_registry(self):
        from scriptase.modules.tts import providers as tts_providers

        self.assertIs(tts_providers.registry, hub.registry('tts'))
        self.assertIs(tts_providers.get_provider('kokoro'), hub.get('tts', 'kokoro'))
        self.assertEqual(
            [p.id for p in tts_providers.list_providers()],
            [p.id for p in hub.list('tts')],
        )
        self.assertTrue(callable(tts_providers.init_tts_registry))

    def test_storyboard_and_animator_packages_expose_the_hub_registry(self):
        from scriptase.modules.video import providers as animator_providers
        from scriptase.modules.image import providers as storyboard_providers

        self.assertIs(storyboard_providers.registry, hub.registry('image'))
        self.assertIs(animator_providers.registry, hub.registry('video'))
        self.assertTrue(callable(storyboard_providers.init_storyboard_registry))
        self.assertTrue(callable(animator_providers.init_animator_registry))

    def test_binding_unpacks_in_the_historical_order(self):
        binding = bind_domain('tts', discover_now=False)
        registry, discover, get_provider, list_providers, init_registry = binding
        self.assertIs(registry, hub.registry('tts'))
        self.assertIs(discover(), hub.registry('tts'))
        self.assertIs(get_provider('kokoro'), hub.get('tts', 'kokoro'))
        self.assertEqual(len(list_providers()), len(hub.list('tts')))
        self.assertIs(init_registry(), hub.registry('tts'))


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='sts_providers_')
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.registry = ProviderRegistry(domain='tts')

    def test_discovery_order_is_sorted_not_filesystem_order(self):
        for provider_id in ('zulu', 'alpha', 'mike'):
            _write_provider(self.base, provider_id)
        self.registry.discovery_scan(self.base)
        self.assertEqual(self.registry.list_ids(), ['alpha', 'mike', 'zulu'])

    def test_discovery_is_idempotent(self):
        _write_provider(self.base, 'alpha')
        self.registry.discovery_scan(self.base)
        self.registry.discovery_scan(self.base)
        self.assertEqual(self.registry.list_ids(), ['alpha'])

    def test_missing_provider_base_is_not_an_error(self):
        self.registry.discovery_scan(os.path.join(self.base, 'does_not_exist'))
        self.assertEqual(self.registry.list_ids(), [])
        self.assertTrue(self.registry._discovered)

    def test_underscore_folders_are_skipped(self):
        _write_provider(self.base, '_scratch')
        _write_provider(self.base, 'alpha')
        self.registry.discovery_scan(self.base)
        self.assertEqual(self.registry.list_ids(), ['alpha'])


class BrokenProviderIsolationTests(unittest.TestCase):
    """One bad provider folder may not hide healthy providers or stop startup."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='sts_broken_')
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.registry = ProviderRegistry(domain='tts')

    def test_broken_providers_are_excluded_individually(self):
        _write_provider(self.base, 'aaa_syntax', body='def manifest(:\n')
        _write_provider(self.base, 'bbb_missing', body='X = 1\n')
        _write_provider(self.base, 'ccc_raises', body='def manifest():\n    raise RuntimeError("boom")\n')
        _write_provider(self.base, 'ddd_wrong_type', body='def manifest():\n    return 42\n')
        _write_provider(
            self.base,
            'eee_id_mismatch',
            body=MANIFEST_TEMPLATE.format(id='other', label='Other', domain='tts'),
        )
        _write_provider(self.base, 'fff_wrong_domain', domain='video')
        _write_provider(self.base, 'zzz_healthy')

        self.registry.discovery_scan(self.base)

        self.assertEqual(self.registry.list_ids(), ['zzz_healthy'])

    def test_only_broken_providers_still_completes_discovery(self):
        _write_provider(self.base, 'broken', body='raise ImportError("nope")\n')
        self.registry.discovery_scan(self.base)
        self.assertEqual(self.registry.list_ids(), [])
        self.assertTrue(self.registry._discovered)

    def test_duplicate_id_keeps_the_incumbent(self):
        manifest = ProviderManifest(
            id='alpha', label='First', domain='tts', kind='local', version='1.0.0',
            capabilities={},
        )
        later = ProviderManifest(
            id='alpha', label='Second', domain='tts', kind='local', version='2.0.0',
            capabilities={},
        )
        self.registry.register('alpha', module=None, manifest=manifest)
        self.registry.register('alpha', module=None, manifest=later)

        self.assertEqual(self.registry.list_ids(), ['alpha'])
        self.assertEqual(self.registry.get('alpha').label, 'First')

    def test_wrong_domain_registration_is_refused(self):
        manifest = ProviderManifest(
            id='alpha', label='Alpha', domain='video', kind='local', version='1.0.0',
            capabilities={},
        )
        self.registry.register('alpha', module=None, manifest=manifest)
        self.assertEqual(self.registry.list_ids(), [])


class ProviderRoutesUseTheHubTests(unittest.TestCase):
    """`/api/providers*` no longer builds a literal {tts, storyboard, animator} dict."""

    def setUp(self):
        from flask import Flask

        from scriptase.providers import providers_bp

        app = Flask(__name__)
        app.register_blueprint(providers_bp)
        self.client = app.test_client()

        patcher = patch.object(
            settings_manager, 'load_settings', return_value=settings_manager._default_settings()
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_listing_covers_every_catalog_domain(self):
        resp = self.client.get('/api/providers')
        self.assertEqual(resp.status_code, 200)
        domains = resp.get_json()['domains']
        # Flask sorts JSON keys, so compare membership rather than order here.
        self.assertEqual(set(domains), set(DOMAINS))
        self.assertEqual(domains['tts']['selected'], 'kokoro')
        self.assertIn('kokoro', [p['id'] for p in domains['tts']['providers']])

    def test_unknown_domain_is_rejected(self):
        resp = self.client.get('/api/providers/music/anything/settings')
        self.assertEqual(resp.status_code, 400)

    def test_unknown_provider_is_not_found(self):
        resp = self.client.get('/api/providers/tts/no_such_provider/settings')
        self.assertEqual(resp.status_code, 404)

    def test_known_provider_returns_its_manifest(self):
        resp = self.client.get('/api/providers/tts/kokoro/settings')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['manifest']['id'], 'kokoro')


class NewDomainIsDataOnlyTests(unittest.TestCase):
    """Adding a domain must be one DomainSpec plus a provider folder (§19.1)."""

    def test_a_hub_over_a_custom_catalog_discovers_its_providers(self):
        base = tempfile.mkdtemp(prefix='sts_demo_domain_')
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        _write_provider(base, 'demo_provider', domain='demo')

        spec = DomainSpec(
            id='demo',
            label='Demo',
            package='scriptase.modules.demo.providers',
            providers_base=base,
            default_provider='demo_provider',
            capability_vocabulary=frozenset({'test_connection'}),
        )
        demo_hub = ProviderHub({'demo': spec})
        demo_hub.discover_all()

        self.assertEqual(demo_hub.domains(), ['demo'])
        self.assertIsNotNone(demo_hub.get('demo', 'demo_provider'))
        self.assertEqual(list(demo_hub.catalog()), ['demo'])

        registry = demo_hub.registry('demo')
        demo_hub.shutdown()
        self.assertIs(demo_hub.registry('demo'), registry)  # facades stay valid
        self.assertEqual(registry.list_ids(), [])
        self.assertEqual([p.id for p in demo_hub.list('demo')], ['demo_provider'])


if __name__ == '__main__':
    unittest.main()
