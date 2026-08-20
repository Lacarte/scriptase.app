"""Step 11.2: package validation, factories, isolation, and lifecycle.

Covers contracts.md §19.3 (aliases, contract_version), §20.1/§20.3 (manifest
validation order and the unknown-field policy), §21.1 (create/shutdown lifecycle),
§21.2 item 6 (atomic snapshot publication and lease draining), §21.4 (exclusion
records), and §25 (browser-safe serialization).
"""

import os
import shutil
import tempfile
import threading
import unittest

from scriptase.providers import validation as v
from scriptase.providers.domains import DomainSpec
from scriptase.providers.hub import ProviderHub
from scriptase.providers.registry import (
    ProviderConstructionError,
    ProviderInstance,
    ProviderManifest,
    ProviderRegistry,
)
from scriptase.providers.runtime import call_provider_runtime


MANIFEST = """
from scriptase.providers import ProviderManifest


def manifest():
    return ProviderManifest(
        id={id!r},
        label={label!r},
        domain={domain!r},
        kind={kind!r},
        version='1.0.0',
        capabilities={capabilities!r},
        aliases={aliases!r},
    )
"""


def write_provider(base, provider_id, *, domain='tts', label=None, kind='local',
                   capabilities=None, aliases=(), manifest_body=None,
                   provider_body=None, schema_body=None):
    folder = os.path.join(base, provider_id)
    os.makedirs(folder, exist_ok=True)
    source = manifest_body if manifest_body is not None else MANIFEST.format(
        id=provider_id,
        label=label or provider_id.title(),
        domain=domain,
        kind=kind,
        capabilities=capabilities if capabilities is not None else {'batch': True},
        aliases=list(aliases),
    )
    _write(folder, 'manifest.py', source)
    if provider_body is not None:
        _write(folder, 'provider.py', provider_body)
    if schema_body is not None:
        _write(folder, 'settings_schema.py', schema_body)
    return folder


def _write(folder, name, source):
    with open(os.path.join(folder, name), 'w', encoding='utf-8') as handle:
        handle.write(source)


def demo_spec(base, domain='demo'):
    return DomainSpec(
        id=domain,
        label='Demo',
        package=f'studio.{domain}.providers',
        providers_base=base,
        default_provider='alpha',
        capability_vocabulary=frozenset({'batch', 'test_connection', 'push_callbacks'}),
    )


class TempProviderBase(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='sts_11_2_')
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.registry = ProviderRegistry(domain='tts')


# -- §20.3 manifest validation ---------------------------------------------


