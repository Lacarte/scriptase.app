<#
.SYNOPSIS
    Scriptase bootstrapper and launcher.

.DESCRIPTION
    One entry point that provisions everything the app needs and then runs it.
    Safe to run repeatedly: each provisioning step is a no-op once satisfied.

      1. Verify Python >= 3.10 and Node >= 18
      2. Create venv/ if missing or broken
      3. Install Python deps when requirements.txt changes (SHA-256 stamp)
      4. Install Node deps when package-lock.json changes (SHA-256 stamp)
      5. Load .env into the child environment
      6. Launch, and guarantee every child dies with this process

    Child processes (Flask, Vite) are placed in a Windows Job Object with
    KILL_ON_JOB_CLOSE. When this process ends by ANY route -- clean exit,
    Ctrl+C, closing the console, crash, Task Manager -- the kernel terminates
    the whole job atomically. There is no polling watchdog, no killing by
    window title, and no killing by port number: those can all fire late or
    hit an unrelated process that happens to hold the port.

.PARAMETER Mode
    dev    Flask + Vite dev server with HMR (default)
    prod   Build the frontend, then serve it from Flask alone
    setup  Provision only; do not launch

.PARAMETER NoBrowser
    Do not open a browser window.

.PARAMETER Reinstall
    Force dependency reinstall even when the stamps are current.

.EXAMPLE
    .\start.bat
.EXAMPLE
    powershell -File tools\launch.ps1 -Mode prod
