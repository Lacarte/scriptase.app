"""Step 15.4 — the vendored ai-web-auto backend.

The done-when is a launcher behaviour: it starts the server when one is absent,
skips it when one is already listening, and treats its absence as a warning
rather than a reason not to start the app. Two of those three run here against a
real socket. The third -- "absence degrades to a warning" -- is a negative,
which is why this file spends as much time asserting what is *not* in the
launcher (a `Fail`, a `throw`) as what is.

The rest guards the two ways this dependency is genuinely tangled:

  - Three separate things resolve the automation port: the PowerShell that
    injects it into the extensions, the PowerShell that starts the server, and
    the Python that binds the socket. A disagreement is invisible from outside
    -- the extension retries forever and the provider looks unresponsive -- so
    all three are run and compared.
  - The vendored tree is a pinned copy of somebody else's repository. Editing it
    is how re-vendoring turns from an overwrite into a merge, so the boundary is
    asserted rather than described.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import socket
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_DIR = ROOT / "tools" / "automation"
VENDOR = AUTOMATION_DIR / "ai-web-auto"
SERVE_PY = AUTOMATION_DIR / "serve.py"
REQS = AUTOMATION_DIR / "requirements.txt"
VENDOR_REQS = VENDOR / "requirements.txt"
AUTOMATION_PS1 = ROOT / "tools" / "automation.ps1"
LAUNCH_PS1 = ROOT / "tools" / "launch.ps1"
CHROMIUM_PS1 = ROOT / "tools" / "chromium.ps1"

DEFAULT_PORT = 8765


def powershell(script: str, env_port: int | None = None) -> subprocess.CompletedProcess:
    prefix = f"$env:SCRIPTASE_AUTOMATION_PORT = '{env_port}'; " if env_port else ""
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", prefix + script],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def code_only(source: str) -> str:
    """PowerShell with the comments taken out.

    Every "must not contain" assertion below is about what a script does, and
    these scripts explain at length in prose what they must not do -- so
    without this the tests fail on their own documentation. Crude on purpose:
    a `#` inside a string literal would go too, and none of them has one.
    """
    source = re.sub(r"<#.*?#>", "", source, flags=re.S)
    return "\n".join(re.sub(r"#.*$", "", line) for line in source.splitlines())


def function_body(source: str, name: str) -> str:
    """One function out of comment-free PowerShell, up to the next one."""
    body = source[source.index(f"function {name}") :]
    following = body.find("\nfunction ", 1)
    return body if following < 0 else body[:following]


@pytest.fixture(scope="module")
def automation() -> str:
    assert AUTOMATION_PS1.is_file(), "tools/automation.ps1 is missing"
    return code_only(AUTOMATION_PS1.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def launcher() -> str:
    return LAUNCH_PS1.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def serve():
    """serve.py as a module.

    That this import works at all is the point: the launcher's own venv has no
    websockets, so a module-level import of the vendored package would fail
    here -- and would equally fail `--help` on a machine that has not been
    provisioned yet.
    """
    spec = importlib.util.spec_from_file_location("scriptase_awa_serve", SERVE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def occupied_port():
    """A port with a real listener on it, for the reuse path."""
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        yield sock.getsockname()[1]


def free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# --- the vendored tree ------------------------------------------------------


def test_the_backend_is_vendored():
    assert (VENDOR / "ai_web_auto_backend" / "core" / "server.py").is_file()
    assert (VENDOR / "ai_web_auto_backend" / "__init__.py").is_file()
    assert VENDOR_REQS.is_file()


def test_the_vendoring_is_pinned_to_a_revision():
    """A copy without a revision is a fork nobody can re-sync."""
    vendor_md = (VENDOR / "VENDOR.md").read_text(encoding="utf-8")
    assert re.search(r"\b[0-9a-f]{40}\b", vendor_md), "VENDOR.md records no upstream revision"


def test_the_upstream_workspace_did_not_come_with_it():
    """1.3 GB of venv, a nested .git, and a second copy of an extension that was
    already ported in 15.2 -- the second copy being the one that matters, since
    the browser would load whichever the launcher staged and nobody would know
    which one they had edited."""
    tracked = subprocess.run(
        # --others so this fails in the commit that vendors the tree rather than
        # in the one after it.
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "tools/automation"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    ).stdout.split()
    assert tracked, "nothing under tools/automation is tracked"
    for path in tracked:
        assert "/venv/" not in path, path
        assert "__pycache__" not in path, path
        assert "ai-web-auto-extension" not in path, f"{path} duplicates the 15.2 extension"


def test_the_automation_venv_is_gitignored():
    probe = "tools/automation/ai-web-auto/venv/Scripts/python.exe"
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", probe],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, f"{probe} is not gitignored"


def test_nothing_scriptase_specific_leaked_into_the_vendored_code():
    """The boundary that keeps re-vendoring an overwrite instead of a merge.
    Everything of ours lives one level up: serve.py, requirements.txt,
    ../../automation.ps1."""
    offenders = [
        path.relative_to(VENDOR).as_posix()
        for path in sorted(VENDOR.rglob("*.py"))
        if re.search(r"scriptase", path.read_text(encoding="utf-8"), re.IGNORECASE)
    ]
    assert not offenders, "edited vendored files: " + ", ".join(offenders)


# --- what the launcher installs --------------------------------------------


def requirement_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_the_installed_set_is_a_subset_of_upstreams_with_upstreams_bounds():
    """Provisioning the transport subset is a deliberate call -- anthropic and
    opencv are 400 MB charged to every start.bat for code nothing calls yet.
    Rewriting a *bound* would not be: it would run the vendored code against a
    version upstream never claimed to support."""
    upstream = set(requirement_lines(VENDOR_REQS))
    for line in requirement_lines(REQS):
        assert line in upstream, f"{line!r} is not what ai-web-auto/requirements.txt pins"


def third_party_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names.add(node.module.split(".")[0])
    return {name for name in names if name not in sys.stdlib_module_names}


def test_the_installed_set_covers_everything_the_server_imports():
    """serve.py reaches core/ and core/ alone. If a re-vendor adds an import
    there, the subset stops being enough -- and the failure would be an
    ImportError at launch, warned past, leaving a socket nobody notices is
    missing."""
    needed: set[str] = set()
    for path in sorted((VENDOR / "ai_web_auto_backend" / "core").glob("*.py")):
        needed |= third_party_imports(path)
    installed = {re.split(r"[<>=!~]", line)[0].strip() for line in requirement_lines(REQS)}
    assert needed <= installed, f"core/ imports {sorted(needed - installed)}, which is not installed"


# --- serve.py ---------------------------------------------------------------


def test_the_entry_point_is_not_the_upstream_repl():
    """Upstream's automation_controller blocks on input(). As a launcher child
    sharing the console it would swallow the keystrokes meant for the
    launcher, after first waiting two minutes for an extension."""
    source = SERVE_PY.read_text(encoding="utf-8")
    body = source[source.index("from __future__") :]
    assert "input(" not in body
    assert "stdin" not in body
    assert "automation_controller" not in body


def test_the_socket_stays_on_loopback(serve):
    """This server drives a browser holding live Google and Grok sessions:
    anything that can reach it can act as the user."""
    assert serve.HOST in {"localhost", "127.0.0.1"}
    assert "0.0.0.0" not in SERVE_PY.read_text(encoding="utf-8")


def test_the_default_port_is_the_one_the_extension_dials(serve):
    endpoint = (
        ROOT / "tools" / "extensions" / "ai-web-auto-extension" / "js" / "modules" / "sts-endpoint.js"
    ).read_text(encoding="utf-8")
    config = json.loads(re.search(r"STS_ENDPOINT = (\{.*?\});", endpoint).group(1))
    assert serve.DEFAULT_PORT == config["automationPort"] == DEFAULT_PORT


@pytest.mark.parametrize(
    ("environ", "expected"),
    [({}, DEFAULT_PORT), ({"SCRIPTASE_AUTOMATION_PORT": " 8799 "}, 8799)],
)
def test_the_port_comes_from_the_environment(serve, environ, expected):
    assert serve.resolve_port(environ) == expected


@pytest.mark.parametrize("value", ["nonsense", "0", "70000"])
def test_a_malformed_port_is_refused_rather_than_ignored(serve, value):
    """Falling back to 8765 when someone asked for something else is the exact
    mismatch this variable exists to prevent."""
    with pytest.raises(SystemExit):
        serve.resolve_port({"SCRIPTASE_AUTOMATION_PORT": value})


# --- the three readings of one port -----------------------------------------


def injected_automation_port(tmp_path: Path, env_port: int | None) -> int:
    stage_dir = tmp_path / "stage"
    result = powershell(
        ". ./tools/chromium.ps1; "
        f"Sync-ScriptaseExtensions -StageDir '{stage_dir}' | Out-Null",
        env_port=env_port,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    staged = stage_dir / "ai-web-auto-extension" / "js" / "modules" / "sts-endpoint.js"
    config = json.loads(
        re.search(r"STS_ENDPOINT = (\{.*?\});", staged.read_text(encoding="utf-8")).group(1)
    )
    return config["automationPort"]


@pytest.mark.parametrize("env_port", [None, 8799])
def test_all_three_readings_of_the_port_agree(serve, tmp_path: Path, env_port):
    """chromium.ps1 injects it, automation.ps1 binds it, serve.py listens on it.
    They deliberately do not share an implementation -- one is in another
    language and one cannot dot-source the other without clobbering its
    -Reinstall switch -- so this is what holds them together."""
    expected = env_port or DEFAULT_PORT

    result = powershell(". ./tools/automation.ps1; Get-ScriptaseAutomationPort", env_port=env_port)
    assert result.returncode == 0, result.stdout + result.stderr
    assert int(result.stdout.strip()) == expected

    assert serve.resolve_port(
        {"SCRIPTASE_AUTOMATION_PORT": str(env_port)} if env_port else {}
    ) == expected
    assert injected_automation_port(tmp_path, env_port) == expected


# --- no dot-sourced module may clobber the launcher -------------------------


def param_names(path: Path) -> set[str]:
    result = powershell(
        "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
        f"'{path}', [ref]$null, [ref]$null); "
        "$ast.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath }"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return set(result.stdout.split())


@pytest.mark.parametrize("module", [AUTOMATION_PS1, CHROMIUM_PS1])
def test_a_dot_sourced_module_declares_no_parameter_the_launcher_declares(module: Path):
    """Dot-sourcing runs a param block in the caller's scope. A second
    -Reinstall would reset the launcher's to $false on the way past, and every
    dependency stamp would go on looking current for the rest of the run."""
    clash = param_names(module) & param_names(LAUNCH_PS1)
    assert not clash, f"{module.name} would overwrite the launcher's {sorted(clash)}"


# --- automation.ps1 ---------------------------------------------------------


def test_the_script_parses():
    result = powershell(
        "$errors = $null; "
        "[void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{AUTOMATION_PS1}', [ref]$null, [ref]$errors); "
        "if ($errors) { $errors | ForEach-Object { $_.ToString() }; exit 1 }"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_dot_sourcing_it_serves_nothing_and_exposes_the_functions():
    called = ["Get-ScriptaseAutomationPort", "Test-AutomationServer",
              "Initialize-AutomationVenv", "Start-AutomationServer"]
    result = powershell(
        ". ./tools/automation.ps1; "
        + "; ".join(
            f"if (-not (Get-Command {name} -EA SilentlyContinue)) {{ throw '{name}' }}"
            for name in called
        )
        + "; 'loaded'"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "loaded" in result.stdout


def test_an_occupied_port_reads_as_occupied(occupied_port: int):
    result = powershell(f". ./tools/automation.ps1; Test-AutomationServer -Port {occupied_port}")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_a_free_port_reads_as_free():
    result = powershell(f". ./tools/automation.ps1; Test-AutomationServer -Port {free_port()}")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_the_port_check_never_opens_a_connection(automation: str):
    """A TcpClient or a curl leaves the server reading an HTTP upgrade that
    never arrives, and it answers with a three-frame traceback in the console.
    V2 hit this and left a note beside its netstat call. Get-NetTCPConnection
    reads the kernel's table and touches nothing."""
    body = function_body(automation, "Test-AutomationServer")
    assert "Get-NetTCPConnection" in body
    for probe in ("TcpClient", "Invoke-WebRequest", "Invoke-RestMethod", "curl"):
        assert probe not in body, f"{probe} would poke the socket it is checking"


