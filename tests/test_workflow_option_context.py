"""Step 12.2: the parameterized option-source contract (contracts.md §23).

Covers the request context allowlist and its normalization (§23.1), the response
envelope (§23.2), the three failure codes (§23.3), and the context-keyed cache
with its three invalidation policies (§23.4).

The per-provider tests run against a *synthetic* `demo` domain in a temp
directory: proving "this source answers differently for two providers" must not
depend on which real providers happen to ship, and a fixture provider is exactly
the zero-touch case §26 promises.
"""

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
from scriptase.engine.options import (
    OptionContext,
    OptionContextError,
    allowed_option_values,
    build_context,
    config_option_context,
    resolve_options,
)
from scriptase.engine.registry import ASYNC_OPTION_SOURCES, OptionSourceSpec

from test_provider_lifecycle import demo_spec, write_provider


# `providers_common.__init__` re-exports the `hub` *singleton*, which shadows the
# submodule of the same name for both `from ... import` and `import ... as`.
hub_module = importlib.import_module('scriptase.providers.hub')


def voice_schema(*voices):
    return (
        "def settings_schema():\n"
        "    return {\n"
        "        'type': 'object',\n"
        "        'properties': {\n"
        "            'voice': {\n"
        "                'type': 'string',\n"
        f"                'ui': {{'type': 'dropdown', 'options': {list(voices)!r}}},\n"
        "            },\n"
        "        },\n"
        "        'required': [],\n"
        "    }\n"
    )


FIXTURE_SPEC = OptionSourceSpec(
    context=('domain', 'provider'), cache='settings', domain='demo'
)


class OptionContextTestCase(unittest.TestCase):
    """A synthetic `demo` domain with two providers offering different voices."""

    def setUp(self):
        workflow_options.clear_option_cache()
        self.addCleanup(workflow_options.clear_option_cache)

        self.base = tempfile.mkdtemp(prefix='sts_12_2_')
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        write_provider(
            self.base, 'alpha', domain='demo', aliases=['legacy_alpha'],
            schema_body=voice_schema('alpha_one', 'alpha_two'),
        )
        write_provider(
            self.base, 'beta', domain='demo',
            schema_body=voice_schema('beta_one'),
        )

        self.spec = demo_spec(self.base)
        self.hub = ProviderHub({'demo': self.spec})
        self.hub.discover_all()

        self.settings = {
            'version': settings_manager.SETTINGS_VERSION,
            'general': {},
            'domains': {
                'demo': {
                    'selected_instance_id': 'alpha',
                    'instances': {
                        'alpha': {
                            'type': 'alpha',
                            'label': 'alpha',
                            'settings': {},
                        }
                    },
                }
            },
        }

        catalog = {'demo': self.spec}
        self._patch(patch.object(hub_module, 'hub', self.hub))
        self._patch(patch.object(domains_module, 'DOMAINS', catalog))
        # Both provider modules bound `hub` and `DOMAINS` at import time.
        for module in (routes_module, catalog_module):
            self._patch(patch.object(module, 'hub', self.hub))
            if hasattr(module, 'DOMAINS'):
                self._patch(patch.object(module, 'DOMAINS', catalog))
        self._patch(patch.object(
            settings_manager, 'load_settings',
            side_effect=lambda: json.loads(json.dumps(self.settings)),
        ))
        self._patch(patch.object(
            settings_manager, 'save_settings', side_effect=self._save
        ))

        self.resolver_calls = []
        self._patch(patch.dict(ASYNC_OPTION_SOURCES, {'fixture_voices': FIXTURE_SPEC}))
        self._patch(patch.dict(
            workflow_options._RESOLVERS, {'fixture_voices': self._fixture_resolver}
        ))

        app = Flask(__name__)
        app.register_blueprint(workflows_bp)
        app.register_blueprint(providers_bp)
        self.client = app.test_client()

    def _fixture_resolver(self, ctx):
        """A context-sensitive resolver, written the way a new one would be.

        Reads the provider's own declared voices rather than calling a private
        helper of `options.py`, so this fixture keeps testing the *envelope* —
        validation, caching, invalidation — however the shipped resolvers are
        rewritten.
        """
        self.resolver_calls.append(dict(ctx.values))
        provider = self.hub.get(ctx.domain, ctx.provider) if ctx.provider else None
        if provider is None:
            return []
        voice = (provider.settings_schema() or {}).get('properties', {}).get('voice') or {}
        return [
            {'value': option, 'label': option}
            for option in (voice.get('ui') or {}).get('options') or []
        ]

    def _save(self, data):
        self.settings = json.loads(json.dumps(data))

    def _patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def fetch(self, source, query=''):
        return self.client.get(f'/api/workflow/options/{source}{query}')