#>
[CmdletBinding()]
param(
    [ValidateSet('dev', 'prod', 'setup')]
    [string]$Mode = 'dev',
    [switch]$NoBrowser,
    [switch]$Reinstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root       = Split-Path -Parent $PSScriptRoot
$VenvDir    = Join-Path $Root 'venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$FrontendDir = Join-Path $Root 'frontend'

# Stamps live beside the artifact they describe, so deleting venv/ or
# node_modules/ invalidates the stamp for free.
$PyStamp   = Join-Path $VenvDir '.requirements.sha256'
$NodeStamp = Join-Path $FrontendDir 'node_modules\.deps.sha256'

$MinPython = [Version]'3.10'
$MinNode   = 18

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

function Write-Step { param([string]$Message) Write-Host "  ~ $Message" -ForegroundColor DarkGray }
function Write-Ok   { param([string]$Message) Write-Host "  + $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "  ! $Message" -ForegroundColor Yellow }
function Write-Err  { param([string]$Message) Write-Host "  x $Message" -ForegroundColor Red }

function Write-Banner {
    Write-Host ''
    Write-Host '  SCRIPTASE' -ForegroundColor Cyan -NoNewline
    Write-Host "  $Mode" -ForegroundColor DarkGray
    Write-Host '  ---------------------------------' -ForegroundColor DarkGray
    Write-Host ''
}

function Fail {
    param([string]$Message, [string]$Fix)
    Write-Host ''
    Write-Err $Message
    if ($Fix) { Write-Host "    $Fix" -ForegroundColor DarkGray }
    Write-Host ''
    exit 1
}

# ---------------------------------------------------------------------------
# 1. Toolchain
# ---------------------------------------------------------------------------

function Resolve-SystemPython {
    # `py -3` is the Windows launcher and is the most reliable; fall back to
    # whatever `python` resolves to.
    #
    # Deliberately uses `--version` rather than `-c "import sys; ..."`: passing a
    # quoted Python snippet through PowerShell to a native exe strips the inner
    # quotes, so the interpreter receives a syntax error and reports itself as
    # missing. A Microsoft Store stub still slips past this check, which is why
    # Initialize-Venv verifies the created interpreter actually runs.
    foreach ($candidate in @(@{ Exe = 'py'; Args = @('-3') }, @{ Exe = 'python'; Args = @() })) {
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
        try {
            $raw = & $candidate.Exe @($candidate.Args + @('--version')) 2>&1
            if ($LASTEXITCODE -ne 0 -or -not $raw) { continue }
            if ("$raw" -notmatch '(\d+)\.(\d+)') { continue }
            $version = [Version]"$($Matches[1]).$($Matches[2])"
            if ($version -ge $MinPython) {
                return @{ Exe = $candidate.Exe; Args = $candidate.Args; Version = $version }
            }
            Write-Warn "Ignoring Python $version at '$($candidate.Exe)' (need >= $MinPython)"
        } catch { continue }
    }
    return $null
}

function Test-Toolchain {
    $python = Resolve-SystemPython
    if (-not $python) {
        Fail "No Python >= $MinPython found." 'Install Python 3.10+ from python.org and re-run.'
    }
    Write-Ok "Python $($python.Version)"

    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        Fail 'npm not found.' 'Install Node.js 18+ from nodejs.org and re-run.'
    }
    $nodeRaw = (& node --version 2>$null)
    if ($nodeRaw -match 'v(\d+)') {
        $major = [int]$Matches[1]
        if ($major -lt $MinNode) { Fail "Node $nodeRaw is too old (need >= $MinNode)." 'Upgrade Node.js and re-run.' }
        Write-Ok "Node $nodeRaw"
    }
    return $python
}

# ---------------------------------------------------------------------------
# 2. Virtual environment
# ---------------------------------------------------------------------------

function Test-VenvHealthy {
    # Existence of the folder proves nothing: an interrupted `python -m venv`
    # leaves a directory whose interpreter cannot start.
    if (-not (Test-Path $VenvPython)) { return $false }
    try {
        & $VenvPython -c 'import sys' 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Initialize-Venv {
    param($Python)
    if (Test-VenvHealthy) {
        Write-Ok 'Virtual environment ready'
        return
    }
    if (Test-Path $VenvDir) {
        Write-Warn 'Virtual environment is broken -- recreating'
        Remove-Item -Recurse -Force $VenvDir
    }
    Write-Step 'Creating virtual environment...'
    & $Python.Exe @($Python.Args + @('-m', 'venv', $VenvDir))
    if ($LASTEXITCODE -ne 0 -or -not (Test-VenvHealthy)) {
        Fail 'Could not create the virtual environment.' "Try manually: python -m venv `"$VenvDir`""
    }
    # A freshly created venv ships a pip that is often years old.
    & $VenvPython -m pip install --upgrade pip --quiet --disable-pip-version-check
    Write-Ok 'Virtual environment created'
}

# ---------------------------------------------------------------------------
# 3/4. Dependency sync, keyed on content hash
# ---------------------------------------------------------------------------

function Get-FileSha {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return '' }
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash
}

function Test-StampCurrent {
    param([string]$StampPath, [string]$Expected)
    if ($Reinstall) { return $false }
    if (-not (Test-Path $StampPath)) { return $false }
    return ((Get-Content $StampPath -Raw).Trim() -eq $Expected)
}

function Sync-PythonDeps {
    $requirements = Join-Path $Root 'requirements.txt'
    if (-not (Test-Path $requirements)) { Fail 'requirements.txt is missing.' }

    $hash = Get-FileSha $requirements
    if (Test-StampCurrent $PyStamp $hash) {
        Write-Ok 'Python dependencies up to date'
        return
    }
    Write-Step 'Installing Python dependencies...'
    & $VenvPython -m pip install -r $requirements --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) {
        Fail 'pip install failed.' 'Scroll up for the failing package. Re-run with -Reinstall after fixing.'
    }
    Set-Content -Path $PyStamp -Value $hash -Encoding ascii
    Write-Ok 'Python dependencies installed'
}

function Sync-NodeDeps {
    $lock        = Join-Path $FrontendDir 'package-lock.json'
    $packageJson = Join-Path $FrontendDir 'package.json'
    if (-not (Test-Path $packageJson)) { Fail 'frontend/package.json is missing.' }

    # Prefer the lockfile: it is what `npm ci` reproduces exactly.
    $source = if (Test-Path $lock) { $lock } else { $packageJson }
    $hash   = Get-FileSha $source

    if ((Test-Path (Join-Path $FrontendDir 'node_modules')) -and (Test-StampCurrent $NodeStamp $hash)) {
        Write-Ok 'Node dependencies up to date'
        return
    }

    Push-Location $FrontendDir
    try {
        if (Test-Path $lock) {
            Write-Step 'Installing Node dependencies (npm ci)...'
            & npm ci
            if ($LASTEXITCODE -ne 0) {
                # `npm ci` refuses to proceed when the lockfile and package.json
                # disagree; `npm install` reconciles them and rewrites the lock.
                Write-Warn 'npm ci failed -- falling back to npm install'
                & npm install
            }
        } else {
            Write-Step 'Installing Node dependencies (npm install)...'
            & npm install
        }
        if ($LASTEXITCODE -ne 0) { Fail 'npm install failed.' 'Scroll up for the error.' }
        # Recompute: npm install may have rewritten the lockfile.
        Set-Content -Path $NodeStamp -Value (Get-FileSha $source) -Encoding ascii
        Write-Ok 'Node dependencies installed'
    } finally {
        Pop-Location
    }
}

# ---------------------------------------------------------------------------
# 5. Environment
# ---------------------------------------------------------------------------

function Import-DotEnv {
    # config.py deliberately reads os.environ only -- it has no python-dotenv
    # dependency. The launcher is what makes a .env file mean anything, so the
    # backend stays dependency-free and tests stay hermetic.
    $envFile    = Join-Path $Root '.env'
    $envExample = Join-Path $Root '.env.example'

    if (-not (Test-Path $envFile)) {
        if (Test-Path $envExample) {
            Copy-Item $envExample $envFile
            Write-Warn 'Created .env from .env.example -- add your API keys before using cloud providers'
        }
        else { return }
    }

    $loaded = 0
    foreach ($line in Get-Content $envFile) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $split = $trimmed.IndexOf('=')
        if ($split -lt 1) { continue }
        $key = $trimmed.Substring(0, $split).Trim()
        $val = $trimmed.Substring($split + 1).Trim().Trim('"').Trim("'")
        # A real environment variable outranks .env, so `set FOO=x && start.bat`
        # behaves the way anyone would expect.
        if (-not [Environment]::GetEnvironmentVariable($key)) {
            [Environment]::SetEnvironmentVariable($key, $val)
            $loaded++
        }
    }
    if ($loaded) { Write-Ok "Loaded $loaded variable(s) from .env" }
}

# ---------------------------------------------------------------------------
# 6. Job Object -- the only cleanup mechanism we need
# ---------------------------------------------------------------------------

if (-not ('Scriptase.JobObject' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace Scriptase {
    public static class JobObject {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        public static extern IntPtr CreateJobObject(IntPtr attributes, string name);

        [DllImport("kernel32.dll")]
        public static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint length);

        [DllImport("kernel32.dll")]
        public static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

        [DllImport("kernel32.dll")]
        public static extern bool TerminateJobObject(IntPtr job, uint exitCode);

        [DllImport("kernel32.dll")]
        public static extern bool CloseHandle(IntPtr handle);

        [StructLayout(LayoutKind.Sequential)]
        public struct BasicLimits {
            public Int64 PerProcessUserTimeLimit;
            public Int64 PerJobUserTimeLimit;
            public UInt32 LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public UInt32 ActiveProcessLimit;
            public IntPtr Affinity;
            public UInt32 PriorityClass;
            public UInt32 SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct IoCounters {
            public UInt64 ReadOperationCount;
            public UInt64 WriteOperationCount;
            public UInt64 OtherOperationCount;
            public UInt64 ReadTransferCount;
            public UInt64 WriteTransferCount;
            public UInt64 OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct ExtendedLimits {
            public BasicLimits BasicLimitInformation;
            public IoCounters IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }

        public const int ExtendedLimitInformation = 9;
        public const uint KillOnJobClose = 0x2000;
    }
}
'@
}

function New-KillOnCloseJob {
    $job = [Scriptase.JobObject]::CreateJobObject([IntPtr]::Zero, $null)
    if ($job -eq [IntPtr]::Zero) { throw 'CreateJobObject failed' }

    $limits = New-Object Scriptase.JobObject+ExtendedLimits
    $limits.BasicLimitInformation.LimitFlags = [Scriptase.JobObject]::KillOnJobClose

    $size = [Runtime.InteropServices.Marshal]::SizeOf([type][Scriptase.JobObject+ExtendedLimits])
    $ptr  = [Runtime.InteropServices.Marshal]::AllocHGlobal($size)
    try {
        [Runtime.InteropServices.Marshal]::StructureToPtr($limits, $ptr, $false)
        if (-not [Scriptase.JobObject]::SetInformationJobObject($job, [Scriptase.JobObject]::ExtendedLimitInformation, $ptr, [uint32]$size)) {
            throw 'SetInformationJobObject failed'
        }
    } finally {
        [Runtime.InteropServices.Marshal]::FreeHGlobal($ptr)
    }
    return $job
}

function Start-JobChild {
    param(
        [IntPtr]$Job,
        [string]$FilePath,
        [string]$Arguments,
        [string]$WorkingDirectory
    )
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName         = $FilePath
    $psi.Arguments        = $Arguments
    $psi.WorkingDirectory = $WorkingDirectory
    # Inherit this console: one window, one interleaved log stream. V2 spawned
    # separate minimised windows, which meant hunting for the failing one.
    #
    # UseShellExecute=false means CreateProcess, which requires a real .exe --
    # it cannot run npm.cmd or npm.ps1. Callers must route shell scripts through
    # cmd.exe; the shell then joins the job and its children inherit membership.
    $psi.UseShellExecute  = $false

    $proc = [Diagnostics.Process]::Start($psi)
    if (-not [Scriptase.JobObject]::AssignProcessToJobObject($Job, $proc.Handle)) {
        Write-Warn "Could not place '$FilePath' in the job -- it may outlive this window"
    }
    return $proc
}

# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

function Wait-ForHealth {
    param([string]$Url, [int]$TimeoutSeconds = 90, [Diagnostics.Process]$Process)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        # A dead child will never become healthy; fail immediately rather than
        # burning the full timeout.
        if ($Process -and $Process.HasExited) {
            Fail "Backend exited with code $($Process.ExitCode) before becoming healthy." 'The traceback is above.'
        }
        try {
            $response = Invoke-RestMethod -Uri $Url -TimeoutSec 3 -ErrorAction Stop
            if ($response.status -eq 'ok') { return $response }
        } catch { Start-Sleep -Milliseconds 400 }
    }
    Fail "Timed out after ${TimeoutSeconds}s waiting for $Url"
}

function Wait-ForPort {
    param([int]$Port, [int]$TimeoutSeconds = 90, [Diagnostics.Process]$Process)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($Process -and $Process.HasExited) {
            Fail "Vite exited with code $($Process.ExitCode) before serving." 'The error is above.'
        }
        $listening = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
        if ($listening) { return $true }
        Start-Sleep -Milliseconds 400
    }
    Fail "Timed out after ${TimeoutSeconds}s waiting for port $Port"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

Write-Banner

$python = Test-Toolchain
Initialize-Venv -Python $python
Sync-PythonDeps
Sync-NodeDeps
Import-DotEnv

if ($Mode -eq 'setup') {
    Write-Host ''
    Write-Ok 'Setup complete.'
    Write-Host '    Run start.bat to launch.' -ForegroundColor DarkGray
    Write-Host ''
    exit 0
}

$backendPort = if ($env:SCRIPTASE_PORT) { [int]$env:SCRIPTASE_PORT } else { 5000 }
$backendHost = if ($env:SCRIPTASE_HOST) { $env:SCRIPTASE_HOST } else { '127.0.0.1' }
$healthUrl   = "http://${backendHost}:${backendPort}/api/health"
$vitePort    = 5173

if ($Mode -eq 'prod') {
    Write-Step 'Building the frontend...'
    Push-Location $FrontendDir
    try {
        & npm run build
        if ($LASTEXITCODE -ne 0) { Fail 'Frontend build failed.' }
    } finally { Pop-Location }
    Write-Ok 'Frontend built'
}

$job = New-KillOnCloseJob
$exitCode = 0

try {
    Write-Host ''
    Write-Step "Starting backend on ${backendHost}:${backendPort}..."
    $flask = Start-JobChild -Job $job -FilePath $VenvPython -Arguments 'app.py' -WorkingDirectory $Root

    $health = Wait-ForHealth -Url $healthUrl -Process $flask
    $version = if ($health.PSObject.Properties.Name -contains 'version') { $health.version } else { 'unknown' }
    Write-Ok "Backend healthy (Scriptase $version)"

    $appUrl = "http://${backendHost}:${backendPort}/"

    if ($Mode -eq 'dev') {
        Write-Step 'Starting Vite dev server...'
        # `Get-Command npm` resolves to npm.ps1 on Windows, which CreateProcess
        # rejects outright ("not a valid application for this OS platform").
        # cmd.exe is the portable shim and lands in the job either way.
        $vite = Start-JobChild -Job $job -FilePath $env:ComSpec -Arguments '/c npm run dev' -WorkingDirectory $FrontendDir
        Wait-ForPort -Port $vitePort -Process $vite | Out-Null
        Write-Ok "Vite serving on :$vitePort"
        $appUrl = "http://localhost:${vitePort}/"
    }

    Write-Host ''
    Write-Host "  Scriptase is running at " -NoNewline
    Write-Host $appUrl -ForegroundColor Cyan
    Write-Host '  Press Ctrl+C or close this window to stop everything.' -ForegroundColor DarkGray
    Write-Host ''

    if (-not $NoBrowser) { Start-Process $appUrl | Out-Null }

    # Block until the backend exits. Vite is a job member, so it dies with us.
    $flask.WaitForExit()
    $exitCode = $flask.ExitCode
}
finally {
    Write-Host ''
    Write-Host '  Stopping Scriptase...' -ForegroundColor Yellow
    # Terminate explicitly rather than trusting the handle to close on exit.
    # KILL_ON_JOB_CLOSE only fires when the LAST handle to the job goes away,
    # and a handle can outlive this script -- when that happened, Flask and its
    # child interpreter survived the launcher and kept port 5000 bound.
    # TerminateJobObject is immediate and unconditional; KILL_ON_JOB_CLOSE stays
    # configured as the backstop for paths where this block never runs at all
    # (Task Manager kill, power loss on the console host).
    [void][Scriptase.JobObject]::TerminateJobObject($job, 0)
    [void][Scriptase.JobObject]::CloseHandle($job)
}

exit $exitCode