class ManifestValidationTests(unittest.TestCase):
    def _validate(self, payload, folder_id='alpha', domain='tts', vocabulary=None):
        return v.validate_manifest(
            folder_id=folder_id,
            domain=domain,
            payload=payload,
            manifest_cls=ProviderManifest,
            capability_vocabulary=vocabulary,
        )

    def _payload(self, **overrides):
        base = {
            'id': 'alpha', 'label': 'Alpha', 'domain': 'tts',
            'kind': 'local', 'version': '1.0.0', 'capabilities': {'batch': True},
        }
        base.update(overrides)
        return base

    def test_valid_dict_payload_is_accepted(self):
        result = self._validate(self._payload())
        self.assertTrue(result.ok)
        self.assertEqual(result.manifest.contract_version, 1)
        self.assertEqual(result.manifest.aliases, [])
        self.assertEqual(result.warnings, [])

    def test_empty_capabilities_is_valid(self):
        # The old truthiness check excluded this; §20.1 requires presence/type only.
        result = self._validate(self._payload(capabilities={}))
        self.assertTrue(result.ok)

    def test_unknown_top_level_field_is_ignored_and_warned(self):
        result = self._validate(self._payload(future_field='x', another=1))
        self.assertTrue(result.ok)
        self.assertEqual(
            result.warnings,
            ['unknown manifest field: another', 'unknown manifest field: future_field'],
        )
        self.assertFalse(hasattr(result.manifest, 'future_field'))

    def test_unknown_capability_is_dropped_and_warned(self):
        result = self._validate(
            self._payload(capabilities={'batch': True, 'teleport': True}),
            vocabulary=frozenset({'batch'}),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.manifest.capabilities, {'batch': True})
        self.assertEqual(result.warnings, ['unknown capability: teleport'])

    def test_non_boolean_capability_is_a_hard_failure(self):
        result = self._validate(self._payload(capabilities={'batch': 'yes'}))
        self.assertEqual(result.reason_code, v.MANIFEST_FIELDS_INVALID)

    def test_unknown_kind_is_a_hard_failure(self):
        result = self._validate(self._payload(kind='quantum'))
        self.assertEqual(result.reason_code, v.MANIFEST_FIELDS_INVALID)

    def test_non_semver_version_is_a_hard_failure(self):
        result = self._validate(self._payload(version='1.0'))
        self.assertEqual(result.reason_code, v.MANIFEST_FIELDS_INVALID)

    def test_invalid_id_shape_is_a_hard_failure(self):
        result = self._validate(self._payload(id='Alpha-One'), folder_id='Alpha-One')
        self.assertEqual(result.reason_code, v.MANIFEST_FIELDS_INVALID)

    def test_missing_required_field_reports_fields_missing(self):
        payload = self._payload()
        del payload['label']
        self.assertEqual(self._validate(payload).reason_code, v.MANIFEST_FIELDS_MISSING)

    def test_id_mismatch_and_domain_mismatch_have_distinct_codes(self):
        self.assertEqual(
            self._validate(self._payload(), folder_id='other').reason_code,
            v.MANIFEST_ID_MISMATCH,
        )
        self.assertEqual(
            self._validate(self._payload(domain='video')).reason_code,
            v.MANIFEST_DOMAIN_MISMATCH,
        )

    def test_wrong_return_type_reports_invalid_type(self):
        self.assertEqual(self._validate(42).reason_code, v.MANIFEST_INVALID_TYPE)

    def test_contract_version_two_is_supported(self):
        result = self._validate(self._payload(contract_version=2))
        self.assertTrue(result.ok)
        self.assertEqual(result.manifest.contract_version, 2)

    def test_future_contract_version_is_rejected_as_unsupported(self):
        result = self._validate(self._payload(contract_version=99))
        self.assertEqual(result.reason_code, v.MANIFEST_UNSUPPORTED_CONTRACT)

    def test_bad_contract_version_type_is_fields_invalid(self):
        for bad in (True, '2', 0, -1):
            with self.subTest(bad=bad):
                self.assertEqual(
                    self._validate(self._payload(contract_version=bad)).reason_code,
                    v.MANIFEST_FIELDS_INVALID,
                )

    def test_alias_shapes_are_enforced(self):
        result = self._validate(self._payload(aliases=['kie-ai', 'gemini']))
        self.assertEqual(result.manifest.aliases, ['kie-ai', 'gemini'])
        self.assertEqual(
            self._validate(self._payload(aliases=['Bad Alias'])).reason_code,
            v.MANIFEST_FIELDS_INVALID,
        )

    def test_alias_equal_to_the_id_is_dropped_not_fatal(self):
        result = self._validate(self._payload(aliases=['alpha', 'legacy']))
        self.assertTrue(result.ok)
        self.assertEqual(result.manifest.aliases, ['legacy'])
        self.assertEqual(result.warnings, ['alias dropped (same as id): alpha'])

    def test_dangerous_urls_never_reach_the_browser(self):
        for url in ('javascript:alert(1)', 'data:text/html,x', 'http://evil.test/x'):
            with self.subTest(url=url):
                self.assertEqual(
                    self._validate(self._payload(open_url=url)).reason_code,
                    v.MANIFEST_FIELDS_INVALID,
                )
        self.assertTrue(self._validate(self._payload(open_url='https://ok.test/x')).ok)
        self.assertTrue(self._validate(self._payload(open_url='http://localhost:5050/x')).ok)


class MessageSanitizationTests(unittest.TestCase):
    """Exclusion and warning strings are browser-safe (contracts.md §21.4, §25)."""

    def test_absolute_paths_are_stripped_to_a_basename(self):
        message = v.sanitize_message(
            r"No module named 'x' at D:\@Workspace\secret-project\studio\tts\provider.py"
        )
        self.assertNotIn('@Workspace', message)
        self.assertIn('provider.py', message)

    def test_posix_paths_are_stripped_too(self):
        self.assertNotIn('/home/user', v.sanitize_message('failed: /home/user/app/thing.py'))

    def test_secret_bearing_text_is_masked(self):
        self.assertEqual(
            v.sanitize_message('auth failed api_key=sk-live-123456'),
            'auth failed api_key=***',
        )

    def test_synthetic_module_names_are_hidden(self):
        self.assertNotIn(
            '_sts_provider_', v.sanitize_message('_sts_provider_tts_alpha_manifest exploded')
        )

    def test_messages_are_truncated_to_200_characters(self):
        self.assertLessEqual(len(v.sanitize_message('x' * 500)), v.MESSAGE_MAX)


