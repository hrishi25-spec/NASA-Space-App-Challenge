#!/usr/bin/env bash
# One-command dev startup: backend :8000 + frontend :5173. Ctrl+C stops both.
set -e
cd "$(dirname "$0")"

# first-run dependency install
[ -d firecal/backend/.venv ] || python3 -m venv firecal/backend/.venv
firecal/backend/.venv/bin/python -c "import fastapi" 2>/dev/null || firecal/backend/.venv/bin/pip install -q -r firecal/backend/requirements.txt
[ -d firecal/frontend/node_modules ] || (cd firecal/frontend && npm install --no-audit --no-fund)

(cd firecal/backend && .venv/bin/uvicorn main:app --port 8000) &
BACK=$!
(cd firecal/frontend && npm run dev) &
FRONT=$!
trap 'kill $BACK $FRONT 2>/dev/null' EXIT INT TERM

echo "backend  http://localhost:8000"
echo "frontend http://localhost:5173  <- open this"
wait
