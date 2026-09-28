# 🔥 Pyro-Harmony — Burning Activity Calendar · NASA Space Apps 2026

A unified fire-intelligence platform that harmonizes MODIS and VIIRS active-fire hotspots (NASA FIRMS archive CSVs) into a single, consistent **burning activity calendar**: daily fire activity over time for any area of interest, with clusters, anomaly detection, and a 30-day forecast.

Beyond the base calendar, it implements the four **Pyro-Harmony** poster pillars:

1. **Multi-decadal burning-activity climatology** — day-of-year heatmap matrix plus a 10th/50th/90th/95th percentile envelope that exposes seasonal onset, peak burning days, and cessation.
2. **The "Sensor Transition Illusion" diagnostic** — quantifies and removes the artificial post-2012 surge caused by VIIRS 375 m deployment, using ESFP footprint scaling and cross-sensor calibration (R², RMSE).
3. **Live FIRMS ingestion + hotspot clustering** — pulls 24 h NRT CSVs (MODIS C6.1, VIIRS S-NPP/NOAA-20/NOAA-21) from NASA's open endpoints, harmonizes on the fly, and DBSCAN-clusters them.
4. **Incident Commander wildfire briefing** — flags consecutive critical days (Z ≥ 2σ), stratifies fuel biomes via K-means, assigns a threat level, and generates exportable (Markdown/clipboard) recommendations.

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
- [Testing & CI](#testing--ci)
- [Configuration & limits](#configuration--limits)
- [Troubleshooting](#troubleshooting)

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

Then one command installs dependencies (first run) and starts everything:

| OS | Command |
|---|---|
| Linux / macOS | `./start.sh` |
| Windows | double-click `start.bat` — or run `start.bat` from cmd (``.\start.bat`` in PowerShell) |

Then open **http://localhost:5173** and click **Load demo** — 5 years of synthetic
MODIS + VIIRS data appears in ~1 second (the Windows script opens your browser
automatically). Stop with Ctrl+C in the launcher window (Windows asks `Y`), or just
close it.

<details>
<summary>Manual run (two terminals, Linux/macOS)</summary>

```bash
# Terminal 1 — backend on :8000
cd firecal/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload

# Terminal 2 — frontend on :5173
cd firecal/frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` → `:8000` automatically (`firecal/frontend/vite.config.js`).
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
.venv\Scripts\python -m uvicorn main:app --reload

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
| **Burning calendar** | GitHub-style heatmap: one row per year, one cell per day, color = harmonized daily detections. Click any day to inspect it. |
| **Map** | Detections for the selected day (±1/3/7/14 d span) — VIIRS orange, MODIS red — plus white DBSCAN cluster polygons. Live-feed points/polygons overlay when pulled. Use **Select area** and click two corners to draw a bounding box; every panel then filters to it. |
| **Anomalies & critical periods** | Monthly climatology bar chart, months above mean + 1σ flagged as *critical*, and a click-through list of anomalous days (z-score vs the same ±7-day window in other years). |
| **Incident Commander briefing** | Threat level (Low/Watch/Elevated/Critical), consecutive-day anomaly streaks, K-means fuel-biome stratification, and actionable recommendations. Copy as Markdown. |
| **Last year + 30-day forecast** | Line chart of the trailing 365 days with the forecast appended. |
| **Seasonal climatology** | Day-of-year percentile envelope (10/50/90/95) with peak, onset, and cessation dates. |
| **Sensor Transition Illusion** | Per-sensor raw detections vs the harmonized line; observed vs adjusted post-2012 growth, artifact removed, calibration stats. |
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
  consecutive-day streaks (Z ≥ 2σ), K-means (k=4) fuel-biome stratification on
  position + FRP after Zhang et al. (2020), rule-based recommendations.
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
| `POST /upload` | multipart `files[]` | Add FIRMS CSVs (200 MB/file cap). HTTP 400 with the reason on bad files. |
| `POST /demo` | `mode=standard\|transition` | Replace data with the synthetic 2020–2024 set, or the 2002–2024 transition set. |
| `DELETE /data` | — | Clear all loaded data. |
| `GET /meta` | — | `{n, start, end, sensors, bounds, hfi, esfp, pixels}` or `{"n": 0}`. |
| `GET /climatology` | `bbox`, `window` (3–45), `step` (1–30) | Per-year DOY series, DOY percentile envelope (p10/50/90/95), peak/onset/cessation summary. |
| `GET /diagnostic` | `bbox` | Sensor Transition Illusion: per-year raw counts per sensor, harmonized totals, observed/adjusted post-2012 growth, calibration (R², RMSE, FRP & ESFP ratios). |
| `GET /live` | `region`, `bbox`, `crop`, `eps`, `min_pts`, `hours` | Pull FIRMS 24h NRT feeds (region name with underscores, e.g. `South_America`), harmonize + cluster on the fly. HTTP 502 if no feed is reachable. |
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
├── Nasa Space app challenge.md      ← challenge brief + 4 reference papers
├── start.sh                        ← one-command dev launcher (Linux/macOS)
├── start.bat                       ← one-command dev launcher (Windows)
├── .github/workflows/ci.yml        ← CI (pytest + frontend build)
└── firecal/
    ├── backend/
    │   ├── main.py                 ← FastAPI app: endpoints, harmonization, analytics
    │   ├── demo.py                 ← synthetic FIRMS generator (2020–24 + 2002–24 transition)
    │   ├── test_smoke.py           ← 15-test API smoke suite
    │   ├── requirements.txt        ← runtime deps
    │   └── requirements-dev.txt    ← + pytest, httpx (for tests)
    └── frontend/
        ├── package.json
        ├── vite.config.js          ← dev proxy /api → :8000
        └── src/
            ├── App.jsx             ← layout: heatmap, map, charts, upload
            ├── panels.jsx          ← poster pillars: hero stats, climatology, diagnostic, live, briefing
            ├── liveMapLayer.jsx    ← live-feed overlay on the map
            ├── lib.js              ← API client, color ramp, formatters
            ├── main.jsx
            └── styles.css
```

## Tech stack

| Layer | Choices |
|---|---|
| Backend | FastAPI, pandas, NumPy, scikit-learn (DBSCAN, K-means), SciPy (convex hull), requests (live FIRMS), optional PyTorch (LSTM) |
| Frontend | React 18, Vite 5, react-leaflet 4 / Leaflet, Recharts |
| Data | NASA FIRMS archive CSVs (MODIS C6.1, VIIRS SNPP/NOAA-20) |
| CI | GitHub Actions — pytest on Python 3.12, `npm ci` + build on Node 20 |

## Testing & CI

```bash
# Backend smoke suite (15 tests, ~1–2 min) — starts the app in-process via TestClient
cd firecal/backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q

# Frontend production build
cd firecal/frontend && npm run build
```

`.github/workflows/ci.yml` runs both on every push to `main` and on pull requests.

The smoke suite covers every endpoint end-to-end (demo load, calendar with/without
bbox, points clamping, clusters, climatology envelope, illusion diagnostic on both
demos, briefing JSON + Markdown, live feed — skipped offline when FIRMS is
unreachable, anomalies, forecast) plus error paths (bad bbox → 400, missing-column
CSV → 400, valid CSV merge, clear).

## Configuration & limits

| Setting | Default | Notes |
|---|---|---|
| `ALLOW_ORIGINS` | `*` | Comma-separated origins; set when deploying so only your frontend can call the API. |
| Upload size | 200 MB / file | Larger files → HTTP 400. |
| Row cap | 2,000,000 | Oldest rows are dropped beyond this (in-memory store, no database). |
| Query params | clamped | `limit` ≤ 20000, `eps` ≤ 5000, `epochs` ≤ 200, `horizon` ≤ 90, etc. |
| `torch` | optional | Install for the LSTM forecast; without it you get seasonal climatology. |

## Troubleshooting

- **“Upload failed — could not reach the backend”** — the FastAPI server isn't running
  (start it on :8000) or a wrong CSV returned HTTP 400; the banner shows the exact reason.
- **Anomalies say “Need >1 year of data”** — upload at least ~400 days of CSVs (demo data qualifies).
- **Forecast says “install torch for LSTM”** — expected without PyTorch; numbers still
  show, via the climatology fallback: `pip install torch`.
- **CORS errors after deploying** — set `ALLOW_ORIGINS` on the backend to your frontend's origin.
- **Upload rejected** — check the file has FIRMS columns
  (`latitude, longitude, acq_date, acq_time, confidence`); the error message lists what's missing.
- **`./start.sh` doesn't work on Windows** — use `start.bat` instead (same one-command
  behavior), or the manual steps in [Quick start](#quick-start).

---

Data source: [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/). Built for the 2026
NASA Space Apps Challenge.
