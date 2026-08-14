# watch.ps1 - live narrated view of what the loop-engineering agents are doing.
#
# The orchestrator's own log only grows at stage boundaries, which makes a
# healthy run look frozen. But every headless `claude -p` builder writes a
# live transcript (.jsonl) as it works. This script follows the newest
# transcript and translates each event into a one-line, timestamped story:
#
#   16:41:02 TOOL Edit    frontend/src/features/workflow/stores/workflow.js
#   16:41:20 SAY  Now adding the debounced autosave timer...
#   16:42:05 TOOL Bash    npm test
#   16:42:06 DENY Bash    npm test   <- permission blocked!
#
# Usage:  powershell -File develop\loop-engineering\watch.ps1
# Ctrl+C stops watching; it never touches the run itself (read-only).

param([int]$PollSeconds = 2)

$ErrorActionPreference = 'SilentlyContinue'
$transcriptDir = "C:\Users\Admin\.claude\projects\d---Workspace--Development--Projects-SCRIPTASE-app"
$repoRoot      = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$logDir        = Join-Path $PSScriptRoot "runtime\logs"

function Stamp { (Get-Date).ToString('HH:mm:ss') }
function Line($tag, $text, $color) {
    $t = ($text -replace '\s+', ' ').Trim()
    if ($t.Length -gt 170) { $t = $t.Substring(0, 167) + '...' }
    Write-Host ("{0} {1,-5} {2}" -f (Stamp), $tag, $t) -ForegroundColor $color
}

Write-Host ""
Write-Host ("{0} watch.ps1 - read-only live view of the loop-engineering run" -f (Stamp)) -ForegroundColor Cyan
Write-Host ("{0} transcripts: {1}" -f (Stamp), $transcriptDir) -ForegroundColor DarkGray
Write-Host ("{0} step logs:   {1}" -f (Stamp), $logDir) -ForegroundColor DarkGray
Write-Host ("{0} Ctrl+C to stop watching (the run keeps going)" -f (Stamp)) -ForegroundColor DarkGray
Write-Host ""

$currentFile = $null
$pos = 0
$lastHead = (git -C $repoRoot log -1 --format='%h %s' 2>$null)
$sawRunner = $false
$runnerStartupDeadline = (Get-Date).AddSeconds(15)

# Do not replay the last agent's transcript when this viewer opens. Follow it
# only from its current end; a newly spawned Claude session starts at byte 0.
$existing = Get-ChildItem "$transcriptDir\*.jsonl" |
    Sort-Object CreationTime -Descending | Select-Object -First 1
if ($existing) {
    $currentFile = $existing.FullName
    $pos = $existing.Length
    Line 'WAIT' 'previous Claude transcript skipped; waiting for new Claude activity' DarkGray
}

while ($true) {
    # Follow the most recently CREATED transcript: each agent spawn makes a new
    # file, so newest-created = the agent currently working. (Newest-written
    # would flip to the interactive session whenever the user chats.)
    $newest = Get-ChildItem "$transcriptDir\*.jsonl" |
        Sort-Object CreationTime -Descending | Select-Object -First 1
    if ($newest -and $newest.FullName -ne $currentFile) {
        $currentFile = $newest.FullName
        $pos = 0
        Write-Host ""
        Line 'AGENT' ("new agent session started -> following " + $newest.Name) Cyan
    }

    if ($currentFile -and (Test-Path $currentFile)) {
        try {
            $fs = [System.IO.File]::Open($currentFile, 'Open', 'Read', 'ReadWrite')
            $fs.Seek($pos, 'Begin') | Out-Null
            $reader = New-Object System.IO.StreamReader($fs)
            while ($null -ne ($raw = $reader.ReadLine())) {
                $pos = $fs.Position
                if (-not $raw.Trim()) { continue }
                try { $j = $raw | ConvertFrom-Json } catch { continue }

                if ($j.type -eq 'assistant' -and $j.message.content) {
                    foreach ($c in $j.message.content) {
                        if ($c.type -eq 'tool_use') {
                            $detail = ''
                            if ($c.input.file_path)     { $detail = $c.input.file_path -replace [regex]::Escape($repoRoot), '.' }
                            elseif ($c.input.command)   { $detail = $c.input.command }
                            elseif ($c.input.pattern)   { $detail = "pattern: " + $c.input.pattern }
                            elseif ($c.input.prompt)    { $detail = $c.input.prompt }
                            $color = switch ($c.name) {
                                'Bash'  { 'Yellow' }
                                'Edit'  { 'Green' }
                                'Write' { 'Green' }
                                default { 'Gray' }
                            }
                            Line 'TOOL' ("{0,-6} {1}" -f $c.name, $detail) $color
                        }
                        elseif ($c.type -eq 'text' -and $c.text) {
                            Line 'SAY' $c.text White
                        }
                    }
                }
                elseif ($j.type -eq 'user' -and $j.message.content) {
                    foreach ($c in $j.message.content) {
                        if ($c.type -eq 'tool_result' -and $c.is_error) {
                            $txt = if ($c.content -is [string]) { $c.content } else { ($c.content | ForEach-Object { $_.text }) -join ' ' }
                            if ($txt -match 'permission|haven''t granted|denied') {
                                Line 'DENY' $txt Red
                            } else {
                                Line 'ERR' $txt DarkYellow
                            }
                        }
                    }
                }
                elseif ($j.type -eq 'result') {
                    Line 'DONE' ("agent finished ({0}, {1} turns)" -f $j.subtype, $j.num_turns) Cyan
                }
            }
            $reader.Close(); $fs.Close()
        } catch { }
    }

    # Announce every new commit the moment it lands.
    $head = (git -C $repoRoot log -1 --format='%h %s' 2>$null)
    if ($head -and $head -ne $lastHead) {
        $lastHead = $head
        Line 'GIT' ("new commit: " + $head) Magenta
    }

    # Close this viewer with its orchestrator instead of accumulating stale
    # watcher windows across repeated run.bat launches.
    $runnerActive = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -eq 'python.exe' -and $_.CommandLine -match 'loop_engineering\.py'
    }).Count -gt 0
    if ($runnerActive) {
        $sawRunner = $true
    } elseif ($sawRunner) {
        Line 'DONE' 'loop-engineering runner stopped; closing activity viewer' Cyan
        break
    } elseif ((Get-Date) -gt $runnerStartupDeadline) {
        Line 'DONE' 'no loop-engineering runner started; closing activity viewer' DarkYellow
        break
    }

    Start-Sleep -Seconds $PollSeconds
}
