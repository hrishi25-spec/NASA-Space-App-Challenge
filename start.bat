@echo off
setlocal
cd /d "%~dp0"
title Burning Activity Calendar

rem --- checks ---
where npm >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js not found. Install the LTS from https://nodejs.org/ and retry.
    pause
    exit /b 1
)

if not exist "firecal\backend\.venv\Scripts\python.exe" (
    echo Creating Python virtualenv...
    py -3 -m venv "firecal\backend\.venv" 2>nul
    if errorlevel 1 python -m venv "firecal\backend\.venv" 2>nul
)
if not exist "firecal\backend\.venv\Scripts\python.exe" (
    echo ERROR: Python not found. Install 3.10+ from https://www.python.org/downloads/ ^(tick "Add to PATH"^) and retry.
    pause
    exit /b 1
)

rem --- first-run dependency install ---
"firecal\backend\.venv\Scripts\python.exe" -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo Installing backend packages, this may take a minute...
    "firecal\backend\.venv\Scripts\python.exe" -m pip install -q -r firecal\backend\requirements.txt
)

if not exist "firecal\frontend\node_modules" (
    echo Installing frontend packages...
    pushd firecal\frontend
    call npm install --no-audit --no-fund
    popd
)

rem --- start both (shared console: logs appear here) ---
echo.
echo   backend  http://localhost:8000
echo   frontend http://localhost:5173  ^<- open this
echo.
echo   Stop: close this window, or press Ctrl+C then Y
echo.
start /b "" cmd /c "cd /d firecal\backend && .venv\Scripts\python.exe -m uvicorn main:app --port 8000"
start /b "" cmd /c "cd /d firecal\frontend && call npm run dev"

timeout /t 5 /nobreak >nul
start "" http://localhost:5173

rem keep the window open until stopped
timeout /t 86400 /nobreak >nul
