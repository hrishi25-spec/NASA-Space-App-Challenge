# 0002 — One image, one process, one port

- **Date:** 2026-10-01
- **Status:** Accepted

## Context

The console is two runtimes: a Vite build that the browser downloads, and a FastAPI process that holds the dataset. Until now the only supported way to run it was `run.py`, which starts both locally and lets Vite's dev proxy carry `/api` to the API — development ergonomics, not a deployment story. A container image makes the project demonstrable on any machine, and the question was where the console should be served from.

Three shapes were available:

1. **Two containers** (nginx serving `dist/`, plus the API) with compose — the conventional split.
2. **One container, two processes** (nginx and uvicorn under a supervisor) — one artifact, but a process manager and two logs to reason about.
3. **One container, one process**: uvicorn serves the built console as static files and answers the API.

## Decision

**Option 3.** The `Dockerfile` is multi-stage: a Node stage runs `npm ci && npm run build` and is discarded; the runtime stage installs the backend requirements, copies `firecal/backend/` and copies `dist/` to `firecal/frontend/dist`, so the paths stay repo-relative and the image serves the console through exactly the code path a local `npm run build` produces.

Two small pieces of the API make that work, both at the end of `main.py`:

- **`/api` prefix strip.** In development Vite proxies `/api` and removes the prefix; with no proxy, the browser's `/api/...` calls arrive with the prefix attached. Middleware removes it before routing. No endpoint starts with `/api`, so nothing can be shadowed, and the unprefixed paths keep working for curl, the tests and the launcher's readiness probe — one regression test asserts both spellings agree.
- **A conditional console mount.** `dist/` is mounted at `/` when it exists, and skipped when it does not, so a development checkout (where Vite serves the console) behaves exactly as before.

## Consequences and deviations

- **One artifact, one port, no proxy config.** `docker run -p 8000:8000` is the whole deployment.
- **The dev topology still differs from production** (two servers, Vite's proxy versus the API's prefix strip). The regression test is what keeps the two honest about the `/api` contract; a two-container layout would have deleted that difference to keep instead.
- **The API now serves static files**, so a bug in the mount could shadow a route. Route order protects the API docs (`/docs`, `/openapi.json` are registered first, so the trailing mount cannot swallow them) and both were verified against a running server, not just by reading the framework.
- **No volume, no database.** The dataset is a process-global `DataFrame` (see [PRD §8](../PRD.md#8-architecture)); an upload spools through `/tmp` and is parsed in memory. Restarting the container therefore clears the dataset, which is the intended behaviour and why the image ships no state directory.
- **The container runs as a non-root user** with no writable application directory, and the healthcheck reuses the `/meta` readiness probe the launcher already uses (slim images ship no curl).
- **The image is ~1.2 GB**, almost all of it the scientific stack (NumPy, SciPy, scikit-learn) that the clustering, biome and percentile work runs on. Trimming it means changing the clustering backend, which is a product decision rather than a packaging one, so the size is documented instead of hidden.
- **Not verified by CI yet.** This environment has no container runtime, so the image was validated by building the console, running that exact filesystem layout locally and exercising it. A build job belongs in `.github/workflows/ci.yml` before anyone relies on the image in a release.
