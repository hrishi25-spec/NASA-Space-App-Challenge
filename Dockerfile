# syntax=docker/dockerfile:1
# Pyro-Harmony in one image: the Vite console is built in a Node stage, then served by the same
# uvicorn that answers the API. One process, one port, no proxy to configure -- the reasoning is
# in docs/decisions/0002-single-image-deployment.md.
#
#   docker build -t pyro-harmony .
#   docker run --rm -p 8000:8000 --env-file .env pyro-harmony      # FIRMS_MAP_KEY is optional
#   open http://127.0.0.1:8000
#
# `npm run build` fires the repo's prebuild guards first, so a broken lazy import or a broken
# adaptive-detail policy fails the image at build time rather than in the browser.

# ---------------------------------------------------------------- console (discarded)
# Debian, not Alpine: this stage only produces dist/, so its size does not matter, and glibc
# keeps the native rollup/esbuild binaries on the path npm expects for the lockfile in the repo.
FROM node:22-slim AS console
WORKDIR /build
# Manifest and lockfile first: this layer is cached until one of them changes.
COPY firecal/frontend/package.json firecal/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY firecal/frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim

# scikit-learn and scipy link against the system OpenMP runtime; it is ~100 KB and its absence
# is the classic "image builds, then dies at import". Nothing else is needed at runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements before source, for the same caching reason as the lockfile above.
COPY firecal/backend/requirements.txt firecal/backend/requirements.txt
RUN pip install --no-cache-dir -r firecal/backend/requirements.txt

# Source, then the built console. The paths stay repo-relative because the API finds the console
# at <backend>/../frontend/dist -- exactly the layout a local `npm run build` produces, so the
# image and a development checkout serve the console through the same code path.
COPY firecal/backend/ firecal/backend/
COPY --from=console /build/dist firecal/frontend/dist

# Unbuffered so `docker logs` shows the API's output as it happens rather than at exit.
ENV PYTHONUNBUFFERED=1 PORT=8000
EXPOSE 8000

# The app's own working directory, set before dropping privileges so nothing has to be created
# as the unprivileged user at start-up.
WORKDIR /app/firecal/backend

# The API keeps no state on disk: an upload spools through /tmp and is parsed in memory, and the
# loaded dataset lives in the process. So there is no volume, no writable data directory, and no
# reason to be root.
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --create-home app
USER app

# `/meta` is the readiness probe the launcher already uses, and python is the one HTTP client
# this image is guaranteed to have (slim ships no curl).
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD ["python", "-c", "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/meta', timeout=4).status < 500 else 1)"]

# `exec` so uvicorn is PID 1 and receives SIGTERM directly: without it `docker stop` waits out
# the full grace period before killing the container.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
