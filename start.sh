#!/usr/bin/env bash
# One-command dev startup (Linux / macOS): backend :8000 + frontend :5173.
# All the real work lives in run.py so Windows, macOS and Linux share one code path.
set -e
cd "$(dirname "$0")"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
    echo "ERROR: Python 3.10+ is required but neither python3 nor python is on PATH."
    echo "Install it from https://www.python.org/downloads/ and retry."
    exit 1
fi

exec "$PY" run.py "$@"
