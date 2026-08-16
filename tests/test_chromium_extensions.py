"""Step 15.2 — the four ported extensions.

The done-when ("all four load pinned, and both provider hubs report a connected
socket") needs a browser and a human, so it is not what these tests are. What
they cover is the failure the step calls its port blocker: the extensions hardcode
ws://localhost:5050 while Scriptase serves on 5000, and a WebSocket that never
opens is indistinguishable from a provider that is not answering. That bug is
invisible until someone spends an afternoon on it, and entirely visible in the
source, which makes it worth a test rather than a launch.

So: the ids that keep the pins working, the WS routes that have to match the
backend, and the single place a port is allowed to appear.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = ROOT / "tools" / "extensions"
CHROMIUM_PS1 = ROOT / "tools" / "chromium.ps1"

# The ids V2's launcher pinned. They are derived from each manifest's "key" and
# therefore survive being copied here and staged again at launch -- which is the
# entire reason the port could keep them.
PINNED_IDS = {
    "STS-grok-sync": "jdookpoacnpjccbglagkajbodnhfabco",
    "STS-gemini-sync": "madklpolldnjjdglmjjjoekceldfjgkl",
    "STS-devtools-extension": "ildalkidbljlnonbcbfeagfmhgdghaeg",
    "ai-web-auto-extension": "lcdcclkfepemmgooijjalcaadbdeicop",
}

# The line Sync-ScriptaseExtensions rewrites with the real ports. Kept identical
# to the pattern in chromium.ps1 (asserted below) so marker drift fails here
# rather than at launch, where it would just look like a dead socket.
#
# The line-end handling is not decoration. The sources are CRLF, .NET's $ does
# not step over the \r, and Python's read_text() hides that by translating
# newlines -- so this test once passed against a pattern PowerShell could never
# match. It is a lookahead so the replacement cannot swallow the \r. Everything
# here reads with newline="" for the same reason.
MARKER = re.compile(
    r"(?m)^(/\* @scriptase-endpoint \*/ (?:var|export const) STS_ENDPOINT = ).*?;[ \t]*(?=\r?$)"
)

ENDPOINT_FILE = "sts-endpoint.js"


def read(path: Path) -> str:
    """Verbatim, CRLF included -- see MARKER."""
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def extension_id(manifest: dict) -> str:
    """Chromium's id: SHA-256 of the DER key, first 16 bytes, nibbles as a-p."""
    digest = hashlib.sha256(base64.b64decode(manifest["key"])).hexdigest()[:32]
    return "".join(chr(ord("a") + int(nibble, 16)) for nibble in digest)


@pytest.fixture(scope="module")
def ps1() -> str:
    return read(CHROMIUM_PS1)


def manifest_of(name: str) -> dict:
    return json.loads(read(EXTENSIONS / name / "manifest.json"))


def source_files(name: str) -> list[Path]:
    return [
        path
        for path in sorted((EXTENSIONS / name).rglob("*"))
        if path.is_file() and path.suffix in {".js", ".json", ".html", ".css"}
    ]


# --- all four are actually here --------------------------------------------


@pytest.mark.parametrize("name", sorted(PINNED_IDS))
def test_the_extension_is_present_and_loadable(name: str):
    assert (EXTENSIONS / name / "manifest.json").is_file(), f"{name} was not ported"
    assert manifest_of(name)["manifest_version"] == 3


@pytest.mark.parametrize("name", sorted(PINNED_IDS))
def test_the_pinned_id_survived_the_copy(name: str):
    """Without "key" an unpacked extension is identified by its path, so moving
    it out of V2 would change its id and every pin would silently miss."""
    manifest = manifest_of(name)
    assert "key" in manifest, f"{name} has no key -- its id would depend on its path"
    assert extension_id(manifest) == PINNED_IDS[name]


def test_the_launcher_derives_ids_instead_of_transcribing_them(ps1: str):
    """A copied id list is a second source of truth, and a wrong id pins nothing
    while looking like it worked."""
    assert "function Get-ChromiumExtensionId" in ps1
    for name, pinned in PINNED_IDS.items():
        assert pinned not in ps1, f"{name}'s id is hardcoded in chromium.ps1"


# --- the port blocker -------------------------------------------------------


