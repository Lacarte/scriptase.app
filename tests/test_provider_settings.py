"""Step 11.3: manifest v2 metadata and settings validation.

Covers contracts.md §20.1 (the `description`/`docs_url`/`environment` fields and
their validation), §21.5 (availability vs health, and the `unknown` default),
§22.1-§22.6 (schema-driven validation, widget vocabulary, conditional fields,
issue severities, secrets and environment fallback), §24.3 (migration of the three
legacy selection keys), and §25 (frontend-safe serialization).
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scriptase.providers import settings_manager
from scriptase.providers import settings_schema as ss
from scriptase.providers import validation as v
from scriptase.providers.domains import DOMAINS
from scriptase.providers.hub import hub
from scriptase.providers.registry import (
    AVAILABLE,
    DEGRADED,
    NEEDS_CONFIGURATION,
    ProviderInstance,
    ProviderManifest,
)
from scriptase.providers.settings_migrations import (
    MIGRATIONS,
    SETTINGS_VERSION,
    apply_migrations,
)


def make_manifest(**overrides) -> ProviderManifest:
    fields = {
        'id': 'alpha',
        'label': 'Alpha',
        'domain': 'tts',
        'kind': 'cloud',
        'version': '1.0.0',
        'capabilities': {'batch': True},
    }
    fields.update(overrides)
    return ProviderManifest(**fields)


def make_instance(manifest=None, *, schema=None, factory=True, schema_raises=False,
                  validate=None, health=None) -> ProviderInstance:
    """Build a `ProviderInstance` over a synthetic provider module."""
    namespace = {}
    if factory:
        namespace['create'] = staticmethod(lambda: object())
    if schema is not None or schema_raises:
        def settings_schema():
            if schema_raises:
                raise RuntimeError('schema exploded')
            return schema
        namespace['settings_schema'] = staticmethod(settings_schema)
    if validate is not None:
        namespace['validate_settings'] = staticmethod(validate)
    if health is not None:
        namespace['health_check'] = staticmethod(health)

    module = type('ProviderModule', (), namespace)
    instance = ProviderInstance('alpha', module, manifest or make_manifest())
    if schema is not None or schema_raises:
        instance.schema_module = module
    return instance


# -- §20.1 manifest v2 fields ------------------------------------------------


class ManifestV2FieldTests(unittest.TestCase):
    def _validate(self, payload, folder_id='alpha', domain='tts'):
        return v.validate_manifest(
            folder_id=folder_id,
            domain=domain,
            payload=payload,
            manifest_cls=ProviderManifest,
        )

    def _payload(self, **overrides):
        data = {
            'id': 'alpha',
            'label': 'Alpha',
            'domain': 'tts',
            'kind': 'cloud',
            'version': '1.0.0',
            'capabilities': {},
        }
        data.update(overrides)
        return data

    def test_full_v2_manifest_is_accepted(self):
        result = self._validate(self._payload(
            description='A one sentence summary.',
            docs_url='https://example.com/docs',
            environment={'api_key': 'ALPHA_API_KEY'},
            contract_version=2,
        ))
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.manifest.description, 'A one sentence summary.')
        self.assertEqual(result.manifest.docs_url, 'https://example.com/docs')
        self.assertEqual(result.manifest.environment, {'api_key': 'ALPHA_API_KEY'})

    def test_defaults_are_empty_not_missing(self):
        result = self._validate(self._payload())
        self.assertTrue(result.ok, result.message)
        self.assertIsNone(result.manifest.description)
        self.assertIsNone(result.manifest.docs_url)
        self.assertEqual(result.manifest.environment, {})

    def test_a_dangerous_docs_url_never_reaches_the_browser(self):
        for url in ('javascript:alert(1)', 'data:text/html,<script>', 'http://evil.test/x'):
            with self.subTest(url=url):
                result = self._validate(self._payload(docs_url=url))
                self.assertEqual(result.reason_code, v.MANIFEST_FIELDS_INVALID)

    def test_a_loopback_docs_url_is_allowed_for_development(self):
        result = self._validate(self._payload(docs_url='http://localhost:5050/docs'))
        self.assertTrue(result.ok, result.message)

    def test_description_length_and_control_characters_are_rejected(self):
        too_long = self._validate(self._payload(description='x' * (v.DESCRIPTION_MAX + 1)))
        self.assertEqual(too_long.reason_code, v.MANIFEST_FIELDS_INVALID)

        control = self._validate(self._payload(description='line\x00break'))
        self.assertEqual(control.reason_code, v.MANIFEST_FIELDS_INVALID)

        self.assertTrue(self._validate(self._payload(description='x' * v.DESCRIPTION_MAX)).ok)

    def test_environment_names_must_look_like_environment_variables(self):
        for environment in (
            {'api_key': 'lowercase'},
            {'api_key': '1LEADING_DIGIT'},
            {'api_key': 'HAS-HYPHEN'},
            {'api_key': 42},
            {'': 'ALPHA_API_KEY'},
        ):
            with self.subTest(environment=environment):
                result = self._validate(self._payload(environment=environment))
                self.assertEqual(result.reason_code, v.MANIFEST_FIELDS_INVALID)

        not_a_mapping = self._validate(self._payload(environment=['ALPHA_API_KEY']))
        self.assertEqual(not_a_mapping.reason_code, v.MANIFEST_FIELDS_INVALID)


class PublicManifestRoundTripTests(unittest.TestCase):
    """Every manifest round-trips through its public representation (§25)."""

    def _round_trip(self, manifest):
        public = manifest.public_dict()
        # JSON-serializable: no callables, no modules, no sets.
        json.dumps(public)
        result = v.validate_manifest(
            folder_id=manifest.id,
            domain=manifest.domain,
            payload=dict(public),
            manifest_cls=ProviderManifest,
        )
        self.assertTrue(result.ok, result.message)
        return public, result.manifest.public_dict()

    def test_a_v2_manifest_round_trips_unchanged(self):
        manifest = make_manifest(
            description='Summary.',
            docs_url='https://example.com',
            aliases=['legacy-id'],
            requires=['api_key'],
            environment={'api_key': 'ALPHA_API_KEY'},
            contract_version=2,
        )
        public, again = self._round_trip(manifest)
        self.assertEqual(public, again)

    def test_the_public_representation_never_carries_environment_names(self):
        manifest = make_manifest(environment={'api_key': 'ALPHA_API_KEY'})
        public = manifest.public_dict()
        self.assertNotIn('environment', public)
        self.assertNotIn('ALPHA_API_KEY', json.dumps(public))

    def test_every_shipped_manifest_round_trips(self):
        for domain in hub.domains():
            for provider in hub.list(domain):
                with self.subTest(provider=f'{domain}/{provider.id}'):
                    public, again = self._round_trip(provider.manifest)
                    self.assertEqual(public, again)
                    blob = json.dumps(public)
                    self.assertNotIn('_sts_provider_', blob)
                    self.assertNotIn(os.sep + 'studio' + os.sep, blob)


# -- §22.5 schema-driven settings validation ---------------------------------


SCHEMA = {
    'type': 'object',
    'properties': {
        'api_key': {'type': 'string', 'label': 'API Key', 'ui': {'type': 'password'}},
        'model': {'type': 'string', 'label': 'Model', 'enum': ['fast', 'hd']},
        'speed': {'type': 'number', 'label': 'Speed', 'minimum': 0.5, 'maximum': 2.0},
        'blend': {'type': 'boolean', 'label': 'Blend', 'ui': {'type': 'toggle'}},
        'blend_ratio': {
            'type': 'integer',
            'label': 'Blend Ratio',
            'ui': {'type': 'slider', 'show_if': {'blend': [True]}},
        },
    },
    'required': ['api_key', 'blend_ratio'],
}


def issues_for(values, schema=SCHEMA):
    return ss.validate_against_schema(schema, values)


class SchemaValidationTests(unittest.TestCase):
    def test_a_provider_without_a_schema_validates_nothing(self):
        self.assertEqual(ss.validate_against_schema(None, {'anything': 1}), [])
        self.assertEqual(ss.validate_against_schema({'type': 'object'}, {'x': 1}), [])

    def test_required_but_empty_is_an_error(self):
        issues = issues_for({'api_key': '   ', 'blend': True, 'blend_ratio': 50})
        self.assertEqual(
            [(i['field'], i['severity']) for i in issues], [('api_key', 'error')]
        )

    def test_zero_and_false_are_not_empty(self):
        issues = issues_for({'api_key': 'k', 'blend': True, 'blend_ratio': 0})
        self.assertEqual(issues, [])

    def test_unknown_saved_keys_are_warned_and_preserved(self):
        values = {'api_key': 'k', 'retired_option': 'keep me'}
        issues = issues_for(values)
        self.assertEqual(
            [(i['field'], i['severity']) for i in issues],
            [('retired_option', 'warning')],
        )
        # Preserved, not dropped: the value survives an invocation-config pass.
        self.assertEqual(ss.invocation_config(SCHEMA, values)['retired_option'], 'keep me')

    def test_a_hidden_field_is_exempt_from_required_and_never_invoked(self):
        values = {'api_key': 'k', 'blend': False, 'blend_ratio': 50}
        self.assertEqual(issues_for(values), [])
        self.assertNotIn('blend_ratio', ss.invocation_config(SCHEMA, values))
        # ...but its stored value is preserved.
        self.assertEqual(values['blend_ratio'], 50)

    def test_a_visible_conditional_field_is_required_again(self):
        issues = issues_for({'api_key': 'k', 'blend': True})
        self.assertEqual(
            [(i['field'], i['severity']) for i in issues], [('blend_ratio', 'error')]
        )

    def test_show_if_is_and_across_keys_or_within_a_list(self):
        schema = {'properties': {'x': {'ui': {'show_if': {'a': ['1', '2'], 'b': [True]}}}}}
        prop = schema['properties']['x']
        self.assertTrue(ss.is_visible(prop, {'a': '2', 'b': True}))
        self.assertFalse(ss.is_visible(prop, {'a': '3', 'b': True}))
        self.assertFalse(ss.is_visible(prop, {'a': '1', 'b': False}))

    def test_type_enum_and_range_violations_are_errors(self):
        base = {'api_key': 'k', 'blend': True, 'blend_ratio': 50}
        cases = {
            'model': {**base, 'model': 'ultra'},
            'speed': {**base, 'speed': 9.0},
            'blend': {**base, 'blend': 'yes'},
        }
        for field_name, values in cases.items():
            with self.subTest(field=field_name):
                issues = issues_for(values)
                self.assertEqual(
                    [(i['field'], i['severity']) for i in issues],
                    [(field_name, 'error')],
                )

    def test_a_boolean_is_not_accepted_as_a_number(self):
        issues = issues_for({'api_key': 'k', 'blend': True, 'blend_ratio': 50, 'speed': True})
        self.assertEqual([(i['field'], i['severity']) for i in issues], [('speed', 'error')])

    def test_an_unrecognized_widget_is_a_warning_not_an_error(self):
        schema = {'properties': {'x': {'type': 'string', 'ui': {'type': 'hologram'}}}}
        issues = ss.validate_against_schema(schema, {'x': 'v'})
        self.assertEqual([(i['field'], i['severity']) for i in issues], [('x', 'warning')])

    def test_textarea_is_part_of_the_frozen_widget_vocabulary(self):
        self.assertIn('textarea', ss.WIDGET_TYPES)
        schema = {'properties': {'x': {'type': 'string', 'ui': {'type': 'textarea'}}}}
        self.assertEqual(ss.validate_against_schema(schema, {'x': 'v'}), [])

    def test_options_and_options_source_together_warn(self):
        schema = {'properties': {'x': {
            'type': 'string',
            'ui': {'type': 'dropdown', 'options': ['a'], 'options_source': {'source': 'tts_voices'}},
        }}}
        issues = ss.validate_against_schema(schema, {'x': 'a'})
        self.assertEqual([(i['field'], i['severity']) for i in issues], [('x', 'warning')])
        self.assertIn('options_source wins', issues[0]['message'])

    def test_issues_are_stable_and_deterministic(self):
        values = {'api_key': '', 'model': 'ultra', 'zzz': 1, 'blend': True}
        first = issues_for(values)
        self.assertEqual(first, issues_for(dict(reversed(list(values.items())))))
        self.assertEqual(
            [i['field'] for i in first], ['api_key', 'blend_ratio', 'model', 'zzz']
        )
        for issue in first:
            self.assertEqual(set(issue), {'field', 'severity', 'message'})


class ProviderValidationTests(unittest.TestCase):
    """`ProviderInstance.validate_settings` = schema issues + the provider hook."""

    def test_schema_and_hook_issues_are_combined(self):
        instance = make_instance(
            schema=SCHEMA,
            validate=lambda s: [{'field': 'model', 'severity': 'warning', 'message': 'slow'}],
        )
        issues = instance.validate_settings({'api_key': 'k', 'blend': True})
        self.assertEqual(
            {(i.field, i.severity) for i in issues},
            {('blend_ratio', 'error'), ('model', 'warning')},
        )

    def test_a_duplicate_hook_issue_is_not_reported_twice(self):
        duplicate = {'field': 'api_key', 'severity': 'error', 'message': 'API Key is required'}
        instance = make_instance(schema=SCHEMA, validate=lambda s: [duplicate])
        issues = instance.validate_settings({'blend': False})
        self.assertEqual(
            [(i.field, i.message) for i in issues],
            [('api_key', 'API Key is required')],
        )

    def test_a_raising_hook_never_echoes_the_submitted_secret(self):
        def explode(settings):
            raise RuntimeError(f"bad credentials: {settings['api_key']}")

        instance = make_instance(schema=SCHEMA, validate=explode)
        issues = instance.validate_settings(
            {'api_key': 'sk-live-topsecret', 'blend': True, 'blend_ratio': 1}
        )
        self.assertEqual(
            [(i.field, i.severity, i.message) for i in issues],
            [('root', 'error', 'Settings validation failed')],
        )
        self.assertNotIn('sk-live-topsecret', repr(issues))


# -- §21.5 availability and health -------------------------------------------


class AvailabilityTests(unittest.TestCase):
    def test_a_configured_provider_is_available(self):
        instance = make_instance(make_manifest(requires=['api_key']))
        self.assertEqual(instance.availability({'api_key': 'k'}), AVAILABLE)

    def test_an_empty_required_key_is_needs_configuration_not_missing(self):
        instance = make_instance(make_manifest(requires=['api_key']))
        # The live settings file stores present-but-empty api_key values (§14.3),
        # so presence must not be mistaken for configuration.
        self.assertEqual(instance.availability({'api_key': ''}), NEEDS_CONFIGURATION)
        self.assertEqual(instance.availability({}), NEEDS_CONFIGURATION)

    def test_no_factory_or_a_broken_schema_is_degraded(self):
        self.assertEqual(make_instance(factory=False).availability({}), DEGRADED)
        self.assertEqual(make_instance(schema_raises=True).availability({}), DEGRADED)

    def test_a_previously_raising_factory_is_degraded(self):
        instance = make_instance()
        instance.provider_module = type('M', (), {
            'create': staticmethod(lambda: (_ for _ in ()).throw(RuntimeError('boom')))
        })
        with self.assertRaises(Exception):
            instance.create()
        self.assertEqual(instance.availability({}), DEGRADED)

    def test_availability_is_serialized_for_the_browser(self):
        instance = make_instance(make_manifest(requires=['api_key']))
        self.assertEqual(instance.to_dict({'api_key': 'k'})['availability'], AVAILABLE)
        self.assertEqual(instance.to_dict({})['availability'], NEEDS_CONFIGURATION)


class HealthTests(unittest.TestCase):
    def test_a_provider_without_a_health_check_is_unknown_not_ok(self):
        # Frozen correction (§21.5): the old default claimed health nobody reported.
        self.assertEqual(make_instance().health_check({}).status, 'unknown')

    def test_a_raising_health_check_is_a_sanitized_failure(self):
        def explode(settings):
            raise RuntimeError('connect failed for api_key=sk-live-topsecret')

        result = make_instance(health=explode).health_check({})
        self.assertEqual(result.status, 'fail')
        self.assertNotIn('sk-live-topsecret', result.message)

    def test_health_never_blocks_availability(self):
        instance = make_instance(
            make_manifest(requires=[]), health=lambda s: {'status': 'fail'}
        )
        self.assertEqual(instance.health_check({}).status, 'fail')
        self.assertEqual(instance.availability({}), AVAILABLE)


# -- §22.6 secrets and the environment fallback ------------------------------


class EnvironmentFallbackTests(unittest.TestCase):
    def test_an_empty_setting_falls_back_to_the_environment(self):
        instance = make_instance(
            make_manifest(requires=['api_key'], environment={'api_key': 'ALPHA_API_KEY'})
        )
        with patch.dict(os.environ, {'ALPHA_API_KEY': 'from-env'}, clear=False):
            self.assertEqual(instance.resolve_settings({'api_key': ''})['api_key'], 'from-env')
            self.assertEqual(instance.availability({'api_key': ''}), AVAILABLE)

    def test_a_stored_value_always_wins_over_the_environment(self):
        instance = make_instance(make_manifest(environment={'api_key': 'ALPHA_API_KEY'}))
        with patch.dict(os.environ, {'ALPHA_API_KEY': 'from-env'}, clear=False):
            self.assertEqual(
                instance.resolve_settings({'api_key': 'stored'})['api_key'], 'stored'
            )

    def test_a_resolved_value_is_never_written_back_or_returned(self):
        instance = make_instance(
            make_manifest(requires=['api_key'], environment={'api_key': 'ALPHA_API_KEY'})
        )
        stored = {'api_key': ''}
        with patch.dict(os.environ, {'ALPHA_API_KEY': 'from-env'}, clear=False):
            instance.resolve_settings(stored)
            payload = instance.to_dict(stored)
        self.assertEqual(stored, {'api_key': ''})
        self.assertNotIn('from-env', json.dumps(payload))

    def test_the_environment_is_only_a_fallback_for_declared_keys(self):
        instance = make_instance(make_manifest(environment={}))
        with patch.dict(os.environ, {'ALPHA_API_KEY': 'from-env'}, clear=False):
            self.assertEqual(instance.resolve_settings({'api_key': ''}), {'api_key': ''})


class SecretTests(unittest.TestCase):
    def test_a_field_is_secret_by_widget_or_by_name(self):
        self.assertTrue(ss.is_secret_field('api_key', None))
        self.assertTrue(ss.is_secret_field('anything', {'ui': {'type': 'password'}}))
        self.assertTrue(ss.is_secret_field('bearer_token', None))
        self.assertFalse(ss.is_secret_field('voice', {'ui': {'type': 'dropdown'}}))

    def test_redaction_replaces_every_secret_with_the_sentinel(self):
        redacted = ss.redact({'api_key': 'sk-live', 'voice': 'Ashley'}, SCHEMA)
        self.assertEqual(redacted, {'api_key': ss.REDACTION_SENTINEL, 'voice': 'Ashley'})

    def test_redaction_recurses_into_nested_documents(self):
        document = {'domains': {'tts': {'per_provider': {'inworld': {'api_key': 'sk-live'}}}}}
        blob = json.dumps(settings_manager.redact_settings(document))
        self.assertNotIn('sk-live', blob)

    def test_a_sentinel_submission_leaves_the_stored_secret_alone(self):
        merged = ss.apply_settings_patch(
            {'api_key': 'sk-live', 'voice': 'Ashley'},
            {'api_key': ss.REDACTION_SENTINEL, 'voice': 'Carter'},
            SCHEMA,
        )
        self.assertEqual(merged, {'api_key': 'sk-live', 'voice': 'Carter'})

    def test_a_real_new_secret_still_replaces_the_stored_one(self):
        merged = ss.apply_settings_patch({'api_key': 'old'}, {'api_key': 'new'}, SCHEMA)
        self.assertEqual(merged['api_key'], 'new')

    def test_a_sentinel_in_a_non_secret_field_is_a_literal_value(self):
        merged = ss.apply_settings_patch({'voice': 'Ashley'}, {'voice': '***'}, SCHEMA)
        self.assertEqual(merged['voice'], '***')

    def test_durable_secrets_are_split_from_portable_options(self):
        secrets, options = ss.split_settings(SCHEMA, {'api_key': 'sk', 'model': 'hd'})
        self.assertEqual(secrets, {'api_key': 'sk'})
        self.assertEqual(options, {'model': 'hd'})

    def test_only_portable_options_reach_a_persisted_job_manifest(self):
        # `_kie_ai_options` is written to output/animator/<id>/grabber_job.json and
        # travels into project archives, so it may carry options but not the key.
        with patch.object(
            settings_manager, 'get_provider_settings',
            return_value={'api_key': 'sk-live', 'model': 'google/nano-banana'},
        ):
            portable = settings_manager.portable_provider_settings('video', 'kie_ai')
        self.assertEqual(portable, {'model': 'google/nano-banana'})

    def test_a_whole_document_write_restores_every_sentinel(self):
        stored = {'domains': {'tts': {'per_provider': {'inworld': {
            'api_key': 'sk-live', 'voice': 'Ashley'}}}}}
        incoming = json.loads(json.dumps(settings_manager.redact_settings(stored)))
        incoming['domains']['tts']['selected_provider'] = 'inworld'

        restored = settings_manager.restore_redacted_secrets(stored, incoming)
        provider = restored['domains']['tts']['per_provider']['inworld']
        self.assertEqual(provider['api_key'], 'sk-live')
        self.assertEqual(restored['domains']['tts']['selected_provider'], 'inworld')


# -- §22.6 / §14.3 first-run seeding -----------------------------------------


class SeedingTests(unittest.TestCase):
    def test_seeding_never_copies_a_secret_or_writes_a_selection(self):
        env = {
            'INWORLD_API_KEY': 'sk-live-topsecret',
            'WAVESPEED_API_KEY': 'ws-secret',
            'KIE_AI_API_KEY': 'kie-secret',
        }
        with patch.dict(os.environ, env, clear=False):
            seeded = settings_manager._seed_from_env()

        self.assertNotIn('sk-live-topsecret', json.dumps(seeded))
        self.assertNotIn('ws-secret', json.dumps(seeded))
        # The INWORLD_API_KEY selection side effect is frozen as removed (§22.6).
        self.assertEqual(
            seeded['domains']['tts']['selected_instance_id'],
            DOMAINS['tts'].default_provider,
        )


# -- §24.3 settings migrations -----------------------------------------------


V1_SETTINGS = {
    'version': 1,
    'general': {},
    'domains': {
        'tts': {'selected_provider': None, 'per_provider': {'inworld': {'api_key': 'sk'}}},
        'image': {'per_provider': {}},
    },
}


class MigrationSequencingTests(unittest.TestCase):
    def test_an_upgrade_migration_actually_runs(self):
        # The pre-11.3 loop skipped every version >= the stored one, so it could
        # never reach a newer target at all.
        self.assertIn(2, MIGRATIONS)
        migrated, changed = apply_migrations(json.loads(json.dumps(V1_SETTINGS)), {})
        self.assertTrue(changed)
        self.assertEqual(migrated['version'], SETTINGS_VERSION)

    def test_the_legacy_selection_is_adopted_and_normalized(self):
        legacy = {'sts-tts-provider': 'inworld', 'sts-storyboard-provider': 'gemini'}
        migrated, _ = apply_migrations(json.loads(json.dumps(V1_SETTINGS)), legacy)
        self.assertEqual(migrated['domains']['tts']['selected_instance_id'], 'inworld')
        self.assertEqual(
            migrated['domains']['image']['selected_instance_id'], 'gemini_ws'
        )

    def test_an_explicit_selection_always_beats_the_legacy_key(self):
        data = json.loads(json.dumps(V1_SETTINGS))
        data['domains']['tts']['selected_provider'] = 'kokoro'
        migrated, _ = apply_migrations(data, {'sts-tts-provider': 'inworld'})
        self.assertEqual(migrated['domains']['tts']['selected_instance_id'], 'kokoro')

    def test_migration_is_lossless(self):
        from scriptase.providers.secrets import is_secret_ref, resolve_secret_refs

        migrated, _ = apply_migrations(json.loads(json.dumps(V1_SETTINGS)), {})
        stored = migrated['domains']['tts']['instances']['inworld']['settings']
        # Step 3.4: credentials become secret refs; the value is still recoverable.
        self.assertTrue(is_secret_ref(stored['api_key']))
        self.assertEqual(resolve_secret_refs(stored), {'api_key': 'sk'})
        # Domains added to the catalog after the file was written are backfilled.
        self.assertEqual(set(migrated['domains']), set(DOMAINS))
        for domain_id, spec in DOMAINS.items():
            self.assertTrue(migrated['domains'][domain_id]['selected_instance_id'])
            self.assertIn('instances', migrated['domains'][domain_id])

    def test_an_already_current_document_is_idempotent(self):
        once, _ = apply_migrations(json.loads(json.dumps(V1_SETTINGS)), {})
        twice, changed = apply_migrations(json.loads(json.dumps(once)), {})
        self.assertFalse(changed)
        self.assertEqual(once, twice)

    def test_a_missing_or_odd_version_is_treated_as_v1(self):
        for version in (None, 'two', True):
            with self.subTest(version=version):
                data = {'domains': {}}
                if version is not None:
                    data['version'] = version
                _, changed = apply_migrations(data, {})
                self.assertTrue(changed)


class MigrationAtWriteBoundaryTests(unittest.TestCase):
    """The version stamp is the completion marker, written atomically (§24.3)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='sts_settings_')
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, 'settings.json')
        self._write(V1_SETTINGS)

        for attr, value in (('SETTINGS_DIR', self.dir), ('SETTINGS_PATH', self.path)):
            patcher = patch.object(settings_manager, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        legacy = patch.object(
            settings_manager, '_read_legacy_user_settings',
            return_value={'sts-tts-provider': 'inworld'},
        )
        legacy.start()
        self.addCleanup(legacy.stop)

    def _write(self, data):
        with open(self.path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)

    def _read(self):
        with open(self.path, 'r', encoding='utf-8') as handle:
            return json.load(handle)

    def test_a_successful_migration_is_persisted_once(self):
        loaded = settings_manager.load_settings()
        self.assertEqual(loaded['version'], SETTINGS_VERSION)
        self.assertEqual(self._read()['version'], SETTINGS_VERSION)
        self.assertEqual(
            self._read()['domains']['tts']['selected_instance_id'], 'inworld'
        )

        # A second load must not rewrite the file.
        with patch.object(settings_manager, 'save_settings') as saver:
            settings_manager.load_settings()
            saver.assert_not_called()

    def test_an_interrupted_write_leaves_the_previous_version_on_disk(self):
        with patch('os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                settings_manager.load_settings()

        on_disk = self._read()
        self.assertEqual(on_disk['version'], 1)
        self.assertIsNone(on_disk['domains']['tts']['selected_provider'])
        self.assertEqual(os.listdir(self.dir), ['settings.json'])  # no temp file left

        # The next load retries the migration and completes it.
        self.assertEqual(settings_manager.load_settings()['version'], SETTINGS_VERSION)
        self.assertEqual(
            self._read()['domains']['tts']['selected_instance_id'], 'inworld'
        )


# -- §22.6 / §25 API egress ---------------------------------------------------


class ProviderApiRedactionTests(unittest.TestCase):
    """No route may serve a secret value or an environment value."""

    SECRET = 'sk-live-topsecret'

    def setUp(self):
        from flask import Flask

        from scriptase.providers import providers_bp

        app = Flask(__name__)
        app.register_blueprint(providers_bp)
        self.client = app.test_client()

        self.settings = settings_manager._default_settings()
        self.settings['domains']['tts']['instances']['inworld'] = {
            'type': 'inworld',
            'label': 'inworld',
            'settings': {'api_key': self.SECRET, 'voice': 'Ashley'},
        }
        self.saved = []

        def _load():
            return json.loads(json.dumps(self.settings))

        def _save(data):
            self.saved.append(data)
            self.settings = json.loads(json.dumps(data))

        loader = patch.object(settings_manager, 'load_settings', side_effect=_load)
        loader.start()
        self.addCleanup(loader.stop)

        saver = patch.object(settings_manager, 'save_settings', side_effect=_save)
        saver.start()
        self.addCleanup(saver.stop)

    def test_the_provider_settings_read_is_redacted(self):
        resp = self.client.get('/api/providers/tts/inworld/settings')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body['settings']['api_key'], ss.REDACTION_SENTINEL)
        self.assertEqual(body['settings']['voice'], 'Ashley')
        self.assertNotIn(self.SECRET, resp.get_data(as_text=True))

    def test_the_whole_settings_document_read_is_redacted(self):
        resp = self.client.get('/api/settings/v2')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.SECRET, resp.get_data(as_text=True))

    def test_saving_the_sentinel_preserves_the_stored_secret(self):
        from scriptase.providers.secrets import is_secret_ref, resolve_secret_refs

        resp = self.client.put(
            '/api/providers/tts/inworld/settings',
            json={'api_key': ss.REDACTION_SENTINEL, 'voice': 'Carter'},
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        stored = self.saved[-1]['domains']['tts']['instances']['inworld']['settings']
        # Step 3.4: the store holds a ref; the credential is still the original.
        self.assertTrue(is_secret_ref(stored['api_key']))
        self.assertEqual(resolve_secret_refs(stored)['api_key'], self.SECRET)
        self.assertEqual(stored['voice'], 'Carter')

    def test_a_whole_document_round_trip_preserves_the_stored_secret(self):
        from scriptase.providers.secrets import is_secret_ref, resolve_secret_refs

        document = self.client.get('/api/settings/v2').get_json()
        document['domains']['tts']['selected_instance_id'] = 'kokoro'
        resp = self.client.put('/api/settings/v2', json=document)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        written = self.saved[-1]
        key = written['domains']['tts']['instances']['inworld']['settings']['api_key']
        # Either still plaintext (no write through set_instance) or a ref that
        # resolves to the original secret.
        if is_secret_ref(key):
            self.assertEqual(
                resolve_secret_refs({'api_key': key})['api_key'], self.SECRET
            )
        else:
            self.assertEqual(key, self.SECRET)
        self.assertEqual(written['domains']['tts']['selected_instance_id'], 'kokoro')

    def test_the_environment_value_never_reaches_a_response(self):
        self.settings['domains']['tts']['instances']['inworld']['settings']['api_key'] = ''
        with patch.dict(os.environ, {'INWORLD_API_KEY': 'env-only-secret'}, clear=False):
            for path in ('/api/settings/v2', '/api/providers/tts/inworld/settings',
                         '/api/providers'):
                with self.subTest(path=path):
                    body = self.client.get(path).get_data(as_text=True)
                    self.assertNotIn('env-only-secret', body)
                    self.assertNotIn('INWORLD_API_KEY', body)

    def test_the_catalog_reports_availability_per_provider(self):
        catalog = self.client.get('/api/providers').get_json()['domains']
        by_id = {p['id']: p for p in catalog['tts']['providers']}
        self.assertEqual(by_id['inworld']['availability'], AVAILABLE)
        self.assertEqual(by_id['kokoro']['availability'], AVAILABLE)

        self.settings['domains']['tts']['instances']['inworld']['settings']['api_key'] = ''
        with patch.dict(os.environ, {}, clear=True):
            catalog = self.client.get('/api/providers').get_json()['domains']
        by_id = {p['id']: p for p in catalog['tts']['providers']}
        self.assertEqual(by_id['inworld']['availability'], NEEDS_CONFIGURATION)

    def test_a_health_probe_redacts_provider_authored_details(self):
        provider = hub.get('tts', 'inworld')
        with patch.object(
            provider, 'health_check',
            return_value=type('H', (), {
                'status': 'warn', 'latency_ms': 1.0, 'message': 'ok',
                'details': {'api_key': self.SECRET},
            })(),
        ):
            resp = self.client.post('/api/providers/tts/inworld/test', json={})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.SECRET, resp.get_data(as_text=True))
        self.assertEqual(resp.get_json()['health']['details']['api_key'], '***')


if __name__ == '__main__':
    unittest.main()
