<#
.SYNOPSIS
    Bundled ungoogled-Chromium: install once, then reuse.

.DESCRIPTION
    Two production providers are extension transports -- Grok and Gemini have no
    usable API for this work, so a real logged-in browser is not optional. That
    browser is a dedicated ungoogled-Chromium running against a persistent
    profile under data\chromium-profile.

    The profile IS the feature. It holds the Google and Grok sessions; wiping it
    means logging in by hand again, so nothing here ever deletes it.

    Dot-source this file to use the functions, or run it directly to install and
    launch:

        . tools\chromium.ps1                    # load the functions
        powershell -File tools\chromium.ps1     # install (if needed) and launch
        powershell -File tools\chromium.ps1 -InstallOnly
        powershell -File tools\chromium.ps1 -Force        # re-download

    Chromium is fetched from the GitHub releases API on first use rather than
    vendored: the archive is ~180 MB, which has no business in a git history,
    and pinning a version in the repo means shipping a browser that silently
    rots. bin\ is gitignored, so the download lands outside version control.

    Step 15.2 adds the four extensions and step 15.3 wires this into
    tools\launch.ps1; both call the functions below rather than re-implementing
    them.

.PARAMETER Url
    URLs to open in the new window. Ignored when a browser is already running,
    because CDP json/new is the right way to add a tab to a live session.

.PARAMETER InstallOnly
    Provision Chromium and the profile, but do not launch.

.PARAMETER Force
    Delete the installed browser and download it again. The profile is
    untouched -- this reinstalls the binary, not your logins.
#>
[CmdletBinding()]
param(
    [string[]]$Url = @(),
    [switch]$InstallOnly,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Captured at load time so the paths survive dot-sourcing into a script whose
# own $PSScriptRoot points somewhere else.
$script:ChromiumRoot    = Split-Path -Parent $PSScriptRoot
$script:ChromiumBinDir  = Join-Path $script:ChromiumRoot 'bin\chromium'
$script:ChromiumHome    = Join-Path $script:ChromiumBinDir 'ungoogled-chromium'
$script:ChromiumExe     = Join-Path $script:ChromiumHome 'chrome.exe'
$script:ChromiumProfile = Join-Path $script:ChromiumRoot 'data\chromium-profile'

$script:ChromiumReleaseApi = 'https://api.github.com/repos/ungoogled-software/ungoogled-chromium-windows/releases'

# launch.ps1 already defines these; when this file is run on its own they have
# to exist anyway. Redefining identical bodies would be the alternative, and one
# copy drifting from the other is exactly the kind of rot worth avoiding.
if (-not (Get-Command Write-Step -ErrorAction SilentlyContinue)) {
    function Write-Step { param([string]$Message) Write-Host "  ~ $Message" -ForegroundColor DarkGray }
    function Write-Ok   { param([string]$Message) Write-Host "  + $Message" -ForegroundColor Green }
    function Write-Warn { param([string]$Message) Write-Host "  ! $Message" -ForegroundColor Yellow }
    function Write-Err  { param([string]$Message) Write-Host "  x $Message" -ForegroundColor Red }
}

# ---------------------------------------------------------------------------
# Where things live
# ---------------------------------------------------------------------------

function Get-ChromiumPaths {
    <# One place that knows the layout, so 15.2 and 15.3 cannot disagree with it. #>
    return [ordered]@{
        Root       = $script:ChromiumRoot
        InstallDir = $script:ChromiumBinDir
        Home       = $script:ChromiumHome
        Exe        = $script:ChromiumExe
        Profile    = $script:ChromiumProfile
    }
}

function Get-ChromiumDebugPort {
    # The extensions and the provider hubs both reach the browser through CDP,
    # so the port is configuration, not a constant buried in a launch line.
    if ($env:SCRIPTASE_CDP_PORT) { return [int]$env:SCRIPTASE_CDP_PORT }
    return 9222
}

function Test-ChromiumCdp {
    <#
        Is a debuggable Chromium already up?

        Deliberately probes CDP rather than looking for a chrome.exe process: a
        browser started by hand, or one left over from a previous run without
        --remote-debugging-port, is useless to us and must not count as running.

        127.0.0.1 only. CDP is unauthenticated remote code execution against a
        profile holding live Google and Grok sessions; it never leaves loopback.
    #>
    param([int]$Port = 0, [int]$TimeoutSec = 2)

    if (-not $Port) { $Port = Get-ChromiumDebugPort }
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec $TimeoutSec -ErrorAction Stop | Out-Null
        return $true
    } catch {
        return $false
    }
}

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

