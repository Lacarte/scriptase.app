"""Reusable provider contract-test kit — step 16.2.

Supplies three things a provider author (or the scaffolder) can lean on without
re-implementing the frozen §20 / §30 / §31 / §33 rules:

  * **shape helpers** — assertions every conforming package must satisfy
    (manifest v2, settings schema, health, egress);
  * **execution fakes** — offline, credential-free providers for the three
    platform shapes (sync document, sync artifact, async multi-asset);
  * **suite mixins** — drop into a unittest/pytest class, override
    `make_provider()` / identity, and the kit drives the shared cases.

Nothing here is registered with the hub. The fakes are pure objects; generated
scaffold tests import the helpers and point them at a real package.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from unittest import mock

from scriptase.providers.invocation import build_invocation
from scriptase.providers.registry import ProviderManifest
from scriptase.providers.results import (
    PARTIAL,
    SUCCEEDED,
    UNIT_FAILED,
    UNIT_SUCCEEDED,
    ProviderResult,
    normalize_ref,
    validate_egress,
)
from scriptase.providers.validation import (
    ID_RE,
    KINDS,
    SEMVER_RE,
    SUPPORTED_CONTRACT_VERSIONS,
    validate_manifest,
)


# ---------------------------------------------------------------------------
# Manifest / package helpers
# ---------------------------------------------------------------------------


def assert_manifest_v2(
    manifest: ProviderManifest | Mapping[str, Any],
    *,
    folder_id: str | None = None,
    domain: str | None = None,
    capability_vocabulary: frozenset[str] | None = None,
) -> ProviderManifest:
    """Validate a manifest against Provider Contract v2 and return the coerced form."""
    if isinstance(manifest, ProviderManifest):
        payload = manifest
        folder = folder_id or manifest.id
        dom = domain or manifest.domain
    else:
        payload = dict(manifest)
        folder = folder_id or str(payload.get("id") or "")
        dom = domain or str(payload.get("domain") or "")

    outcome = validate_manifest(
        folder,
        dom,
        payload,
        ProviderManifest,
        capability_vocabulary=capability_vocabulary,
    )
    assert outcome.ok, f"{outcome.reason_code}: {outcome.message}"
    result = outcome.manifest
    assert isinstance(result, ProviderManifest)
    assert result.contract_version in SUPPORTED_CONTRACT_VERSIONS
    assert result.contract_version == 2, "scaffolded providers ship on contract_version=2"
    assert ID_RE.fullmatch(result.id)
    assert result.kind in KINDS
    assert SEMVER_RE.fullmatch(result.version)
    assert isinstance(result.capabilities, dict)
    assert all(isinstance(v, bool) for v in result.capabilities.values())
    return result


def assert_settings_schema(schema: Mapping[str, Any] | None) -> None:
    """A settings schema is either absent or a JSON-Schema-shaped object."""
    if schema is None:
        return
    assert isinstance(schema, dict)
    assert schema.get("type") == "object"
    props = schema.get("properties") or {}
    assert isinstance(props, dict)
    required = schema.get("required") or []
    assert isinstance(required, list)
    for key in required:
        assert key in props, f"required field {key!r} missing from properties"


def assert_health_shape(result: Mapping[str, Any]) -> None:
    """`health_check()` returns the frozen status object (§21.5)."""
    assert isinstance(result, dict)
    assert result.get("status") in {"ok", "warn", "fail", "degraded"}
    if "message" in result and result["message"] is not None:
        assert isinstance(result["message"], str)
        assert len(result["message"]) <= 200
    if "latency_ms" in result and result["latency_ms"] is not None:
        assert isinstance(result["latency_ms"], (int, float))


def assert_egress_clean(result: ProviderResult | Mapping[str, Any]) -> None:
    """The envelope that leaves a provider carries no secrets or absolute paths."""
    payload = result.to_dict() if isinstance(result, ProviderResult) else dict(result)
    problems = validate_egress(payload)
    assert not problems, f"egress violations: {problems}"


def load_provider_modules(provider_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Load `manifest.py` / `provider.py` / `settings_schema.py` from a package dir.

    Used by scaffold unit tests that write into a temp tree the hub does not
    scan, and by generated smoke tests that want the package under test without
    going through a process-wide registry.
    """
    import importlib.util
    from pathlib import Path

    base = Path(provider_dir)
    modules: dict[str, Any] = {}
    for name in ("manifest", "provider", "settings_schema"):
        path = base / f"{name}.py"
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location(
            f"_sts_scaffold_load_{base.name}_{name}", path
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[name] = module
    return modules


# ---------------------------------------------------------------------------
# Fakes — one per execution shape
# ---------------------------------------------------------------------------


@dataclass
class FakeSyncDocumentProvider:
    """Offline sync-document provider (script / scene_director shape)."""

    prefix: str = "fake"
    shutdown_calls: int = 0

    def generate(self, configuration: Mapping[str, Any], *, project_id: str) -> dict:
        from scriptase.shared.io_utils import safe_json_write
        import config

        idea = str((configuration or {}).get("idea") or "hello")
        script_text = f"{self.prefix}: {idea}"
        sections = {"hook": script_text, "cta": f"{self.prefix} cta"}
        document = {
            "project_id": project_id,
            "story_text": script_text,
            "sections": sections,
            "metadata": {
                "word_count": len(script_text.split()),
                "estimated_duration": max(1, len(script_text.split()) // 3),
                "language": str((configuration or {}).get("language") or "english"),
            },
            "pipeline_ref": {"tts_project_id": None, "scenes_project_id": None},
        }
        path = os.path.join(config.OUTPUT_DIR, "fake_document", project_id, "story.json")
        safe_json_write(path, document, indent=2)
        return {**document, "path": path}

    def invoke(self, request, invocation) -> ProviderResult:
        options = request if isinstance(request, Mapping) else getattr(request, "model_dump", lambda: {})()
        document = self.generate(options, project_id=invocation.project_id)
        path = document.pop("path")
        ref = normalize_ref(path)
        invocation.progress(ready=1, total=1, state="succeeded")
        return ProviderResult(
            payload={**document, "document_ref": ref},
            artifact_refs=[ref],
            metadata={"shape": "sync_document"},
        )

    def shutdown(self) -> None:
        self.shutdown_calls += 1


@dataclass
class FakeSyncArtifactProvider:
    """Offline sync-artifact provider (tts shape)."""

    voice: str = "fx_calm"
    shutdown_calls: int = 0
    _RIFF: bytes = b"RIFF$\x00\x00\x00WAVEfmt "

    def synthesize(self, text, settings, voice=None, speed=1.0, on_progress=None):
        from scriptase.modules.tts.providers.base import TTSResult

        job_dir = settings.get("output_dir") or tempfile.mkdtemp(prefix="sts_fake_tts_")
        os.makedirs(job_dir, exist_ok=True)
        basename = settings.get("output_basename") or "voice"
        path = os.path.join(job_dir, f"{basename}.wav")
        with open(path, "wb") as handle:
            handle.write(self._RIFF)
        if on_progress:
            on_progress("fake synthesizing")
        return TTSResult(
            audio_path=path,
            duration_seconds=max(0.1, len(text or "") / (12.0 * float(speed or 1.0))),
            sample_rate=int(settings.get("sample_rate") or 24000),
            metadata={"voice": voice or self.voice, "prompt": text},
        )

    def list_voices(self, settings):
        from scriptase.modules.tts.providers.base import Voice

        return [Voice(id=self.voice, name="Fake", language="en-us")]

    def invoke(self, request, invocation) -> ProviderResult:
        fields = request if isinstance(request, Mapping) else request.model_dump()
        text = str(fields.get("text") or "")
        voice = str(fields.get("voice") or self.voice)
        speed = float(fields.get("speed") or 1.0)
        settings = {
            **dict(invocation.settings or {}),
            **dict(invocation.options or {}),
            "output_dir": invocation.output_dir or tempfile.mkdtemp(prefix="sts_fake_tts_"),
            "output_basename": str(fields.get("output_basename") or "voice"),
        }
        result = self.synthesize(text, settings, voice=voice, speed=speed)
        ref = normalize_ref(result.audio_path)
        invocation.progress(ready=1, total=1, state="succeeded")
        return ProviderResult(
            payload={
                "audio_ref": ref,
                "duration_seconds": result.duration_seconds,
                "sample_rate": result.sample_rate,
                "format": "wav",
                "voice": voice,
                "characters_billed": len(text),
            },
            artifact_refs=[ref],
            metadata={"shape": "sync_artifact"},
        )

    def shutdown(self) -> None:
        self.shutdown_calls += 1


@dataclass
class FakeAsyncMultiAssetProvider:
    """Offline async multi-asset provider (storyboard / animator shape)."""

    unit_bytes: bytes = b"\x89PNG\r\n\x1a\n"
    fail_last: bool = False
    shutdown_calls: int = 0

    def __post_init__(self) -> None:
        self.jobs: dict[str, dict] = {}

    def submit(self, request, invocation):
        from scriptase.providers.jobs import JobHandle, JobStatus, RUNNING

        total = _unit_count(request, invocation)
        handle = JobHandle(
            job_id=f"fake-async-{invocation.invocation_id[:12]}",
            domain=invocation.domain,
            provider_id=invocation.provider_id,
            project_id=invocation.project_id,
            invocation_id=invocation.invocation_id,
        )
        self.jobs[handle.job_id] = {
            "status": JobStatus(job_id=handle.job_id, state=RUNNING, ready=0, total=total),
            "invocation": invocation,
            "units": [],
        }
        invocation.progress(ready=0, total=total, message="submitted")
        return handle

    def poll(self, job_id: str, invocation):
        from scriptase.providers.errors import (
            PROVIDER_UNIT_FAILED,
            ProviderError,
            ProviderErrorPayload,
        )
        from scriptase.providers.jobs import SUCCEEDED as JOB_SUCCEEDED
        from scriptase.providers.results import UnitResult

        job = self.jobs.get(job_id)
        if job is None:
            from scriptase.providers.jobs import unknown_job_status

            return unknown_job_status(job_id)

        status = job["status"]
        index = len(job["units"])
        last = index == status.total - 1
        if self.fail_last and last:
            job["units"].append(
                UnitResult(
                    index,
                    UNIT_FAILED,
                    error=ProviderErrorPayload.from_error(
                        ProviderError(
                            PROVIDER_UNIT_FAILED,
                            "Fake unit failed",
                            retryable=True,
                        )
                    ),
                )
            )
        else:
            ref = self._write_unit(job["invocation"], index)
            job["units"].append(
                UnitResult(index, UNIT_SUCCEEDED, artifact_refs=(ref,), metadata={"unit": index})
            )

        produced = sum(1 for unit in job["units"] if unit.state == UNIT_SUCCEEDED)
        if len(job["units"]) >= status.total:
            status = status.advance(
                state=PARTIAL if self.fail_last else JOB_SUCCEEDED,
                ready=produced,
                units=tuple(job["units"]),
            )
        else:
            status = status.advance(ready=produced, units=tuple(job["units"]))
        job["status"] = status
        invocation.progress(ready=produced, total=status.total)
        return status

    def cancel_job(self, job_id: str, invocation) -> None:
        from scriptase.providers.jobs import JOB_CANCELLED

        job = self.jobs.get(job_id)
        if job is not None:
            job["status"] = job["status"].advance(state=JOB_CANCELLED)

    def _write_unit(self, invocation, index: int) -> str:
        destination = os.path.join(invocation.output_dir or tempfile.mkdtemp(), f"unit-{index}.png")
        path = (
            invocation.stage_artifact(destination)
            if getattr(invocation, "stage_artifact", None) is not None
            else destination
        )
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(self.unit_bytes)
        try:
            return normalize_ref(destination)
        except Exception:
            return f"unit-{index}.png"

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _unit_count(request, invocation) -> int:
    options = dict(getattr(invocation, "options", None) or {})
    if options.get("unit_count") is not None:
        return max(1, int(options["unit_count"]))
    if isinstance(request, Mapping):
        scenes = request.get("scenes") or request.get("units") or ()
        if scenes:
            return len(scenes)
    scenes = getattr(request, "scenes", None)
    if isinstance(scenes, (list, tuple)) and scenes:
        return len(scenes)
    return 3


# ---------------------------------------------------------------------------
# Suite mixins
# ---------------------------------------------------------------------------


class SyncDocumentContractSuite:
    """Assertions every sync-document provider (script shape) must satisfy.

    Subclasses set `domain` / `provider_id` and implement `make_provider()`.
    """

    domain = "script"
    provider_id = "fake_document"
    project_id = "pm_SCAFFOLD01"

    def make_provider(self):
        return FakeSyncDocumentProvider()

    def sample_configuration(self) -> dict:
        return {"idea": "a quiet town forgets its own name", "language": "english"}

    def setUp(self):  # unittest compatibility
        self.output_root = tempfile.mkdtemp(prefix="sts_sync_doc_")
        self._output_patches = []
        for target in (
            "config.OUTPUT_DIR",
            "scriptase.providers.results.OUTPUT_DIR",
        ):
            patcher = mock.patch(target, self.output_root)
            patcher.start()
            self._output_patches.append(patcher)
        self.provider = self.make_provider()

    def tearDown(self):
        for patcher in getattr(self, "_output_patches", ()):
            patcher.stop()
        import shutil

        shutil.rmtree(self.output_root, ignore_errors=True)

    def test_generate_writes_managed_document(self):
        document = self.provider.generate(
            self.sample_configuration(), project_id=self.project_id
        )
        assert document["story_text"]
        path = document["path"]
        assert os.path.isfile(path)
        assert os.path.commonpath([self.output_root, os.path.abspath(path)]) == os.path.abspath(
            self.output_root
        )

    def test_invoke_returns_clean_envelope(self):
        invocation = build_invocation(
            None,
            domain=self.domain,
            provider_id=self.provider_id,
            project_id=self.project_id,
            output_dir=os.path.join(self.output_root, self.domain, self.project_id),
            settings={},
            options=self.sample_configuration(),
        )
        result = self.provider.invoke(self.sample_configuration(), invocation)
        assert isinstance(result, ProviderResult)
        assert result.artifact_refs
        assert_egress_clean(result)


class SyncArtifactContractSuite:
    """Assertions every sync-artifact provider (tts shape) must satisfy."""

    domain = "tts"
    provider_id = "fake_artifact"
    project_id = "pm_SCAFFOLD02"

    def make_provider(self):
        return FakeSyncArtifactProvider()

    def sample_request(self) -> dict:
        return {"text": "hello scaffold", "voice": "fx_calm", "speed": 1.0}

    def setUp(self):
        self.output_root = tempfile.mkdtemp(prefix="sts_sync_art_")
        self._output_patches = []
        for target in (
            "config.OUTPUT_DIR",
            "config.TTS_DIR",
            "scriptase.providers.results.OUTPUT_DIR",
        ):
            value = (
                os.path.join(self.output_root, "tts")
                if target.endswith("TTS_DIR")
                else self.output_root
            )
            patcher = mock.patch(target, value)
            patcher.start()
            self._output_patches.append(patcher)
        self.provider = self.make_provider()

    def tearDown(self):
        for patcher in getattr(self, "_output_patches", ()):
            patcher.stop()
        import shutil

        shutil.rmtree(self.output_root, ignore_errors=True)

    def test_invoke_returns_audio_ref(self):
        out = os.path.join(self.output_root, "tts", self.project_id)
        os.makedirs(out, exist_ok=True)
        invocation = build_invocation(
            None,
            domain=self.domain,
            provider_id=self.provider_id,
            project_id=self.project_id,
            output_dir=out,
            settings={},
            options={},
        )
        result = self.provider.invoke(self.sample_request(), invocation)
        assert isinstance(result, ProviderResult)
        assert result.payload.get("audio_ref")
        assert_egress_clean(result)


class AsyncMultiAssetContractSuite:
    """Assertions every async multi-asset provider must satisfy."""

    domain = "image"
    provider_id = "fake_async"
    project_id = "pm_SCAFFOLD03"

    def make_provider(self):
        return FakeAsyncMultiAssetProvider()

    def sample_request(self) -> dict:
        return {"scenes": [{"id": 0}, {"id": 1}, {"id": 2}]}

    def setUp(self):
        self.output_root = tempfile.mkdtemp(prefix="sts_async_")
        self._output_patches = []
        for target in (
            "config.OUTPUT_DIR",
            "scriptase.providers.results.OUTPUT_DIR",
        ):
            patcher = mock.patch(target, self.output_root)
            patcher.start()
            self._output_patches.append(patcher)
        self.provider = self.make_provider()

    def tearDown(self):
        for patcher in getattr(self, "_output_patches", ()):
            patcher.stop()
        import shutil

        shutil.rmtree(self.output_root, ignore_errors=True)

    def test_submit_poll_reaches_terminal_success(self):
        out = os.path.join(self.output_root, self.domain, self.project_id)
        os.makedirs(out, exist_ok=True)
        invocation = build_invocation(
            None,
            domain=self.domain,
            provider_id=self.provider_id,
            project_id=self.project_id,
            output_dir=out,
            settings={},
            options={"unit_count": 3},
        )
        handle = self.provider.submit(self.sample_request(), invocation)
        status = None
        for _ in range(5):
            status = self.provider.poll(handle.job_id, invocation)
            if status.state in {SUCCEEDED, PARTIAL, "cancelled", "failed"}:
                break
        assert status is not None
        assert status.state == SUCCEEDED
        assert status.ready == status.total == 3


def run_suite_methods(suite_cls: type, *, make_provider: Callable[[], Any] | None = None) -> None:
    """Drive every `test_*` method on a suite class (pytest-friendly entry)."""
    instance = suite_cls()
    if make_provider is not None:
        instance.make_provider = make_provider  # type: ignore[method-assign]
    if hasattr(instance, "setUp"):
        instance.setUp()
    try:
        for name in sorted(dir(instance)):
            if name.startswith("test_") and callable(getattr(instance, name)):
                getattr(instance, name)()
    finally:
        if hasattr(instance, "tearDown"):
            instance.tearDown()


__all__ = [
    "AsyncMultiAssetContractSuite",
    "FakeAsyncMultiAssetProvider",
    "FakeSyncArtifactProvider",
    "FakeSyncDocumentProvider",
    "SyncArtifactContractSuite",
    "SyncDocumentContractSuite",
    "assert_egress_clean",
    "assert_health_shape",
    "assert_manifest_v2",
    "assert_settings_schema",
    "load_provider_modules",
    "run_suite_methods",
]
