# 🔥 Pyro-Harmony — Burning Activity Calendar · NASA Space Apps 2026

A unified fire-intelligence platform that harmonizes MODIS and VIIRS active-fire hotspots (NASA FIRMS archive CSVs) into a single, consistent **burning activity calendar**: daily fire activity over time for any area of interest, with clusters, anomaly detection, and a 30-day forecast.

Beyond the base calendar, it implements the four **Pyro-Harmony** poster pillars:

1. **Multi-decadal burning-activity climatology** — day-of-year heatmap matrix plus a 10th/50th/90th/95th percentile envelope that exposes seasonal onset, peak burning days, and cessation.
2. **The "Sensor Transition Illusion" diagnostic** — quantifies and removes the artificial post-2012 surge caused by VIIRS 375 m deployment, using ESFP footprint scaling and cross-sensor calibration (R², RMSE).
3. **Live FIRMS ingestion + hotspot clustering** — pulls 24 h NRT CSVs (MODIS C6.1, VIIRS S-NPP/NOAA-20/NOAA-21) from NASA's open endpoints, harmonizes on the fly, and DBSCAN-clusters them.
4. **Incident Commander wildfire briefing** — flags consecutive critical days (z ≥ 2σ), stratifies fuel biomes via K-means, assigns a threat level, and generates exportable (Markdown/clipboard) recommendations.

Headline metrics shown in the UI strip: **HFII** (harmonized fire intensity, Σ FRP·ESFP), **ESFP** (equivalent standard pixels, nadir-normalized footprints), hotspot count, and record span.