function Resolve-ChromiumDownload {
    <#
        Ask GitHub for the newest Windows x64 build.

        /releases/latest is tried first but cannot be trusted alone:
        ungoogled-chromium-windows publishes plenty of builds as pre-releases,
        which /latest excludes outright -- and on a repo whose newest tags are
        all pre-releases it answers 404. The listing endpoint is the fallback,
        and it returns newest-first including pre-releases.
    #>
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    foreach ($endpoint in @("$($script:ChromiumReleaseApi)/latest", "$($script:ChromiumReleaseApi)?per_page=10")) {
        try {
            $releases = @(Invoke-RestMethod -Uri $endpoint -TimeoutSec 30 -UseBasicParsing -ErrorAction Stop)
        } catch {
            continue
        }
        foreach ($release in $releases) {
            if ($release.PSObject.Properties.Name -notcontains 'assets') { continue }
            $asset = @($release.assets) | Where-Object { $_.name -match 'windows_x64\.zip$' } | Select-Object -First 1
            if ($asset) {
                return @{ Url = $asset.browser_download_url; Name = $asset.name; Tag = $release.tag_name }
            }
        }
    }
    return $null
}

function Expand-ChromiumArchive {
    param([Parameter(Mandatory)][string]$ZipPath)

    $staging = Join-Path $script:ChromiumBinDir '.extract'
    if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
    New-Item -ItemType Directory -Force -Path $staging | Out-Null

    Write-Step 'Extracting...'
    try {
        # Expand-Archive pushes every one of ~2000 entries through the pipeline
        # and takes minutes; the framework call is a straight stream copy.
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $staging)

        # The release wraps its payload in a version-stamped folder, so the real
        # install root is wherever chrome.exe landed. Shallowest wins.
        $exe = Get-ChildItem -Path $staging -Filter 'chrome.exe' -Recurse -File |
            Sort-Object { $_.FullName.Length } | Select-Object -First 1
        if (-not $exe) { throw 'chrome.exe is not in the archive -- the download is not a Chromium release.' }

        # Only swap the live install once extraction has actually produced a
        # browser, so a failure here leaves the previous one working.
        if (Test-Path $script:ChromiumHome) { Remove-Item -Recurse -Force $script:ChromiumHome }
        Move-Item -Path $exe.Directory.FullName -Destination $script:ChromiumHome -Force
    } finally {
        Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue
    }
}

function Install-Chromium {
    <#
        Ensure bin\chromium\ungoogled-chromium\chrome.exe exists. Returns its path.

        A no-op after the first run -- that is what keeps later launches at
        about a second.
    #>
    param([switch]$Force)

    if ($Force -and (Test-Path $script:ChromiumHome)) {
        Write-Step 'Removing the installed Chromium (-Force)...'
        Remove-Item -Recurse -Force $script:ChromiumHome
    }
    if (Test-Path $script:ChromiumExe) { return $script:ChromiumExe }

    New-Item -ItemType Directory -Force -Path $script:ChromiumBinDir | Out-Null

    Write-Step 'Locating the latest ungoogled-Chromium release...'
    $release = Resolve-ChromiumDownload
    if (-not $release) {
        throw "Could not reach the GitHub releases API. Download a *_windows_x64.zip by hand from $($script:ChromiumReleaseApi) and extract it so that chrome.exe sits at $($script:ChromiumExe)."
    }

    $zip  = Join-Path $script:ChromiumBinDir $release.Name
    $part = "$zip.part"
    Remove-Item $part -Force -ErrorAction SilentlyContinue

    Write-Step "Downloading $($release.Name) (~180 MB, once)..."
    $previousProgress = $ProgressPreference
    try {
        # PS 5.1 repaints the progress bar per chunk; across 180 MB that is
        # minutes of pure console I/O and looks like a hung download.
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $release.Url -OutFile $part -UseBasicParsing -ErrorAction Stop
    } finally {
        $ProgressPreference = $previousProgress
    }

    # The archive earns its real name only once it is complete, so an
    # interrupted download can never be mistaken for one on the next run.
    Move-Item -Path $part -Destination $zip -Force
    Write-Ok "Downloaded $($release.Tag)"

    try {
        Expand-ChromiumArchive -ZipPath $zip
    } finally {
        # ~180 MB that is worth nothing once extracted, and re-downloadable.
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path $script:ChromiumExe)) { throw "Extraction finished but $($script:ChromiumExe) is missing." }
    Write-Ok 'Chromium installed'
    return $script:ChromiumExe
}

