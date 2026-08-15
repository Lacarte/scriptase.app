@echo off
:: Scriptase -- the one-command add-a-provider path (step 12.5).
::
::   new-provider.bat <domain> <provider_id> [--kind <kind>] [--label <label>]
::
:: Examples:
::   new-provider.bat tts my_provider --kind cloud
::   new-provider.bat image my_renderer --kind extension
::   new-provider.bat                          show domains, kinds, and options
::
:: Scaffolds the package, runs the contract tests it generates, and regenerates
:: the provider docs from the live hub. Adding a provider creates and registers
:: its package alone -- no node, adapter, route, or shared UI component changes.
::
:: Lives beside start.bat because bin\ is gitignored for fetched binaries. All
:: real logic lives in scriptase\providers\scaffold.py, where the tests reach
:: it; tools\new-provider.ps1 only resolves the venv interpreter.

setlocal
cd /d "%~dp0"
title Scriptase - new provider

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\new-provider.ps1" %*
set "EXITCODE=%ERRORLEVEL%"

endlocal & exit /b %EXITCODE%