@pytest.mark.parametrize("name", sorted(PINNED_IDS))
def test_only_the_endpoint_file_names_a_port(name: str):
    """V2 spread localhost:5050 across background scripts, content scripts and
    dev notes. One file may name a port; the rest must read it."""
    offenders = []
    for path in source_files(name):
        if path.name == ENDPOINT_FILE:
            continue
        for number, line in enumerate(read(path).splitlines(), 1):
            if re.search(r"(?:localhost|127\.0\.0\.1):\d+", line):
                offenders.append(f"{path.relative_to(EXTENSIONS)}:{number}: {line.strip()}")
    assert not offenders, "hardcoded endpoints outside " + ENDPOINT_FILE + ":\n" + "\n".join(offenders)


@pytest.mark.parametrize("name", sorted(PINNED_IDS))
def test_the_endpoint_file_carries_the_injection_marker(name: str):
    """The marker is what the launcher rewrites. Lose it and the extension keeps
    its default port with nothing to say so."""
    found = [path for path in source_files(name) if path.name == ENDPOINT_FILE]
    assert found, f"{name} has no {ENDPOINT_FILE}"
    for path in found:
        assert MARKER.search(read(path)), (
            f"{path.relative_to(EXTENSIONS)} has no @scriptase-endpoint marker"
        )


def test_the_launcher_rewrites_exactly_that_marker(ps1: str):
    assert MARKER.pattern in ps1, (
        "chromium.ps1 matches a different pattern than the extensions carry"
    )


def test_the_injected_defaults_match_the_committed_ones(ps1: str):
    """Staging on the default port must be a no-op. If the two drift, every
    launch quietly rewrites the extensions into something the sources never say.
    """
    template = re.search(
        r"'(\{\{\"host\":.*?\}\})' -f", ps1
    )
    assert template, "the endpoint config template is missing from chromium.ps1"
    rendered = (
        template.group(1)
        .replace("{{", "{")
        .replace("}}", "}")
        .replace("{0}", "localhost")
        .replace("{1}", "5000")
        .replace("{2}", "5000,5173")
        .replace("{3}", "8765")
    )
    committed = MARKER.search(
        read(EXTENSIONS / "STS-grok-sync" / "src" / ENDPOINT_FILE)
    )
    assert committed is not None
    payload = committed.group(0)[len(committed.group(1)) :].strip().rstrip(";")
    assert json.loads(rendered) == json.loads(payload)


@pytest.mark.parametrize(
    ("name", "loader"),
    [
        ("STS-grok-sync", "importScripts(chrome.runtime.getURL(\"src/sts-endpoint.js\"))"),
        ("STS-gemini-sync", "importScripts(chrome.runtime.getURL('sts-endpoint.js'))"),
        ("STS-devtools-extension", "importScripts(chrome.runtime.getURL('sts-endpoint.js'))"),
        ("ai-web-auto-extension", "from './modules/sts-endpoint.js'"),
    ],
)
def test_the_service_worker_loads_the_endpoint_file(name: str, loader: str):
    """A config nobody reads is worse than a hardcoded one: it looks configured."""
    worker = manifest_of(name)["background"]["service_worker"]
    assert loader in read(EXTENSIONS / name / worker)


@pytest.mark.parametrize("name", ["STS-grok-sync", "STS-gemini-sync"])
def test_the_content_script_gets_the_endpoint_file_first(name: str):
    """Both panels build a URL at parse time, before the background has anything
    to broadcast, so STS_ENDPOINT has to already be in that world."""
    scripts = manifest_of(name)["content_scripts"][0]["js"]
    assert scripts[0].endswith(ENDPOINT_FILE), f"{name} loads {scripts[0]} before its config"
    assert len(scripts) > 1


# --- the sockets have to land somewhere ------------------------------------


@pytest.mark.parametrize(
    ("name", "worker", "module", "attribute"),
    [
        (
            "STS-grok-sync",
            "src/background.js",
            "scriptase.modules.video.ws_runtime",
            "WS_ROUTE",
        ),
        (
            "STS-gemini-sync",
            "background.js",
            "scriptase.modules.image.gemini_ws",
            "WS_ROUTE",
        ),
    ],
)
def test_the_extension_targets_the_route_the_hub_serves(
    name: str, worker: str, module: str, attribute: str
):
    """Right port, wrong path fails exactly as silently as the wrong port."""
    import importlib

    route = getattr(importlib.import_module(module), attribute)
    source = read(EXTENSIONS / name / worker)
    assert route in source, f"{name} does not connect to {route}"


