"""Step 16.4 — Failure isolation and security hardening.

Fuzzes malformed manifests, schemas, results, callbacks, provider exceptions,
giant metadata, bad paths, and secret values. Verifies one provider's import,
health, execution, or shutdown failure cannot break siblings or the process,
and that concurrent catalog reads stay consistent during reload.

Done-when surfaces for secrets (contracts.md §36): API, SSE, logs, records,
archives, and notifications.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import zipfile
from unittest import mock

from scriptase.providers import boundary
from scriptase.providers import results as R
from scriptase.providers import validation as v
from scriptase.providers.domains import DomainSpec
from scriptase.providers.errors import (
    PROVIDER_FAILED,
    PROVIDER_RESULT_INVALID,
    ProviderError,
)
from scriptase.providers.hub import ProviderHub
from scriptase.providers.invocation import ProviderInvocation
from scriptase.providers.registry import (
    ProviderConstructionError,
    ProviderManifest,
    ProviderRegistry,
)
from scriptase.providers.transports.callbacks import (
    MAX_CALLBACK_BODY_BYTES,
    REJECTED_MALFORMED,
    REJECTED_OVERSIZED,
    CallbackIntake,
)
from scriptase.engine.notifications import dispatch_run_notification
from scriptase.engine.project_archive import create_archive
from scriptase.engine.redaction import REDACTED
from scriptase.engine.scheduler import WorkflowScheduler


SECRET = "sk-live-topsecret-16-4-probe"
PATH_SECRET = "C:/Users/Admin/secrets/creds.json"
LEAKY_TEXT = f"provider rejected api_key={SECRET} reading {PATH_SECRET}"

MANIFEST = """
from scriptase.providers import ProviderManifest


def manifest():
    return ProviderManifest(
        id={id!r},
        label={label!r},
        domain={domain!r},
        kind='local',
        version='1.0.0',
        capabilities={{'batch': True}},
        requires={requires!r},
    )
