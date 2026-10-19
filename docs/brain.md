# Brain — Pyro-Harmony at a glance

The orientation page: what this project is, how the pieces fit, the numbers that matter, and the traps worth knowing before touching anything. Deep product detail lives in [PRD.md](PRD.md); the console internals in [frontend.md](frontend.md); install and API examples in the [README](../README.md).

## The pitch

Satellites have tracked active fires for 20+ years, but the record is fragmented by sensor: MODIS (1 km, from 2000) and VIIRS (375 m, from 2012) cannot be compared directly, and the raw record looks like fire exploded in 2012 when most of that surge is the satellite changing. Pyro-Harmony harmonizes both sensors into one comparable daily series and presents it as four pillars: a burning-activity calendar + multi-decadal climatology, the Sensor Transition Illusion diagnostic, live FIRMS ingestion with DBSCAN clustering, and an Incident Commander briefing.

## Status snapshot

| Thing | State |
|---|---|
| Tests | 148 passing — 73 API smoke + 34 security + 41 local-archive, run in-process via `TestClient` |
| Frontend build | Clean, including the prebuild lazy-export, adaptive-detail, chart-layout and orbital-drift guards |
| Startup weight | Import ≈ 2.2 s, baseline RSS ≈ 104 MB (dev machine; re-measured ≈ 0.8 s / 103.5 MB on the Windows checkout after the LightGBM work). `lightgbm` is lazily imported and unloaded at start-up, so it adds nothing here |
| Layout | Arranged per the repo standard; see [decisions/0001](decisions/0001-repository-layout.md) |

**Documented demo figures** (2002–2024 transition demo, from the PRD's verification table): 57,867 hotspots (MODIS 18,310 / VIIRS 39,557), 2002-01-19 → 2024-12-21, HFII 1,771,574.5, ESFP 136,409.8. The illusion reads **+304.0 % raw → +11.7 % harmonized, 292.3 pp of artifact**, era factor 3.618, calibration R² 0.867 / RMSE 2.91 MW over 9,767 matchups.

## Architecture

```text
browser (React 18 + Vite 5) ──/api──▶ FastAPI (single process, uvicorn)
        │                                   │
        │  shell · map · panels             │  harmonize() → one process-global DataFrame
        │  lazy charts · client cache       │  derived endpoints, memoized until data changes
        ▼                                   ▼
  styles.css "ember dusk"            pandas · NumPy · scikit-learn · SciPy · requests · LightGBM (lazy)
```

Two structural decisions do most of the work:

1. **The dataset is a process-global in-memory DataFrame** with a memo cache keyed by endpoint arguments — that is why warm analytics are ~10–100 ms and there is no database to run. The cost: two workers would not share state, and any caller can replace the dataset for everyone.
2. **The frontend ships as a small shell plus lazily-fetched heavy pieces** — the map engine and chart code only arrive when opened, which keeps first paint around 55 KB gzipped.

## Repo map

| Path | What lives there |
|---|---|
| `firecal/backend/main.py` | Every endpoint plus the cores: `harmonize`, `harmonized_daily`, `_zstats`, `_streaks`, `_threat`, `_biomes`, `_cluster_payload`, `_esfp`, `cached` |
| `firecal/backend/train.py` | Trains the seasonal *prior* from the FIRMS archive in chunks and writes `model/` |
| `firecal/backend/forecast_model.py` | The trained prior — 2° cell × day-of-year shape, bbox lookup, checkpoint IO |
| `firecal/backend/train_forecast.py` | Trains the global LightGBM forecaster on a 2°-cell × day panel; blocked backtest, writes `model/lgbm_*` |
| `firecal/backend/lgbm_forecast.py` | The LightGBM model's shared half: features, checkpoint IO (hash-verified), the prior-vs-model gate, the conformal band, `/forecast` serving |
| `firecal/backend/model/` | The trained checkpoints (prior + LightGBM). Gitignored, rebuilt by the trainers, optional to the API |
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

The console's opening move is the first of those: `GET /datasets` publishes the archive files on the machine (id, sensor, kind, size, and a sampled per-year **coverage** block — the box, the 2° cells and the row counts, with `thin_years` for a window that covers a fraction of the inventory's ground — never a path), and `POST /datasets/load` opens one by reading a capped number of rows from evenly spaced offsets across the file. What was read comes back in `meta.load` and is shown in the console, because a 750,000-row slice of a 16M-row export is a sample and the panels must not read as if it were the file.

## Constants worth knowing