function Initialize-ChromiumProfile {
    <#
        Create data\chromium-profile if it is missing, and otherwise leave it
        strictly alone. It carries the logged-in Google and Grok sessions that
        the extension transports exist to drive; there is no cache-clearing or
        reset path here on purpose, because every one of them costs a human a
        round of manual sign-ins.
    #>
    if (-not (Test-Path $script:ChromiumProfile)) {
        New-Item -ItemType Directory -Force -Path $script:ChromiumProfile | Out-Null
        Write-Warn 'Fresh browser profile -- sign in to Google and Grok in the window that opens'
    }
    return $script:ChromiumProfile
}

# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

function Start-BundledChromium {
    <#
        Install if needed, then launch, then wait for CDP.

        Returns the Process when this call started the browser, or $null when a
        debuggable one was already listening. Throws on failure so the caller
        decides whether that is fatal -- for the launcher (step 15.3) it is not.
    #>
    param([string[]]$Url = @(), [int]$Port = 0, [switch]$Force)

    if (-not $Port) { $Port = Get-ChromiumDebugPort }

    if (Test-ChromiumCdp -Port $Port) {
        Write-Ok "Chromium already listening on CDP :$Port -- reusing it"
        return $null
    }

    $exe        = Install-Chromium -Force:$Force
    $profileDir = Initialize-ChromiumProfile

    # Quoted here rather than left to Start-Process, which joins an argument
    # array on spaces without quoting anything.
    $chromeArgs = @(
        "--remote-debugging-port=$Port"
        "--user-data-dir=`"$profileDir`""
        '--no-first-run'
        '--no-default-browser-check'
        '--disable-default-apps'
        '--window-position=100,100'
        '--window-size=1400,900'
    ) + $Url

    Write-Step "Launching Chromium (CDP :$Port)..."
    $proc = Start-Process -FilePath $exe -ArgumentList $chromeArgs -PassThru

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        # CDP is checked before HasExited: a launch that hands off to an
        # existing window exits at once yet still leaves a usable browser.
        if (Test-ChromiumCdp -Port $Port) {
            Write-Ok "Chromium ready on CDP :$Port"
            return $proc
        }
        if ($proc.HasExited) {
            throw "Chromium exited immediately (code $($proc.ExitCode)). Another Chromium is probably already using $profileDir without a debugging port -- close it and re-run."
        }
        Start-Sleep -Milliseconds 300
    }
    throw "Chromium did not open its debugging port ($Port) within 30s."
}

# ---------------------------------------------------------------------------
# Direct invocation
# ---------------------------------------------------------------------------

# Dot-sourcing stops here: the caller wants the functions, not a browser.
if ($MyInvocation.InvocationName -eq '.') { return }

try {
    if ($InstallOnly) {
        Install-Chromium -Force:$Force | Out-Null
        Initialize-ChromiumProfile | Out-Null
        Write-Ok 'Chromium ready'
        exit 0
    }
    Start-BundledChromium -Url $Url -Force:$Force | Out-Null
    exit 0
} catch {
    Write-Err $_.Exception.Message
    exit 1
}
