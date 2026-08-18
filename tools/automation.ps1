<#
.SYNOPSIS
    The vendored ai-web-auto WebSocket server: provision its venv, then run it.

.DESCRIPTION
    ai-web-auto is a separate project with its own dependencies and its own
    :8765 server, copied into tools\automation\ai-web-auto (see the VENDOR.md
    there). Two of the browser extensions dial that socket as they load, so the
    launcher brings it up before Chromium -- the same reason Flask comes before
    Chromium.

    Its venv is separate from the app's and stays that way. Its dependency set
    is upstream's, resolved against upstream's bounds, and merging the two would
    let a browser-automation project constrain the version of pydantic the
    backend runs on.

    Every failure here is a warning. The automation server is one transport for
    one extension; the rest of Scriptase does not know it exists, so a missing
    venv or an occupied port must never be the reason the app will not start.
    Nothing in this file throws, and nothing calls Fail.

    Dot-source it for the functions, or run it directly to provision and serve:

        . tools\automation.ps1                        # load the functions
        powershell -File tools\automation.ps1         # provision, then serve
        powershell -File tools\automation.ps1 -InstallOnly
        powershell -File tools\automation.ps1 -Port 8799

    Dot-sourcing runs this param block in the caller's scope, so no name here
    may collide with one launch.ps1 declares. A second -Reinstall would reset
    the launcher's own to $false on the way past, and every dependency stamp
    would go on looking current for the rest of the run -- which is why the
    reinstall switch below is -Force, matching chromium.ps1's.
    tests/test_automation_backend.py holds the rule.

.PARAMETER Port
    The port to bind. Defaults to SCRIPTASE_AUTOMATION_PORT, then 8765 -- the
    same resolution serve.py and the extension staging in chromium.ps1 use.

.PARAMETER InstallOnly
    Provision the venv, but do not serve.

.PARAMETER Force
    Reinstall the dependencies even when the stamp is current.
