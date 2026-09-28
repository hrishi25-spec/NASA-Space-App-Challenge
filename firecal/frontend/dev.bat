@echo off
rem Dev helper: runs the Vite dev server in its own minimized window (survives the shell that launched it).
cd /d "%~dp0"
node node_modules\vite\bin\vite.js --host
