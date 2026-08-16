"""Step 15.3 — launcher sequencing.

The done-when needs a human at a screen: start.bat yields a Chromium window with
the app and the provider tabs in it, and killing Chromium's ability to start
still leaves a working app in the default browser. What is worth automating is
everything about that which fails silently.

Three things, specifically:

  - The order. Flask, then Chromium, then Vite is not a preference. The
    extensions dial the backend WebSocket as they load, and reordering costs a
    round of failed reconnects that presents as "the provider is not responding".
  - Which failures are fatal. Chromium is two of ~thirty providers; Vite in dev
    mode is the entire UI. Getting that backwards turns an unreachable GitHub
    releases API into an app that will not start.
  - CDP itself. Chrome has refused GET on /json/new since 111, and V2's launcher
    still uses GET behind `curl -s -o nul`, so its pipeline tab silently stopped
    opening at some point and nobody noticed. That one is only visible by
    actually speaking the protocol, so the last section does.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCH_PS1 = ROOT / "tools" / "launch.ps1"
CHROMIUM_PS1 = ROOT / "tools" / "chromium.ps1"


@pytest.fixture(scope="module")
def launcher() -> str:
    assert LAUNCH_PS1.is_file(), "tools/launch.ps1 is missing"
    return LAUNCH_PS1.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def chromium() -> str:
    return CHROMIUM_PS1.read_text(encoding="utf-8")


def main_block(source: str) -> str:
    """Everything from the launch sequence down, so the docstring at the top of
    the file cannot satisfy an ordering assertion by describing it."""
    return source[source.index("$job = New-KillOnCloseJob") :]


# --- the order --------------------------------------------------------------


def test_flask_starts_before_chromium_which_starts_before_vite(launcher: str):
    body = main_block(launcher)
    flask = body.index("Wait-ForHealth")
    browser = body.index("Start-ChromiumOrWarn")
    vite = body.index("npm run dev")
    assert flask < browser < vite, "the launch order is Flask, Chromium, Vite"


def test_the_app_tab_is_opened_only_once_vite_is_serving(launcher: str):
    """In dev the app URL is Vite's, and it does not exist until Vite answers.
    Opening the tab earlier lands on a connection error."""
    body = main_block(launcher)
    assert body.index("Wait-ForPort") < body.index("Open-ChromiumTab -Url $appUrl")


# --- what is fatal and what is not ------------------------------------------


def test_a_chromium_failure_is_a_warning(launcher: str):
    helper = launcher[launcher.index("function Start-ChromiumOrWarn") :]
    helper = helper[: helper.index("# ------")]
    assert "catch" in helper
    assert "Write-Warn" in helper
    assert "Fail " not in helper, "a browser failure must not stop the launcher"
    assert "exit 1" not in helper


def test_a_vite_failure_is_still_fatal(launcher: str):
    """Wait-ForPort calls Fail, and the launcher must keep using it for Vite:
    in dev mode there is no UI to degrade to."""
    assert "Fail " in launcher[launcher.index("function Wait-ForPort") :][:900]
    assert "Wait-ForPort -Port $vitePort -Process $vite" in launcher


def test_the_app_tab_call_cannot_throw_past_the_launcher(launcher: str, chromium: str):
    """Step 4 is inside the try whose finally terminates the job, so an
    exception out of Open-ChromiumTab would tear down a fully working app after
    everything came up."""
    body = chromium[chromium.index("function Open-ChromiumTab") :]
    assert "throw" not in body
    assert "return $false" in body


# --- the browser outlives the launcher --------------------------------------


def test_chromium_is_not_a_job_member(launcher: str):
    """Flask and Vite die with this window because a leftover one holds a port.
    The browser is the opposite: it holds the Google and Grok sessions, and
    reusing a running one in about a second is only possible if it survives."""
    for line in main_block(launcher).splitlines():
        if "Start-JobChild" in line:
            assert "app.py" in line or "npm run dev" in line, f"Chromium in the job: {line.strip()}"


def test_the_launcher_delegates_to_the_chromium_module(launcher: str):
    """One place knows how to start a browser. A second launch line here would
    drift from the profile, the extensions and the debug port."""
    assert ". (Join-Path $PSScriptRoot 'chromium.ps1')" in launcher
    for reimplementation in ("chrome.exe", "--remote-debugging-port", "--load-extension"):
        assert reimplementation not in launcher


def test_the_default_browser_is_the_fallback_not_the_default(launcher: str):
    body = main_block(launcher)
    assert "if ($chromiumReady) {" in body
    assert re.search(r"elseif \(-not \$NoBrowser\) \{\s*Start-Process \$appUrl", body), (
        "a failed Chromium must still leave the app open in the default browser"
    )


def test_both_opt_outs_exist(launcher: str):
    assert "[switch]$NoChromium" in launcher
    assert "-not $NoBrowser -and -not $NoChromium" in launcher


# --- the provider tabs ------------------------------------------------------


def test_the_provider_tabs_are_passed_to_the_browser(launcher: str):
    assert "Start-ChromiumOrWarn -Url (Get-ChromiumProviderTabs)" in main_block(launcher)


def test_a_reused_browser_still_gets_the_provider_tabs(launcher: str):
    """Start-BundledChromium returns $null when it reused a running browser --
    that browser started before this run and never saw the URLs."""
    helper = launcher[launcher.index("function Start-ChromiumOrWarn") :]
    assert "if (-not $browser)" in helper
    assert "foreach ($tab in $Url) { Open-ChromiumTab" in helper


# --- and then actually run it -----------------------------------------------
#
# PowerShell is not optional on this project -- start.bat, the launcher and the
# Job Object all require it -- so none of this skips.


def powershell(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


@pytest.mark.parametrize("path", [LAUNCH_PS1, CHROMIUM_PS1])
def test_the_script_parses(path: Path):
    """The launcher cannot be run from a test, so at minimum it must not be
    syntactically broken -- a missing brace here is discovered by a human whose
    app will not start."""
    result = powershell(
        "$errors = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$null, [ref]$errors); "
        "if ($errors) { $errors | ForEach-Object { $_.ToString() }; exit 1 }"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_launcher_dot_source_loads_what_the_launcher_calls(launcher: str):
    """Dot-sourced exactly the way launch.ps1 does it, because that form is what
    has to keep returning before chromium.ps1 launches anything -- and because a
    rename on either side is otherwise found by a human whose app will not start.
    """
    called = sorted(set(re.findall(r"\b((?:Start|Open|Get)-(?:Chromium|Bundled)\w*)", launcher)))
    called = [name for name in called if name != "Start-ChromiumOrWarn"]
    assert "Open-ChromiumTab" in called and "Start-BundledChromium" in called

    result = powershell(
        "$PSScriptRoot = (Resolve-Path ./tools).Path; "
        ". (Join-Path $PSScriptRoot 'chromium.ps1'); "
        + "; ".join(f"if (-not (Get-Command {name} -EA SilentlyContinue)) {{ throw '{name}' }}" for name in called)
        + "; 'loaded'"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "loaded" in result.stdout


def test_the_provider_tab_defaults_are_the_pages_the_extensions_drive():
    result = powershell(". ./tools/chromium.ps1; Get-ChromiumProviderTabs")
    assert result.returncode == 0, result.stderr
    tabs = result.stdout.split()
    assert any("grok.com" in tab for tab in tabs), tabs
    assert any("gemini.google.com" in tab for tab in tabs), tabs


def test_a_provider_tab_can_be_turned_off():
    """An empty value cannot mean this: Windows deletes an environment variable
    that is set to the empty string, so .env has no way to express it."""
    result = powershell(
        "$env:SCRIPTASE_TAB_GROK = 'off'; . ./tools/chromium.ps1; Get-ChromiumProviderTabs"
    )
    assert result.returncode == 0, result.stderr
    assert "grok.com" not in result.stdout
    assert "gemini.google.com" in result.stdout


class FakeCdp(BaseHTTPRequestHandler):
    """Just enough of the DevTools HTTP endpoint to catch the verb bug."""

    def log_message(self, *args):  # noqa: D102 - silence the default stderr log
        pass

    def _reply(self, code: int, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.server.seen.append(("GET", self.path))
        if self.path.startswith("/json/version"):
            return self._reply(200, {"Browser": "HeadlessFake"})
        if self.path.startswith("/json/list"):
            return self._reply(200, self.server.targets)
        if self.path.startswith("/json/new"):
            if self.server.put_refused:
                return self._reply(200, {"id": "fallback"})
            # What every Chrome since 111 answers.
            return self._reply(
                405, {"error": "Using unsafe HTTP verb GET to invoke /json/new."}
            )
        return self._reply(404, {})

    def do_PUT(self):
        self.server.seen.append(("PUT", self.path))
        if self.path.startswith("/json/new"):
            if self.server.put_refused:
                return self._reply(405, {})
            return self._reply(200, {"id": "new"})
        return self._reply(404, {})


@pytest.fixture
def cdp():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeCdp)
    server.seen = []
    server.targets = []
    server.put_refused = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def open_tab(port: int, url: str) -> subprocess.CompletedProcess:
    return powershell(
        f". ./tools/chromium.ps1; "
        f"if (Open-ChromiumTab -Url '{url}' -Port {port}) {{ 'opened' }} else {{ 'failed' }}"
    )


def test_a_new_tab_is_requested_with_put(cdp):
    """The bug this whole test section exists for."""
    result = open_tab(cdp.server_port, "http://localhost:5173/")
    assert "opened" in result.stdout, result.stdout + result.stderr
    assert ("PUT", "/json/new?http://localhost:5173/") in cdp.seen, cdp.seen
    assert not [entry for entry in cdp.seen if entry == ("GET", "/json/new")]


def test_an_older_build_still_gets_its_tab(cdp):
    cdp.put_refused = True
    result = open_tab(cdp.server_port, "http://localhost:5173/")
    assert "opened" in result.stdout, result.stdout + result.stderr
    assert [method for method, path in cdp.seen if path.startswith("/json/new")] == ["PUT", "GET"]


def test_the_url_is_not_percent_encoded(cdp):
    """/json/new?{url} takes the query string verbatim; encoding it opens a tab
    on a literally-encoded address."""
    url = "https://gemini.google.com/u/0/app?pageId=none"
    open_tab(cdp.server_port, url)
    assert ("PUT", f"/json/new?{url}") in cdp.seen, cdp.seen


def test_an_already_open_origin_is_not_duplicated(cdp):
    """Relaunching all day must not stack tabs, and the app being open on
    /editor is the app being open."""
    cdp.targets = [{"type": "page", "url": "http://localhost:5173/editor"}]
    result = open_tab(cdp.server_port, "http://localhost:5173/")
    assert "opened" in result.stdout, result.stdout + result.stderr
    assert not [entry for entry in cdp.seen if entry[1].startswith("/json/new")], cdp.seen


def test_a_page_on_another_origin_is_not_mistaken_for_the_app(cdp):
    cdp.targets = [{"type": "page", "url": "https://grok.com/imagine"}]
    open_tab(cdp.server_port, "http://localhost:5173/")
    assert [entry for entry in cdp.seen if entry[1].startswith("/json/new")], cdp.seen


def test_a_dead_browser_reports_failure_rather_than_throwing(cdp):
    """This runs after the app is up, inside the try whose finally kills every
    child. A raised exception here would take the working app down with it."""
    port = cdp.server_port
    cdp.shutdown()
    result = open_tab(port, "http://localhost:5173/")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "failed" in result.stdout, result.stdout
