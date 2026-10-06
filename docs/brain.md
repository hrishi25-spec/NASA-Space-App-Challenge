# Brain — Pyro-Harmony at a glance

The orientation page: what this project is, how the pieces fit, the numbers that matter, and the traps worth knowing before touching anything. Deep product detail lives in [PRD.md](PRD.md); the console internals in [frontend.md](frontend.md); install and API examples in the [README](../README.md).

## The pitch

Satellites have tracked active fires for 20+ years, but the record is fragmented by sensor: MODIS (1 km, from 2000) and VIIRS (375 m, from 2012) cannot be compared directly, and the raw record looks like fire exploded in 2012 when most of that surge is the satellite changing. Pyro-Harmony harmonizes both sensors into one comparable daily series and presents it as four pillars: a burning-activity calendar + multi-decadal climatology, the Sensor Transition Illusion diagnostic, live FIRMS ingestion with DBSCAN clustering, and an Incident Commander briefing.

## Status snapshot

| Thing | State |
|---|---|
| Tests | 106 passing — 44 API smoke + 34 security + 28 local-archive, run in-process via `TestClient` |
| Frontend build | Clean, including the prebuild lazy-export, adaptive-detail, chart-layout and orbital-drift guards |
| Startup weight | Import ≈ 2.2 s, baseline RSS ≈ 104 MB (measured on the dev machine after the lazy scipy/sklearn change) |
| Layout | Arranged per the repo standard; see [decisions/0001](decisions/0001-repository-layout.md) |

