# 0003 — LightGBM is the archive forecast model; the LSTM serving path is retired

- **Date:** 2026-10-11
- **Status:** Accepted

## Context

`/forecast` had two paths. With `torch` installed it fine-tuned a small LSTM per request on
the operator's own frame, warm-started from an archive checkpoint when one existed; without
`torch` — which is the default, since `torch` is a heavy optional dependency — it fell back
to a day-of-year climatology scaled to the frame's recent level, blended with the
archive-trained 2-degree-cell prior. FR-10.6 had already taught that prior to be built from
the FIRMS archive, but the seasonal fallback was still the path almost every install ran,
and FR-10.3 could never be marked done because the neural half needed an optional wheel.

The archived record is not a single series. It is ~10 GB of MODIS and VIIRS detections
spanning many fire seasons and the whole globe, and the shape that matters is the one a
*cell* has in a *season* — the seasonal fallback throws that structure away by averaging it
into one global curve. A model that is fitted once, offline, over every cell and season, and
then served from a small checkpoint, fits the data we actually have far better than either a
per-request neural fit or a single global climatology.

## Decision

- **LightGBM, one global model, Tweedie objective.** `train_forecast.py` reduces the archive
  to a 2-degree-cell × day panel whose target is the *harmonized* daily activity — the same
  quantity `/forecast` serves, built through `main.harmonize(geometry=False)` and the single
  `main.sensor_factors()` rescale, so training and serving cannot diverge. Features are
  sin/cos day-of-year, 1/7/14/28-day lags, 7/28-day rolling means, the cell's training-years
  day-of-year climatology and its latitude/longitude. No ERA5, no exogenous predictors.
- **Validation is blocked, never random.** Leave-one-fire-season-out in time, plus a
  spatial hold-out by curated region (30° tiles as the fallback); `test_smoke.py` asserts
  the split code contains no random split, and that the folds are disjoint and cover every
  day once.
- **The prior keeps serving unless LightGBM earns the horizon.** `lgbm_forecast.gate()`
  serves the checkpoint only at a horizon whose *stored* backtest MASE is strictly better
  than the seasonal prior's, and the response's `model` field names which one ran and why. A
  negative result is a valid result: if the model does not win, the checkpoint is still
  written and the metrics record the loss, and the prior serves.
- **`torch` stays optional and the LSTM serving path is gone.** `/forecast` no longer
  imports `torch` at all; `train.py`'s optional LSTM training pass remains but nothing reads
  its `lstm.pt` output. `torch` is neither required nor used to serve a forecast.
- **`lightgbm` is imported lazily**, inside the functions that use it, like `scipy` and
  `scikit-learn` — the app's start-up budget is ~2 s and the booster is only needed the
  first time a checkpoint is actually read.

## Consequences

- **A checkpoint is an upgrade, never a dependency.** A missing, truncated, foreign-schema
  or unreadable checkpoint degrades to the seasonal prior and names the fallback. Because
  LightGBM's C++ parser *aborts the process* on a truncated model file rather than raising,
  `lgbm_forecast.load()` verifies the booster's length and SHA-256 (recorded by `save()`)
  before LightGBM ever sees it; the verified bytes are parsed from memory.
- **Serving an AOI means summing cells.** `/forecast` builds each cell's lag/rolling
  features from the frame, rolls the model forward recursively and sums the cells in the AOI
  (bounded to the most active `MAX_CELLS`). A global model has nothing to say about ground it
  never saw, so an AOI with no trained cells falls back rather than extrapolating.
- **The measured backtest is not a win.** On the repository's own synthetic 2002–2024
  fixture the seasonal prior beat LightGBM at every horizon (see the PRD verification table);
  the gate therefore keeps the prior. The real archive is not on this machine, so no
  real-data score exists yet — that is stated in the PRD rather than papered over.
- **`.data/` and `model/` stay gitignored.** The checkpoint and the panel cache are derived,
  rebuilt by `train_forecast.py`, and never committed.