| Concern | Value |
|---|---|
| Confidence floor | ≥ 30 (MODIS 0–100; VIIRS `l/n/h` → 20/60/90) |
| Nadir cells | MODIS 1.0 km², VIIRS 0.140625 km² (375 m I-band) |
| Clustering | DBSCAN eps 550 m, minPts 3, 12 h window; top 300 clusters by size |
| Climatology | rolling 15-day percentiles; onset/cessation = first/last DOY where p95 > 50 % of max |
| Illusion | era split pre-2012 vs 2012–2015 overlap; factor = measured collocated detection ratio |
| Data thresholds | climatology/briefing ≥ 60 days · anomalies > 400 days · forecast ≥ 120 days |
| Forecast model | Global LightGBM, Tweedie objective (power 1.5); features sin/cos DOY, 1/7/14/28-day lags, 7/28-day rolling means, training-years DOY climatology, cell lat/lon; served only where its stored backtest MASE beats the prior's, judged by the curated preset the AOI sits wholly inside (`regions.region_for_box`) and by the pooled panel otherwise; `MAX_CELLS` 2,000 caps an AOI's cells |
| Backtest splits | leave-one-fire-season-out in time (calendar-year seasons) **and** a spatial block hold-out by curated region (30° tiles as a fallback); never random; the round count is picked by early stopping on the last 90 days of the training rows and the returned booster is refitted on all of them; MASE at horizons 1/7/14/30 |
| Forecast interval | Split conformal, in-repo, per horizon on the log1p **relative** error; calibrated on a block strictly later than training, scored on the next block; the (1−α) quantile is the rank-corrected order statistic; band = `expm1(log1p(ŷ) ± q_h)`; a horizon past the calibrated window reuses the widest width; `coverage.within_tolerance` is false when empirical coverage is >5 points off nominal |
| Threat | `max_z + 0.5·streak_days + min(2, recent_mean/25)`; Watch ≥ 3.5, Critical ≥ 6 |
| Caps | 2 M rows total, 200 MB/file, 400 MB/request, ≤ 20 files, 64 MB per outbound feed, 2 concurrent live ingests |
| Local archive slice | 750,000 rows read (1,000–2,000,000) across ≤ 24 evenly spaced offsets; 1 concurrent open; `.data/` is gitignored so CI and the image see none |
| Merged archives | `all=true` · 2,000,000 rows split by file bytes · per-file accounting + per-file skips |
| Bucket pull | One at a time (the colliding caller is told so, not queued); a failed pull is answered from memory for 60 s; a success never is |
| Sensor naming | instrument, not platform — `SNPP`/`NPP`/`N20`/`N21`/`NOAA-20`/`NOAA-21` → **VIIRS**, so the three VIIRS platforms are one sensor (they are the same instrument; `SENSOR_ALIASES` in `main.py`) |
| Camera | globe ≤ 3.7 · flat ≥ 5.2 · start 1.65 · tiles ≤ 16 · axial tilt 23.44° while auto-rotating · `LOW_END` = ≤ 4 cores or ≤ 4 GB |

## Commands

```bash
python run.py                      # set up + start both servers (any OS)
scripts/check.sh                   # backend tests + doc figures + frontend build (scripts\check.bat on Windows)
cd firecal/backend && python train.py          # train the seasonal prior over .data/ (~15 min)
cd firecal/backend && python train_forecast.py # train the LightGBM forecaster over .data/ (writes model/lgbm_*)
cd firecal/backend && python demo.py   # write demo_modis.csv / demo_viirs.csv to upload (fixture)
FIRMS_MAP_KEY=… in .env            # enables POST /archive (real 1–5 day windows)
```

## Invariants and traps

