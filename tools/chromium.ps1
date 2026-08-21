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

    The extensions under tools\extensions are loaded unpacked and pinned by
    the ids their manifest keys produce. They are not loaded from there directly:
    each launch stages a copy under data\chromium-extensions with the real
    backend port written into its sts-endpoint.js, because V2 hardcoded
    ws://localhost:5050 and Scriptase serves on 5000. See
    Sync-ScriptaseExtensions.

    tools\launch.ps1 sequences all of this: Flask, then Chromium, then Vite. It
    dot-sources this file and calls the functions below rather than
    re-implementing them.

.PARAMETER Url
    URLs to open in the new window. Ignored when a browser is already running,
    because CDP json/new -- Open-ChromiumTab below -- is the right way to add a
    tab to a live session.

.PARAMETER AppPort
    The port the Scriptase backend is on, injected into the extensions. Defaults
    to SCRIPTASE_PORT, then 5000 -- the same resolution config.PORT uses.

.PARAMETER InstallOnly
    Provision Chromium and the profile, but do not launch.

.PARAMETER Force
    Delete the installed browser and download it again. The profile is
    untouched -- this reinstalls the binary, not your logins.
#>
[CmdletBinding()]
param(
    [string[]]$Url = @(),
    [int]$AppPort = 0,
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
$script:ExtensionSource = Join-Path $script:ChromiumRoot 'tools\extensions'
$script:ExtensionStage  = Join-Path $script:ChromiumRoot 'data\chromium-extensions'

$script:ChromiumReleaseApi = 'https://api.github.com/repos/ungoogled-software/ungoogled-chromium-windows/releases'

# PowerShell 5.1's UTF8 encoding emits a BOM, which Chromium's JSON parser and
# its ES module loader both object to.
$script:Utf8NoBom = New-Object Text.UTF8Encoding($false)

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
        Root            = $script:ChromiumRoot
        InstallDir      = $script:ChromiumBinDir
        Home            = $script:ChromiumHome
        Exe             = $script:ChromiumExe
        Profile         = $script:ChromiumProfile
        ExtensionSource = $script:ExtensionSource
        ExtensionStage  = $script:ExtensionStage
    }
}

function Get-ScriptaseAppPort {
    # The backend port is config.PORT's twin; both read SCRIPTASE_PORT.
    if ($env:SCRIPTASE_PORT) { return [int]$env:SCRIPTASE_PORT }
    return 5000
}

function Get-ChromiumDebugPort {
    # The extensions and the provider hubs both reach the browser through CDP,
    # so the port is configuration, not a constant buried in a launch line.
    if ($env:SCRIPTASE_CDP_PORT) { return [int]$env:SCRIPTASE_CDP_PORT }
    return 9222
}

function Get-ChromiumProviderTabs {
    <#
        The pages the two extension transports drive.

        Both extensions are content scripts: they do nothing at all until their
        page is open, so a browser without these tabs is a browser where Grok
        and Gemini simply never respond. Opening them at launch is what makes
        "start the app" mean "the providers are ready".

        Overridable through .env because these URLs belong to somebody else and
        will move -- a Google account with multiple profiles needs a different
        /u/N/ prefix, for one. Set either to `off` to skip that tab; an empty
        value cannot mean anything here, because Windows deletes an environment
        variable that is set to the empty string.
    #>
    $wanted = [ordered]@{
        SCRIPTASE_TAB_GROK   = 'https://grok.com/imagine'
        SCRIPTASE_TAB_GEMINI = 'https://gemini.google.com/u/0/app?pageId=none'
    }

    $tabs = foreach ($name in $wanted.Keys) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if (-not $value) { $value = $wanted[$name] }
        $value = $value.Trim()
        if ($value -and $value -ne 'off') { $value }
    }
    return @($tabs)
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
# Extensions
# ---------------------------------------------------------------------------

