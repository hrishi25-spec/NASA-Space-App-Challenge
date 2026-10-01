@echo off
rem The same checks CI runs: backend tests, then the frontend production build.
rem Dependency setup is the launcher's job: run.py.
setlocal
cd /d "%~dp0.."

echo == backend tests ==
cd firecal\backend
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pytest -q
) else (
    echo NOTE: no backend venv yet - run "python run.py" once to create it.
    python -m pytest -q
)
if errorlevel 1 goto fail

echo.
echo == frontend build ==
cd ..\frontend
call npm run build
if errorlevel 1 goto fail

echo.
echo OK - backend tests and frontend build both passed.
endlocal & exit /b 0

:fail
echo.
echo FAILED - see the output above.
endlocal & exit /b 1
