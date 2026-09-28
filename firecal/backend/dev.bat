@echo off
rem Dev helper: runs the FastAPI backend in its own minimized window (survives the shell that launched it).
cd /d "%~dp0"
python -m uvicorn main:app --port 8000
