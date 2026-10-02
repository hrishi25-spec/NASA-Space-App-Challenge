# 🔥 Pyro-Harmony — Burning Activity Calendar · NASA Space Apps 2026

A unified fire-intelligence platform that harmonizes MODIS and VIIRS active-fire hotspots (NASA FIRMS archive CSVs) into a single, consistent **burning activity calendar**: daily fire activity over time for any area of interest, with clusters, anomaly detection, and a 30-day forecast.

Beyond the base calendar, it implements the four **Pyro-Harmony** poster pillars:

1. **Multi-decadal burning-activity climatology** — day-of-year heatmap matrix plus a 10th/50th/90th/95th percentile envelope that exposes seasonal onset, peak burning days, and cessation.
2. **The "Sensor Transition Illusion" diagnostic** — quantifies and removes the artificial post-2012 surge caused by VIIRS 375 m deployment, using the detection ratio measured on days both sensors flew, plus cross-sensor calibration (R², RMSE).
3. **Live FIRMS ingestion + hotspot clustering** — pulls 24 h NRT CSVs (MODIS C6.1, VIIRS S-NPP/NOAA-20/NOAA-21) from NASA's open endpoints, harmonizes on the fly, and DBSCAN-clusters them.
4. **Incident Commander wildfire briefing** — flags consecutive critical days (z ≥ 2σ), stratifies fuel biomes via K-means, assigns a threat level, and generates exportable (Markdown/clipboard) recommendations.

Headline metrics shown in the UI strip: **HFII** (harmonized fire intensity, Σ FRP·ESFP), **ESFP** (equivalent standard pixels, nadir-normalized footprints), hotspot count, and record span.

