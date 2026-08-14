"""The provider-boundary fixture layer — step 11.4 creates it, 13.x–15.x fill it.

contracts.md §46.2 adds a second fixture layer beside the existing port fixtures
(`scriptase/engine/fixtures/`, frozen by step 2.5). Port fixtures describe what
flows *between* nodes; these describe what crosses the *provider* boundary:

    tests/fixtures/providers/<domain>/<provider_id>/
        request.json          the frozen §32 domain request
        raw_response.json     recorded provider payload, sanitized at record time
        expected_result.json  the §31 ProviderResult the adapter must produce

Two validators run over them, and they are deliberately different (§46.4 rule 2):

  * `validate_sanitation()` covers all three files. It is the *record-time*
    rule — no credentials, no absolute paths, no wall-clock timestamps, no
    account identifiers — so a fixture is safe to commit.
  * `results.validate_egress()` covers `expected_result.json` only. It is the
    stricter §36 rule, and it must **not** run over `raw_response.json`: a
    recorded Storyboard or Animator response needs its synthetic remote URL in
    order to exercise the code that removes it before egress.

Media bytes are never re-recorded. A fixture that needs media points into
`scriptase/engine/fixtures/media/`, so the repo keeps one copy of every byte.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from config import ROOT_DIR
from scriptase.providers.results import validate_egress


FIXTURE_SCHEMA_VERSION = 1
PROVIDER_FIXTURES_DIR = os.path.join(ROOT_DIR, "tests", "fixtures", "providers")
MANIFEST_NAME = "manifest.json"
GENERATOR_NAME = "generate.py"

FIXTURE_FILES = ("request.json", "raw_response.json", "expected_result.json")
EGRESS_CHECKED = ("expected_result.json",)

# Media refs must point into the port-fixture media directory (§46.2).
MEDIA_ROOT = "media/"
# The browser-visible prefix under which every managed artifact is served.
MANAGED_URL_PREFIX = "/output/"

_ABSOLUTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|//[^/]|/(?!/))")
# Real-looking credentials. Fixtures use obvious placeholders instead.
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(?:sk-[A-Za-z0-9_-]{8,}|bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|[A-Za-z0-9_-]{32,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})\b"
)
# A wall-clock timestamp makes a fixture non-reproducible; the frozen sample
# instant is the one value allowed.
FROZEN_TIMESTAMP_PREFIX = "2026-01-01T00:00:00"
_TIMESTAMP_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
# Account identifiers observed in the archived recordings.
_ACCOUNT_RE = re.compile(r"(?i)\b(?:account|customer|tenant|org)[_-]?id\b")


def fixture_root(root: str | None = None) -> str:
    return os.path.abspath(root or PROVIDER_FIXTURES_DIR)


def fixture_dir(domain: str, provider_id: str, *, root: str | None = None) -> str:
    return os.path.join(fixture_root(root), domain, provider_id)


def load_fixture(domain: str, provider_id: str, name: str, *, root: str | None = None) -> Any:
    """Read one fixture file. Raises `FileNotFoundError` when it is absent."""
    path = os.path.join(fixture_dir(domain, provider_id, root=root), name)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def list_boundaries(root: str | None = None) -> list[tuple[str, str]]:
    """Every recorded `(domain, provider_id)` pair, in a stable order."""
    base = fixture_root(root)
    found: list[tuple[str, str]] = []
    if not os.path.isdir(base):
        return found
    for domain in sorted(os.listdir(base)):
        domain_dir = os.path.join(base, domain)
        if not os.path.isdir(domain_dir) or domain.startswith((".", "_")):
            continue
        for provider_id in sorted(os.listdir(domain_dir)):
            if os.path.isdir(os.path.join(domain_dir, provider_id)):
                found.append((domain, provider_id))
    return found


# -- sanitation (contracts.md §46.4 rule 2) ---------------------------------


def validate_sanitation(value: Any, *, path: str = "", _depth: int = 0) -> list[str]:
    """Record-time rules, applied to all three fixture files.

    Deliberately *weaker* than `validate_egress`: a raw response may legitimately
    carry a synthetic remote URL and provider-specific keys.
    """
    problems: list[str] = []
    if _depth > 16:
        return [f"{path or '<root>'}: nesting is too deep"]

    if isinstance(value, dict):
        for key, child in value.items():
            where = f"{path}.{key}" if path else str(key)
            if _ACCOUNT_RE.search(str(key)):
                problems.append(f"{where}: account identifier must not be recorded")
            problems.extend(validate_sanitation(child, path=where, _depth=_depth + 1))
        return problems

    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            problems.extend(
                validate_sanitation(child, path=f"{path}[{index}]", _depth=_depth + 1)
            )
        return problems

    if isinstance(value, str):
        text = value.strip()
        # `/output/...` is a managed browser URL relative to OUTPUT_DIR, not an
        # arbitrary filesystem path. It is exactly what the persisted manifests
        # contain and what the legacy adapters must convert into a ref, so a
        # recording may keep it. `validate_egress` still rejects it, and only
        # ever runs over the envelope.
        if _ABSOLUTE_PATH_RE.match(text) and not text.startswith(MANAGED_URL_PREFIX):
            return [f"{path or '<root>'}: absolute path must not be recorded"]
        if _SECRET_VALUE_RE.search(text):
            return [f"{path or '<root>'}: credential-shaped value must not be recorded"]
        match = _TIMESTAMP_RE.search(text)
        if match and not text.startswith(FROZEN_TIMESTAMP_PREFIX):
            return [
                f"{path or '<root>'}: wall-clock timestamp {match.group(0)!r}; "
                f"use {FROZEN_TIMESTAMP_PREFIX}Z"
            ]
        return problems

    return problems


# -- manifest hashing (contracts.md §46.4 rule 4) ---------------------------


def _tracked_files(base: str) -> list[str]:
    tracked: list[str] = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            # `.bak` is the rotation `safe_json_write` leaves behind; it is
            # regenerated state, not a fixture.
            if name in {MANIFEST_NAME, GENERATOR_NAME} or name.endswith(".bak"):
                continue
            relative = os.path.relpath(os.path.join(root, name), base)
            tracked.append(relative.replace("\\", "/"))
    return sorted(tracked)


def build_manifest(root: str | None = None) -> dict:
    """The manifest-with-SHA-256 that freezes the fixture set (§46.4 rule 4)."""
    base = fixture_root(root)
    files = {}
    for relative in _tracked_files(base):
        data = open(os.path.join(base, relative), "rb").read()
        files[relative] = {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    return {"fixture_schema_version": FIXTURE_SCHEMA_VERSION, "files": files}


def write_manifest(root: str | None = None) -> str:
    """Regenerate `manifest.json`. Editing a fixture without this fails a test."""
    from scriptase.shared.io_utils import safe_json_write

    base = fixture_root(root)
    path = os.path.join(base, MANIFEST_NAME)
    safe_json_write(path, build_manifest(base), indent=2)
    return path


def validate_fixtures(root: str | None = None) -> list[str]:
    """Validate the committed provider fixtures. Empty list == contract holds."""
    base = fixture_root(root)
    problems: list[str] = []
    if not os.path.isdir(base):
        return [f"{base} does not exist"]

    manifest_path = os.path.join(base, MANIFEST_NAME)
    if not os.path.isfile(manifest_path):
        return [f"{MANIFEST_NAME} is missing — run tests/fixtures/providers/generate.py"]
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("fixture_schema_version") != FIXTURE_SCHEMA_VERSION:
        problems.append("manifest fixture_schema_version mismatch")

    listed = manifest.get("files") or {}
    on_disk = set(_tracked_files(base))
    for missing in sorted(set(listed) - on_disk):
        problems.append(f"manifest lists a missing fixture: {missing}")
    for unlisted in sorted(on_disk - set(listed)):
        problems.append(f"fixture file not recorded in the manifest: {unlisted}")
    for relative, entry in sorted(listed.items()):
        path = os.path.join(base, relative)
        if not os.path.isfile(path):
            continue
        data = open(path, "rb").read()
        if len(data) != entry.get("bytes"):
            problems.append(f"{relative}: byte size differs from the manifest")
        if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            problems.append(f"{relative}: SHA-256 differs from the manifest")
    if problems:
        return problems

    for domain, provider_id in list_boundaries(base):
        directory = fixture_dir(domain, provider_id, root=base)
        for name in FIXTURE_FILES:
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                problems.append(f"{domain}/{provider_id}: {name} is missing")
                continue
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            label = f"{domain}/{provider_id}/{name}"
            problems.extend(f"{label}: {item}" for item in validate_sanitation(payload))
            if name in EGRESS_CHECKED:
                problems.extend(f"{label}: {item}" for item in validate_egress(payload))
                problems.extend(
                    f"{label}: {item}" for item in _validate_expected_result(payload)
                )
    return problems


def _validate_expected_result(payload: Any) -> list[str]:
    """`expected_result.json` must be a §31 envelope, not an arbitrary blob."""
    if not isinstance(payload, dict):
        return ["expected result is not an object"]
    problems = []
    if payload.get("result_version") != 1:
        problems.append("expected result must declare result_version 1")
    for required in ("domain", "provider_id", "status", "payload", "artifact_refs"):
        if required not in payload:
            problems.append(f"expected result is missing {required!r}")
    for ref in payload.get("artifact_refs") or []:
        if isinstance(ref, str) and ref.startswith(MEDIA_ROOT):
            media = os.path.join(
                ROOT_DIR, "scriptase", "engine", "fixtures", ref
            )
            if not os.path.isfile(media):
                problems.append(f"media ref does not exist in the port fixtures: {ref}")
    return problems


__all__ = [
    "EGRESS_CHECKED",
    "FIXTURE_FILES",
    "FIXTURE_SCHEMA_VERSION",
    "FROZEN_TIMESTAMP_PREFIX",
    "PROVIDER_FIXTURES_DIR",
    "build_manifest",
    "fixture_dir",
    "fixture_root",
    "list_boundaries",
    "load_fixture",
    "validate_fixtures",
    "validate_sanitation",
    "write_manifest",
]