# --- the generated copy stays out of the repo ------------------------------


def test_the_staged_extensions_are_gitignored():
    probe = "data/chromium-extensions/STS-grok-sync/manifest.json"
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", probe],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, f"{probe} is not gitignored -- it is regenerated every launch"


@pytest.mark.parametrize(
    "name",
    ["Get-ChromiumExtensionId", "Get-ScriptaseExtensions", "Sync-ScriptaseExtensions",
     "Set-ChromiumPinnedExtensions"],
)
def test_the_launcher_exposes_the_extension_functions(ps1: str, name: str):
    assert f"function {name}" in ps1


def test_chromium_is_launched_with_the_staged_extensions(ps1: str):
    body = ps1[ps1.index("function Start-BundledChromium") :]
    assert "Sync-ScriptaseExtensions" in body, "the extensions are never staged"
    assert "--load-extension=" in body
    assert "Set-ChromiumPinnedExtensions" in body


def test_staging_fails_loudly_when_the_marker_is_gone(ps1: str):
    """The one outcome worth crashing over: a launch that silently hands the
    browser extensions still pointing at V2's port."""
    body = ps1[ps1.index("function Sync-ScriptaseExtensions") :]
    body = body[: body.index("function Set-ChromiumPinnedExtensions")]
    assert body.count("throw") >= 2


# --- and then actually run it ----------------------------------------------
#
# Everything above reads source. That is enough for drift and not enough for
# correctness: the first two bugs in this step were a guard that fired on every
# default-port launch, and a regex that matched in Python and not in .NET
# because the sources are CRLF. Neither is visible without running the thing,
# and both would have shipped as "the provider is not responding".
#
# PowerShell is not optional on this project -- start.bat, the launcher and the
# Job Object all require it -- so this does not skip.


def stage(tmp_path: Path, port: int) -> Path:
    stage_dir = tmp_path / "stage"
    script = (
        ". ./tools/chromium.ps1; "
        f"Sync-ScriptaseExtensions -AppPort {port} -StageDir '{stage_dir}' | Out-Null"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    return stage_dir


def test_staging_injects_the_port_the_backend_is_actually_on(tmp_path: Path):
    stage_dir = stage(tmp_path, 5099)

    staged = sorted(stage_dir.rglob(ENDPOINT_FILE))
    assert len(staged) == len(PINNED_IDS), f"staged {len(staged)} endpoint files"
    for path in staged:
        match = MARKER.search(read(path))
        assert match, f"{path} lost its marker while being staged"
        config = json.loads(match.group(0)[len(match.group(1)) :].strip().rstrip(";"))
        assert config["appPorts"] == [5099], f"{path.parent.name} still points at {config}"
        assert 5099 in config["uiPorts"]


def test_staging_leaves_no_bom_and_no_hardcoded_port(tmp_path: Path):
    """PowerShell 5.1's -Encoding UTF8 writes a BOM, and a BOM in front of the
    ai-web-auto module service worker stops it loading at all."""
    stage_dir = stage(tmp_path, 5099)
    for path in stage_dir.rglob("*.js"):
        assert not path.open("rb").read().startswith(b"\xef\xbb\xbf"), f"{path} has a BOM"
    assert not [
        path for path in stage_dir.rglob(ENDPOINT_FILE) if "5000" in read(path).splitlines()[-1]
    ]


def test_staging_on_the_default_port_changes_nothing(tmp_path: Path):
    """The committed defaults and the injected ones have to agree, or every
    ordinary launch quietly rewrites the extensions into something the sources
    never said."""
    stage_dir = stage(tmp_path, 5000)
    for path in stage_dir.rglob(ENDPOINT_FILE):
        source = EXTENSIONS / path.relative_to(stage_dir)
        assert read(path) == read(source), f"{source} is rewritten by a default-port launch"


def test_staging_does_not_touch_the_committed_sources(tmp_path: Path):
    before = {path: read(path) for path in EXTENSIONS.rglob(ENDPOINT_FILE)}
    stage(tmp_path, 5099)
    assert {path: read(path) for path in before} == before