function Get-ChromiumExtensionId {
    <#
        Derive an unpacked extension's id from the "key" in its manifest.

        Chromium computes the id as the first 16 bytes of SHA-256 over the
        DER public key, each nibble mapped 0-f to a-p. Because the key travels
        with the manifest, the id survives being copied to another path -- which
        is what lets the ids stay pinned across the port from V2, and what lets
        the staging copy below exist at all.

        Derived rather than transcribed: a hardcoded id list is a second source
        of truth that goes stale silently, and a wrong id pins nothing while
        looking like it worked.
    #>
    param([Parameter(Mandatory)][string]$ManifestPath)

    $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.PSObject.Properties.Name -notcontains 'key') {
        throw "$ManifestPath has no `"key`" -- its id would change on every copy."
    }

    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = $sha.ComputeHash([Convert]::FromBase64String($manifest.key)) } finally { $sha.Dispose() }

    $id = New-Object Text.StringBuilder
    foreach ($byte in $hash[0..15]) {
        [void]$id.Append([char](97 + ($byte -shr 4)))
        [void]$id.Append([char](97 + ($byte -band 0x0F)))
    }
    return $id.ToString()
}

function Get-ScriptaseExtensions {
    <# Every extension under tools\extensions that has a manifest, with its id. #>
    if (-not (Test-Path $script:ExtensionSource)) { return @() }

    return @(Get-ChildItem -Path $script:ExtensionSource -Directory | ForEach-Object {
        $manifest = Join-Path $_.FullName 'manifest.json'
        if (-not (Test-Path $manifest)) { return }
        [pscustomobject]@{
            Name   = $_.Name
            Source = $_.FullName
            Id     = Get-ChromiumExtensionId -ManifestPath $manifest
        }
    })
}

function Sync-ScriptaseExtensions {
    <#
        Stage the extensions with the ports this run actually uses, and return
        one descriptor per staged extension.

        Why a staged copy instead of loading tools\extensions directly: the
        extensions need to know where the backend is, and V2 answered that by
        hardcoding ws://localhost:5050. Scriptase serves on 5000, so a
        straight port would connect to nothing -- silently, because a socket
        that never opens looks exactly like a provider that is not responding.
        Replacing one constant with another only relocates that failure to
        whoever sets SCRIPTASE_PORT.

        So each extension carries an sts-endpoint.js holding its defaults, and
        staging rewrites the marked line in the copy with the real ports. The
        committed sources stay clean, the generated tree is disposable, and the
        extension ids are unaffected because they come from the manifest key.
    #>
    param(
        [int]$AppPort = 0,
        [int]$VitePort = 5173,
        [int]$AutomationPort = 0,
        [string]$HostName = 'localhost',
        # Only the tests pass this. Restaging the live tree underneath a running
        # browser is a real way to break a session, so they stage elsewhere.
        [string]$StageDir = ''
    )

    if (-not $AppPort) { $AppPort = Get-ScriptaseAppPort }
    # The automation port belongs to tools\automation.ps1, but this file cannot
    # dot-source that one for Get-ScriptaseAutomationPort: its param block would
    # land in this scope and reset -InstallOnly to $false halfway through a run.
    # tests/test_automation_backend.py runs both readings and compares them.
    if (-not $AutomationPort) {
        $AutomationPort = if ($env:SCRIPTASE_AUTOMATION_PORT) { [int]$env:SCRIPTASE_AUTOMATION_PORT } else { 8765 }
    }
    if (-not $StageDir) { $StageDir = $script:ExtensionStage }

    $extensions = Get-ScriptaseExtensions
    if (-not $extensions.Count) {
        Write-Warn "No extensions found under $($script:ExtensionSource)"
        return @()
    }

    # Built by hand rather than via ConvertTo-Json: PowerShell 5.1 renders a
    # one-element array as a bare scalar, and appPorts must stay a list.
    $uiPorts = @($AppPort)
    if ($VitePort -and $VitePort -ne $AppPort) { $uiPorts += $VitePort }
    $config = '{{"host":"{0}","appPorts":[{1}],"uiPorts":[{2}],"automationPort":{3}}}' -f `
        $HostName, $AppPort, ($uiPorts -join ','), $AutomationPort

    # Matched, not just replaced: on the default port the rewrite is a no-op, so
    # "the text changed" would report a missing marker on every ordinary launch.
    # The sources are CRLF and .NET's $ does not step over the \r, so the line
    # end has to be matched -- but as a lookahead, or the replacement eats the
    # \r and staging rewrites every file's line endings on the way past.
    $marker = '(?m)^(/\* @scriptase-endpoint \*/ (?:var|export const) STS_ENDPOINT = ).*?;[ \t]*(?=\r?$)'

    New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

    $staged = foreach ($extension in $extensions) {
        $target = Join-Path $StageDir $extension.Name
        if (Test-Path $target) { Remove-Item -Recurse -Force $target }
        Copy-Item -Path $extension.Source -Destination $target -Recurse -Force

        $endpoints = @(Get-ChildItem -Path $target -Filter 'sts-endpoint.js' -Recurse -File)
        if (-not $endpoints.Count) {
            throw "$($extension.Name) has no sts-endpoint.js -- it would keep whatever port its source hardcodes."
        }
        foreach ($endpoint in $endpoints) {
            $text = Get-Content -LiteralPath $endpoint.FullName -Raw -Encoding UTF8
            if (-not [regex]::IsMatch($text, $marker)) {
                throw "The @scriptase-endpoint marker is missing from $($endpoint.FullName); the injected port would be dropped."
            }
            $updated = [regex]::Replace($text, $marker, ('${1}' + $config + ';'))
            # Not Set-Content -Encoding UTF8: on PowerShell 5.1 that writes a BOM,
            # and a BOM in front of an ES module service worker is a parse error.
            [IO.File]::WriteAllText($endpoint.FullName, $updated, $script:Utf8NoBom)
        }

        [pscustomobject]@{ Name = $extension.Name; Path = $target; Id = $extension.Id }
    }

    $staged = @($staged)
    Write-Ok "$($staged.Count) extensions staged on :$AppPort"
    return $staged
}

