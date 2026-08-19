@echo off
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
:: Launcher for the loop-engineering orchestrator.
:: Double-click       -> choose an agent profile, then run phase by phase.
:: From a terminal:
::   run.bat --status
::   run.bat --phase 2
::   run.bat --until 3.3 --builder claude --coding-fallback codex --reviewer codex
::   run.bat --steps 1 --no-push
cd /d "%~dp0..\.."
title Scriptase - Loop Engineering

if not exist "venv\Scripts\python.exe" (
    echo [run.bat] venv\Scripts\python.exe not found - run setup.bat first.
    goto :hold
)

set EXITCODE=0
if not "%~1"=="" goto :with_args

:menu
echo ========================================================================
echo [run.bat] Choose the agents for this run:
echo.
echo   [1] Claude codes; Codex takes over at the limit; Codex reviews
echo   [2] Codex builds, fixes, and reviews
echo   [3] Claude builds, fixes, and reviews
echo   [4] AGY codes; Codex limit fallback; Codex reviews
echo   [5] Grok 4.5 codes; Codex limit fallback; Codex reviews
echo   [6] Claude codes,  Grok 4.5 reviews
echo   [Q] Cancel
echo.
choice /c 123456Q /n /m "Select 1, 2, 3, 4, 5, 6, or Q: "
if errorlevel 7 goto :cancelled
if errorlevel 6 goto :claude_code_grok_review
if errorlevel 5 goto :grok_code_codex_review
if errorlevel 4 goto :agy_code_codex_review
if errorlevel 3 goto :all_claude
if errorlevel 2 goto :all_codex

:default_profile
:: NOTE: agy requires an interactive Google OAuth login and cannot authenticate in a
:: headless run, so it is not used as the limit fallback. Switch back only after
:: running `agy` once by hand and completing the sign-in.
set "PROFILE=Claude codes; Codex limit fallback; Codex reviews"
set "RUNARGS=--by-phase --builder claude --fixer claude --coding-fallback codex --reviewer codex"
set "USES_CLAUDE=1"
goto :launch

:all_codex
set "PROFILE=Codex builds, fixes, and reviews"
set "RUNARGS=--by-phase --builder codex --fixer codex --coding-fallback none --reviewer codex"
set "USES_CLAUDE=0"
goto :launch

:all_claude
set "PROFILE=Claude builds, fixes, and reviews"
set "RUNARGS=--by-phase --builder claude --fixer claude --coding-fallback none --reviewer claude"
set "USES_CLAUDE=1"
goto :launch

:agy_code_codex_review
:: agy is quota-limited per-account; with no fallback a quota hit halts the run
:: with zero steps completed. Codex takes over instead, and the handoff is sticky
:: for the rest of the run.
set "PROFILE=AGY builds and fixes; Codex limit fallback; Codex reviews"
set "RUNARGS=--by-phase --builder agy --fixer agy --coding-fallback codex --reviewer codex"
set "USES_CLAUDE=0"
goto :launch

:grok_code_codex_review
set "PROFILE=Grok 4.5 builds and fixes; Codex limit fallback; Codex reviews"
set "RUNARGS=--by-phase --builder grok --fixer grok --coding-fallback codex --reviewer codex"
set "USES_CLAUDE=0"
goto :launch

:claude_code_grok_review
:: The two agents named are the only two used: Grok reviews, and Grok also takes
:: over coding if Claude hits its usage limit. Codex is not pulled in as the
:: fallback here because the point of this profile is a second opinion from a
:: different model family -- falling back to Codex would quietly make it a
:: third, and a limit hit must never halt a run with steps still queued.
set "PROFILE=Claude builds and fixes; Grok 4.5 limit fallback; Grok 4.5 reviews"
set "RUNARGS=--by-phase --builder claude --fixer claude --coding-fallback grok --reviewer grok"
set "USES_CLAUDE=1"
goto :launch

:launch
echo.
echo ========================================================================
echo [run.bat] LOOP STARTING - %PROFILE%.
echo [run.bat] Press Ctrl+C here if you need to stop the engineering loop.
echo ========================================================================
echo.
if "%USES_CLAUDE%"=="1" start "Loop Engineering - Claude Activity" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0watch.ps1"
venv\Scripts\python.exe -u "develop\loop-engineering\loop_engineering.py" %RUNARGS%
set EXITCODE=%errorlevel%
goto :hold

:with_args
venv\Scripts\python.exe -u "develop\loop-engineering\loop_engineering.py" %*
set EXITCODE=%errorlevel%
goto :hold

:cancelled
echo.
echo [run.bat] Cancelled - nothing was started.
set EXITCODE=0

:hold
:: Keep the console open when launched by double-click from Explorer
:: (cmdcmdline then contains this script's full path; in a real terminal it doesn't).
echo %cmdcmdline% | find /i "%~f0" >nul && (
    echo.
    echo [run.bat] Run finished with exit code %EXITCODE%.
    echo [run.bat] Press any key to close this window.
    pause >nul
)
endlocal & exit /b %EXITCODE%
