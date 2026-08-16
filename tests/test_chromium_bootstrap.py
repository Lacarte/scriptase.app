"""Step 15.1 — the bundled Chromium bootstrap.

The module itself is PowerShell, and the headless loop can run pytest but not
PowerShell, so these are assertions about the text. That sounds weak until you
look at what actually goes wrong here: someone vendors the archive back into
git, someone pins a version, or someone adds a "clear the profile" convenience
that silently signs a human out of Google and Grok. All three are visible in the
source, and all three are expensive to discover by running the thing.

The launch path is verified by a human, per the step's definition of done: a
clean checkout downloads and launches Chromium once, and later launches reuse it
in about a second.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools" / "chromium.ps1"


@pytest.fixture(scope="module")
def source() -> str:
    assert MODULE.is_file(), "tools/chromium.ps1 is missing"
    return MODULE.read_text(encoding="utf-8")


# --- the archive is fetched, never carried ---------------------------------


def test_chromium_is_downloaded_from_the_releases_api(source: str):
    """V2 vendored a 183 MB zip. The whole point of this step is not doing that."""
    assert "api.github.com/repos/ungoogled-software/ungoogled-chromium-windows/releases" in source
    assert "Invoke-WebRequest" in source, "nothing actually downloads the archive"


def test_no_chromium_archive_is_tracked_in_git():
    tracked = subprocess.run(
        ["git", "ls-files", "--", "*.zip", "bin/**", "data/**"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert tracked.returncode == 0, tracked.stderr
    offenders = [
        line
        for line in tracked.stdout.splitlines()
        if line.strip() and Path(line).name != ".gitkeep"
    ]
    assert not offenders, f"binaries or profile data are in version control: {offenders}"


def test_no_chromium_version_is_pinned(source: str):
    """A hardcoded build is a browser that rots without anyone noticing.

    The URL comes from whatever the API answers, so no Chromium version number
    should appear in the source at all.
    """
    import re

    # e.g. the 146.0.7680.153 in V2's vendored filename.
    pinned = re.findall(r"\b\d{2,3}\.\d+\.\d{4}\.\d+\b", source)
    assert not pinned, f"a Chromium build is pinned in the source: {pinned}"


def test_a_prerelease_only_repository_still_resolves(source: str):
    """ungoogled-chromium-windows ships most builds as pre-releases.

    /releases/latest skips those and 404s when the newest tags are all
    pre-release, so the plain listing endpoint has to be tried as well or a
    clean checkout can fail to install at all.
    """
    assert "/latest" in source
    assert "per_page" in source, "no fallback past /releases/latest"


def test_a_partial_download_cannot_be_mistaken_for_a_complete_one(source: str):
    """Interrupt V2's download and it left a zip that failed extraction forever."""
    assert ".part" in source
    assert "Move-Item -Path $part" in source, "the archive must be renamed only once complete"


# --- the profile is the feature --------------------------------------------


def test_the_profile_lives_where_the_plan_says(source: str):
    assert "data\\chromium-profile" in source
    assert "bin\\chromium" in source


def test_the_profile_is_never_deleted(source: str):
    """It holds the Google and Grok logins; wiping it costs a human a manual
    re-authentication round. V2 cleared four extension caches on every launch —
    that belongs to the extensions (15.2), not to profile maintenance, and it is
    also why V2's launches were never fast."""
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "Remove-Item" not in stripped:
            continue
        assert "ChromiumProfile" not in stripped, f"the profile is deleted: {stripped}"


def test_the_profile_is_gitignored():
    probe = "data/chromium-profile/Default/Cookies"
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", probe],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, (
        f"{probe} is not gitignored — the browser profile carries live sessions"
    )


# --- reuse, and the seam the next two steps build on ------------------------


def test_a_running_browser_is_reused_rather_than_relaunched(source: str):
    """'Later launches reuse it in about a second' is the step's done-when."""
    launch = source.index("function Start-BundledChromium")
    start_process = source.index("Start-Process", launch)
    reuse = source.index("Test-ChromiumCdp", launch)
    assert reuse < start_process, "Start-BundledChromium must probe CDP before spawning"


def test_readiness_is_a_cdp_probe_not_a_sleep(source: str):
    """A process handle says nothing about whether the debugging port is up, and
    the extensions in 15.2 connect through that port."""
    assert "/json/version" in source
    assert "127.0.0.1" in source, "CDP must be probed on loopback only"


def test_the_debug_port_is_configurable(source: str):
    """15.2's port blocker in miniature: the extensions hardcode a port and the
    app serves on another. Nothing here may add a third hardcoded constant."""
    assert "SCRIPTASE_CDP_PORT" in source


@pytest.mark.parametrize(
    "name",
    [
        "Get-ChromiumPaths",
        "Get-ChromiumDebugPort",
        "Test-ChromiumCdp",
        "Install-Chromium",
        "Initialize-ChromiumProfile",
        "Start-BundledChromium",
    ],
)
def test_the_functions_steps_15_2_and_15_3_call_are_present(source: str, name: str):
    assert f"function {name}" in source


def test_dot_sourcing_the_module_does_not_launch_a_browser(source: str):
    """15.3 dot-sources this to sequence Flask, then Chromium, then Vite.
    Loading the functions must not have side effects."""
    assert "$MyInvocation.InvocationName -eq '.'" in source


def test_failure_is_raised_rather_than_exiting(source: str):
    """A Chromium failure is non-fatal to the launcher (15.3), which it can only
    honour if this throws instead of killing the process."""
    body = source[source.index("function Start-BundledChromium") :]
    body = body[: body.index("# ---------------------------------------------------------------------------")]
    assert "throw" in body
    assert "exit 1" not in body, "the library path must not terminate the launcher"
