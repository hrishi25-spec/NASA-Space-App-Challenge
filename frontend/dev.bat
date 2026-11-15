@echo off
rem Dev helper: runs the Vite dev server in this window (host/port come from vite.config.js).
cd /d "%~dp0"
node node_modules\vite\bin\vite.js