Built for the [2026 NASA Space Apps Challenge](https://spaceappschallenge.org/) (Earth Science / Software). The full challenge brief and the four reference research papers are in [`Nasa Space app challenge.md`](./Nasa%20Space%20app%20challenge.md).

## Table of contents

- [Why](#why)
- [Quick start](#quick-start)
- [Getting FIRMS data](#getting-firms-data)
- [What you see](#what-you-see)
- [Method](#method)
- [API reference](#api-reference)
- [Project structure](#project-structure)
- [Tech stack](#tech-stack)
- [Design system](#design-system)
- [Running on low-end hardware](#running-on-low-end-hardware)
- [Testing & CI](#testing--ci)
- [Configuration & limits](#configuration--limits)
- [Security notes](#security-notes)
- [Troubleshooting](#troubleshooting)

Planning and feature-level detail lives in [PRD.md](./PRD.md).

## Why

Satellites have tracked active fires for 20+ years, but the record is split across sensors
(VIIRS 375 m vs MODIS 1 km) whose detections cannot be compared directly. This app
normalizes them into one daily timescale so scientists, land managers, and responders can
see when and where burning has happened — and spot unusual seasons early.

## Quick start

First, clone the repository:

```bash
git clone https://github.com/hrishi25-spec/NASA-Space-App-Challenge.git
```

Then one command installs dependencies (first run) and starts everything. The launcher
is plain standard-library Python, so Windows, macOS and Linux all run the same code:

| OS | Command |
|---|---|
| Any | `python run.py` |
| Linux / macOS | `./start.sh` — a thin wrapper around `run.py` |
| Windows | double-click `start.bat` — a thin wrapper around `run.py` |

`run.py` creates the backend virtualenv, installs whatever is missing (Python and npm),
starts the API on `127.0.0.1:8000` and the dev server on `127.0.0.1:5173`, waits until
both answer, then opens **http://localhost:5173** for you. Ctrl+C stops both servers,
including the node/esbuild children. Add `--no-open` to skip the browser.

Click **Load demo** — 5 years of synthetic MODIS + VIIRS data appears in ~1 second.
The launcher needs no shell beyond that: no bash on Windows, no `.bat` on Linux.

<details>
<summary>Manual run (two terminals, Linux/macOS)</summary>

```bash
# Terminal 1 — backend on :8000
cd firecal/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — frontend on :5173
cd firecal/frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` → `127.0.0.1:8000` automatically
(`firecal/frontend/vite.config.js`). Bind `127.0.0.1` rather than leaving it to
`localhost`: on Node 17+ that name can resolve to `::1` first, which the proxy would
then miss.
</details>

<details>
<summary>Windows manual run (two terminals)</summary>

`start.bat` does all of this for you — use these steps only if you prefer running the
servers yourself. Open two PowerShell (or cmd) windows.

```powershell
# Terminal 1 — backend on :8000
cd firecal\backend
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — frontend on :5173
cd firecal\frontend
npm install
npm run dev
```

Notes for Windows:

- Use `py -3` (standard Python launcher); if it's missing, use `python -m venv .venv`.
- Run uvicorn as `.venv\Scripts\python -m uvicorn ...` — more reliable than the
  `uvicorn.exe` shim.
- If PowerShell blocks scripts, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
  once, or use **cmd** instead (commands are identical).
- Stop both with Ctrl+C in each terminal.

The Vite dev server proxies `/api` → `:8000` automatically (`firecal/frontend/vite.config.js`).
</details>

### Requirements

- Python 3.10+ (CI runs 3.12) — <https://www.python.org/downloads/> (check **Add to PATH**; the `py -3` launcher comes with it)
- Node.js 18+ (CI runs 20) — <https://nodejs.org/> (LTS is fine; npm is included)

## Getting FIRMS data

1. Download archive CSVs from <https://firms.modaps.eosdis.nasa.gov/download/> — pick
   **MODIS C6.1** and/or **VIIRS SNPP / NOAA-20**, same country/region so the sensors overlap.
2. Click **Upload FIRMS CSVs** in the app (multiple files at once are fine).
3. For **anomalies** and the **forecast**, upload **more than one year** of data.

You can also generate realistic fake files instead: run `python demo.py` in
`firecal/backend/` to write `demo_modis.csv` / `demo_viirs.csv`, then upload them like
real FIRMS files (they exercise the exact same parsing pipeline).

No files at hand? The UI's **Load demo** button loads a 2020–2024 synthetic set, and
**Load 2002–2024 demo** loads a 23-year transition dataset (MODIS-only era → VIIRS
ramp-up after 2012) that makes the Sensor Transition Illusion visible: raw detections
surge after 2012 while the harmonized record stays flat.

## What you see

| Panel | What it does |
|---|---|
| **Hero stats strip** | HFII (Σ FRP·ESFP), equivalent standard pixels (ESFP), hotspots harmonized, record span. |
| **Burning calendar** | GitHub-style heatmap: one row per year, one cell per day, color = harmonized daily detections. A **Year** selector narrows it to a single-year calendar. Click any day to inspect it. |
| **Map** | One camera that morphs a **3D Earth globe** into a flat map as you zoom (the badge tracks `3D GLOBE → TRANSITION → 2D MAP`); scroll in past the transition for the flat view, or press **Globe view** to fly back. Detections for the selected day (±1/3/7/14 d span) — **MODIS coral, VIIRS amber, live points pale gold** — plus soft-sand DBSCAN cluster polygons, on either **Satellite** imagery or the colour **Terrain** basemap (both toggles sit with the other view controls in the top-right). The bottom-left chip is a pure readout (`day · hotspots · clusters · MW`) so it never covers the Esri attribution. Live-feed points/polygons overlay when pulled. Use **Select area** and click two corners to draw a bounding box; every panel then filters to it. |
| **Anomalies & critical periods** | A click-through list of anomalous days (z-score vs the same ±7-day window in other years) and the months running above mean + 1σ flagged as *critical*. |
| **Incident Commander briefing** | Threat level (Low/Watch/Elevated/Critical) with its score, record mean and last-30-days readout, then the full report split across **four sub-tabs** — Situation, Critical streaks, Fuel types, Actions — each with a count badge so you can see what is inside before opening it. Streak rows jump the map to that window; **Copy MD** exports the whole briefing. The right-rail card keeps the compact headline version. |
| **Last year + 30-day forecast** | Line chart of the trailing 365 days with the forecast appended, now with an Observed/Forecast legend and the fitted method named. |
| **Seasonal climatology** | Day-of-year percentile envelope (10/50/90/95) with **Peak day** and **Fire season** (onset → cessation) called out above the chart. |
| **Sensor Transition Illusion** | Per-sensor raw detections vs the harmonized line; observed vs adjusted post-2012 growth, artifact removed, calibration stats. In the 2002–2024 demo this reads +102.4 % raw → +17 % harmonized, 85.4 pp of artifact. |
| **Live FIRMS 24h feed** | Region selector; pulls MODIS + 3 VIIRS NRT feeds, harmonizes, clusters, and overlays them on the map. |

## Method

- **Harmonization** — unified confidence scale (MODIS 0–100; VIIRS `l/n/h` → 20/60/90);
  detections below confidence 30 dropped for both sensors; UTC timestamps from
  `acq_date` + `acq_time`; duplicate rows removed on `(lat, lon, time, sensor)`.
  Because VIIRS 375 m finds more fires than MODIS 1 km, per-sensor daily counts are
  **rescaled to the best-covered sensor over their overlap period** before summing.
- **ESFP / HFII** — every detection keeps its FIRMS `scan`/`track` footprint; the
  nadir-normalized expansion ratio (≈10× at MODIS scan edge vs ≈2–3× for VIIRS) yields
  *equivalent standard pixels*, and HFII = Σ FRP·ESFP (standardized radiative energy).
- **Climatology** — rolling 15-day percentiles per day-of-year across all years;
  onset/cessation = first/last DOY where the 95th percentile exceeds 50 % of its max.
- **Illusion diagnostic** — pre/post-2012 daily means, VIIRS scaling from collocated
  FRP + ESFP ratios, daily-count correlation (R²) and RMSE in the 2012–2015 overlap.
- **Briefing** — z-scores vs the same ±7-day DOY window in other years (vectorized),
  consecutive-day streaks (z ≥ 2σ, 2-day gap tolerance), K-means (k=4) fuel-biome
  stratification on position + FRP after Zhang et al. (2020), threat score
  `max_z + 0.5·streak_days + min(2, recent_mean/25)`, rule-based recommendations.
- **Calendar** — daily harmonized counts per year, filterable by drawn bounding box and date range.
- **Clusters** — DBSCAN in projected metres + scaled time (eps 550 m, minPts 3, 12 h
  window), rendered as convex-hull polygons; parameters from the GISTDA Thailand paper
  (GIS-IDEAS 2024).
- **Anomalies** — z-score of each day against the climatology of the same ±7-day window
  in *other* years; critical months = monthly mean above mean + 1σ.
- **Forecast** — 30-day LSTM (PyTorch, optional) with seasonal sin/cos day-of-year
  features; without `torch` it falls back to scaled seasonal climatology.

## API reference

All routes are relative to the backend (`http://localhost:8000`, or `/api` through the
dev proxy). Interactive docs at `/docs` (Swagger UI).

| Method & path | Parameters | Description |
|---|---|---|
| `POST /upload` | multipart `files[]`, `demo_transition` (bool) | Add FIRMS CSVs (200 MB/file, 400 MB/request, ≤20 files). HTTP 400 with the sanitised filename and reason on bad files, HTTP 413 if the request declares more than 400 MB. `demo_transition=true` replaces the dataset with the 2002–2024 demo — the poster dataset is loaded by this flag, **not** by naming a file `demo_transition.csv`. |
| `POST /demo` | `mode=standard\|transition` | Replace data with the synthetic 2020–2024 set, or the 2002–2024 transition set. |
| `DELETE /data` | — | Clear all loaded data. |
| `GET /meta` | — | `{n, start, end, sensors, bounds, hfi, esfp, pixels}` or `{"n": 0}`. |
| `GET /climatology` | `bbox`, `window` (3–45), `step` (1–30) | Per-year DOY series, DOY percentile envelope (p10/50/90/95), peak/onset/cessation summary. |
| `GET /diagnostic` | `bbox` | Sensor Transition Illusion: per-year raw counts per sensor, harmonized totals, observed/adjusted post-2012 growth, calibration (R², RMSE, FRP & ESFP ratios). |
| `GET /live` | `region`, `bbox`, `crop`, `eps`, `min_pts`, `hours` | Pull FIRMS 24h NRT feeds (region name with underscores, e.g. `South_America`), harmonize + cluster on the fly. `region` is allowlisted because it is interpolated into the outbound URL (HTTP 400 otherwise), at most two ingests run at once (HTTP 429), and HTTP 502 means no feed was reachable. |
| `GET /briefing` | `bbox`, `z` (1–5), `min_days`, `format=json\|markdown` | Threat level, critical streaks, fuel biomes, recommendations. Markdown for incident hand-off. |
| `GET /calendar` | `bbox`, `start`, `end` | Daily rows: `{date, count, raw, frp}`. |
| `GET /points` | `bbox`, `start`, `end`, `limit` (1–20000) | Map points, randomly sampled if over the limit. |
| `GET /clusters` | `bbox`, `start`, `end`, `eps` (10–5000), `min_pts` (1–100), `hours` (0.5–720) | DBSCAN clusters, top 300 by size, each with a convex `hull`. |
| `GET /anomalies` | `bbox`, `z` (0.5–10) | `{anomalies[], critical[], monthly[]}`; needs >1 year of data. |
| `GET /forecast` | `bbox`, `horizon` (1–90), `epochs` (1–200) | `{model, forecast[]}`; needs ≥120 days. |

`bbox` format: `minlat,minlon,maxlat,maxlon` (e.g. `bbox=17,98,20,101`).

## Project structure

```
.
├── README.md                       ← you are here
├── PRD.md                          ← product requirements: features, acceptance criteria, status
├── Nasa Space app challenge.md      ← challenge brief + 4 reference papers
├── run.py                          ← the one-command launcher (any OS, stdlib only)
├── start.sh                        ← thin wrapper: ./start.sh (Linux/macOS)
├── start.bat                       ← thin wrapper: start.bat (Windows)
├── .github/workflows/ci.yml        ← CI (pytest + frontend build)
└── firecal/
    ├── backend/
    │   ├── main.py                 ← FastAPI app: endpoints, harmonization, analytics
    │   ├── demo.py                 ← synthetic FIRMS generator (2020–24 + 2002–24 transition)
    │   ├── test_smoke.py           ← 19-test API smoke suite (encodings, gzip, cache invalidation)
    │   ├── test_security.py        ← 20-test hardening suite (URL allowlist, upload caps, CORS)
    │   ├── requirements.txt        ← runtime deps (with security floors)
    │   └── requirements-dev.txt    ← + pytest, httpx (for tests)
    └── frontend/
        ├── package.json            ← `prebuild` runs the lazy-export guard below
        ├── vite.config.js          ← dev proxy /api → :8000
        ├── scripts/
        │   └── check-lazy-exports.mjs ← fails the build if a React.lazy import cannot resolve
        └── src/
            ├── App.jsx             ← layout: heatmap, map, drawer tabs (lazy-loads the rest)
            ├── MissionMap.jsx      ← MapLibre stage: 3D globe ⇄ flat map, clusters, picking
            ├── charts.jsx          ← chart tabs (lazy: pulls Recharts only when opened)
            ├── ForecastChart.jsx   ← forecast line chart (lazy)
            ├── panels.jsx          ← chart-free pillars: hero stats, live feed, briefing
            ├── lib.js              ← API client (memoized), heat ramp, formatters
            ├── main.jsx
            └── styles.css          ← "ember dusk" design system + the letter-case contract
```

## Tech stack

| Layer | Choices |
|---|---|
| Backend | FastAPI, pandas, NumPy, scikit-learn (DBSCAN, K-means), SciPy (convex hull), requests (live FIRMS), optional PyTorch (LSTM) |
| Frontend | React 18, Vite 5, MapLibre GL 6 (one camera morphing a 3D globe into a flat map), Recharts |
| Tooling | `check-lazy-exports.mjs` (zero-dep build guard, wired as `prebuild`) |
| Data | NASA FIRMS archive CSVs (MODIS C6.1, VIIRS SNPP/NOAA-20) |
| CI | GitHub Actions — pytest on Python 3.12, `npm ci` + build on Node 20 |

## Design system

The UI is a soft-UI (neumorphic) surface set in one place, `styles.css`. Each control is
extruded from the surface colour by a light shadow from the top-left and a dark one from
the bottom-right; anything "pressed" inverts to an inset shadow of the same pair. Shadow
blur radii are deliberately modest, because large-blur shadows are re-rasterized as the
map animates over them.

**"Ember dusk" palette.** A warm charcoal-teal base rather than cold navy, with every
accent desaturated one step below full saturation — no neon — while the amber still clears
roughly 7:1 against the base. Soothing for a long shift, instantly legible at a glance.

| Token | Value | Role |
|---|---|---|
| `--bg` / `--surface` | `#141a1d` / `#1a2226` | page base and the soft-UI material |
| `--sh-dark` / `--sh-lite` | `#080b0d` / `#2a343a` | the shadow pair that does all the extruding |
| `--fg` / `--mut` | `#d6e0e2` / `#8a9aa0` | body text and secondary text |
| `--acc` | `#f2a65a` | ember amber — primary accent, fire signal, median line |
| `--acc2` | `#7fd1c8` | soft teal — secondary accent, harmonized/model output, selection box |
| `--ok` / `--warn` / `--bad` | `#8fd6a4` / `#e9c46a` / `#e88a8a` | jade, sand, soft coral |

Colour carries meaning consistently across the app: **MODIS is coral, VIIRS is amber, live
feed is pale gold, clusters are sand, and anything modelled or harmonized is teal** — the
same colours in the map legend, the diagnostic bars, and the forecast lines. The heat ramp
runs from the surface colour through warm browns to a pale sand, so an idle day recedes
into the panel instead of reading as a low value.

**Letter-case contract.** Labels, headings, buttons, tabs, legend items and micro-labels
are uppercased *by CSS*, so the strings in the source stay readable and capitalisation lives
in exactly one place. Prose, hints and values stay in sentence case. Acronyms (HFII, ESFP,
FRP, MODIS, VIIRS, DBSCAN, FIRMS, MW) are always written in full caps, and the statistic
symbol stays lowercase **z**. The contract is documented at the top of `styles.css`; the one
sanctioned exception is an `h3` subtitle, which reads as prose.

## Running on low-end hardware

The app targets machines with a weak CPU, little RAM and no discrete GPU, so it is
built to stay responsive rather than to look impressive in a profiler.

**First paint is small.** MapLibre (~280 KB gzipped) and Recharts (~109 KB gzipped) are
code-split behind `React.lazy`, so the console shell paints after loading only the app
chunk plus React — about **170 KB raw / 55 KB gzipped**, against 2,078 KB before the
split. Measured cold: DOMContentLoaded **1,768 ms → 283 ms**, requests **44 → 14**. The
map engine is fetched when the map mounts; the charting library only when a chart tab is
opened — and hovering or focusing a drawer tab starts that download early, so the click
lands on an already-warm module. `manualChunks` is a function over the module path rather
than an object of package names: the object form matched only entry files, which pulled
Recharts back into the first paint.

**Interactions are memoized twice.** The API gzips its JSON (≈4–9× smaller on the
calendar, points and climatology payloads) and each analytics endpoint is memoized
until the dataset changes, so DBSCAN clustering, the K-means briefing and the rolling
percentile climatology are computed once rather than on every click. The frontend keeps
the same responses in memory, so revisiting a day, span or AOI issues no request at all.
The demo generator is cached too, so **Load demo** is instant after the first run.

**Rendering avoids GPU traps.** Raster tiles stop at zoom 16 (deeper zooms upscale) and
fade animation is off, so panning and zooming stop paying per-tile animation costs; the
zoom listener no longer schedules a React render per frame; the scroll background and the
map vignette were rewritten so they don't repaint on every scroll tick. On a machine with
four cores or less, MSAA is disabled and camera moves become instant (`LOW_END` in`MissionMap.jsx`). Redundant UI effects respect `prefers-reduced-motion`.

## Testing & CI

```bash
# 39 tests, ~2 min — starts the app in-process via TestClient
cd firecal/backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q

# Frontend production build (the prebuild step runs the lazy-export guard first)
cd firecal/frontend && npm run build
npm run check:lazy                 # …or run the guard on its own
```

`.github/workflows/ci.yml` runs both on every push to `main` and on pull requests.

**`test_smoke.py` (19)** covers every endpoint end-to-end — demo load, calendar with and
without bbox, points clamping, clusters, climatology envelope, illusion diagnostic on both
demos, briefing JSON + Markdown, live feed (skipped offline when FIRMS is unreachable),
anomalies, forecast — plus error paths (bad bbox → 400, missing-column CSV → 400, valid CSV
merge, clear), the three CSV encodings (UTF-8, cp1252, UTF-16 BOM), gzip on the wire, and
cache invalidation after a dataset change.

**`test_security.py` (20)** pins the input-handling guarantees described under
[Security notes](#security-notes), so they fail loudly if they regress: unknown/traversal/
host-injection `region` values are rejected *without* an outbound fetch, the concurrency
guard returns 429, the request and per-file upload caps and the file-count cap each fire,
a filename cannot summon the demo dataset, reflected filenames come back sanitised, and
CORS grants the local origin but not a hostile one.

**`check-lazy-exports.mjs`** resolves every `React.lazy(() => import(...))` in `src/` and
fails the build when the target has no default export (or a mapped named export does not
exist). This exact mistake — `lazy(() => import("./charts"))` against a module with only
named exports — compiles and builds cleanly, then throws at render time and blanks the page;
no type checker or bundler catches it, so it is checked explicitly.

## Configuration & limits

| Setting | Default | Notes |
|---|---|---|
| `ALLOW_ORIGINS` | local origins | Comma-separated origins; set when deploying so only your frontend can call the API. The dev server proxies `/api`, so the browser is same-origin and needs no grant. |
| Upload size | 200 MB / file, 400 MB / request | Per-file is enforced while reading; the request-wide cap is checked from `Content-Length` before the body is buffered → HTTP 413. |
| Upload count | 20 files / request | Public demo console, no auth: a request carrying 50 files is not a use case. |
| Outbound feed cap | 64 MB | One live FIRMS CSV download; larger responses are abandoned mid-stream. |
| Concurrent live ingests | 2 | Each call is 4 downloads + DBSCAN/K-means; extra callers get HTTP 429 instead of stacking. |
| Region allowlist | 8 FIRMS regions | `region` is interpolated into the outbound URL, so anything off the list → HTTP 400 before any fetch. |
| Row cap | 2,000,000 | Oldest rows are dropped beyond this (in-memory store, no database). |
| Query params | clamped | `limit` ≤ 20000, `eps` ≤ 5000, `epochs` ≤ 200, `horizon` ≤ 90, etc. |
| `torch` | optional | Install for the LSTM forecast; without it you get seasonal climatology. |

## Security notes

The threat model is a public hackathon demo: an anonymous caller can read public NASA
data and can replace the in-memory dataset. What the API does enforce:

- **Client input never selects a URL.** `region` reaches the outbound FIRMS request, so it
  is checked against an allowlist first (400 otherwise). `bbox` is range-validated, and every
  numeric parameter is clamped.
- **Uploads are bounded before they are buffered.** The declared `Content-Length` is rejected
  early, each file is read in 1 MiB slices and abandoned the moment it passes its cap, and a
  request may carry at most 20 files. A size check *after* `await f.read()` would let one
  request park gigabytes in memory first.
- **A filename is data, not a command.** The poster's 2002–2024 dataset is loaded via
  `POST /upload?demo_transition=true`, not by naming a file `demo_transition.csv`.
- **Reflected input is sanitised.** Filenames are stripped of paths, control characters and
  newlines (which would otherwise forge log lines) before appearing in an error body.
- **CORS defaults to the local origins**, not `*`, and is never paired with credentials — with
  no auth and no cookies, `*` only let any visited web page drive `/upload` and `/demo`.
- **Dependency floors** in `requirements.txt` cover the multipart advisories
  (CVE-2024-47874, CVE-2024-53981) that were reachable through `/upload`.

Known gaps, accepted for a prototype and worth closing before real deployment:

- No authentication or rate limiting: any caller can replace the dataset for everyone, and a
  burst of requests still costs CPU. The live-ingest semaphore only stops the worst case.
- The dataset is process-global mutable state; two workers would not share it.
- `npm audit` flags the Vite/esbuild **dev server** (path traversal in `.map` handling and
  cross-origin reads). Neither is in the production bundle; the fix is a major Vite upgrade,
  and the dev server is bound to `127.0.0.1` in the meantime.

## Troubleshooting

- **“Upload failed — could not reach the backend”** — the FastAPI server isn't running
  (start it on :8000) or a wrong CSV returned HTTP 400; the banner shows the exact reason.
- **Anomalies say “Need >1 year of data”** — upload at least ~400 days of CSVs (demo data qualifies).
- **Forecast says “install torch for LSTM”** — expected without PyTorch; numbers still
  show, via the climatology fallback: `pip install torch`.
- **CORS errors after deploying** — set `ALLOW_ORIGINS` on the backend to your frontend's origin.
- **Upload rejected** — check the file has FIRMS columns
  (`latitude, longitude, acq_date, acq_time, confidence`); the error message lists what's missing.
- **`Could not create a virtualenv` on Linux** — the venv module isn't installed:
  `sudo apt install python3-venv` (Debian/Ubuntu), then run the launcher again.
- **`ERROR: Node.js was not found on PATH`** — install the LTS from <https://nodejs.org/>
  and reopen the terminal so `node`/`npm` are on `PATH`.
- **`port 5173 is already in use`** — the launcher still starts and reports the port
  Vite actually chose (e.g. `:5174`); the `/api` proxy keeps working. Close the other
  server if you want the canonical URL back.
- **Upload rejected as “not a readable CSV”** — check the file has FIRMS columns
  (`latitude, longitude, acq_date, acq_time, confidence`). CSV text encodings are
  detected automatically (UTF-8, cp1252/Excel-Windows, UTF-16/Excel-macOS).
- **Nothing at `http://localhost:5173` but the launcher says ready** — your system may
  resolve `localhost` to `::1`; open the `127.0.0.1` URL the launcher prints instead.

---

Data source: [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/). Built for the 2026
NASA Space Apps Challenge.
