@echo off
rem Dev helper: runs the FastAPI backend in this window.
cd /d "%~dp0"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