# ---------------------------------------------------------------------------
# §23.1 — context is an allowlist, and it is normalized
# ---------------------------------------------------------------------------

class ContextValidationTests(OptionContextTestCase):
    def test_an_undeclared_parameter_is_rejected_not_ignored(self):
        # Silently ignoring `providr=beta` resolves options for the *selected*
        # provider and looks like it worked.
        resp = self.fetch('fixture_voices', '?providr=beta')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()['error']['code'], 'OPTION_CONTEXT_INVALID')

    def test_a_declared_parameter_is_rejected_on_a_source_that_does_not_take_it(self):
        resp = self.fetch('export_profiles', '?provider=alpha')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()['error']['code'], 'OPTION_CONTEXT_INVALID')

    def test_an_unknown_domain_is_rejected(self):
        with self.assertRaises(OptionContextError):
            build_context('fixture_voices', {'domain': 'not_a_domain'})

    def test_a_domain_outside_the_source_scope_is_rejected(self):
        # `tts_voices?domain=image` is a nonsense pairing the client could
        # otherwise cache and save.
        with self.assertRaises(OptionContextError):
            build_context('tts_voices', {'domain': 'scene_director'})

    def test_an_unregistered_provider_is_rejected(self):
        resp = self.fetch('fixture_voices', '?provider=ghost')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()['error']['code'], 'OPTION_CONTEXT_INVALID')

    def test_an_alias_normalizes_to_the_canonical_id(self):
        ctx = build_context('fixture_voices', {'provider': 'legacy_alpha'})
        self.assertEqual(ctx.values, {'domain': 'demo', 'provider': 'alpha'})

    def test_an_omitted_provider_falls_back_to_the_selection(self):
        self.assertEqual(build_context('fixture_voices', {}).provider, 'alpha')
        self.settings['domains']['demo']['selected_instance_id'] = 'beta'
        self.assertEqual(build_context('fixture_voices', {}).provider, 'beta')

    def test_an_unresolvable_selection_falls_back_to_the_domain_default(self):
        self.settings['domains']['demo']['selected_instance_id'] = 'uninstalled'
        self.assertEqual(build_context('fixture_voices', {}).provider, 'alpha')

    def test_a_node_type_context_must_name_a_registry_node(self):
        spec = OptionSourceSpec(context=('node_type',))
        with patch.dict(ASYNC_OPTION_SOURCES, {'fixture_voices': spec}):
            self.assertEqual(
                build_context('fixture_voices', {'node_type': 'tts.generate'}).values,
                {'node_type': 'tts.generate'},
            )
            with self.assertRaises(OptionContextError):
                build_context('fixture_voices', {'node_type': 'evil.node'})

    def test_a_project_id_context_must_survive_sanitization(self):
        spec = OptionSourceSpec(context=('project_id',))
        with patch.dict(ASYNC_OPTION_SOURCES, {'fixture_voices': spec}):
            with self.assertRaises(OptionContextError):
                build_context('fixture_voices', {'project_id': '../../etc/passwd'})


# ---------------------------------------------------------------------------
# §23.2 — the response envelope
# ---------------------------------------------------------------------------

class ResponseEnvelopeTests(OptionContextTestCase):
    def test_the_response_echoes_the_normalized_context(self):
        resp = self.fetch('fixture_voices', '?provider=legacy_alpha')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['source'], 'fixture_voices')
        # The client caches on the server's interpretation, not its query string.
        self.assertEqual(body['context'], {'domain': 'demo', 'provider': 'alpha'})
        self.assertTrue(body['generated_at'])

    def test_a_context_free_source_still_answers_the_old_shape(self):
        body = self.fetch('export_profiles').get_json()
        self.assertEqual(body['context'], {})
        self.assertEqual(
            [opt['value'] for opt in body['options']],
            ['yt_shorts', 'tiktok', 'reels', 'yt_landscape', 'square'],
        )
        for option in body['options']:
            self.assertIn('label', option)


# ---------------------------------------------------------------------------
# The point of the whole step: one source, two providers, two answers
# ---------------------------------------------------------------------------

class PerProviderResolutionTests(OptionContextTestCase):
    def values(self, query=''):
        return [opt['value'] for opt in self.fetch('fixture_voices', query).get_json()['options']]

    def test_one_source_resolves_differently_for_two_providers(self):
        self.assertEqual(self.values('?provider=alpha'), ['alpha_one', 'alpha_two'])
        self.assertEqual(self.values('?provider=beta'), ['beta_one'])

    def test_a_context_free_request_follows_the_selection(self):
        self.assertEqual(self.values(), ['alpha_one', 'alpha_two'])
        self.settings['domains']['demo']['selected_instance_id'] = 'beta'
        workflow_options.invalidate_settings_cache('demo')
        self.assertEqual(self.values(), ['beta_one'])

    def test_every_domain_has_a_providers_source(self):
        # P32 is gone: one resolver serves all five, so a sixth domain is a
        # spec entry and nothing else.
        for domain in ('script', 'scene_director', 'tts', 'image', 'video'):
            with self.subTest(domain=domain):
                spec = ASYNC_OPTION_SOURCES[f'{domain}_providers']
                self.assertEqual(spec.domain, domain)
                self.assertIs(
                    workflow_options._RESOLVERS[f'{domain}_providers'],
                    workflow_options._provider_options,
                )