- **A filename is data, not a command.** The transition demo loads via `POST /demo` or `?demo_transition=true` — never by naming a file.
- **An archive's size is not its extent.** `archives.attach_coverage` samples every export and judges each calendar year against the inventory's own box: this machine's `.data/` ends with 358 days of a California-only NRT window, and it used to list exactly like a global year. The flag (`thin_years`, `note`) is what the picker and the merged **Dataset** panel show; `train_forecast.consistent_span` reaches the same conclusion independently from the panel's own 30-day level, so the two act as a cross-check rather than sharing a switch. The sample is cached in `<root>/.coverage.json` by size+mtime; a file that cannot be sampled answers `unavailable` and never fails the listing.
- **An archive id is a name, not a path.** `/datasets/load` resolves its `id` against the inventory the scan produced and re-checks containment against the root; no request string is ever joined onto a path, so a traversal id has nothing to escape from.
- **Client input never selects a URL.** `region` is allowlisted before any outbound fetch; writes are origin-gated; uploads are capped before buffering; `FIRMS_MAP_KEY` is read from the environment only and never echoed.
- **scipy and scikit-learn import lazily** inside clustering/briefing. Do not move them back to module scope — it costs ~2.5 s of startup.
- **Never import chart code in the shell.** `charts.jsx` and `ForecastChart.jsx` are lazy for a reason; a new lazy target must resolve to a default export or the build guard fails.
- **Derived values must degrade honestly.** Thin selections answer `200` with a `note`; every panel is required to show that note instead of spinning.
- **`torch` is gone from the forecast, serving and training alike.** The per-request LSTM was replaced by the LightGBM model ([ADR 0003](decisions/0003-lightgbm-forecast.md)), and `train.py`'s neural pass — which wrote a `model/lstm.pt` nothing read — was removed with it, so no code path imports `torch` any more and `requirements.txt` does not carry it. Without a LightGBM checkpoint `/forecast` answers with the scaled seasonal climatology — archive-trained when a prior exists — and names the fallback in the UI.
- **`lightgbm` imports lazily**, inside `lgbm_forecast.load()`. Moving it to module scope costs start-up for a model only needed on the first served forecast; `test_smoke.py` asserts it with an AST scan.
- **The forecast gate keeps the prior except on the days LightGBM earned.** Scoring is discrete (1/7/14/30), so each day is judged by the nearest measured horizon at least as long as it; the earned days are served by the checkpoint, the rest by the prior, and `method` is `lgbm`/`prior`/`blend` with every row naming its own source. A missing, truncated, foreign-schema or losing checkpoint degrades to the prior and names it.
- **The gate is judged by the AOI's own regime, not just the planet's.** An AOI wholly inside a curated preset (`regions.region_for_box`) is scored by that preset's backtest row — the panel's pooled MASE is dominated by whichever regime burns most, so it can win while the preset loses. A box crossing presets, or the whole frame, is judged by the pooled panel. Only a *missing or incomplete* regional row falls back to the global one: a regional loss is a loss. `checkpoint.scored_on` names the scope that judged the response, and the regional row is the preset's whole box rather than the drawn AOI, which is the nearest quantity the checkpoint measured.
- **The forecast band is measured, not assumed.** `coverage.within_tolerance` is false when the empirical coverage on the held-out block is more than 5 points off nominal, and the panel is required to label the band *indicative* then. On the synthetic fixture it is false (79–87 % against a nominal 90 %) — that is the honest state, not a bug to tune away. On the real archive the shipped 365-day cut cannot run (the trimmed 731-day record against 1,095 needed), so no band ships; a supplementary 300-day cut under-covers at 56–76 %.
- **A coverage break in the archive is trimmed, not trained across.** `consistent_span` drops a trailing block whose 30-day level stays 50× below the record's own busy level for a month — this machine's archive ends with a 358-day NRT export over one state, 0.0007× the global level before it. Averaging across that seam halves the day-of-year climatology and floods training with all-zero rows; the drop, its dates and the ratio go into `metrics.panel.coverage`.
- **The training panel is a contiguous daily grid.** `train_forecast.panel_from_counts` reindexes to every day (a day no cell burned is a zero row). Without it a lag or rolling feature reaches across unobserved days in training while `frame_cell_series` reindexes at serve time, and the model is fitted on a different quantity from the one it predicts.
- **Never hand LightGBM a file it did not write.** Its C++ parser calls `Log::Fatal` on a truncated model and aborts the process, so `lgbm_forecast.load()` checks the recorded SHA-256 and parses from memory.
- **The training archive is never committed.** `.data/` is ~10 GB of local NASA exports and `firecal/backend/model/` is derived from it; both are gitignored, and a missing or malformed checkpoint is not an error.
- **Training and serving must harmonize identically.** `train.py` reads the archive through the server's own `harmonize(geometry=False)` and `harmonized_daily()`. A second implementation of the sensor rescale would train the model on a different quantity than the endpoint predicts.
- **CSS uppercases labels.** Write labels in sentence case and let the contract do the casing; acronyms are the only all-caps strings in source.

## Next steps

The follow-ups from the last review round, highest value first — two have landed and are marked done; the PRD's [roadmap](PRD.md#14-roadmap) and [gap list](PRD.md#13-known-gaps--risks) hold the full picture:

| Step | Why it is next |
|---|---|
| ✅ Done — `train_forecast.py` over the real FIRMS archive | Re-fitted 2026-10-19 on 15 exports / 10.3 GB / 126.2 M rows. The panel is **731 days × 3,928 cells** (2.76 M training rows) because the coverage guard now trims the archive's last 358 days — a state-sized NRT export at 0.0007× the level before it — instead of averaging it into the climatology; the round count (144) is picked on the last 90 days and the booster is refitted on every training row. Leave-one-season-out MASE at h=1/7/14/30: LightGBM **2.141/1.950/1.945/2.642** vs the prior's **1.478/1.934/1.983/2.027** — the model earns only h=14 on the pooled panel (h=7 is a 0.8 % loss), so a 30-day request answers days 1–7 and 15–30 from the prior and days 8–14 from the model. Region-scoped it still earns ground: California 1.605/1.666/1.594 vs 1.621/1.693/1.715 at 7/14/30 (days 2–30), Punjab 1.558/1.512 vs 1.844/2.079 at 7/14. The h=1 loss is data, not recursion (day 1 is a one-step prediction) or the round cap (2,000 rounds: +0.4 % MAE): across the seam the climatology read 0.78× the 2024 level and the forecast responded to yesterday at slope 0.53, and the two-season fold trained on 65 days — on that fold a full-row fit on the trimmed panel scored h=1 MASE **3.039** against 7.097 on the untrimmed one, while the full-row refit alone moved it 7.110 → 7.097. What remains is structural: a hedged per-cell conditional mean with no level anchor, where the prior (1.478) and persistence (1.212) both re-anchor on the recent aggregate — re-anchoring the model's own output measured 84,772 → 61,710 MAE on that fold, still behind the prior, so none shipped. The conformal band is **not applicable** (the trimmed 731-day record is 364 short of the 1,095-day cut) and a supplementary 300-day cut under-covers at 56–76 % against 90 % nominal, so this checkpoint ships no band |
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
