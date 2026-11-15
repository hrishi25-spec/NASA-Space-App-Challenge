# 0005 — Flatten the repository layout

- **Date:** 2026-11-15
- **Status:** Accepted

## Context

The repository kept both runtimes inside a `firecal/` wrapper: `firecal/backend/` and
`firecal/frontend/`. The wrapper held no project-level files, configuration or tooling of
its own — it existed only as a parent directory. Every path that crossed it paid for the
extra level (`parents[2]`, `parent.parent.parent`), and the README, contributor guide,
CI workflow, Dockerfile and launcher all had to spell the wrapper out.

## Decision

Remove the wrapper. `backend/` and `frontend/` are now top-level siblings, alongside
`docs/`, `scripts/` and `.github/`. Paths that assumed the old depth were updated to the
new depth; the API still finds the console at `<backend>/../frontend/dist`, so the image
and a local build continue to serve through the same code path.

## Consequences and deviations

- **One less level in every path.** The backend is still not a Python package (see
  [0001](0001-repository-layout.md)); that remains a separate, deliberate move.
- **History is preserved.** The move was done with `git mv`, so `git log --stat` reports
  renames rather than delete/add pairs.
- **The layout is documented once.** The root README, `CONTRIBUTING.md`, `docs/AGENTS.md`
  and `docs/brain.md` now describe the flattened tree, and the path references in the
  Dockerfile, CI workflow and check scripts match it.