"""

FACTORY = (
    "class P:\n"
    "    pass\n"
    "\n"
    "def create():\n"
    "    return P()\n"
)


def _write(folder, name, source):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
        handle.write(source)


def write_provider(
    base,
    provider_id,
    *,
    domain="tts",
    label=None,
    requires=(),
    manifest_body=None,
    provider_body=None,
    schema_body=None,
):
    folder = os.path.join(base, provider_id)
    source = manifest_body if manifest_body is not None else MANIFEST.format(
        id=provider_id,
        label=label or provider_id.title(),
        domain=domain,
        requires=list(requires),
    )
    _write(folder, "manifest.py", source)
    if provider_body is not None:
        _write(folder, "provider.py", provider_body)
    if schema_body is not None:
        _write(folder, "settings_schema.py", schema_body)
    return folder


def demo_spec(base, domain="demo"):
    return DomainSpec(
        id=domain,
        label="Demo",
        package=f"studio.{domain}.providers",
        providers_base=base,
        default_provider="alpha",
        capability_vocabulary=frozenset({"batch", "test_connection"}),
    )


class FailureIsolationTests(unittest.TestCase):
    """One provider's failure never hides or breaks a sibling."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="sts_16_4_iso_")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.registry = ProviderRegistry(domain="tts")

    def test_import_failure_excludes_only_the_broken_package(self):
        write_provider(
            self.base,
            "broken",
            manifest_body=f"raise ImportError({LEAKY_TEXT!r})\n",
        )
        write_provider(self.base, "healthy", provider_body=FACTORY)
        self.registry.discovery_scan(self.base)

        self.assertEqual(self.registry.list_ids(), ["healthy"])
        excluded = self.registry.excluded()
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0]["id"], "broken")
        blob = json.dumps(excluded)
        self.assertNotIn(SECRET, blob)
        self.assertNotIn("C:/Users", blob)
        self.assertIsNotNone(self.registry.get("healthy").create())

    def test_syntax_error_and_raising_schema_do_not_block_neighbours(self):
        write_provider(self.base, "aaa_syntax", manifest_body="def manifest(:\n")
        write_provider(
            self.base,
            "bravo",
            provider_body=FACTORY,
            schema_body="def settings_schema():\n    raise RuntimeError('boom')\n",
        )
        write_provider(self.base, "charlie", provider_body=FACTORY)
        self.registry.discovery_scan(self.base)

        self.assertEqual(self.registry.list_ids(), ["bravo", "charlie"])
        self.assertEqual(
            [e["id"] for e in self.registry.excluded()], ["aaa_syntax"]
        )
        bravo = self.registry.get("bravo")
        self.assertEqual(bravo.availability(), "degraded")
        self.assertIsNotNone(self.registry.get("charlie").create())

    def test_create_failure_is_bounded_and_attributable(self):
        write_provider(
            self.base,
            "broken",
            provider_body=(
                "def create():\n"
                f"    raise RuntimeError({LEAKY_TEXT!r})\n"
            ),
        )
        write_provider(self.base, "healthy", provider_body=FACTORY)
        self.registry.discovery_scan(self.base)

        broken = self.registry.get("broken")
        with self.assertRaises(ProviderConstructionError) as ctx:
            broken.create()
        self.assertEqual(ctx.exception.code, "PROVIDER_CREATE_FAILED")
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertNotIn("C:/Users", str(ctx.exception))
        self.assertIsNotNone(self.registry.get("healthy").create())

    def test_health_failure_is_isolated_and_sanitized(self):
        write_provider(
            self.base,
            "broken",
            provider_body=(
                "def create():\n"
                "    return object()\n"
                "\n"
                "def health_check(settings):\n"
                f"    raise RuntimeError({LEAKY_TEXT!r})\n"
            ),
        )
        write_provider(
            self.base,
            "healthy",
            provider_body=(
                "def create():\n"
                "    return object()\n"
                "\n"
                "def health_check(settings):\n"
                "    return {'status': 'ok', 'message': 'fine'}\n"
            ),
        )
        self.registry.discovery_scan(self.base)

        bad = self.registry.get("broken").health_check({})
        good = self.registry.get("healthy").health_check({})
        self.assertEqual(bad.status, "fail")
        self.assertNotIn(SECRET, bad.message or "")
        self.assertNotIn("C:/Users", bad.message or "")
        self.assertEqual(good.status, "ok")
        self.assertEqual(good.message, "fine")

    def test_health_details_never_echo_secrets_or_paths(self):
        write_provider(
            self.base,
            "leaky",
            provider_body=(
                "def create():\n"
                "    return object()\n"
                "\n"
                "def health_check(settings):\n"
                "    return {\n"
                "        'status': 'fail',\n"
                "        'message': 'upstream failed',\n"
                f"        'details': {{'api_key': {SECRET!r}, "
                f"'path': {PATH_SECRET!r}, 'note': 'ok'}},\n"
                "    }\n"
            ),
        )
        self.registry.discovery_scan(self.base)
        health = self.registry.get("leaky").health_check({})
        details = health.details or {}
        blob = json.dumps(details)
        self.assertNotIn(SECRET, blob)
        self.assertNotIn("C:/Users", blob)
        self.assertTrue("***" in blob or REDACTED in blob)
        self.assertEqual(details.get("note"), "ok")

    def test_execution_exception_never_leaks_and_sibling_still_runs(self):
        write_provider(
            self.base,
            "broken",
            provider_body=(
                "class P:\n"
                "    def invoke(self, request, invocation):\n"
                f"        raise RuntimeError({LEAKY_TEXT!r})\n"
                "\n"
                "def create():\n"
                "    return P()\n"
            ),
        )
        write_provider(
            self.base,
            "healthy",
            provider_body=(
                "from scriptase.providers.results import ProviderResult, SUCCEEDED\n"
                "\n"
                "class P:\n"
                "    def invoke(self, request, invocation):\n"
                "        return ProviderResult(status=SUCCEEDED, payload={'ok': True})\n"
                "\n"
                "def create():\n"
                "    return P()\n"
            ),
        )
        self.registry.discovery_scan(self.base)

        broken = self.registry.get("broken").create()
        healthy = self.registry.get("healthy").create()
        inv_broken = ProviderInvocation(
            domain="tts", provider_id="broken", project_id="pm_TEST01"
        )
        inv_healthy = ProviderInvocation(
            domain="tts", provider_id="healthy", project_id="pm_TEST01"
        )

        with self.assertRaises(ProviderError) as caught:
            boundary.invoke(lambda inv: broken.invoke({}, inv), inv_broken)
        error = caught.exception
        self.assertEqual(error.code, PROVIDER_FAILED)
        self.assertNotIn(SECRET, error.message)
        self.assertNotIn("C:/Users", error.message)
        self.assertNotIn("secret", error.message.lower())

        result = boundary.invoke(lambda inv: healthy.invoke({}, inv), inv_healthy)
        self.assertEqual(result.status, R.SUCCEEDED)

    def test_shutdown_failure_does_not_prevent_sibling_shutdown(self):
        shared = os.path.join(self.base, "shutdown_order.txt").replace("\\", "/")
        write_provider(
            self.base,
            "alpha",
            provider_body=(
                "class P:\n"
                "    def shutdown(self):\n"
                f"        open({shared!r}, 'a', encoding='utf-8').write('alpha\\n')\n"
                "        raise RuntimeError('teardown boom')\n"
                "\n"
                "def create():\n"
                "    return P()\n"
            ),
        )
        write_provider(
            self.base,
            "bravo",
            provider_body=(
                "class P:\n"
                "    def shutdown(self):\n"
                f"        open({shared!r}, 'a', encoding='utf-8').write('bravo\\n')\n"
                "\n"
                "def create():\n"
                "    return P()\n"
            ),
        )
        self.registry.discovery_scan(self.base)
        self.registry.get("alpha").create()
        self.registry.get("bravo").create()
        self.registry.shutdown_instances()
        lines = open(shared, encoding="utf-8").read().splitlines()
        self.assertEqual(lines, ["bravo", "alpha"])