#>
[CmdletBinding()]
param(
    [int]$Port = 0,
    [switch]$InstallOnly,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Captured at load time, the way chromium.ps1 does it, so the paths survive
# dot-sourcing.
$script:AutomationRoot   = Split-Path -Parent $PSScriptRoot
$script:AutomationDir    = Join-Path $script:AutomationRoot 'tools\automation'
$script:AutomationHome   = Join-Path $script:AutomationDir 'ai-web-auto'
$script:AutomationServe  = Join-Path $script:AutomationDir 'serve.py'
$script:AutomationReqs   = Join-Path $script:AutomationDir 'requirements.txt'
$script:AutomationVenv   = Join-Path $script:AutomationHome 'venv'
$script:AutomationPython = Join-Path $script:AutomationVenv 'Scripts\python.exe'
# Beside the artifact it describes, so deleting the venv invalidates it for free.
$script:AutomationStamp  = Join-Path $script:AutomationVenv '.requirements.sha256'
$script:AppVenvPython    = Join-Path $script:AutomationRoot 'venv\Scripts\python.exe'

$script:AutomationDefaultPort = 8765

# launch.ps1 already defines these; running this file on its own still needs
# them. Same arrangement as chromium.ps1, and for the same reason.
if (-not (Get-Command Write-Step -ErrorAction SilentlyContinue)) {
    function Write-Step { param([string]$Message) Write-Host "  ~ $Message" -ForegroundColor DarkGray }
    function Write-Ok   { param([string]$Message) Write-Host "  + $Message" -ForegroundColor Green }
    function Write-Warn { param([string]$Message) Write-Host "  ! $Message" -ForegroundColor Yellow }
    function Write-Err  { param([string]$Message) Write-Host "  x $Message" -ForegroundColor Red }
}

# ---------------------------------------------------------------------------
# Where things live
# ---------------------------------------------------------------------------

function Get-AutomationPaths {
    return [ordered]@{
        Root       = $script:AutomationRoot
        Home       = $script:AutomationHome
        Serve      = $script:AutomationServe
        Reqs       = $script:AutomationReqs
        Venv       = $script:AutomationVenv
        VenvPython = $script:AutomationPython
        Stamp      = $script:AutomationStamp
    }
}

function Get-ScriptaseAutomationPort {
    <#
        The port ai-web-auto binds.

        Three places resolve this and they must agree: here, serve.py's
        resolve_port, and the automationPort that Sync-ScriptaseExtensions
        writes into the staged extensions. A disagreement is invisible from the
        outside -- the extension retries a socket that will never open, and the
        provider just looks unresponsive -- which is why they all read one
        environment variable instead of each holding a constant, and why
        tests/test_automation_backend.py runs all three and compares them.
    #>
    if ($env:SCRIPTASE_AUTOMATION_PORT) { return [int]$env:SCRIPTASE_AUTOMATION_PORT }
    return $script:AutomationDefaultPort
}

function Test-AutomationServer {
    <#
        Is something already listening on the automation port?

        Passive on purpose. The obvious alternatives -- curl, or opening a
        TcpClient -- start a connection the server then tries to read an HTTP
        upgrade from, and it answers a dead socket with a three-deep traceback
        in the console. V2 hit this and left a note next to its netstat call
        saying not to use curl. Get-NetTCPConnection reads the kernel's table
        and touches nothing.
    #>
    param([int]$Port = 0)

    if (-not $Port) { $Port = Get-ScriptaseAutomationPort }
    $listening = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($listening) { return $true }

    # Get-NetTCPConnection uses the StandardCimv2 provider, which can be
    # present but deny reads to a non-administrator. netstat reads the same
    # kernel table without opening a connection and works in that environment.
    $escapedPort = [regex]::Escape($Port.ToString())
    $netstat = & "$env:SystemRoot\System32\netstat.exe" -ano -p TCP 2>$null
    return [bool]($netstat | Select-String -Pattern ":$escapedPort\s+.*\sLISTENING\s+\d+\s*$")
}

# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------

function Initialize-AutomationVenv {
    <#
        Create tools\automation\ai-web-auto\venv and install into it. Returns
        whether the venv is usable afterwards.

        Keyed on the SHA-256 of the requirements file, like the app's own
        dependency sync, so the second run is a no-op.

        Warns rather than throwing on every path. This runs inside the
        launcher's provisioning phase, ahead of the app itself, and a pip
        failure here has no business stopping a backend that does not import
        any of it.
    #>
    param([string]$PythonExe = '', [switch]$Reinstall)

    if (-not (Test-Path $script:AutomationHome)) {
        Write-Warn "ai-web-auto is not vendored at $($script:AutomationHome) -- skipping"
        return $false
    }
    if (-not (Test-Path $script:AutomationReqs)) {
        Write-Warn "$($script:AutomationReqs) is missing -- skipping ai-web-auto"
        return $false
    }

    if (-not $PythonExe) { $PythonExe = $script:AppVenvPython }
    if (-not (Test-Path $script:AutomationPython)) {
        # A venv interpreter can create another venv, so the app's is enough and
        # this file never has to repeat launch.ps1's system-Python discovery.
        if (-not (Test-Path $PythonExe)) {
            Write-Warn 'No interpreter to build the ai-web-auto venv with -- run start.bat -Mode setup first'
            return $false
        }
        if (Test-Path $script:AutomationVenv) {
            Write-Warn 'The ai-web-auto venv is broken -- recreating'
            Remove-Item -Recurse -Force $script:AutomationVenv
        }
        Write-Step 'Creating the ai-web-auto virtual environment...'
        & $PythonExe -m venv $script:AutomationVenv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $script:AutomationPython)) {
            Write-Warn 'Could not create the ai-web-auto venv -- the automation server will not start'
            return $false
        }
        # A freshly created venv ships whatever pip the base interpreter bundled,
        # which is often years old -- the same reason Initialize-Venv does this.
        & $script:AutomationPython -m pip install --upgrade pip --quiet --disable-pip-version-check
    }

    $hash = (Get-FileHash -Path $script:AutomationReqs -Algorithm SHA256).Hash
    if (-not $Reinstall -and (Test-Path $script:AutomationStamp) -and
        ((Get-Content $script:AutomationStamp -Raw).Trim() -eq $hash)) {
        Write-Ok 'ai-web-auto dependencies up to date'
        return $true
    }

    Write-Step 'Installing ai-web-auto dependencies...'
    & $script:AutomationPython -m pip install -r $script:AutomationReqs --quiet --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) {
        Write-Warn 'Could not install the ai-web-auto dependencies -- the automation server will not start'
        return $false
    }
    Set-Content -Path $script:AutomationStamp -Value $hash -Encoding ascii
    Write-Ok 'ai-web-auto dependencies installed'
    return $true
}

