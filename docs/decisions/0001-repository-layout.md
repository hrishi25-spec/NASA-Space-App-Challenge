# 0001 — Repository layout follows the standard, with documented deviations

- **Date:** 2026-10-01
- **Status:** Accepted

## Context

A stranger who clones this repository should be able to run it and find the code they need in minutes. A review against the repository-organization standard found the root carrying loose reference documents beside the source, several links left stale by an earlier partial docs move, and no written record of why the tree looks the way it does.

## Decision

- **The root is a lobby.** It holds the front-door files (`README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `.gitignore`, `.env.example`, `.editorconfig`), the launchers (`run.py`, `start.sh`, `start.bat`) and four directories: `docs/`, `scripts/`, `firecal/`, `.github/`.
- **Reference documents live in `docs/`**, kebab-cased (`nasa-space-apps-challenge.md`, `modis-viirs-integrated-review.md`), with [docs/README.md](../README.md) as their index.
- **Decisions are recorded here**, numbered, newest last.
- **`scripts/check.sh` / `scripts/check.bat` are the interface to automation** — the same checks CI runs (backend tests, frontend build).
- **Generated output stays out of git** (`__pycache__/`, `.venv/`, `node_modules/`, `dist/`), and the local `github setup/` scaffold is ignored rather than tracked.

## Consequences and deviations

- **No LICENSE yet** — a deliberate, reversible choice. Unlicensed work is only usable locally, so this must be revisited before any public release or reuse.
- **No CODEOWNERS** — there are no teams to map folders to yet; writing one would be fiction. Add it when maintainers are named.
- **CI keeps two parallel jobs** (backend, frontend) instead of one call into `scripts/check.*`: the two toolchains install independently and parallelism halves the wall-clock. Both jobs run the same commands the local script runs.
- **`firecal/backend` and `firecal/frontend` stay side by side without workspace tooling** — one product, two runtimes (FastAPI and Vite). Splitting them further would be folder churn with no benefit to a reader, so the layout is documented instead.
- **The backend is not a Python package yet** (`pyro_harmony/`) — move code when you touch it, not in a cosmetic pass. This ADR is the place to record it when it happens.
- **`github setup/` is local-only.** It is a reference scaffold, not part of the product, so it is gitignored and never committed.