# -- §21.4 exclusion records ------------------------------------------------


class ExclusionRecordTests(TempProviderBase):
    def test_every_failure_mode_is_recorded_with_its_reason_code(self):
        write_provider(self.base, 'aaa_syntax', manifest_body='def manifest(:\n')
        write_provider(self.base, 'bbb_missing', manifest_body='X = 1\n')
        write_provider(
            self.base, 'ccc_raises',
            manifest_body='def manifest():\n    raise RuntimeError("boom")\n',
        )
        write_provider(
            self.base, 'ddd_wrong_type', manifest_body='def manifest():\n    return 42\n'
        )
        write_provider(self.base, 'eee_mismatch', manifest_body=MANIFEST.format(
            id='other', label='Other', domain='tts', kind='local',
            capabilities={}, aliases=[],
        ))
        write_provider(self.base, 'fff_domain', domain='video')
        write_provider(self.base, 'ggg_kind', kind='quantum')
        write_provider(self.base, 'zzz_healthy')

        self.registry.discovery_scan(self.base)

        self.assertEqual(self.registry.list_ids(), ['zzz_healthy'])
        self.assertEqual(
            {e['id']: e['reason_code'] for e in self.registry.excluded()},
            {
                'aaa_syntax': v.MANIFEST_LOAD_FAILED,
                'bbb_missing': v.MANIFEST_MISSING,
                'ccc_raises': v.MANIFEST_RAISED,
                'ddd_wrong_type': v.MANIFEST_INVALID_TYPE,
                'eee_mismatch': v.MANIFEST_ID_MISMATCH,
                'fff_domain': v.MANIFEST_DOMAIN_MISMATCH,
                'ggg_kind': v.MANIFEST_FIELDS_INVALID,
            },
        )

    def test_exclusions_are_serialized_for_the_provider_modal(self):
        write_provider(self.base, 'broken', manifest_body='raise ImportError("nope")\n')
        write_provider(self.base, 'healthy')
        self.registry.discovery_scan(self.base)

        payload = self.registry.to_dict(selected_provider='healthy')
        self.assertEqual(payload['count'], 1)
        self.assertEqual(len(payload['excluded']), 1)
        self.assertEqual(payload['excluded'][0]['id'], 'broken')

    def test_exclusion_messages_never_carry_a_filesystem_path(self):
        write_provider(self.base, 'broken', manifest_body='import no_such_module_xyz\n')
        self.registry.discovery_scan(self.base)
        message = self.registry.excluded()[0]['message']
        self.assertNotIn(self.base, message)
        self.assertNotIn(os.sep + os.sep, message)

    def test_duplicate_registration_is_recorded_as_duplicate_id(self):
        first = ProviderManifest(
            id='alpha', label='First', domain='tts', kind='local', version='1.0.0',
        )
        later = ProviderManifest(
            id='alpha', label='Second', domain='tts', kind='local', version='2.0.0',
        )
        self.registry.register('alpha', module=None, manifest=first)
        self.registry.register('alpha', module=None, manifest=later)

        self.assertEqual(self.registry.get('alpha').label, 'First')
        self.assertEqual(
            [e['reason_code'] for e in self.registry.excluded()], [v.DUPLICATE_ID]
        )

    def test_a_present_but_broken_settings_schema_is_a_warning_not_an_exclusion(self):
        write_provider(
            self.base, 'alpha',
            provider_body='def create():\n    return object()\n',
            schema_body='raise ValueError("bad schema")\n',
        )
        self.registry.discovery_scan(self.base)
        provider = self.registry.get('alpha')
        self.assertIsNotNone(provider)
        self.assertIn('settings_schema.py failed to load', provider.warnings)


# -- §19.3 aliases ----------------------------------------------------------


