@echo off
:: Scriptase launcher.
::
:: Double-click to provision and run in dev mode, or from a terminal:
::   start.bat                 dev: Flask + Vite with hot reload
::   start.bat -Mode prod      build the frontend, serve it from Flask
::   start.bat -Mode setup     install dependencies only, do not launch
::   start.bat -NoBrowser      do not open a browser
::   start.bat -NoPull         skip the fast-forward pull from origin
::   start.bat -Reinstall      force a dependency reinstall
::
:: All real logic lives in tools\launch.ps1 -- this file only forwards to it.
:: Closing this window terminates the backend and the dev server together.

setlocal
cd /d "%~dp0"
title Scriptase

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\launch.ps1" %*
set "EXITCODE=%ERRORLEVEL%"

:: Keep the window open when launched from Explorer (cmdcmdline contains this
:: script's path); in a real terminal, exit quietly so scripting still works.
echo %cmdcmdline% | find /i "%~f0" >nul && (
    echo.
    echo [start.bat] Exited with code %EXITCODE%.
    pause >nul
)

endlocal & exit /b %EXITCODE%
