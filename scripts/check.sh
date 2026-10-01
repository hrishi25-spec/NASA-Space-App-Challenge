#!/usr/bin/env bash
# The one command that must pass before a review — the same checks CI runs:
# the backend test suite, then the frontend production build (which runs the
# lazy-export guard first).  Dependency setup is the launcher's job: run.py.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== backend tests =="
cd firecal/backend
if [ -x ".venv/bin/python" ]; then
    .venv/bin/python -m pytest -q
elif [ -x ".venv/Scripts/python.exe" ]; then
    .venv/Scripts/python.exe -m pytest -q      # Git Bash on Windows
else
    PY="$(command -v python3 || command -v python || true)"
    if [ -z "$PY" ]; then
        echo "ERROR: no python3/python on PATH — run python run.py once to create the venv."
        exit 1
    fi
    "$PY" -m pytest -q
fi

echo
echo "== frontend build =="
cd ../frontend
npm run build

echo
echo "OK — backend tests and frontend build both passed."