function Set-ChromiumPinnedExtensions {
    <#
        Pin the extensions to the toolbar by editing the profile Preferences.

        Written before launch on purpose: Chromium rewrites Preferences from
        memory when it exits, so an edit made while it runs is discarded. On a
        brand-new profile the file does not exist yet, and the pins appear on
        the second launch -- that is a cosmetic delay, not a failure, so it
        never stops a launch.
    #>
    param([Parameter(Mandatory)][string[]]$Id)

    $prefsPath = Join-Path $script:ChromiumProfile 'Default\Preferences'
    if (-not (Test-Path $prefsPath)) {
        Write-Step 'No Preferences yet -- extensions will pin on the next launch'
        return
    }

    try {
        $prefs = Get-Content -LiteralPath $prefsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($prefs.PSObject.Properties.Name -notcontains 'extensions') {
            $prefs | Add-Member -Name 'extensions' -Value ([pscustomobject]@{}) -MemberType NoteProperty
        }
        $prefs.extensions | Add-Member -Name 'pinned_extensions' -Value $Id -MemberType NoteProperty -Force
        [IO.File]::WriteAllText($prefsPath, ($prefs | ConvertTo-Json -Depth 100 -Compress), $script:Utf8NoBom)
        Write-Ok 'Extensions pinned to the toolbar'
    } catch {
        # A mangled Preferences file costs the user their pins, not their
        # session -- worth a warning, never worth failing the launch.
        Write-Warn "Could not pin the extensions: $($_.Exception.Message)"
    }
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
    param([string[]]$Url = @(), [int]$Port = 0, [int]$AppPort = 0, [switch]$Force)

    if (-not $Port) { $Port = Get-ChromiumDebugPort }

    if (Test-ChromiumCdp -Port $Port) {
        Write-Ok "Chromium already listening on CDP :$Port -- reusing it"
        return $null
    }

    $exe        = Install-Chromium -Force:$Force
    $profileDir = Initialize-ChromiumProfile
    $extensions = Sync-ScriptaseExtensions -AppPort $AppPort

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
    )

    if ($extensions.Count) {
        Set-ChromiumPinnedExtensions -Id @($extensions.Id)
        # Chromium 137 ignores --load-extension unless this feature is off.
        # Harmless on builds that still honour the switch outright.
        $chromeArgs += '--disable-features=DisableLoadExtensionCommandLineSwitch'
        $chromeArgs += "--load-extension=`"$(@($extensions.Path) -join ',')`""
    }

    $chromeArgs += $Url

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

function Open-ChromiumTab {
    <#
        Open a URL as a tab in the running Chromium, and return whether it is
        now open.

        This is the reason the launcher does not hand the app URL to
        Start-Process: the browser that matters is already running with the
        profile and the extensions, and a second one -- the default browser, or
        a second Chromium against a locked profile -- helps nobody.

        Two details that are easy to get wrong and silent when you do:

        - The verb is PUT. Chrome refuses GET on /json/new ("Using unsafe HTTP
          verb GET to invoke /json/new") since 111, which is every build this
          project will ever download. GET is kept as a fallback for older
          builds; a stale reference implementation using it is exactly why V2's
          pipeline tab quietly stopped opening.
        - The URL is the raw query string. /json/new?{url} takes everything
          after the first '?' verbatim, so percent-encoding it would open a
          literally-encoded address. Fragments do not survive the trip and no
          caller has one -- the app routes are history-mode.
    #>
    param([Parameter(Mandatory)][string]$Url, [int]$Port = 0, [switch]$Force)

    if (-not $Port) { $Port = Get-ChromiumDebugPort }
    $base = "http://127.0.0.1:$Port"

    # Tabs are matched by origin, not by full URL. A relaunch should not stack a
    # duplicate on a session someone has navigated somewhere else -- and if the
    # app is open on /editor, that IS the app being open.
    if (-not $Force) {
        $wanted = $Url -as [uri]
        try {
            # PowerShell 5.1's Invoke-RestMethod hands a JSON array to the
            # pipeline as a single Object[], so this unrolls a level -- without
            # it every target looks like an object with no "url" and the check
            # silently never matches.
            $targets = @(Invoke-RestMethod -Uri "$base/json/list" -TimeoutSec 5 -ErrorAction Stop) |
                ForEach-Object { $_ }
            foreach ($target in @($targets)) {
                $names = $target.PSObject.Properties.Name
                if ($names -notcontains 'url' -or $names -notcontains 'type') { continue }
                if ($target.type -ne 'page') { continue }
                $open = $target.url -as [uri]
                if ($open -and $wanted -and $open.Authority -eq $wanted.Authority) { return $true }
            }
        } catch {
            # No target list means no browser; the request below will say so.
        }
    }

    foreach ($method in @('Put', 'Get')) {
        try {
            Invoke-RestMethod -Method $method -Uri "$base/json/new?$Url" -TimeoutSec 10 -ErrorAction Stop | Out-Null
            return $true
        } catch { continue }
    }

    Write-Warn "Could not open $Url through CDP :$Port"
    return $false
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
        Sync-ScriptaseExtensions -AppPort $AppPort | Out-Null
        Write-Ok 'Chromium ready'
        exit 0
    }
    if (-not $Url.Count) { $Url = Get-ChromiumProviderTabs }
    Start-BundledChromium -Url $Url -AppPort $AppPort -Force:$Force | Out-Null
    exit 0
} catch {
    Write-Err $_.Exception.Message
    exit 1
}