# ---------------------------------------------------------------------------
# §23.3 — failure semantics
# ---------------------------------------------------------------------------

class FailureSemanticsTests(OptionContextTestCase):
    def test_an_unknown_source_is_a_404(self):
        resp = self.fetch('evil_source')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()['error']['code'], 'NOT_FOUND')

    def test_a_failing_resolver_is_a_503_without_its_exception_text(self):
        def boom(_ctx):
            raise RuntimeError('api key sk-secret-value rejected')

        with patch.dict(workflow_options._RESOLVERS, {'fixture_voices': boom}):
            resp = self.fetch('fixture_voices')
        self.assertEqual(resp.status_code, 503)
        body = resp.get_json()['error']
        self.assertEqual(body['code'], 'PROVIDER_UNAVAILABLE')
        self.assertNotIn('sk-secret-value', json.dumps(body))

    def test_a_failing_resolver_is_never_cached(self):
        calls = []

        def boom(_ctx):
            calls.append(1)
            raise RuntimeError('offline')

        with patch.dict(workflow_options._RESOLVERS, {'fixture_voices': boom}):
            self.fetch('fixture_voices')
            self.fetch('fixture_voices')
        self.assertEqual(len(calls), 2)

    def test_non_loopback_is_403(self):
        resp = self.client.get(
            '/api/workflow/options/export_profiles',
            environ_overrides={'REMOTE_ADDR': '10.2.2.2'},
        )
        self.assertEqual(resp.status_code, 403)

    def test_save_time_validation_fails_open_on_a_bad_context(self):
        self.assertIsNone(allowed_option_values('fixture_voices', {'provider': 'ghost'}))


# ---------------------------------------------------------------------------
# §23.4 — the cache is keyed by source *and* context
# ---------------------------------------------------------------------------

class CacheTests(OptionContextTestCase):
    def test_each_context_is_cached_separately(self):
        self.fetch('fixture_voices', '?provider=alpha')
        self.fetch('fixture_voices', '?provider=alpha')
        self.fetch('fixture_voices', '?provider=beta')
        self.assertEqual(
            self.resolver_calls,
            [
                {'domain': 'demo', 'provider': 'alpha'},
                {'domain': 'demo', 'provider': 'beta'},
            ],
        )

    def test_a_settings_write_invalidates_that_domain_only(self):
        self.fetch('fixture_voices', '?provider=alpha')
        self.fetch('story_tones')
        workflow_options.invalidate_settings_cache('demo')
        self.fetch('fixture_voices', '?provider=alpha')
        self.assertEqual(len(self.resolver_calls), 2)

        # A different domain's write leaves this domain's entry alone.
        workflow_options.invalidate_settings_cache('tts')
        self.fetch('fixture_voices', '?provider=alpha')
        self.assertEqual(len(self.resolver_calls), 2)

    def test_a_selection_write_through_the_api_invalidates_the_cache(self):
        self.assertEqual(
            [o['value'] for o in self.fetch('fixture_voices').get_json()['options']],
            ['alpha_one', 'alpha_two'],
        )
        resp = self.client.put(
            '/api/providers/demo/selection', json={'provider_id': 'beta'}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            [o['value'] for o in self.fetch('fixture_voices').get_json()['options']],
            ['beta_one'],
        )

    def test_a_provider_settings_write_through_the_api_invalidates_the_cache(self):
        self.fetch('fixture_voices', '?provider=alpha')
        resp = self.client.put(
            '/api/providers/demo/alpha/settings', json={'voice': 'alpha_two'}
        )
        self.assertEqual(resp.status_code, 200)
        self.fetch('fixture_voices', '?provider=alpha')
        self.assertEqual(len(self.resolver_calls), 2)

    def test_discovery_invalidation_only_touches_discovery_sources(self):
        self.fetch('fixture_voices', '?provider=alpha')
        workflow_options.invalidate_discovery_cache()
        self.fetch('fixture_voices', '?provider=alpha')
        self.assertEqual(len(self.resolver_calls), 1)

    def test_the_cache_is_bounded_per_source(self):
        cache = workflow_options._OptionCache()
        limit = workflow_options.MAX_CACHE_ENTRIES_PER_SOURCE
        for index in range(limit + 5):
            ctx = OptionContext('fixture_voices', FIXTURE_SPEC, {'provider': f'p{index}'})
            cache.put(ctx, [])
        self.assertEqual(cache.size(), limit)
        # The oldest are the ones dropped.
        oldest = OptionContext('fixture_voices', FIXTURE_SPEC, {'provider': 'p0'})
        newest = OptionContext(
            'fixture_voices', FIXTURE_SPEC, {'provider': f'p{limit + 4}'}
        )
        self.assertIsNone(cache.get(oldest))
        self.assertIsNotNone(cache.get(newest))

    def test_a_settings_entry_expires_on_its_ttl(self):
        clock = [1000.0]
        with patch.object(workflow_options.time, 'monotonic', lambda: clock[0]):
            self.fetch('fixture_voices', '?provider=alpha')
            clock[0] += workflow_options.SETTINGS_CACHE_TTL_SECONDS + 1
            self.fetch('fixture_voices', '?provider=alpha')
        self.assertEqual(len(self.resolver_calls), 2)


