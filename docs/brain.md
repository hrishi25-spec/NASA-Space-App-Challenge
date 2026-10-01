# Brain — Pyro-Harmony at a glance

The orientation page: what this project is, how the pieces fit, the numbers that matter, and the traps worth knowing before touching anything. Deep product detail lives in [PRD.md](PRD.md); the console internals in [frontend.md](frontend.md); install and API examples in the [README](../README.md).

## The pitch

Satellites have tracked active fires for 20+ years, but the record is fragmented by sensor: MODIS (1 km, from 2000) and VIIRS (375 m, from 2012) cannot be compared directly, and the raw record looks like fire exploded in 2012 when most of that surge is the satellite changing. Pyro-Harmony harmonizes both sensors into one comparable daily series and presents it as four pillars: a burning-activity calendar + multi-decadal climatology, the Sensor Transition Illusion diagnostic, live FIRMS ingestion with DBSCAN clustering, and an Incident Commander briefing.

## Status snapshot

| Thing | State |
|---|---|
| Tests | 55 passing — 33 API smoke + 22 security, run in-process via `TestClient` |
| Frontend build | Clean, including the prebuild lazy-export guard |
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
| `firecal/backend/main.py` | Every endpoint plus the cores: `harmonize`, `daily`, `_zstats`, `_streaks`, `_threat`, `_biomes`, `_cluster_payload`, `_esfp`, `cached` |
| `firecal/backend/demo.py` | Synthetic FIRMS generator (2020–24 standard + 2002–24 transition) |
| `firecal/backend/regions.py` | Five curated AOI presets |
| `firecal/backend/test_*.py` | Smoke and security suites, colocated with the app |
| `firecal/frontend/src/` | Console: `App.jsx`, `MissionMap.jsx`, `panels.jsx`, `charts.jsx`, `plot.jsx`, `lib.js`, `styles.css` |
| `docs/` | This page, PRD, sensor review, challenge brief, ADRs |
| `scripts/check.sh` / `.bat` | The same checks CI runs |
| `Dockerfile` | Console build + API in one image, one port ([decisions/0002](decisions/0002-single-image-deployment.md)) |
| `.github/workflows/ci.yml` | pytest job + frontend build job |

## Data flow

**Upload, live pull, archive window, or demo → harmonize (confidence floor, UTC time, de-duplicate, per-sensor rescale, ESFP/HFII) → one DataFrame → derived endpoints (memoized, invalidated on change) → gzip → client cache → panels.**

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
| Camera | globe ≤ 3.7 · flat ≥ 5.2 · start 1.65 · tiles ≤ 16 · `LOW_END` = ≤ 4 cores or ≤ 4 GB |

## Commands

```bash
python run.py                      # set up + start both servers (any OS)
scripts/check.sh                   # backend tests + frontend build (scripts\check.bat on Windows)
cd firecal/backend && python demo.py   # write demo_modis.csv / demo_viirs.csv to upload
FIRMS_MAP_KEY=… in .env            # enables POST /archive (real 1–5 day windows)
```

## Invariants and traps

- **A filename is data, not a command.** The transition demo loads via `POST /demo` or `?demo_transition=true` — never by naming a file.
- **Client input never selects a URL.** `region` is allowlisted before any outbound fetch; writes are origin-gated; uploads are capped before buffering; `FIRMS_MAP_KEY` is read from the environment only and never echoed.
- **scipy and scikit-learn import lazily** inside clustering/briefing. Do not move them back to module scope — it costs ~2.5 s of startup.
- **Never import chart code in the shell.** `charts.jsx` and `ForecastChart.jsx` are lazy for a reason; a new lazy target must resolve to a default export or the build guard fails.
- **Derived values must degrade honestly.** Thin selections answer `200` with a `note`; every panel is required to show that note instead of spinning.
- **`torch` is optional.** Without it the forecast falls back to scaled seasonal climatology and names the fallback in the UI.
- **CSS uppercases labels.** Write labels in sentence case and let the contract do the casing; acronyms are the only all-caps strings in source.

## Where to look next

| Question | Read |
|---|---|
| What does the product promise, and what is missing? | [PRD.md](PRD.md) — status table, gaps, roadmap |
| How is the console built? | [frontend.md](frontend.md) |
| Why is the repo arranged this way? | [decisions/](decisions/) |
| How do the sensors compare? | [modis-viirs-integrated-review.md](modis-viirs-integrated-review.md) |
| What was the challenge? | [nasa-space-apps-challenge.md](nasa-space-apps-challenge.md) |
| What are the agent rules here? | [AGENTS.md](AGENTS.md) |