class ConcurrentReloadTests(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="sts_16_4_reload_")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        write_provider(self.base, "alpha", domain="demo", provider_body=FACTORY)
        self.hub = ProviderHub(catalog={"demo": demo_spec(self.base)})
        self.hub.discover_all()

    def test_readers_never_see_a_partial_catalog_during_reload(self):
        write_provider(self.base, "bravo", domain="demo", provider_body=FACTORY)
        write_provider(self.base, "charlie", domain="demo", provider_body=FACTORY)
        observed = []
        barrier = threading.Barrier(9)
        done = threading.Event()
        errors = []

        def reader():
            try:
                barrier.wait(timeout=5)
                while not done.is_set():
                    ids = self.hub.registry("demo").list_ids()
                    observed.append(tuple(ids))
                    # Atomic publish: only the complete old or complete new set.
                    self.assertIn(
                        ids,
                        (["alpha"], ["alpha", "bravo", "charlie"]),
                        ids,
                    )
                # One more sample after reload finishes so both sets are seen.
                observed.append(tuple(self.hub.registry("demo").list_ids()))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(8)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=5)
        report = self.hub.reload()
        done.set()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(errors, [])
        self.assertIn("demo", report.swapped)
        self.assertEqual(
            self.hub.registry("demo").list_ids(),
            ["alpha", "bravo", "charlie"],
        )
        self.assertIn(("alpha",), observed)
        self.assertIn(("alpha", "bravo", "charlie"), observed)

    def test_invoke_during_reload_uses_a_stable_instance(self):
        write_provider(
            self.base,
            "alpha",
            domain="demo",
            provider_body=(
                "from scriptase.providers.results import ProviderResult, SUCCEEDED\n"
                "import time\n"
                "\n"
                "class P:\n"
                "    def invoke(self, request, invocation):\n"
                "        time.sleep(0.05)\n"
                "        return ProviderResult(status=SUCCEEDED, payload={'n': 1})\n"
                "\n"
                "def create():\n"
                "    return P()\n"
            ),
        )
        self.hub.registry("demo").reset()
        self.hub.discover_all()
        provider = self.hub.get("demo", "alpha")
        self.assertIsNotNone(provider)
        instance = provider.create()
        results = []
        errors = []

        def invoke():
            try:
                inv = ProviderInvocation(
                    domain="demo", provider_id="alpha", project_id="pm_TEST01"
                )
                with provider.lease():
                    results.append(
                        boundary.invoke(lambda i: instance.invoke({}, i), inv)
                    )
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=invoke)
        thread.start()
        write_provider(self.base, "bravo", domain="demo", provider_body=FACTORY)
        report = self.hub.reload()
        thread.join(timeout=5)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, R.SUCCEEDED)
        self.assertIn("demo", report.swapped)