# ---------------------------------------------------------------------------
# Serve
# ---------------------------------------------------------------------------

function Start-AutomationServer {
    <#
        Start the server unless one is already up. Returns the Process this call
        started, or $null -- which covers "reused the running one" as much as
        "could not start it", because the caller does nothing different either
        way.

        Never throws. The launcher calls this between a healthy backend and the
        browser, inside the try whose finally tears down every child, so an
        exception escaping here would take a working app down over a WebSocket
        relay that most runs never touch.

        $Job is the launcher's kill-on-close job object. Unlike Chromium, this
        process is a job member: it holds a port and carries no session worth
        preserving, so it should die with the window that started it. Passing
        [IntPtr]::Zero -- what a standalone run does -- just leaves it out.
    #>
    param([int]$Port = 0, [IntPtr]$Job = [IntPtr]::Zero)

    if (-not $Port) { $Port = Get-ScriptaseAutomationPort }

    if (Test-AutomationServer -Port $Port) {
        Write-Ok "ai-web-auto already listening on :$Port -- reusing it"
        return $null
    }
    if (-not (Test-Path $script:AutomationPython)) {
        Write-Warn "ai-web-auto is not provisioned -- run start.bat -Mode setup, or powershell -File tools\automation.ps1 -InstallOnly"
        return $null
    }

    try {
        Write-Step "Starting ai-web-auto on ws://localhost:$Port..."
        $psi = New-Object Diagnostics.ProcessStartInfo
        $psi.FileName         = $script:AutomationPython
        $psi.Arguments        = "`"$($script:AutomationServe)`" --port $Port"
        $psi.WorkingDirectory = $script:AutomationRoot
        # Inherit this console, like Flask and Vite: one interleaved log stream.
        # serve.py reads nothing from stdin, which is exactly why it exists --
        # upstream's entry point is a REPL and would eat the launcher's input.
        $psi.UseShellExecute  = $false

        $proc = [Diagnostics.Process]::Start($psi)

        if ($Job -ne [IntPtr]::Zero -and ('Scriptase.JobObject' -as [type])) {
            if (-not [Scriptase.JobObject]::AssignProcessToJobObject($Job, $proc.Handle)) {
                Write-Warn 'Could not place ai-web-auto in the job -- it may outlive this window'
            }
        }

        $deadline = (Get-Date).AddSeconds(20)
        while ((Get-Date) -lt $deadline) {
            if (Test-AutomationServer -Port $Port) {
                Write-Ok "ai-web-auto serving on ws://localhost:$Port"
                return $proc
            }
            if ($proc.HasExited) {
                Write-Warn "ai-web-auto exited with code $($proc.ExitCode) -- the automation extension will not connect"
                return $null
            }
            Start-Sleep -Milliseconds 250
        }
        Write-Warn "ai-web-auto did not bind :$Port within 20s -- continuing without it"
        return $proc
    } catch {
        Write-Warn "Could not start ai-web-auto -- $($_.Exception.Message)"
        return $null
    }
}

# ---------------------------------------------------------------------------
# Direct invocation
# ---------------------------------------------------------------------------

# Dot-sourcing stops here: the caller wants the functions, not a server.
if ($MyInvocation.InvocationName -eq '.') { return }

if (-not (Initialize-AutomationVenv -Reinstall:$Force)) { exit 1 }
if ($InstallOnly) {
    Write-Ok 'ai-web-auto ready'
    exit 0
}

# Foreground, and owned by this console: Ctrl+C stops it.
$server = Start-AutomationServer -Port $Port
if (-not $server) { exit 1 }
$server.WaitForExit()
exit $server.ExitCode