class AliasResolutionTests(TempProviderBase):
    def test_alias_resolves_to_the_canonical_provider(self):
        write_provider(self.base, 'kie_ai', aliases=['kie-ai'])
        self.registry.discovery_scan(self.base)

        self.assertIs(self.registry.get('kie-ai'), self.registry.get('kie_ai'))
        self.assertEqual(self.registry.aliases(), {'kie-ai': 'kie_ai'})

    def test_a_real_id_always_beats_an_alias(self):
        write_provider(self.base, 'alpha', aliases=['bravo'])
        write_provider(self.base, 'bravo')
        self.registry.discovery_scan(self.base)

        self.assertEqual(self.registry.get('bravo').id, 'bravo')
        self.assertIn(
            'alias dropped (collides with provider id): bravo',
            self.registry.get('alpha').warnings,
        )
        self.assertEqual(self.registry.excluded(), [])

    def test_colliding_aliases_warn_both_providers_and_exclude_neither(self):
        write_provider(self.base, 'alpha', aliases=['legacy'])
        write_provider(self.base, 'bravo', aliases=['legacy'])
        self.registry.discovery_scan(self.base)

        self.assertEqual(self.registry.get('legacy').id, 'alpha')  # discovery order wins
        self.assertIn(
            "alias dropped (claimed by 'alpha'): legacy", self.registry.get('bravo').warnings
        )
        self.assertIn(
            "alias also claimed by 'bravo': legacy", self.registry.get('alpha').warnings
        )
        self.assertEqual(self.registry.excluded(), [])
        self.assertEqual(self.registry.list_ids(), ['alpha', 'bravo'])


# -- §21.1 construction and teardown ----------------------------------------


FACTORY_PROVIDER = """
class Demo:
    instances = 0
    def __init__(self):
        Demo.instances += 1
        self.closed = False
    def shutdown(self):
        self.closed = True


def create():
    return Demo()
"""


class FactoryLifecycleTests(TempProviderBase):
    def test_create_is_memoized_per_provider(self):
        write_provider(self.base, 'alpha', provider_body=FACTORY_PROVIDER)
        self.registry.discovery_scan(self.base)
        provider = self.registry.get('alpha')

        self.assertFalse(provider.constructed)  # discovery never constructs
        first = provider.create()
        self.assertIs(first, provider.create())
        self.assertEqual(type(first).instances, 1)

    def test_concurrent_create_calls_construct_once(self):
        write_provider(self.base, 'alpha', provider_body=FACTORY_PROVIDER)
        self.registry.discovery_scan(self.base)
        provider = self.registry.get('alpha')

        results = []
        barrier = threading.Barrier(8)

        def build():
            barrier.wait()
            results.append(provider.create())

        threads = [threading.Thread(target=build) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(set(id(r) for r in results)), 1)
        self.assertEqual(type(results[0]).instances, 1)

    def test_legacy_get_provider_factory_still_resolves(self):
        write_provider(
            self.base, 'alpha',
            provider_body='class L:\n    pass\n\n\ndef get_provider():\n    return L()\n',
        )
        self.registry.discovery_scan(self.base)
        self.assertEqual(type(self.registry.get('alpha').create()).__name__, 'L')

    def test_a_raising_factory_is_isolated_and_reported(self):
        write_provider(
            self.base, 'alpha',
            provider_body='def create():\n    raise RuntimeError("api_key=sk-secret boom")\n',
        )
        write_provider(self.base, 'bravo', provider_body=FACTORY_PROVIDER)
        self.registry.discovery_scan(self.base)

        broken = self.registry.get('alpha')
        with self.assertRaises(ProviderConstructionError) as ctx:
            broken.create()
        self.assertEqual(ctx.exception.code, 'PROVIDER_CREATE_FAILED')
        self.assertNotIn('sk-secret', str(ctx.exception))
        self.assertTrue(any('create() raised' in w for w in broken.warnings))

        # A second attempt fails from the recorded error, without re-running the body.
        with self.assertRaises(ProviderConstructionError):
            broken.create()
        # …and the healthy neighbour is unaffected.
        self.assertIsNotNone(self.registry.get('bravo').create())

    def test_a_provider_without_a_factory_is_flagged_at_discovery(self):
        write_provider(self.base, 'alpha')
        self.registry.discovery_scan(self.base)
        provider = self.registry.get('alpha')

        self.assertIn('no create() factory found in the provider package', provider.warnings)
        with self.assertRaises(ProviderConstructionError):
            provider.create()

    def test_shutdown_runs_once_and_never_raises(self):
        write_provider(
            self.base, 'alpha',
            provider_body=(
                'class Demo:\n'
                '    calls = 0\n'
                '    def shutdown(self):\n'
                '        Demo.calls += 1\n'
                '        raise RuntimeError("teardown exploded")\n'
                '\n\ndef create():\n    return Demo()\n'
            ),
        )
        self.registry.discovery_scan(self.base)
        provider = self.registry.get('alpha')
        instance = provider.create()

        provider.shutdown()
        provider.shutdown()

        self.assertEqual(type(instance).calls, 1)
        self.assertTrue(any('shutdown() failed' in w for w in provider.warnings))

    def test_registry_shuts_down_in_reverse_construction_order(self):
        order = []
        registry = ProviderRegistry(domain='tts')

        class Recorder:
            def __init__(self, name):
                self.name = name

            def shutdown(self):
                order.append(self.name)

        for name in ('alpha', 'bravo', 'charlie'):
            manifest = ProviderManifest(
                id=name, label=name.title(), domain='tts', kind='local', version='1.0.0',
            )
            registry.register(name, module=None, manifest=manifest)
            instance = registry.get(name)
            instance.provider_module = type(
                'M', (), {'create': staticmethod(lambda n=name: Recorder(n))}
            )
            instance.create()

        registry.shutdown_instances()
        self.assertEqual(order, ['charlie', 'bravo', 'alpha'])