Built for the [2026 NASA Space Apps Challenge](https://spaceappschallenge.org/) (Earth Science / Software). The full challenge brief and the four reference research papers are in [`docs/nasa-space-apps-challenge.md`](docs/nasa-space-apps-challenge.md).

## Table of contents

- [Why](#why)
- [Quick start](#quick-start)
- [Getting FIRMS data](#getting-firms-data)
  - [Local archives](#local-archives)
- [Training the model](#training-the-model)
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
- [Contributing](#contributing)

Planning and feature-level detail lives in [docs/PRD.md](docs/PRD.md).

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

Then choose a dataset. The console opens on the FIRMS exports it finds in `.data/` —
the same directory `train.py` reads — so every panel is computed from real NASA records, and
opening one is a click rather than a generated stand-in. **Merge all archives** takes every VIIRS
and every MODIS in that directory, every year it covers, into one record. A fresh clone has none
(that directory is ~10 GB and git-ignored), so the standby card points at the upload path
instead.
The launcher needs no shell beyond that: no bash on Windows, no `.bat` on Linux.

<details>
<summary>Docker (one image, one port, no toolchain to install)</summary>

```bash
docker build -t pyro-harmony .
docker run --rm -p 8000:8000 --env-file .env pyro-harmony
# then open http://127.0.0.1:8000
```

The image builds the console (`npm run build`, guards included) and serves it from the same
uvicorn that answers the API — one process, one port, no proxy. `--env-file .env` is optional
and is how you pass `FIRMS_MAP_KEY`. The container keeps no state on disk, so there is nothing
to mount or back up.

</details>

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

0. Already have a folder of exports? Leave them in `.data/` — the console lists
   whatever is there at startup, opens one directly, or merges the lot into one record
   (see [Local archives](#local-archives)).
1. Otherwise download archive CSVs from <https://firms.modaps.eosdis.nasa.gov/download/> — pick
   **MODIS C6.1** and/or **VIIRS SNPP / NOAA-20 / NOAA-21**, same country/region so the
   sensors overlap.
2. Click **Upload FIRMS CSVs** in the app (multiple files at once are fine).
3. For **anomalies** and the **forecast**, upload **more than one year** of data.

Or let the backend pull a real window for you: with a free
[FIRMS MAP_KEY](https://firms.modaps.eosdis.nasa.gov/api/map_key/) in `.env`, **Real 3-day
pull** in the live panel loads 1–5 days straight from the FIRMS area API for the selected
region (or drawn AOI) and merges them into the current record. Without a key the button
says so instead of failing silently — the download path still works offline.

### Local archives

Everything under `.data/` is offered as a dataset: the console
walks both spellings at startup, finds the `fire_archive_*.csv` / `fire_nrt_*.csv` files
NASA's area download writes, and labels each by sensor and kind. Those files are large —
188 KB to 1.87 GB in a typical export — so **opening one reads a bounded slice** rather than
the whole thing: 750,000 rows by default, taken from evenly spaced offsets across the file
instead of from its head, because the opening fortnight of a chronological global export
cannot answer a calendar question. The **Dataset** panel in the left rail then names the file,
its sensor, and how much of it the numbers above came from (`712,800 of ~3,830,728 rows ·
spread`) — a calendar drawn from a sample is a sample, and the console says which sample.

**Or merge the whole directory into one record.** *Merge all N archives* (also the first entry
in the **Local archives…** selector) reads every export at once — every VIIRS, every MODIS,
every year the directory covers — so the console opens on the full record rather than one
file's. The budget is split across the files **by size**, because these exports are wildly
unequal and an even split would spend the budget on a 136 KB file while the 1.87 GB year got
the same few thousand rows; a merge's default budget is the store's own 2,000,000-row cap. On
the reference directory — 15 files, MODIS C6.1 + VIIRS S-NPP/NOAA-20/NOAA-21, ~125M rows,
2023-09-30 → 2026-09-22 — that is **1,799,078 detections over 2023-09-30 → 2026-07-05** in
~37 s, two sensors, a four-year calendar. The Dataset panel lists what each file contributed,
and one unreadable export is skipped and named rather than costing the other fourteen.

Change the budget with `limit=` on the load call (clamped to the same 2,000,000-row ceiling as
the store) or read the head of the file with `spread=false`. On the reference machine a 308 MB
MODIS archive opens in ~6 s and a 1,384 MB file in ~9 s; one archive opens at a time.

> Sensors are counted by **instrument**, not by platform. Suomi NPP, NOAA-20 and NOAA-21 all
> carry the same VIIRS, and the S-NPP exports say `instrument = SNPP` where the others say
> `VIIRS` — so a merged record reports two sensors (MODIS, VIIRS), not four.

You can also generate realistic fake files instead: run `python demo.py` in
`firecal/backend/` to write `demo_modis.csv` / `demo_viirs.csv`, then upload them like real
FIRMS files (they exercise the exact same parsing pipeline). The console itself offers no demo
button — what it shows you is the archive on disk — but `POST /demo` stays a documented
endpoint (`mode=transition` builds the 23-year MODIS→VIIRS record whose numbers the docs and
the test suite quote), and it is the only data source a fresh clone has.

## Training the model

`/forecast` always works: with no checkpoint it fits a climatology to your own record. The
checkpoint is what lets it start from the real NASA archive instead.

```bash
cd firecal/backend
python train.py                # every CSV in the training directory
python train.py --inventory    # list what would be read, and stop
python train.py --limit 200000 # head of each file, for a quick run
```

It streams every `*.csv` under `.data/`, harmonizes
each chunk with the server's own rules, and reduces the whole record to a day-of-year
seasonal shape per 2° cell plus the harmonized daily series — 1.8 MB out of 10 GB in the
reference run, written to `firecal/backend/model/`. Nothing is read into memory whole and
nothing is committed: the archive is 10 GB of local NASA area exports, the checkpoint is
derived from it, and both are in `.gitignore`. Delete `model/` and the API behaves exactly
as it did before. Add `torch` to `requirements.txt` and the same run also fits the LSTM
that `/forecast` warm-starts from.

The forecast panel names which one answered. With a checkpoint (`Seasonal climatology +
archive prior`) the archive's shape is blended into the frame's own season — in log space,
fading out as the frame covers more years itself — because a record of a single fire season
is one sample per day and cannot know its own shape. The reference run read 126 million
detections across 1,089 days and learned what a 2° cell looks like through the year: the
Thai dry-season peak in late March, Amazon burning in September, California's summer in
July.

## What you see

| Panel | What it does |
|---|---|
| **Hero stats strip** | HFII (Σ FRP·ESFP), equivalent standard pixels (ESFP), hotspots harmonized, record span. |
| **Dataset** | What is actually open: the archive file, its sensor and kind, and the slice the numbers came from (`712,800 of ~3,830,728 rows · spread`); after a merge, the archive count, the sensors, the same slice line against the directory's total, and a per-file breakdown of what each export contributed. Present only when the dataset came from `.data/`. |
| **Burning calendar** | GitHub-style heatmap: one row per year, one cell per day, color = harmonized daily detections. A **Year** selector narrows it to a single-year calendar. Click any day to inspect it. |
| **Region presets** | The *Fly to…* picker in the command bar (California, Amazon & Pantanal, Southeastern Australia, Punjab & Haryana, Mediterranean basin) sets the AOI filter, flies the camera to a regional zoom, and fills the **Selection** panel with the region's fuel type, peak season and notable fire years. Every panel then recomputes for that AOI; when an AOI holds no detections the Selection panel says so and offers *Clear area*, because the open archive may simply not cover that box. |
| **Map** | One camera that morphs a **3D Earth globe** into a flat map as you zoom (the badge tracks `3D GLOBE → TRANSITION → 2D MAP`); scroll in past the transition for the flat view, or press **Globe view** to fly back. **Fly to AOI** fits the drawn box, **Reset orbit** returns to the default global attitude, and **Auto-rotate** turns the globe about **Earth's real axis**: the camera tilts to the planet's 23.44° obliquity while the drift runs, so the globe turns the way Earth turns and the north pole traces the small circle it traces from orbit, instead of spinning like a top about a vertical line. The rate is real too — 6°/s, or 3°/s on a weak machine, the same speed whatever the frame rate and never teleporting when a frame runs long (opt-in, any gesture stops it, and a camera you tilted by hand is levelled only if the drift is what tilted it). Detections for the selected day (±1/3/7/14 d span) — **MODIS coral, VIIRS amber, live points pale gold** — plus soft-sand DBSCAN cluster polygons, on one of three basemaps: **Satellite** imagery, the colour **Terrain** map, or **Vector** tiles (CARTO Dark Matter) whose coastlines and place names stay crisp however far you zoom, since vector geometry is redrawn rather than upscaled. All three toggles sit with the other view controls, in the bottom-left row under the readout, and a slow connection opens on **Vector** because it is the lightest of the three. The bottom-left column is readout first (`day · hotspots · clusters · MW`), controls beneath it, and it sits on the map's own edge; it steps up only while an *expanded* attribution notice would reach under it, so no control is ever covered and no space is left empty under the row. Dragging, rotating and zooming stay light on every basemap: the canvas render ratio is capped, MSAA and tile fade are off, and expired tiles are not re-fetched mid-gesture. Live-feed points/polygons overlay when pulled. Use **Select area** and click two corners to draw a bounding box; every panel then filters to it. |
| **Anomalies & critical periods** | A click-through list of anomalous days (z-score vs the same ±7-day window in other years) and the months running above mean + 1σ flagged as *critical*. |
| **Incident Commander briefing** | Threat level (Low/Watch/Elevated/Critical) with its score, record mean and last-30-days readout, then the full report split across **four sub-tabs** — Situation, Critical streaks, Fuel types, Actions — each with a count badge so you can see what is inside before opening it. Streak rows jump the map to that window; **Copy MD** exports the whole briefing. The right-rail card keeps the compact headline version. |
| **Last year + 30-day forecast** | Full-width line chart of the trailing 365 days with the forecast appended, its method named (`Seasonal climatology + archive prior` once the model has been trained — see below), an Observed/Forecast legend — and zoom: drag across the plot to select a window, or take the last 90/180/365 days from the **Window** selector and **Reset zoom**. |
| **Seasonal climatology** | Full-width day-of-year percentile envelope (10/50/90/95) with **Peak day**, **Fire season** (onset → cessation), the record span and the median day as cards beneath it. |
| **Sensor Transition Illusion** | Full-width per-sensor raw detections vs the harmonized line; observed vs adjusted post-2012 growth, artifact removed, calibration stats. On the reference 2002–2024 record (what `POST /demo?mode=transition` builds and the suite pins) this reads +304.0 % raw → +11.7 % harmonized, 292.3 pp of artifact; every open archive gets its own diagnostic, and a region preset draws its own record (Southeastern Australia measured +339.2 % → +23.6 %, 315.6 pp, era factor 3.553, 10,046 matchups, R² 0.848). |
| **Live FIRMS 24h feed** | Region selector; pulls MODIS + 3 VIIRS NRT feeds, harmonizes, clusters, and overlays them on the map. |

## Method

- **Harmonization** — unified confidence scale (MODIS 0–100; VIIRS `l/n/h` → 20/60/90);
  detections below confidence 30 dropped for both sensors; UTC timestamps from
  `acq_date` + `acq_time`; duplicate rows removed on `(lat, lon, time, sensor)`.
  Because VIIRS 375 m finds more fires than MODIS 1 km, per-sensor daily counts are
  **rescaled to the best-covered sensor over their overlap period** before summing.
- **ESFP / HFII** — every detection keeps its FIRMS `scan`/`track` footprint, divided by
  that sensor's own nadir cell (MODIS 1 km², VIIRS 0.140625 km² — the 375 m I-band
  product FIRMS distributes, not the 750 m M-band one) to give the footprint expansion
  ratio: 1.0 at nadir, ≈9.7× at the edge of scan for either sensor, never below 1.0.
  Those are the *equivalent standard pixels*, and HFII = Σ FRP·ESFP.
- **Climatology** — rolling 15-day percentiles per day-of-year across all years;
  onset/cessation = first/last DOY where the 95th percentile exceeds 50 % of its max.
- **Illusion diagnostic** — pre/post-2012 daily means; the era factor is the measured
  detection ratio on days both sensors flew (VIIRS resolves several times more
  detections over the same fires), and the comparable record takes the larger of the two
  counts in a common unit per day, so a fire both sensors saw is counted once.  Also
  reports daily-count correlation (R²), RMSE and the FRP/ESFP ratios in the overlap.
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
| `POST /datasets/load` | `id`, `all` (bool), `limit` (1,000–2,000,000; default 750,000, or 2,000,000 when `all=true`), `spread` (bool, default true) | Open a local archive — or, with `all=true`, **every** archive merged into one record: all sensors, all years. Rows are *read*, so the reader stops and a 1.87 GB file costs about what a 50 MB one does; with `all=true` the budget is split across the files by size. HTTP 404 for an id the inventory does not hold (400 when `all=true` and the directory is empty), 429 while another archive is opening, 400 when a CSV is not a FIRMS export or holds no usable rows. Returns `meta` plus a **`load`** block — for one file `file/sensor/kind/mb/capped`, for a merge `merged/archives/sensors/files[]/skipped[]` naming each export's rows — plus `rows_read`, `rows_kept`, `rows_estimate`, `spread`, `limit`. The console labels the slice from it, because the record on screen and the file it came from are not the same span. |
| `GET /datasets` | — | The FIRMS archives found on this machine, smallest first: `{id, name, sensor, kind, label, bytes, mb}` each. `id` is relative to the archive root and is the only handle the load endpoint accepts — no absolute path is published, not even the roots that were walked. `{"items": []}` is the normal answer in CI, in the container image and on a fresh clone. |
| `POST /demo` | `mode=standard\|transition`, `region` | **Fixture, not a console feature** — the console has no demo button. Replace data with the synthetic 2020–2024 set, or the 2002–2024 transition set. `region` scopes the generated record (and its own seed) to a preset AOI; HTTP 400 for an unknown key. It is what the test suite loads, and the only data source a checkout without `.data/` has. |
| `POST /archive` | `region`, `bbox`, `source`, `days` (1–5), `date`, `append` | Load a **real** FIRMS window through the area API and merge it into the record (like an upload). Needs `FIRMS_MAP_KEY`: HTTP 400 with the link and the `.env` locations when it is missing, 400 for an unknown source/region/bad date, 502 when FIRMS is unreachable. Rows outside the requested AOI are dropped, and the response is `meta` plus `{source, region, days}`. |
| `DELETE /data` | — | Clear all loaded data. |
| `GET /regions` | — | Curated AOI presets: `{key, name, subtitle, bbox, center, zoom, biome, peak_months, events[], firms_region}`. `firms_region` is always on the live-feed allowlist. |
| `GET /meta` | — | `{n, start, end, sensors, bounds, hfi, esfp, pixels}` or `{"n": 0}`. |
| `GET /climatology` | `bbox`, `window` (3–45), `step` (1–30) | Per-year DOY series, DOY percentile envelope (p10/50/90/95), peak/onset/cessation summary. |
| `GET /diagnostic` | `bbox` | Sensor Transition Illusion: per-year raw counts per sensor, the comparable record, observed/adjusted post-2012 growth, the era scaling factor, calibration (R², RMSE, FRP & ESFP ratios). |
| `GET /live` | `region`, `bbox`, `crop`, `eps`, `min_pts`, `hours` | Pull FIRMS 24h NRT feeds (region name with underscores, e.g. `South_America`), harmonize + cluster on the fly. `region` is allowlisted because it is interpolated into the outbound URL (HTTP 400 otherwise), at most two ingests run at once (HTTP 429), and HTTP 502 means no feed was reachable. |
| `GET /briefing` | `bbox`, `z` (1–5), `min_days`, `format=json\|markdown` | Threat level, critical streaks, fuel biomes, recommendations. Markdown for incident hand-off. |
| `GET /calendar` | `bbox`, `start`, `end` | Daily rows: `{date, count, raw, frp}`. |
| `GET /points` | `bbox`, `start`, `end`, `limit` (1–20000) | Map points (`{lat, lon, frp, sensor}`), randomly sampled if over the limit. |
| `GET /clusters` | `bbox`, `start`, `end`, `eps` (10–5000), `min_pts` (1–100), `hours` (0.5–720) | DBSCAN clusters, top 300 by size, each with a convex `hull`. Only those 300 are hulled (hulling every cluster made one uncached call cost 33 s on a 23-year record); above 60k detections the input is stride-sampled across the whole period rather than truncated to the oldest rows. |
| `GET /anomalies` | `bbox`, `z` (0.5–10) | `{anomalies[], critical[], monthly[]}`; needs >1 year of data. |
| `GET /forecast` | `bbox`, `horizon` (1–90), `epochs` (1–200) | `{model, forecast[]}`; needs ≥120 days. |

`bbox` format: `minlat,minlon,maxlat,maxlon` (e.g. `bbox=17,98,20,101`).

## Project structure

```
.
├── README.md                       ← you are here
├── CONTRIBUTING.md                 ← how to propose work and run the checks
├── SECURITY.md                     ← how to report a vulnerability
├── CHANGELOG.md                    ← user-facing changes, newest first
├── .editorconfig                   ← cross-editor basics: charset, indentation, newlines
├── .env.example                    ← optional FIRMS_MAP_KEY + ALLOW_ORIGINS (copy to .env)
├── run.py                          ← the one-command launcher (any OS, stdlib only)
├── start.sh / start.bat            ← thin wrappers around run.py
├── Dockerfile                      ← console build + API in one image (see decisions/0002)
├── .dockerignore                   ← keeps host node_modules/.venv/dist out of the build
├── scripts/
│   ├── check.sh / check.bat        ← the same checks CI runs (backend tests + doc figures + frontend build)
│   └── check-doc-figures.py        ← fails when a documented count or guard name drifts from the code
├── docs/
│   ├── README.md                   ← docs index
│   ├── PRD.md                      ← product requirements: features, acceptance criteria, status
│   ├── AGENTS.md                   ← house rules for coding agents
│   ├── nasa-space-apps-challenge.md ← challenge brief + 4 reference papers
│   ├── modis-viirs-integrated-review.md ← MODIS/VIIRS sensor comparison notes
│   └── decisions/                  ← ADRs; 0001 records this layout
├── .github/workflows/ci.yml        ← CI (pytest + doc figures + frontend build)
└── firecal/
    ├── backend/
    │   ├── main.py                 ← FastAPI app: endpoints, harmonization, analytics
    │   ├── regions.py              ← curated AOI presets: bbox, biome, peak season, notable fires
    │   ├── demo.py                 ← synthetic FIRMS generator (2020–24 + 2002–24 transition) — the test fixture, not a UI feature
    │   ├── archives.py             ← the local archive inventory + the bounded, spread slice reader
    │   ├── train.py                ← trains the model from the FIRMS archive (writes model/)
    │   ├── forecast_model.py       ← the trained prior: 2° cell × day-of-year, checkpoint IO
    │   ├── model/                  ← trained checkpoint (gitignored; rebuilt by train.py)
    │   ├── test_smoke.py           ← 40-test API smoke suite (encodings, gzip, cache, presets, archive, training, /api prefix)
    │   ├── test_security.py        ← 34-test hardening suite (URL allowlist, upload caps, CORS, CSP hosts)
    │   ├── test_archives.py        ← 24-test suite for the local-archive picker (inventory, slice, merge, ids, gate)
    │   ├── requirements.txt        ← runtime deps (with security floors)
    │   └── requirements-dev.txt    ← + pytest, httpx (for tests)
    └── frontend/
        ├── package.json            ← `prebuild` runs the four guards below
        ├── vite.config.js          ← dev proxy /api → :8000
        ├── scripts/
        │   ├── check-lazy-exports.mjs ← fails the build if a React.lazy import cannot resolve
        │   ├── check-quality-policy.mjs ← replays frame times through the adaptive-detail policy
        │   ├── check-chart-fill.mjs   ← asserts the chart layout arithmetic (fill, axes, hover)
        │   └── check-spin-policy.mjs  ← asserts the globe drift's rate and frame-step policy
        └── src/
            ├── App.jsx             ← layout: heatmap, map, drawer tabs (lazy-loads the rest)
            ├── MissionMap.jsx      ← MapLibre stage: 3D globe ⇄ flat map, clusters, picking
            ├── charts.jsx          ← chart tabs (lazy: fetched only when a tab opens)
            ├── plot.jsx            ← hand-rolled SVG chart kit (axes, bands, bars, hover card)
            ├── chartGeometry.js    ← the kit's pure layout maths (guarded at build time)
            ├── autoRotate.js       ← the globe drift's rate and frame-step policy
            ├── ForecastChart.jsx   ← forecast line chart (lazy)
            ├── panels.jsx          ← chart-free pillars: hero stats, live feed, briefing
            ├── lib.js              ← API client (memoized), heat ramp, formatters
            ├── main.jsx
            └── styles.css          ← "ember dusk" design system + the letter-case contract
```

## Tech stack

| Layer | Choices |
|---|---|
| Backend | FastAPI, pandas, NumPy, scikit-learn (DBSCAN, K-means), SciPy (convex hull), requests (live FIRMS), optional PyTorch (LSTM warm-started from the trained checkpoint) |
| Frontend | React 18, Vite 5, MapLibre GL 6 (one camera morphing a 3D globe into a flat map), hand-rolled SVG charts |
| Tooling | Four zero-dep `prebuild` guards: `check-lazy-exports.mjs`, `check-quality-policy.mjs`, `check-chart-fill.mjs`, `check-spin-policy.mjs` |
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

**First paint is small.** MapLibre (~280 KB gzipped) is code-split behind `React.lazy`, so
the console shell paints after loading only the app chunk plus React — about **170 KB raw /
55 KB gzipped**, against 2,078 KB before the split. Measured cold: DOMContentLoaded
**1,768 ms → 283 ms**, requests **44 → 14**. The map engine is fetched when the map mounts;
charting code only when a chart tab is opened — and hovering or focusing a drawer tab
starts that download early, so the click lands on an already-warm module.

**Charts are hand-rolled SVG, not a charting library.** A chart tab used to pull a 404 KB
(108.7 KB gzipped) vendor chunk plus ~10 transitive packages (d3, victory-vendor,
react-smooth, …) to draw three charts. `src/plot.jsx` does axes, an envelope band, grouped
bars, line series, a legend and a hover readout in ~220 lines — the same approach as the
calendar heatmap that was already hand-rolled — so a chart tab costs about **11 KB raw /
5 KB gzipped** and the app has one fewer dependency family (and `recharts`, `cobe`,
`leaflet` and `react-leaflet` are gone from `package.json`).

**The charts fill the tab and answer the pointer.** Each chart lays itself out in its
container's own pixels — measured with a `ResizeObserver` and written back into the SVG
`viewBox`, so one unit is one CSS pixel — which is what lets a wide window get a wide plot
with 9px labels that stay 9px rather than a fixed box scaled down. Hovering draws a
crosshair and a readout card listing every series' value (exact counts where the axis is in
thousands), `←`/`→` walk it from the keyboard, and the forecast chart zooms by dragging
across the plot. All of that arithmetic lives in `chartGeometry.js` as pure functions, so
`check-chart-fill.mjs` can assert the parts you would otherwise only notice by looking: the
plot fills its container, an axis can never clip a percentile band, labels never crowd each
other, the readout card stays inside the frame, and a gap in a series breaks the line.

**Interactions are memoized twice.** The API gzips its JSON (≈4–9× smaller on the
calendar, points and climatology payloads) and each analytics endpoint is memoized
until the dataset changes, so DBSCAN clustering, the K-means briefing and the rolling
percentile climatology are computed once rather than on every click. The frontend keeps
the same responses in memory, so revisiting a day, span or AOI issues no request at all.
The demo generator is cached too, so `POST /demo` is instant after the first run.

**Rendering avoids GPU traps.** Raster tiles stop at zoom 16 (deeper zooms upscale) and
fade animation is off, so panning and zooming stop paying per-tile animation costs; the
zoom listener no longer schedules a React render per frame; the scroll background and the
map vignette were rewritten so they don't repaint on every scroll tick. The canvas renders
at most 1.5× and never with MSAA, expired tiles are not re-validated mid-gesture, and the
same Earth is never drawn several times per frame. On a machine with four cores or less
(`LOW_END` in `MissionMap.jsx`) the cap drops to 1× and camera moves become instant.

**A slow drag reports itself.** The map measures its own frame times while the camera is
moving: if a gesture holds a sustained low frame rate it drops to a 1× canvas and takes the
detection points out of the draw until the motion stops, then hands the detail straight
back. A drag that keeps up is never touched, and neither a three-frame stutter nor a stalled
tab counts as a frame rate — the policy is pure, and unit-tested as a prebuild guard.
Redundant UI effects respect `prefers-reduced-motion`.

## Testing & CI

The one command that must pass before a review runs three checks:

```bash
scripts/check.sh          # POSIX — or scripts\check.bat on Windows
```

Both are thin wrappers around the commands below, which is also what CI runs:

```bash
# 98 tests, ~90 s — starts the app in-process via TestClient
cd firecal/backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q

# Frontend production build (prebuild runs all four guards: lazy, detail, chart, drift)
cd firecal/frontend && npm run build
npm run check:lazy                 # …or run one guard on its own
npm run check:charts

# Doc figures — fails when a documented count or guard name drifts from the code
python scripts/check-doc-figures.py
```

`.github/workflows/ci.yml` runs all three on every push to `main` and on pull requests.

**`test_smoke.py` (40)** covers every endpoint end-to-end — demo load, calendar with and
without bbox, points clamping, clusters, climatology envelope, illusion diagnostic on both
demos, briefing JSON + Markdown, live feed (skipped offline when FIRMS is unreachable),
anomalies, forecast — plus error paths (bad bbox → 400, missing-column CSV → 400, valid CSV
merge, clear), the three CSV encodings (UTF-8, cp1252, UTF-16 BOM), gzip on the wire, and
cache invalidation after a dataset change. The region work added its own cases: the preset
catalog is well-formed and every `firms_region` stays on the live allowlist, a per-region
demo really lands inside its bbox and carries the calendar, the per-region seed is stable
and region-specific, `.env` parsing handles comments/`export`/quotes, and `/archive`
validates the request *before* the key, explains a missing key, builds the area-API URL in
west,south,east,north order, and merges rows while dropping anything outside the AOI.

**`test_archives.py` (24)** covers the local-archive picker against a purpose-built fixture
directory — three archives over two instruments, one of them an S-NPP export that names its
platform: the inventory order (smallest first) and its labels, that no filesystem path reaches
the response, that no archive at all is an empty list rather than an error, that a CSV which is
not a FIRMS export is refused with the missing columns named, and — the part that matters — what
the slice reader does. A bounded read stops at the row cap instead of reading the file; a spread
read covers the whole record while a head read stays inside its opening days, which is the whole
reason the default is spread; and the row estimate stays within a tenth of the fixture's true
count. Six malformed ids (traversal, absolute paths, a bare filename, an empty string, a real
filename reached through another archive's directory) are all refused, a real CSV one directory
above the root is not openable, and opening an archive is refused from a foreign `Origin` like
any other write. It also pins the slice note as a fact about the *dataset* rather than about the
response that installed it: `GET /meta` keeps reporting it after a page refresh, and every other
way of replacing the dataset — an upload, a clear — drops it. The merge cases assert that three
archives produce **two** sensors, that the budget follows file size rather than an even split,
that a broken export is skipped and named instead of sinking the rest, and that merging an empty
directory is a 400 rather than a crash.

**`test_security.py` (34)** pins the input-handling guarantees described under
[Security notes](#security-notes), so they fail loudly if they regress: unknown/traversal/
host-injection `region` values are rejected *without* an outbound fetch, the concurrency
guard returns 429, the request and per-file upload caps and the file-count cap each fire,
a filename cannot summon the demo dataset, reflected filenames come back sanitised, and
CORS grants the local origin but not a hostile one.

**`check-chart-fill.mjs`** drives `chartGeometry.js` — the chart kit's pure layout maths —
from Node, with no browser and no rendering: a 1,400px tab plots its full width less the
axis gutters, the first and last rows land on the frame, an axis top is always a readable
step that covers both edges of every band, x labels never crowd the one after them, bar
columns stay inside the frame, hover snaps to the nearest row and its card is flipped
rather than clipped at the right edge, and a series with a gap is split into runs instead of
being drawn through zero. It also fails the build if the chart ever returns to a scaled,
letterboxing viewBox, or if the card's CSS width and the clamp in code drift apart.

**`check-spin-policy.mjs`** simulates frame cadences through `autoRotate.js`, the globe drift's
policy: a second of drift is the same number of degrees at 100 fps, 50, 20 and 10 fps (the old
fixed 0.12° per timer tick was 0.86°/s on a weak machine — a full turn every seven minutes — and
its speed was whatever the timer happened to be), a five-second frame advances one clamped
250 ms slice instead of 30°, and the globe never turns backwards across the ±180 seam. It also
pins the wiring: animation frames rather than a timer, and `map.isMoving()` rather than an API
the public `Map` does not have.

**`check-lazy-exports.mjs`** resolves every `React.lazy(() => import(...))` in `src/` and
fails the build when the target has no default export (or a mapped named export does not
exist). This exact mistake — `lazy(() => import("./charts"))` against a module with only
named exports — compiles and builds cleanly, then throws at render time and blanks the page;
no type checker or bundler catches it, so it is checked explicitly.

**`scripts/check-doc-figures.py`** keeps the figures this document quotes honest. It counts
the backend suite by parsing `test_*.py` — test functions with `@pytest.mark.parametrize`
expanded, no pytest run and no imports — and fails when any count the docs state (the suite
sizes above, the totals in the PRD and the brain, CONTRIBUTING's composition) disagrees with
what the code would collect; a claim that disappears fails too, so a number may be updated
but not quietly dropped. It cross-checks guard names the same way: every `check-*.mjs` named
in a markdown file exists on disk, every guard on disk is named in this README and the
frontend guide, and every guard is wired into an npm script that `prebuild` chains. Zero
dependencies, its own `docs` CI job, and the first step of `scripts/check.sh`.

## Configuration & limits

| Setting | Default | Notes |
|---|---|---|
| `ALLOW_ORIGINS` | local origins | Comma-separated origins; set when deploying so only your frontend can call the API. The dev server proxies `/api`, so the browser is same-origin and needs no grant. |
| `FIRMS_MAP_KEY` | unset | Optional, read from the environment only (never from a request); enables `POST /archive`. `.env` is loaded from `firecal/backend/`, `firecal/` or the repo root, and a real environment variable always wins. |
| Archive window | 1–5 days per pull | FIRMS area-API limit; `days` is clamped, `source` is one of four mapped products, and `date` must be `YYYY-MM-DD`. |
| Local archives | `.data/` | Searched recursively for `fire_*.csv` and git-ignored — so the list is simply empty in CI, in the image and on a fresh clone. |
| Archive slice | 750,000 rows (1,000–2,000,000) | Rows **read**, not kept: the reader stops at the cap, so opening a 1.87 GB export costs about what a 50 MB one does. `spread=false` reads the head instead of the whole file. |
| Merged archives | 2,000,000 rows, split by file size | `all=true` reads every export under the same cap, dividing the budget by each file's bytes; an unreadable export is skipped and named in `load.skipped`. |
| Concurrent archive opens | 1 | Seconds of pandas work each; a second caller gets HTTP 429 instead of doubling peak memory. |
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
- **An archive id is a name, not a path.** `POST /datasets/load` resolves its `id` *inside the
  inventory* `GET /datasets` produced, with a containment check against the root as well — no
  request-supplied string is ever joined onto a path, so traversal, an absolute path and a real
  CSV one directory up all have nothing to escape from. The response publishes no absolute path
  (not even the roots that were walked), and opening an archive is a write, so the `Origin` gate
  covers it like `/upload`.
- **Reflected input is sanitised.** Filenames are stripped of paths, control characters and
  newlines (which would otherwise forge log lines) before appearing in an error body.
- **CORS defaults to the local origins**, not `*`, and is never paired with credentials — with
  no auth and no cookies, `*` only let any visited web page drive `/upload` and `/demo`.
- **Writes are gated by `Origin`, because CORS does not stop a request.** The browser sends a
  form POST without a preflight, so a page the operator merely had open could still drive
  `/upload`, `/demo`, `/archive` and `/live`. `POST`/`PUT`/`PATCH`/`DELETE` now need an
  `Origin` of either this host or an explicit `ALLOW_ORIGINS` entry (403 otherwise); a caller
  that sends no `Origin` at all (curl, pytest, the launcher) is untouched, and reads are never
  gated.
- **Dependency floors** in `requirements.txt` cover the multipart advisories
  (CVE-2024-47874, CVE-2024-53981) that were reachable through `/upload`.
- **The page itself is served with a policy, and it is checked against the map's third parties.** `Content-Security-Policy` limits scripts and connections to this origin plus the two tile hosts (Esri raster and CARTO vector); a template that names `https://*.basemaps.cartocdn.com` is *not* enough for the bare host its style document lives on, so `test_security.py` asserts every host the frontend loads against the directive that governs it — a new basemap that the policy forbids now fails the suite rather than loading a blank map.
- **The FIRMS MAP_KEY never comes from a request.** It is read from the process environment
  (or the git-ignored `.env`), matched against `[A-Za-z0-9]{6,64}` before it is interpolated
  into the outbound URL, and never echoed back — including through the one path that used to
  leak it: `requests` puts the whole URL in its own exception text, so a transport failure is
  now reduced to `request failed: <ExceptionType>` before it can reach a 502 body. Everything
  else in that URL — source, AOI, day range, date — is allowlisted, range-checked or
  regex-validated first.

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
- **The map well is empty/black** — if the notice in the well names a blocked URL, the page's
  `Content-Security-Policy` refused it: report it, since the tile hosts it allows are pinned by the
  test suite. If it says the WebGL2 renderer would not start, the browser has no WebGL2 — turn on
  hardware acceleration (in Firefox, `about:config` → `webgl.disabled` should be `false`) and
  reload. Every other panel works without the map.
- **Anomalies say “Need >1 year of data”** — upload at least ~400 days of CSVs, or open an archive whose record spans a year.
- **The standby card says “No local archives found”** — expected on a fresh clone, in CI and
  in the container image: `.data/` is ~10 GB of local NASA exports and is git-ignored.
  Drop a folder of FIRMS exports there (any depth) and restart, or use **Upload CSVs**.
- **Opening a big archive takes a few seconds** — it is reading up to 750,000 rows off disk and
  estimating the rest; only one archive opens at a time, and a second request answers 429, which
  the console reports rather than hanging on.
- **Forecast says “install torch for LSTM”** — expected without PyTorch; numbers still
  show, via the climatology fallback: `pip install torch`.
- **Forecast says just “Seasonal climatology”** — there is no trained checkpoint yet. Run
  `python firecal/backend/train.py` over a FIRMS archive to add the `archive prior`; the
  endpoint needs no restart to pick it up on its next computation.
- **CORS errors after deploying** — set `ALLOW_ORIGINS` on the backend to your frontend's origin.
- **“Real-window pull failed: FIRMS_MAP_KEY is not set”** — expected: the area API needs a
  free key. Copy `.env.example` to `.env` and paste it in, or export `FIRMS_MAP_KEY`, or keep
  using CSV uploads and the open 24 h feeds, which need no key.
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

## Contributing

Bug reports and pull requests are welcome — start with [CONTRIBUTING.md](CONTRIBUTING.md).
The docs index is [docs/README.md](docs/README.md) and layout decisions are recorded in
[docs/decisions/](docs/decisions/). Security issues: see [SECURITY.md](SECURITY.md).

No licence has been chosen yet, so no licence is granted for reuse — treat the code as
all-rights-reserved until one is added.

---

Data source: [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/). Built for the 2026
NASA Space Apps Challenge.
