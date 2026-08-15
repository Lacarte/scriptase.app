<#
.SYNOPSIS
    The one-command add-a-provider path (step 12.5).

.DESCRIPTION
    Transport only. `python` is not on PATH on this machine, so this resolves
    the venv interpreter and forwards every argument to the scaffolder, which
    owns the real work: scaffold the package, run the contract tests it
    generates, and regenerate the docs from the live hub.

    Keeping the logic in Python is deliberate -- the headless loop can run
    pytest but not PowerShell, so anything decided here would be untestable.

.EXAMPLE
    new-provider.bat tts my_provider --kind cloud

.EXAMPLE
    new-provider.bat image my_renderer --kind extension --no-docs
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScaffoldArgs
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root       = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root 'venv\Scripts\python.exe'

Write-Host ''
Write-Host '  SCRIPTASE' -ForegroundColor Cyan -NoNewline
Write-Host '  new provider' -ForegroundColor DarkGray
Write-Host '  ---------------------------------' -ForegroundColor DarkGray
Write-Host ''

if (-not (Test-Path $VenvPython)) {
    Write-Host '  x No project virtual environment found.' -ForegroundColor Red
    Write-Host '    Run: start.bat -Mode setup' -ForegroundColor DarkGray
    Write-Host ''
    exit 1
}

# No arguments: show the scaffolder's own help rather than a second, rotting
# copy of the domain and kind vocabulary.
if (-not $ScaffoldArgs -or $ScaffoldArgs.Count -eq 0) {
    $ScaffoldArgs = @('--help')
}

Push-Location $Root
try {
    & $VenvPython -m scriptase.providers.scaffold @ScaffoldArgs
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $code