# -- §21.2 item 6: atomic publication and lease draining --------------------


class AtomicPublicationTests(TempProviderBase):
    def test_a_rescan_is_invisible_until_it_completes(self):
        write_provider(self.base, 'alpha')
        self.registry.discovery_scan(self.base)
        self.assertEqual(self.registry.list_ids(), ['alpha'])

        write_provider(self.base, 'bravo')
        write_provider(self.base, 'charlie')

        observed = []
        original = self.registry._load_provider

        def spy(builder, provider_id, provider_path, manifest_file):
            # Mid-scan a concurrent reader must still see the complete old catalog,
            # never the partially built one (contracts.md §21.2 item 6).
            observed.append(self.registry.list_ids())
            return original(builder, provider_id, provider_path, manifest_file)

        self.registry._load_provider = spy
        self.registry._discovered = False
        self.registry.discovery_scan(self.base)

        self.assertEqual(observed, [['alpha'], ['alpha'], ['alpha']])
        self.assertEqual(self.registry.list_ids(), ['alpha', 'bravo', 'charlie'])

    def test_snapshots_are_immutable_once_published(self):
        write_provider(self.base, 'alpha')
        self.registry.discovery_scan(self.base)
        held = self.registry.snapshot

        write_provider(self.base, 'bravo')
        self.registry.discovery_scan(self.base)

        self.assertEqual(list(held.providers), ['alpha'])
        self.assertEqual(self.registry.list_ids(), ['alpha', 'bravo'])

    def test_a_dropped_provider_is_shut_down_only_after_its_lease_drains(self):
        write_provider(self.base, 'alpha', provider_body=FACTORY_PROVIDER)
        self.registry.discovery_scan(self.base)
        provider = self.registry.get('alpha')
        instance = provider.create()

        entered = threading.Event()
        release = threading.Event()

        def serve():
            with provider.lease():
                entered.set()
                release.wait(5)

        worker = threading.Thread(target=serve)
        worker.start()
        entered.wait(5)

        shutil.rmtree(os.path.join(self.base, 'alpha'))
        retire_done = threading.Event()

        def swap():
            self.registry.discovery_scan(self.base)
            retire_done.set()

        swapper = threading.Thread(target=swap)
        swapper.start()

        # New lookups cannot acquire it any more, but the in-flight request is safe.
        self.assertFalse(retire_done.wait(0.3))
        self.assertFalse(instance.closed)

        release.set()
        worker.join(5)
        swapper.join(5)
        self.assertTrue(retire_done.is_set())
        self.assertTrue(instance.closed)
        self.assertIsNone(self.registry.get('alpha'))


# -- runtime binding --------------------------------------------------------


