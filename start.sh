#!/usr/bin/env bash
# One-command dev startup: backend :8000 + frontend :5173. Ctrl+C stops both.
set -e
cd "$(dirname "$0")"

# first-run dependency install (recreates the venv if a system Python
# upgrade left it broken — common on rolling releases like Arch)
[ -d firecal/backend/.venv ] || python3 -m venv firecal/backend/.venv
if ! firecal/backend/.venv/bin/python -c "import fastapi" 2>/dev/null; then
    echo "Installing backend packages..."
    if ! firecal/backend/.venv/bin/pip install -q -r firecal/backend/requirements.txt; then
        echo "pip failed — recreating the virtualenv (system Python may have been upgraded)"
        rm -rf firecal/backend/.venv
        python3 -m venv firecal/backend/.venv
        firecal/backend/.venv/bin/pip install -q -r firecal/backend/requirements.txt
    fi
fi
[ -d firecal/frontend/node_modules ] || (cd firecal/frontend && npm install --no-audit --no-fund)

(cd firecal/backend && .venv/bin/uvicorn main:app --port 8000) &
BACK=$!
(cd firecal/frontend && npm run dev) &
FRONT=$!
trap 'kill $BACK $FRONT 2>/dev/null' EXIT INT TERM

echo "backend  http://localhost:8000"
echo "frontend http://localhost:5173  <- open this"

# wait for the backend before handing the URL to the user
if command -v curl >/dev/null 2>&1; then
  printf "waiting for backend"
  for _ in $(seq 1 30); do
    curl -sf -m 2 http://localhost:8000/meta >/dev/null 2>&1 && { echo " ✓"; break; }
    printf "."; sleep 1
  done
  curl -sf -m 2 http://localhost:8000/meta >/dev/null 2>&1 || \
    echo " ✗ backend did not come up — check its output above"
fi

wait
