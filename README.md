# 🔥 Burning Activity Calendar — NASA Space Apps 2026

Harmonizes MODIS and VIIRS active-fire hotspots (NASA FIRMS archive CSVs) into a single, consistent **burning activity calendar**: daily fire activity over time for any area of interest, with clusters, anomaly detection, and a 30-day forecast.

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

Then open **http://localhost:5173** and click **Load demo data** — 4 years of synthetic
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

## What you see

| Panel | What it does |
|---|---|
| **Burning calendar** | GitHub-style heatmap: one row per year, one cell per day, color = harmonized daily detections. Click any day to inspect it. |
| **Map** | Detections for the selected day (±1/3/7/14 d span) — VIIRS orange, MODIS red — plus white DBSCAN cluster polygons. Use **Select area** and click two corners to draw a bounding box; every panel then filters to it. |
| **Anomalies & critical periods** | Monthly climatology bar chart, months above mean + 1σ flagged as *critical*, and a click-through list of anomalous days (z-score vs the same ±7-day window in other years). |
| **Last year + 30-day forecast** | Line chart of the trailing 365 days with the forecast appended. |

## Method

- **Harmonization** — unified confidence scale (MODIS 0–100; VIIRS `l/n/h` → 20/60/90);
  detections below confidence 30 dropped for both sensors; UTC timestamps from
  `acq_date` + `acq_time`; duplicate rows removed on `(lat, lon, time, sensor)`.
  Because VIIRS 375 m finds more fires than MODIS 1 km, per-sensor daily counts are
  **rescaled to the best-covered sensor over their overlap period** before summing.
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
| `POST /demo` | — | Replace data with synthetic 2020–2023 demo set. |
| `DELETE /data` | — | Clear all loaded data. |
| `GET /meta` | — | `{n, start, end, sensors, bounds}` or `{"n": 0}`. |
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
    │   ├── main.py                 ← FastAPI app: all endpoints & analytics
    │   ├── demo.py                 ← synthetic FIRMS data generator
    │   ├── test_smoke.py           ← 10-test API smoke suite
    │   ├── requirements.txt        ← runtime deps
    │   └── requirements-dev.txt    ← + pytest, httpx (for tests)
    └── frontend/
        ├── package.json
        ├── vite.config.js          ← dev proxy /api → :8000
        └── src/
            ├── App.jsx             ← UI: heatmap, map, charts, upload
            ├── main.jsx
            └── styles.css
```

## Tech stack

| Layer | Choices |
|---|---|
| Backend | FastAPI, pandas, NumPy, scikit-learn (DBSCAN), SciPy (convex hull), optional PyTorch (LSTM) |
| Frontend | React 18, Vite 5, react-leaflet 4 / Leaflet, Recharts |
| Data | NASA FIRMS archive CSVs (MODIS C6.1, VIIRS SNPP/NOAA-20) |
| CI | GitHub Actions — pytest on Python 3.12, `npm ci` + build on Node 20 |

## Testing & CI

```bash
# Backend smoke suite (10 tests, ~25 s) — starts the app in-process via TestClient
cd firecal/backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q

# Frontend production build
cd firecal/frontend && npm run build
```

`.github/workflows/ci.yml` runs both on every push to `main` and on pull requests.

The smoke suite covers every endpoint end-to-end (demo load, calendar with/without
bbox, points clamping, clusters, anomalies, forecast) plus error paths (bad bbox → 400,
missing-column CSV → 400, valid CSV merge, clear).

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
