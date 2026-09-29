@echo off
rem One-command dev startup (Windows): backend :8000 + frontend :5173.
rem All the real work lives in run.py so Windows, macOS and Linux share one code path.
setlocal
cd /d "%~dp0"
title Pyro-Harmony

set "PYCMD=python"
rem prefer the py launcher, but only if it really has Python 3
py -3 -V >nul 2>&1 && set "PYCMD=py -3"

%PYCMD% "%~dp0run.py" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo   The launcher exited with code %RC%.
    echo   If Python or Node.js is missing, install them and run this file again:
    echo     Python 3.10+  https://www.python.org/downloads/
    echo     Node.js 18+   https://nodejs.org/
    echo.
    pause
)
endlocal & exit /b %RC%