# ---------------------------------------------------------------------------
# §23.3/§24.1 — save-time validation follows the node, not the global selection
# ---------------------------------------------------------------------------

class SaveTimeContextTests(OptionContextTestCase):
    FIELDS = {'engine': {'name': 'engine', 'default': 'alpha'}}

    def test_the_node_provider_field_wins_over_the_selection(self):
        self.assertEqual(
            config_option_context('fixture_voices', {'engine': 'beta'}, self.FIELDS),
            {'provider': 'beta'},
        )

    def test_an_unwritten_provider_field_uses_its_schema_default(self):
        # Rule 2 of §24.1: switching the global selection must not change how an
        # existing saved workflow validates or runs.
        self.assertEqual(
            config_option_context('fixture_voices', {}, self.FIELDS),
            {'provider': 'alpha'},
        )

    def test_provider_id_is_preferred_over_the_legacy_names(self):
        self.assertEqual(
            config_option_context(
                'fixture_voices',
                {'provider_id': 'beta', 'provider': 'alpha', 'engine': 'alpha'},
                {},
            ),
            {'provider': 'beta'},
        )

    def test_a_node_with_no_provider_field_defers_to_the_selection(self):
        self.assertIsNone(config_option_context('fixture_voices', {}, {}))

    def test_a_context_free_source_never_gets_a_context(self):
        self.assertIsNone(
            config_option_context('story_tones', {'provider_id': 'beta'}, {})
        )

    def test_one_providers_voice_is_not_valid_for_another(self):
        allowed = allowed_option_values(
            'fixture_voices', config_option_context('fixture_voices', {'engine': 'beta'}, {})
        )
        self.assertEqual(allowed, frozenset({'beta_one'}))


# ---------------------------------------------------------------------------
# The parity guards from step 2.3 stay intact
# ---------------------------------------------------------------------------

class ShippedSourceTests(unittest.TestCase):
    """The real catalog, not a fixture: `tts_voices` is already per-provider."""

    def setUp(self):
        workflow_options.clear_option_cache()
        self.addCleanup(workflow_options.clear_option_cache)

    def test_the_shipped_tts_source_resolves_per_provider(self):
        inworld = allowed_option_values('tts_voices', {'provider': 'inworld'})
        self.assertTrue(inworld)
        self.assertIsNone(allowed_option_values('tts_voices', {'provider': 'kokoro'}))

    def test_a_provider_without_any_voices_has_no_retired_local_fallback(self):
        from scriptase.modules.tts import dispatch

        with patch.object(dispatch, 'list_voices', return_value=[]):
            options, _ = resolve_options('tts_voices', {'provider': 'inworld'})
        self.assertEqual(options, [])


class ParityTests(unittest.TestCase):
    def test_resolver_table_matches_allowlist(self):
        self.assertEqual(set(workflow_options._RESOLVERS), set(ASYNC_OPTION_SOURCES))

    def test_every_spec_declares_a_known_cache_policy(self):
        from scriptase.engine.registry import CACHE_POLICIES

        for source, spec in ASYNC_OPTION_SOURCES.items():
            with self.subTest(source=source):
                self.assertIn(spec.cache, CACHE_POLICIES)

    def test_every_provider_source_is_scoped_to_a_real_domain(self):
        from scriptase.providers.domains import DOMAINS

        for source, spec in ASYNC_OPTION_SOURCES.items():
            if spec.domain is None:
                continue
            with self.subTest(source=source):
                self.assertIn(spec.domain, DOMAINS)

    def test_resolve_options_is_still_callable_with_one_argument(self):
        options, context = resolve_options('story_tones')
        self.assertEqual(context, {})
        self.assertGreater(len(options), 1)


if __name__ == '__main__':
    unittest.main()