class FuzzMalformedInputsTests(unittest.TestCase):
    def test_malformed_manifest_payloads_are_excluded_not_raised(self):
        cases = [
            None,
            42,
            "not-a-manifest",
            {},
            {"id": "bad-id!", "label": "X", "domain": "tts", "kind": "local",
             "version": "1.0.0", "capabilities": {}},
            {"id": "alpha", "label": "X", "domain": "video", "kind": "local",
             "version": "1.0.0", "capabilities": {}},
            {"id": "alpha", "label": "X", "domain": "tts", "kind": "spaceship",
             "version": "1.0.0", "capabilities": {}},
            {"id": "alpha", "label": "X", "domain": "tts", "kind": "local",
             "version": "not-semver", "capabilities": {}},
            {"id": "alpha", "label": "X", "domain": "tts", "kind": "local",
             "version": "1.0.0", "capabilities": {}, "contract_version": 99},
            {"id": "alpha", "label": "X", "domain": "tts", "kind": "local",
             "version": "1.0.0", "capabilities": {}, "aliases": ["Not_Valid"]},
            {"id": "alpha", "label": "X", "domain": "tts", "kind": "local",
             "version": "1.0.0", "capabilities": {},
             "open_url": "javascript:alert(1)"},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                result = v.validate_manifest(
                    folder_id="alpha",
                    domain="tts",
                    payload=payload,
                    manifest_cls=ProviderManifest,
                    capability_vocabulary=frozenset({"batch"}),
                )
                self.assertFalse(result.ok)
                self.assertIn(result.reason_code, v.EXCLUSION_REASON_CODES)
                self.assertTrue(result.message)

    def test_giant_and_malformed_results_are_rejected(self):
        with self.assertRaises(ProviderError) as path_err:
            R.coerce_result(
                R.ProviderResult(
                    status=R.SUCCEEDED,
                    artifact_refs=[r"C:\tmp\voice.wav"],
                ),
                domain="tts",
                provider_id="fixture",
            )
        self.assertIn(
            path_err.exception.code,
            ("PROVIDER_ARTIFACT_UNMANAGED", PROVIDER_RESULT_INVALID),
        )

        with self.assertRaises(ProviderError) as secret_err:
            R.coerce_result(
                R.ProviderResult(
                    status=R.SUCCEEDED,
                    payload={"api_key": SECRET},
                ),
                domain="tts",
                provider_id="fixture",
            )
        self.assertEqual(secret_err.exception.code, PROVIDER_RESULT_INVALID)

        huge = {f"k{i}": "x" * 5000 for i in range(100)}
        result = R.coerce_result(
            R.ProviderResult(status=R.SUCCEEDED, metadata=huge),
            domain="tts",
            provider_id="fixture",
        )
        self.assertLessEqual(len(result.metadata), R.METADATA_MAX_KEYS)
        for value in result.metadata.values():
            if isinstance(value, str):
                self.assertLessEqual(len(value), R.METADATA_STRING_MAX)

        leaks = R.validate_egress({"path": PATH_SECRET, "api_key": SECRET})
        self.assertTrue(leaks)

    def test_malformed_and_oversized_callbacks_are_rejected(self):
        intake = CallbackIntake()
        self.assertEqual(
            intake.accept(payload={"status": "done"}).outcome,
            REJECTED_MALFORMED,
        )
        huge = "x" * (MAX_CALLBACK_BODY_BYTES + 1)
        self.assertEqual(
            intake.accept(
                correlation=("image", "wavespeed_webhook", "pm_X", "job_1"),
                body=huge,
            ).outcome,
            REJECTED_OVERSIZED,
        )


class SecretEgressSurfaceTests(unittest.TestCase):
    """Secrets never appear in records, SSE, archives, or notifications."""

    def test_scheduler_failure_record_and_sse_never_contain_the_secret(self):
        events = []
        workflow = {
            "schema_version": 1,
            "workflow_id": "wf_ABC123",
            "name": "Hardening",
            "description": "",
            "nodes": [{
                "id": "n_secret",
                "type": "stub.input",
                "type_version": 1,
                "name": "Secret source",
                "position": {"x": 0, "y": 0},
                "configuration": {
                    "port_type": "generic_json",
                    "payload": {"api_key": SECRET, "ordinary": "safe"},
                },
                "disabled": False,
            }],
            "edges": [],
            "variables": {},
            "viewport": {"x": 0, "y": 0, "zoom": 1},
            "settings": {"on_error": "stop"},
            "extensions": {},
            "created_at": "2026-08-09T12:00:00Z",
            "updated_at": "2026-08-09T12:00:00Z",
        }

        def resolver(node):
            def execute(inputs, config, context):
                raise RuntimeError(LEAKY_TEXT)

            return execute

        with tempfile.TemporaryDirectory(prefix="sts_16_4_secret_") as root:
            result = WorkflowScheduler(
                workflow,
                project_id="pm_ABC123",
                lock_root=os.path.join(root, "locks"),
                output_dir=root,
                executor_resolver=resolver,
                on_event=events.append,
            ).run()
            record = result.execution_record
            execution_id = record["execution_id"]
            record_path = os.path.join(
                root, "workflows", "executions", f"{execution_id}.json"
            )
            persisted = (
                open(record_path, "rb").read() if os.path.isfile(record_path) else b""
            )
            emitted = json.dumps(events).encode()
            record_blob = json.dumps(record).encode()
            for blob in (persisted, emitted, record_blob):
                self.assertNotIn(SECRET.encode(), blob)
                self.assertNotIn(b"C:/Users", blob)

    def test_archive_redacts_secrets_even_if_source_files_are_dirty(self):
        with tempfile.TemporaryDirectory(prefix="sts_16_4_arch_") as root:
            workflows = os.path.join(root, "workflows")
            executions = os.path.join(workflows, "executions")
            projects = os.path.join(root, "projects", "pm_ABC123")
            os.makedirs(executions)
            os.makedirs(projects)
            workflow = {
                "schema_version": 1,
                "workflow_id": "wf_ABC123",
                "name": "Dirty",
                "description": "",
                "nodes": [{
                    "id": "n_script",
                    "type": "script.input",
                    "type_version": 1,
                    "name": "Script",
                    "position": {"x": 0, "y": 0},
                    "configuration": {"text": "hello", "api_key": SECRET},
                    "disabled": False,
                }],
                "edges": [],
                "variables": {},
                "viewport": {"x": 0, "y": 0, "zoom": 1},
                "settings": {"on_error": "stop"},
                "extensions": {},
                "created_at": "2026-08-09T12:00:00Z",
                "updated_at": "2026-08-09T12:00:00Z",
            }
            record = {
                "schema_version": 1,
                "execution_id": "ex_ABC123",
                "workflow_id": "wf_ABC123",
                "workflow_snapshot": workflow,
                "project_id": "pm_ABC123",
                "run_mode": "full",
                "status": "succeeded",
                "started_at": "2026-08-09T12:01:00Z",
                "finished_at": "2026-08-09T12:01:01Z",
                "nodes": {
                    "n_script": {
                        "artifact_refs": ["projects/pm_ABC123/media.bin"],
                        "error": {"message": f"api_key={SECRET}"},
                    }
                },
            }
            with open(
                os.path.join(workflows, "wf_ABC123.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(workflow, handle)
            with open(
                os.path.join(executions, "ex_ABC123.json"), "w", encoding="utf-8"
            ) as handle:
                json.dump(record, handle)
            with open(os.path.join(projects, "media.bin"), "wb") as handle:
                handle.write(b"media")

            archive = io.BytesIO()
            create_archive("wf_ABC123", "pm_ABC123", archive, output_dir=root)
            archive.seek(0)
            with zipfile.ZipFile(archive) as zf:
                for name in ("workflow.json", "executions/ex_ABC123.json"):
                    payload = zf.read(name)
                    self.assertNotIn(SECRET.encode(), payload, name)
                    self.assertIn(REDACTED.encode(), payload, name)

    def test_notification_delivery_errors_are_sanitized(self):
        workflow = {
            "schema_version": 1,
            "workflow_id": "wf_ABC123",
            "name": "Notify",
            "settings": {
                "notifications": {
                    "on_failure": True,
                    "windows_toast": False,
                    "webhook": {"enabled": True, "url": "http://127.0.0.1:9/hook"},
                }
            },
        }
        execution = {
            "execution_id": "ex_ABC123",
            "workflow_id": "wf_ABC123",
            "project_id": "pm_ABC123",
            "status": "failed",
            "finished_at": "2026-08-09T12:00:00Z",
        }

        def boom(*_args, **_kwargs):
            raise RuntimeError(LEAKY_TEXT)

        with tempfile.TemporaryDirectory(prefix="sts_16_4_notify_") as root:
            with mock.patch(
                "scriptase.engine.notifications.requests.post", side_effect=boom
            ):
                record = dispatch_run_notification(
                    workflow, execution, output_dir=root
                )
            error = record["deliveries"]["webhook"]["error"]
            self.assertNotIn(SECRET, error)
            self.assertNotIn("C:/Users", error)
            self.assertEqual(record["deliveries"]["webhook"]["status"], "failed")
            persisted = open(
                os.path.join(root, "workflows", "notifications", "ex_ABC123.json"),
                encoding="utf-8",
            ).read()
            self.assertNotIn(SECRET, persisted)


class HealthResultObjectTests(unittest.TestCase):
    def test_health_result_objects_are_sanitized_too(self):
        base = tempfile.mkdtemp(prefix="sts_16_4_hr_")
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        write_provider(
            base,
            "typed",
            provider_body=(
                "from scriptase.providers.registry import HealthResult\n"
                "\n"
                "def create():\n"
                "    return object()\n"
                "\n"
                "def health_check(settings):\n"
                f"    return HealthResult(status='fail', message={LEAKY_TEXT!r},\n"
                f"                        details={{'token': {SECRET!r}}})\n"
            ),
        )
        registry = ProviderRegistry(domain="tts")
        registry.discovery_scan(base)
        health = registry.get("typed").health_check({})
        self.assertEqual(health.status, "fail")
        self.assertNotIn(SECRET, health.message or "")
        self.assertNotIn("C:/Users", health.message or "")
        self.assertNotIn(SECRET, json.dumps(health.details or {}))


if __name__ == "__main__":
    unittest.main()
