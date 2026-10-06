@echo off
rem The same checks CI runs: doc figures, doc links and that guard's own
rem test suite, backend tests, then the frontend build.
rem Dependency setup is the launcher's job: run.py.
setlocal
cd /d "%~dp0.."

echo == doc figures ==
if exist "firecal\backend\.venv\Scripts\python.exe" (
    "firecal\backend\.venv\Scripts\python.exe" scripts\check-doc-figures.py
) else (
    python scripts\check-doc-figures.py
)
if errorlevel 1 goto fail

echo.
echo == doc links ==
if exist "firecal\backend\.venv\Scripts\python.exe" (
    "firecal\backend\.venv\Scripts\python.exe" scripts\check-doc-links.py
) else (
    python scripts\check-doc-links.py
)
if errorlevel 1 goto fail

echo == doc-link self-test ==
if exist "firecal\backend\.venv\Scripts\python.exe" (
    "firecal\backend\.venv\Scripts\python.exe" scripts\test_check_doc_links.py
) else (
    python scripts\test_check_doc_links.py
)
if errorlevel 1 goto fail

echo.
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
echo OK - doc figures, doc links, the doc-link self-test, backend tests and frontend build all passed.
endlocal & exit /b 0

:fail
echo.
echo FAILED - see the output above.
endlocal & exit /b 1