class RuntimeBindingTests(unittest.TestCase):
    def test_a_failing_register_runtime_is_reported_not_raised(self):
        module = type('M', (), {
            'register_runtime': staticmethod(
                lambda app, sock: (_ for _ in ()).throw(RuntimeError('ws bind failed'))
            )
        })
        binding = call_provider_runtime('grok_automa', module, object(), object())
        self.assertFalse(binding.bound)
        self.assertIn('register_runtime() failed', binding.error)

    def test_a_module_without_the_hook_is_not_an_error(self):
        binding = call_provider_runtime('inworld', type('M', (), {}), object(), object())
        self.assertFalse(binding.bound)
        self.assertIsNone(binding.error)


RUNTIME_PROVIDER = """
bound = []


def register_runtime(app, sock):
    bound.append((app, sock))


def create():
    return object()
"""


class HubRuntimeBindingTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='sts_11_2_rt_')
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)

    def _hub(self):
        return ProviderHub({'demo': demo_spec(self.base)})

    def test_only_extension_providers_get_a_runtime(self):
        write_provider(
            self.base, 'alpha', domain='demo', kind='extension',
            capabilities={'push_callbacks': True}, provider_body=RUNTIME_PROVIDER,
        )
        write_provider(
            self.base, 'bravo', domain='demo', kind='local', provider_body=RUNTIME_PROVIDER
        )
        hub = self._hub()
        hub.discover_all()
        hub.bind_runtimes(app=object(), sock=object())

        self.assertEqual(len(hub.get('demo', 'alpha').provider_module.bound), 1)
        self.assertEqual(hub.get('demo', 'bravo').provider_module.bound, [])

    def test_push_callbacks_without_the_extension_kind_is_warned(self):
        write_provider(
            self.base, 'alpha', domain='demo', kind='cloud',
            capabilities={'push_callbacks': True}, provider_body=RUNTIME_PROVIDER,
        )
        hub = self._hub()
        hub.discover_all()
        hub.bind_runtimes(app=object(), sock=object())

        provider = hub.get('demo', 'alpha')
        self.assertEqual(provider.provider_module.bound, [])
        self.assertTrue(any('push_callbacks' in w for w in provider.warnings))

    def test_a_broken_runtime_does_not_stop_the_others_binding(self):
        write_provider(
            self.base, 'alpha', domain='demo', kind='extension',
            provider_body='def register_runtime(app, sock):\n    raise RuntimeError("boom")\n',
        )
        write_provider(
            self.base, 'bravo', domain='demo', kind='extension', provider_body=RUNTIME_PROVIDER
        )
        hub = self._hub()
        hub.discover_all()
        hub.bind_runtimes(app=object(), sock=object())

        self.assertTrue(
            any('register_runtime() failed' in w for w in hub.get('demo', 'alpha').warnings)
        )
        self.assertEqual(len(hub.get('demo', 'bravo').provider_module.bound), 1)


# -- guarded dev reload -----------------------------------------------------


class GuardedReloadTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='sts_11_2_reload_')
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        write_provider(self.base, 'alpha', domain='demo', provider_body=FACTORY_PROVIDER)
        self.hub = ProviderHub({'demo': demo_spec(self.base)})
        self.hub.discover_all()

    def test_adding_a_provider_folder_changes_the_catalog(self):
        write_provider(self.base, 'bravo', domain='demo', provider_body=FACTORY_PROVIDER)
        report = self.hub.reload()

        self.assertEqual(report.swapped, ['demo'])
        self.assertEqual([p.id for p in self.hub.list('demo')], ['alpha', 'bravo'])

    def test_removing_a_provider_folder_changes_the_catalog(self):
        shutil.rmtree(os.path.join(self.base, 'alpha'))
        report = self.hub.reload()

        self.assertEqual(report.swapped, ['demo'])
        self.assertEqual(self.hub.list('demo'), [])

    def test_an_invalid_edit_retains_the_last_good_catalog(self):
        original = self.hub.get('demo', 'alpha')
        _write(os.path.join(self.base, 'alpha'), 'manifest.py', 'def manifest(:\n')

        report = self.hub.reload()

        self.assertEqual(report.swapped, [])
        self.assertEqual(report.retained, {'demo': ['alpha would be excluded']})
        self.assertIs(self.hub.get('demo', 'alpha'), original)

    def test_a_new_broken_folder_does_not_block_a_valid_addition(self):
        write_provider(self.base, 'bravo', domain='demo', provider_body=FACTORY_PROVIDER)
        write_provider(self.base, 'zzz_broken', manifest_body='def manifest(:\n')

        report = self.hub.reload()

        self.assertEqual(report.swapped, ['demo'])
        self.assertEqual([p.id for p in self.hub.list('demo')], ['alpha', 'bravo'])
        self.assertEqual(
            [e['id'] for e in self.hub.registry('demo').excluded()], ['zzz_broken']
        )

    def test_a_swapped_out_provider_is_shut_down(self):
        instance = self.hub.create('demo', 'alpha')
        shutil.rmtree(os.path.join(self.base, 'alpha'))

        self.hub.reload()

        self.assertTrue(instance.closed)