def test_a_server_that_is_already_listening_is_reused(occupied_port: int):
    """The done-when's "skips it when already listening". A second server on the
    same port cannot bind, and killing the first would take out whatever session
    it is holding."""
    result = powershell(
        ". ./tools/automation.ps1; "
        f"$p = Start-AutomationServer -Port {occupied_port}; "
        "if ($p) { 'started' } else { 'none' }"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "reusing" in result.stdout
    assert "none" in result.stdout, "it started a second server on an occupied port"


def test_an_absent_server_is_started_or_warned_about():
    """The done-when's other two branches, and which one is taken depends on
    whether this machine has provisioned the venv -- so both are asserted and
    neither is skipped. The interesting one for a developer is the first; the
    interesting one for a clean checkout is the second, since a launcher that
    stopped there would be trading a whole app for a WebSocket relay."""
    result = powershell(
        ". ./tools/automation.ps1; "
        f"$p = Start-AutomationServer -Port {free_port()}; "
        "if (-not $p) { 'none' } elseif ($p.HasExited) { 'exited' } "
        "else { 'serving'; $p.Kill() }"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if (VENDOR / "venv" / ".requirements.sha256").is_file():
        assert "serving" in result.stdout, result.stdout
    else:
        assert "none" in result.stdout and "not provisioned" in result.stdout, result.stdout


def test_the_entry_point_runs_without_the_vendored_dependencies():
    """--help on an unprovisioned checkout has to say something useful, which is
    why serve.py imports the package inside a function. Run with the app's own
    interpreter, which has no websockets."""
    result = subprocess.run(
        [sys.executable, str(SERVE_PY), "--help"], capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--port" in result.stdout


def test_the_reuse_check_happens_before_anything_is_spawned(automation: str):
    body = function_body(automation, "Start-AutomationServer")
    assert body.index("Test-AutomationServer") < body.index("Process]::Start")


def test_starting_it_is_warn_only(automation: str):
    """It runs between a healthy backend and the browser, inside the try whose
    finally kills every child, so an exception here would tear down a working
    app over a socket most runs never touch."""
    body = function_body(automation, "Start-AutomationServer")
    assert "catch" in body and "Write-Warn" in body
    assert "throw" not in body
    assert "Fail " not in body


def test_provisioning_is_warn_only(automation: str):
    body = function_body(automation, "Initialize-AutomationVenv")
    assert "throw" not in body
    assert "Fail " not in body
    assert body.count("Write-Warn") >= 3


def test_provisioning_is_stamped(automation: str):
    """Same contract as the app's own dependency sync: the second run is a
    no-op. Without it every launch pays a pip resolve."""
    assert "Get-FileHash" in automation
    assert "AutomationStamp" in automation


def test_the_venv_is_separate_from_the_apps():
    """Merging them would let a browser-automation project constrain the version
    of pydantic the backend runs on."""
    result = powershell(
        ". ./tools/automation.ps1; (Get-AutomationPaths).Venv; (Get-AutomationPaths).Reqs"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    venv, reqs = [Path(line.strip()) for line in result.stdout.strip().splitlines()]
    assert venv == VENDOR / "venv", venv
    assert venv != ROOT / "venv"
    assert reqs == REQS, reqs


# --- the launcher -----------------------------------------------------------


def main_block(source: str) -> str:
    return source[source.index("$job = New-KillOnCloseJob") :]


def test_it_starts_after_the_backend_and_before_the_browser(launcher: str):
    """The extension dials this socket as its service worker loads, which is the
    same reason Flask comes before Chromium."""
    body = main_block(launcher)
    assert body.index("Wait-ForHealth") < body.index("Start-AutomationServer")
    assert body.index("Start-AutomationServer") < body.index("Start-ChromiumOrWarn")


def test_it_is_a_job_member(launcher: str):
    """Unlike Chromium, it holds a port and no session worth preserving, so it
    should go when the window does."""
    line = next(
        line for line in main_block(launcher).splitlines() if "Start-AutomationServer" in line
    )
    assert "-Job $job" in line, line


def test_a_missing_automation_server_does_not_stop_the_launcher(launcher: str):
    body = main_block(launcher)
    start = body.index("--- 2. ai-web-auto")
    section = body[start : body.index("--- 3. Chromium")]
    assert "Fail" not in section
    assert "exit 1" not in section


def test_the_venv_is_provisioned_before_setup_mode_returns(launcher: str):
    """start.bat -Mode setup is the "install everything, launch nothing" door;
    leaving this out would make the first real launch the one that pays."""
    assert launcher.index("Initialize-AutomationVenv") < launcher.index("if ($Mode -eq 'setup')")


def test_the_opt_out_covers_both_the_venv_and_the_server(launcher: str):
    assert "[switch]$NoAutomation" in launcher
    assert launcher.count("if (-not $NoAutomation)") == 2


def test_the_launcher_delegates_to_the_automation_module(launcher: str):
    """One place knows how to start it. A second command line here would drift
    from the venv, the port and the entry point."""
    assert ". (Join-Path $PSScriptRoot 'automation.ps1')" in launcher
    for reimplementation in ("serve.py", "ai_web_auto_backend", "8765"):
        assert reimplementation not in launcher