**Documented demo figures** (2002–2024 transition demo, from the PRD's verification table): 57,867 hotspots (MODIS 18,310 / VIIRS 39,557), 2002-01-19 → 2024-12-21, HFII 1,771,574.5, ESFP 136,409.8. The illusion reads **+304.0 % raw → +11.7 % harmonized, 292.3 pp of artifact**, era factor 3.618, calibration R² 0.867 / RMSE 2.91 MW over 9,767 matchups.

## Architecture

```text
browser (React 18 + Vite 5) ──/api──▶ FastAPI (single process, uvicorn)
        │                                   │
        │  shell · map · panels             │  harmonize() → one process-global DataFrame
        │  lazy charts · client cache       │  derived endpoints, memoized until data changes
        ▼                                   ▼
  styles.css "ember dusk"            pandas · NumPy · scikit-learn · SciPy · requests
```

Two structural decisions do most of the work:

1. **The dataset is a process-global in-memory DataFrame** with a memo cache keyed by endpoint arguments — that is why warm analytics are ~10–100 ms and there is no database to run. The cost: two workers would not share state, and any caller can replace the dataset for everyone.
2. **The frontend ships as a small shell plus lazily-fetched heavy pieces** — the map engine and chart code only arrive when opened, which keeps first paint around 55 KB gzipped.

## Repo map

| Path | What lives there |
|---|---|
| `firecal/backend/main.py` | Every endpoint plus the cores: `harmonize`, `harmonized_daily`, `_zstats`, `_streaks`, `_threat`, `_biomes`, `_cluster_payload`, `_esfp`, `cached` |
| `firecal/backend/train.py` | Trains the model from the FIRMS archive in chunks and writes `model/` |
| `firecal/backend/forecast_model.py` | The trained prior — 2° cell × day-of-year shape, bbox lookup, checkpoint IO |
| `firecal/backend/model/` | The trained checkpoint. Gitignored, rebuilt by `train.py`, optional to the API |
| `firecal/backend/archives.py` | The local-archive inventory under `.data/`, the bounded spread slice reader, `allocate()` (a merge budget split by file size) and `read_merge()` (all of them at once) |
| `firecal/backend/demo.py` | Synthetic FIRMS generator (2020–24 standard + 2002–24 transition) — the test fixture; nothing in the UI calls it |
| `firecal/backend/regions.py` | Five curated AOI presets |
| `firecal/backend/test_*.py` | Smoke, security and archive suites, colocated with the app |
| `firecal/frontend/src/` | Console: `App.jsx`, `MissionMap.jsx`, `panels.jsx`, `charts.jsx`, `plot.jsx`, `chartGeometry.js`, `lib.js`, `styles.css` |
| `docs/` | This page, PRD, sensor review, challenge brief, ADRs |
| `scripts/check.sh` / `.bat` + `scripts/check-doc-figures.py` + `scripts/check-doc-links.py` + `scripts/test_check_doc_links.py` | The same checks CI runs: two doc guards (one fails when a documented figure drifts from the code, the other when a relative link does not resolve) plus the link guard's own test suite, so its rules cannot drift either |
| `Dockerfile` | Console build + API in one image, one port ([decisions/0002](decisions/0002-single-image-deployment.md)) |
| `.github/workflows/ci.yml` | pytest job + docs job (figures + links) + frontend build job |

## Data flow

**Open a local archive, upload, live pull, or archive window → harmonize (confidence floor, UTC time, de-duplicate, per-sensor rescale, ESFP/HFII) → one DataFrame → derived endpoints (memoized, invalidated on change) → gzip → client cache → panels.**

The console's opening move is the first of those: `GET /datasets` publishes the archive files on the machine (id, sensor, kind, size — never a path), and `POST /datasets/load` opens one by reading a capped number of rows from evenly spaced offsets across the file. What was read comes back in `meta.load` and is shown in the console, because a 750,000-row slice of a 16M-row export is a sample and the panels must not read as if it were the file.

## Constants worth knowing

| Concern | Value |
|---|---|
| Confidence floor | ≥ 30 (MODIS 0–100; VIIRS `l/n/h` → 20/60/90) |
| Nadir cells | MODIS 1.0 km², VIIRS 0.140625 km² (375 m I-band) |
| Clustering | DBSCAN eps 550 m, minPts 3, 12 h window; top 300 clusters by size |
| Climatology | rolling 15-day percentiles; onset/cessation = first/last DOY where p95 > 50 % of max |
| Illusion | era split pre-2012 vs 2012–2015 overlap; factor = measured collocated detection ratio |
| Data thresholds | climatology/briefing ≥ 60 days · anomalies > 400 days · forecast ≥ 120 days |
| Threat | `max_z + 0.5·streak_days + min(2, recent_mean/25)`; Watch ≥ 3.5, Critical ≥ 6 |
| Caps | 2 M rows total, 200 MB/file, 400 MB/request, ≤ 20 files, 64 MB per outbound feed, 2 concurrent live ingests |
| Local archive slice | 750,000 rows read (1,000–2,000,000) across ≤ 24 evenly spaced offsets; 1 concurrent open; `.data/` is gitignored so CI and the image see none |
| Merged archives | `all=true` · 2,000,000 rows split by file bytes · per-file accounting + per-file skips |
| Sensor naming | instrument, not platform — `SNPP`/`NPP`/`N20`/`N21`/`NOAA-20`/`NOAA-21` → **VIIRS**, so the three VIIRS platforms are one sensor (they are the same instrument; `SENSOR_ALIASES` in `main.py`) |
| Camera | globe ≤ 3.7 · flat ≥ 5.2 · start 1.65 · tiles ≤ 16 · axial tilt 23.44° while auto-rotating · `LOW_END` = ≤ 4 cores or ≤ 4 GB |

## Commands

```bash
python run.py                      # set up + start both servers (any OS)
scripts/check.sh                   # backend tests + doc figures + frontend build (scripts\check.bat on Windows)
cd firecal/backend && python train.py # train the forecast prior over .data/ (~15 min)
cd firecal/backend && python demo.py   # write demo_modis.csv / demo_viirs.csv to upload (fixture)
FIRMS_MAP_KEY=… in .env            # enables POST /archive (real 1–5 day windows)
```

## Invariants and traps

- **A filename is data, not a command.** The transition demo loads via `POST /demo` or `?demo_transition=true` — never by naming a file.
- **An archive id is a name, not a path.** `/datasets/load` resolves its `id` against the inventory the scan produced and re-checks containment against the root; no request string is ever joined onto a path, so a traversal id has nothing to escape from.
- **Client input never selects a URL.** `region` is allowlisted before any outbound fetch; writes are origin-gated; uploads are capped before buffering; `FIRMS_MAP_KEY` is read from the environment only and never echoed.
- **scipy and scikit-learn import lazily** inside clustering/briefing. Do not move them back to module scope — it costs ~2.5 s of startup.
- **Never import chart code in the shell.** `charts.jsx` and `ForecastChart.jsx` are lazy for a reason; a new lazy target must resolve to a default export or the build guard fails.
- **Derived values must degrade honestly.** Thin selections answer `200` with a `note`; every panel is required to show that note instead of spinning.
- **`torch` is optional.** Without it the forecast falls back to scaled seasonal climatology — archive-trained when a checkpoint exists — and names the fallback in the UI.
- **The training archive is never committed.** `.data/` is ~10 GB of local NASA exports and `firecal/backend/model/` is derived from it; both are gitignored, and a missing or malformed checkpoint is not an error.
- **Training and serving must harmonize identically.** `train.py` reads the archive through the server's own `harmonize(geometry=False)` and `harmonized_daily()`. A second implementation of the sensor rescale would train the model on a different quantity than the endpoint predicts.
- **CSS uppercases labels.** Write labels in sentence case and let the contract do the casing; acronyms are the only all-caps strings in source.

## Next steps

The follow-ups from the last review round, highest value first — two have landed and are marked done; the PRD's [roadmap](PRD.md#14-roadmap) and [gap list](PRD.md#13-known-gaps--risks) hold the full picture:

| Step | Why it is next |
|---|---|
| Launch the console live and verify calendar, forecast and the dataset picker end to end | This repo is developed on Windows, the one platform the docs admit was never exercised (PRD gap 5); the suite now passes here, so the running app is the remaining check |
| Add a Windows job to the CI matrix | The suite is green on Windows since the `hf`-CLI resolution fix (`archives.py`); CI should keep it that way (NFR-5) |
| ✅ Done — per-file upload outcomes in `/upload` | PRD gap 8 is closed: a file whose rows all fail harmonization used to be silently ignored when a dataset already exists (200, unchanged data); the response now carries an `upload` block naming each file's rows or refusal reason, a request where nothing is accepted is a 400 naming every file, and the console shows it in a neutral banner |
| ✅ Done — keep the root a lobby per [ADR 0001](decisions/0001-repository-layout.md) | `TRAINING_REPORT.md` and `TRAINING_BRIEFING.md` (the `train_data.py` outputs) are gitignored and the stray `~/skills/` folder a tool created in the repo root is gone — the root holds only product files again |

## Where to look next

| Question | Read |
|---|---|
| What does the product promise, and what is missing? | [PRD.md](PRD.md) — status table, gaps, roadmap |
| How is the console built? | [frontend.md](frontend.md) |
| Why is the repo arranged this way? | [decisions/](decisions/) |
| How do the sensors compare? | [modis-viirs-integrated-review.md](modis-viirs-integrated-review.md) |
| What was the challenge? | [nasa-space-apps-challenge.md](nasa-space-apps-challenge.md) |
| What are the agent rules here? | [AGENTS.md](AGENTS.md) |