class ZeroTouchProviderTests(unittest.TestCase):
    """A provider folder is the whole edit (contracts.md §26).

    Uses a private registry over the real `tts` provider path so the assertion is
    about the shipped discovery path, not a synthetic one, without mutating the
    process-wide hub.
    """

    def setUp(self):
        from scriptase.providers.domains import DOMAINS

        self.base = DOMAINS['tts'].providers_base
        self.folder = os.path.join(self.base, 'zzz_fixture_provider')
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def _ids(self):
        registry = ProviderRegistry(
            domain='tts', capability_vocabulary=frozenset({'batch', 'test_connection'})
        )
        registry.discovery_scan(self.base)
        return registry.list_ids()

    def test_adding_and_removing_a_folder_changes_the_catalog(self):
        baseline = self._ids()
        self.assertNotIn('zzz_fixture_provider', baseline)

        write_provider(
            self.base, 'zzz_fixture_provider', provider_body=FACTORY_PROVIDER
        )
        self.assertEqual(self._ids(), baseline + ['zzz_fixture_provider'])

        shutil.rmtree(self.folder)
        self.assertEqual(self._ids(), baseline)


class ShippedCatalogTests(unittest.TestCase):
    """The seven shipped providers must survive the stricter validation."""

    def setUp(self):
        from scriptase.providers.hub import hub

        self.hub = hub

    def test_every_shipped_provider_loads_without_warnings_or_exclusions(self):
        for domain in self.hub.domains():
            registry = self.hub.registry(domain)
            with self.subTest(domain=domain):
                self.assertEqual(registry.excluded(), [])
                for provider in registry.list_providers():
                    self.assertEqual(provider.warnings, [], provider.id)

    def test_every_shipped_provider_resolves_a_factory(self):
        for domain in self.hub.domains():
            for provider in self.hub.list(domain):
                with self.subTest(provider=f'{domain}/{provider.id}'):
                    self.assertIsNotNone(provider.create_callable)

    def test_serialization_leaks_no_modules_or_paths(self):
        for domain in self.hub.domains():
            for provider in self.hub.list(domain):
                payload = provider.to_dict()
                with self.subTest(provider=f'{domain}/{provider.id}'):
                    self.assertEqual(
                        set(payload),
                        {
                            'id', 'label', 'domain', 'kind', 'version', 'contract_version',
                            'aliases', 'requires', 'capabilities', 'open_url',
                            'docs_url', 'description', 'availability',
                            'has_settings', 'warnings', 'provider_type',
                        },
                    )
                    blob = repr(payload)
                    self.assertNotIn('_sts_provider_', blob)
                    self.assertNotIn(os.sep + 'studio' + os.sep, blob)


class ProviderInstanceCacheTests(unittest.TestCase):
    """Only the caches the contract declares exist (contracts.md §21.1)."""

    def test_settings_schema_is_memoized_and_validation_is_not(self):
        calls = {'schema': 0, 'validate': 0}
        module = type('M', (), {
            'settings_schema': staticmethod(
                lambda: calls.__setitem__('schema', calls['schema'] + 1) or {'type': 'object'}
            ),
            'validate_settings': staticmethod(
                lambda s: calls.__setitem__('validate', calls['validate'] + 1) or []
            ),
        })
        instance = ProviderInstance(
            'alpha', module=None,
            manifest=ProviderManifest(
                id='alpha', label='Alpha', domain='tts', kind='local', version='1.0.0'
            ),
            provider_module=module,
        )

        instance.settings_schema()
        instance.settings_schema()
        instance.validate_settings({})
        instance.validate_settings({'a': 1})

        self.assertEqual(calls, {'schema': 1, 'validate': 2})
        self.assertFalse(hasattr(instance, '_cached_validation'))
        self.assertFalse(hasattr(instance, '_cached_health'))


if __name__ == '__main__':
    unittest.main()
