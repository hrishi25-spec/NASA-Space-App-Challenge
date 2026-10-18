#!/usr/bin/env python3
"""Fit the global LightGBM forecaster on the FIRMS archive.

    python train_forecast.py                 # scan .data/, build the panel, fit, backtest
    python train_forecast.py --limit 200000  # a few rows per file, for a smoke run
    python train_forecast.py --inventory     # list the files that would be read, stop
    python train_forecast.py --no-backtest   # fit and write the checkpoint only

What it produces
----------------
`model/lgbm_forecast.txt`, `model/lgbm_climo.npz` and `model/lgbm_metrics.json`, which
`/forecast` reads through `lgbm_forecast.py`.  The directory is gitignored and rebuilt from
the archive; delete it and the endpoint answers with the seasonal prior exactly as before.

The panel
---------
One row per 2-degree cell per day, target = that cell's *harmonized* daily activity: the
per-sensor rescale comes from `main.sensor_factors()`, the same function `daily()` uses, so
the model predicts the quantity `/forecast` serves.  The archive is read in chunks through
`main.harmonize(geometry=False)` -- the server's own harmonizer, as `train.py` does -- and
reduced to a (date x cell) count table, cached as `model/lgbm_panel.parquet` so the folds
below do not rescan ~10 GB.

Features
--------
sin/cos day-of-year, the cell's latitude/longitude, log1p counts lagged 1/7/14/28 days,
log1p rolling means over 7/28 days and the cell's day-of-year climatology computed from
*training years only*.  No ERA5, no exogenous predictor.

How it is validated
-------------------
Never a random split.  A time block hold-out removes one fire season at a time (leave-one-
fire-season-out) and a coarse-tile spatial block removes one region of ground; both are
asserted in `test_smoke.py` so the rule cannot drift.  Climatology and lags are built only
from data before the forecast origin.  Point-forecast MASE is reported against the existing
seasonal prior and a seasonal-naive forecast at horizons 1/7/14/30 days, per curated region.

The serving gate
----------------
`/forecast` serves LightGBM only at a horizon whose stored backtest MASE beats the seasonal
prior; otherwise it serves the prior.  If the model does not win, that is the result -- the
checkpoint is still written and the metrics record it, and the prior keeps serving.
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forecast_model as fm      # noqa: E402
import lgbm_forecast as lg       # noqa: E402
import main                      # noqa: E402  (the archive is harmonized with the server's rules)
import regions                   # noqa: E402

NEEDED = {"latitude", "longitude", "acq_date", "acq_time", "confidence",
          "brightness", "bright_ti4", "frp", "satellite", "instrument"}
CHUNK = 1_000_000
HORIZONS = (1, 7, 14, 30)

# A cell joins the panel once it has burned on at least this many distinct days.  Below it
# the cell's series is a handful of coincidences and adds noise to a model that already
# carries ~16,000 cells.
MIN_CELL_DAYS = 5

# Coarse spatial block for the hold-out: 30 degrees is wide enough that two blocks rarely
# share a fire regime, which is the point of a spatial split.
SPATIAL_BLOCK_DEG = 30.0

TWEEDIE_POWER = 1.5
DEFAULT_PARAMS = {
    "objective": "tweedie",
    "tweedie_variance_power": TWEEDIE_POWER,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 40,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "max_bin": 127,
    "verbosity": -1,
    "num_threads": 0,
}


def find_csvs(data_dir):
    """Every CSV in the archive, in a stable order so two runs agree."""
    return sorted(p for p in Path(data_dir).rglob("*.csv") if p.is_file())


# ------------------------------------------------------------------------------- scan
def scan(paths, chunk=CHUNK, limit=0, log=None):
    """Stream the archive into per-(cell, date, sensor) counts, with per-file accounting.

    Chunked, never all at once.  Each chunk goes through `main.harmonize(geometry=False)`
    -- the same confidence floor, timestamp build and sensor naming the endpoint applies --
    so the panel and the served series are the same quantity.
    """
    log = log or (lambda *a: None)
    parts, files = [], []
    sensors, rows, kept, total_bytes = {}, 0, 0, 0
    start = end = None
    for i, path in enumerate(paths, 1):
        size = path.stat().st_size
        total_bytes += size
        f_rows = f_kept = 0
        t0 = time.time()
        for raw in pd.read_csv(path, chunksize=chunk, usecols=lambda c: c in NEEDED):
            if limit and f_rows >= limit:
                break
            if limit:
                raw = raw.iloc[: limit - f_rows]
            f_rows += len(raw)
            h = main.harmonize(raw, geometry=False)
            f_kept += len(h)
            if h.empty:
                continue
            cell = fm.cell_bins(h.lat.values, h.lon.values)
            g = (h.assign(cell=cell)
                   .groupby(["cell", "date", "sensor"], observed=True).size()
                   .rename("n").reset_index())
            parts.append(g)
            lo, hi = h.date.min(), h.date.max()
            start = lo if start is None or lo < start else start
            end = hi if end is None or hi > end else end
            for s, n in h.sensor.value_counts().items():
                sensors[s] = sensors.get(s, 0) + int(n)
        rows += f_rows
        kept += f_kept
        files.append({"file": path.name, "bytes": size, "rows": f_rows, "kept": f_kept})
        log(f"  [{i}/{len(paths)}] {path.name:<40} {f_rows:>10,} rows  "
            f"{size / 1e6:>7.1f} MB  {time.time() - t0:>6.1f}s")

    if parts:
        cd = pd.concat(parts).groupby(["cell", "date", "sensor"], observed=True)["n"].sum().reset_index()
    else:
        cd = pd.DataFrame(columns=["cell", "date", "sensor", "n"])
    return {"cell_days": cd, "files": files, "rows": rows, "kept": kept, "bytes": total_bytes,
            "sensors": sensors,
            "start": None if start is None else str(start.date()),
            "end": None if end is None else str(end.date())}


def panel_from_counts(cell_days, min_cell_days=MIN_CELL_DAYS):
    """Turn per-(cell, date, sensor) counts into a harmonized (dates x cells) panel.

    The per-sensor multiplier is `main.sensor_factors()` measured on the *whole* archive --
    the identical rule `daily()` applies per frame -- and is applied per cell, so summing a
    row of the panel reproduces what `/forecast` will later predict.
    """
    if cell_days is None or not len(cell_days):
        return pd.DataFrame(), {}
    global_piv = cell_days.groupby(["date", "sensor"], observed=True)["n"].sum().unstack(fill_value=0)
    factors = main.sensor_factors(global_piv)
    wide = (cell_days.pivot_table(index=["date", "cell"], columns="sensor", values="n",
                                  fill_value=0, aggfunc="sum")
                     .mul(pd.Series(factors), axis="columns").sum(axis=1)
                     .unstack(fill_value=0.0))
    wide = wide.rename_axis(index="date", columns="cell").sort_index().sort_index(axis=1)
    wide.columns = wide.columns.astype("int64")
    wide.index = pd.DatetimeIndex(wide.index)
    # The archive only has a row for a (cell, date) that burned, so a quiet day -- or a day
    # no cell anywhere burned -- is simply absent. Reindex to a contiguous daily grid: the
    # lag and rolling features count *days*, and serving's `frame_cell_series` reindexes the
    # same way. Without this a 28-day mean would reach across an unobserved month as though
    # it were 28 consecutive days, and training would not match what `/forecast` does.
    wide = wide.reindex(pd.date_range(wide.index.min(), wide.index.max()), fill_value=0.0)
    wide = wide.loc[:, wide.sum(axis=0) > 0] if wide.shape[1] else wide
    active = (wide > 0).sum(axis=0)
    keep = active[active >= min_cell_days].index
    return wide[keep], factors


def panel_from_csv(paths, chunk=CHUNK, limit=0, log=None, min_cell_days=MIN_CELL_DAYS):
    sc = scan(paths, chunk=chunk, limit=limit, log=log)
    Y, factors = panel_from_counts(sc["cell_days"], min_cell_days=min_cell_days)
    return Y, sc, factors


# ---------------------------------------------------------------------------- splits
def time_folds(Y):
    """Leave-one-fire-season-out: one fold per calendar year, train on the rest.

    Fire-season year == calendar year here (the panel is a day-of-year series, so a season
    split at a year boundary is the honest available unit).  No shuffle, no random_state:
    the folds are disjoint, ordered and cover every day exactly once.
    """
    years = Y.index.year.to_numpy()
    folds = []
    for y in sorted(set(years.tolist())):
        test = years == y
        train = ~test
        if train.sum() and test.sum():
            folds.append((str(y), train, test))
    return folds


def _column_mask(n_cells, idx):
    m = np.zeros(n_cells, dtype=bool)
    m[idx] = True
    return m


def spatial_folds(Y, block_deg=SPATIAL_BLOCK_DEG):
    """Spatial block hold-outs: the curated regions first, coarse tiles as the fallback.

    Holding out a named fire region and training on the rest is the spatial analogue of
    the seasonal split: can a model fitted everywhere *else* predict a region it has never
    seen?  Returns (folds, kind), each fold `(name, train_cells, test_cells)` with boolean
    column masks.  A panel that overlaps fewer than two curated regions (a fixture in one
    small box, say) falls back to 30-degree tiles so the split still exists; if even that
    yields a single block the caller reports it as not applicable rather than scoring a
    degenerate fold.
    """
    folds = []
    for key in regions.REGIONS:
        out = _column_mask(Y.shape[1], cells_in_box(Y.columns, regions.region_box(key)))
        if out.any() and (~out).any():
            folds.append((key, ~out, out))
    if len(folds) >= 2:
        return folds, "curated regions"
    la, lo = lg.cell_center(np.asarray(Y.columns, dtype=np.int64))
    tile = (np.floor((la + 90.0) / block_deg).astype(int) * 1000
            + np.floor((lo + 180.0) / block_deg).astype(int))
    tiles = [(str(t), ~(tile == t), tile == t) for t in sorted(set(tile.tolist()))
             if (tile == t).any() and (~(tile == t)).any()]
    return tiles, "coarse tiles"


def cells_in_box(cells, box):
    """Indices of the panel cells whose centre falls inside a (minlat, minlon, maxlat, maxlon)."""
    la, lo = lg.cell_center(np.asarray(cells, dtype=np.int64))
    a, b, c, e = box
    inside = (la >= a) & (la <= c) & (lo >= b) & (lo <= e)
    return np.flatnonzero(inside)


# ------------------------------------------------------------------------------ fit
def _rows_mask(mask, n_cells, ok):
    """Expand a per-date boolean mask to the (date x cell) row order build_features uses."""
    return np.repeat(np.asarray(mask, dtype=bool), n_cells) & ok


def fit_model(Y, climo, train_mask, params=None, rounds=600, early_stopping=40, log=None):
    """Fit one global Tweedie booster on the training rows, early-stopping on a time block.

    The early-stopping set is the most recent training season rather than a random slice:
    with a time series, a random validation row is a near-duplicate of a training row, and
    the stopping point it picks is optimistic.  Returns (booster, best_iteration, n_train).
    """
    log = log or (lambda *a: None)
    import lightgbm as lgb

    params = dict(DEFAULT_PARAMS if params is None else params)
    X, y, ok = lg.build_features(Y, climo)
    n_cells = Y.shape[1]
    years = Y.index.year.to_numpy()
    train_rows = _rows_mask(train_mask, n_cells, ok)
    if not train_rows.any():
        raise ValueError("fit_model: no training rows")

    train_years = sorted(set(years[np.asarray(train_mask)].tolist()))
    val_year = train_years[-1] if len(train_years) > 1 else None
    if val_year is None:
        tr = train_rows
        valid = (None, None)
    else:
        is_val = _rows_mask(years == val_year, n_cells, ok)
        tr = train_rows & ~is_val
        valid = (X[is_val], y[is_val]) if is_val.any() else (None, None)

    dtr = lgb.Dataset(X[tr], label=y[tr], feature_name=list(lg.FEATURES), free_raw_data=True)
    callbacks = [lgb.log_evaluation(0)]
    valid_sets = []
    if valid[0] is not None:
        valid_sets = [lgb.Dataset(valid[0], label=valid[1], reference=dtr)]
        callbacks.append(lgb.early_stopping(early_stopping, verbose=False))
    booster = lgb.train(params, dtr, num_boost_round=int(rounds),
                        valid_sets=valid_sets, callbacks=callbacks)
    best = booster.best_iteration or int(rounds)
    log(f"    fit {int(tr.sum()):,} rows, {best} best iter"
        + (f" (stopped on {val_year})" if valid_sets else ""))
    return booster, best, int(tr.sum())


# ------------------------------------------------------------------------- baselines
def _doy_curve(series, train_mask, window=15):
    """Smoothed day-of-year climatology of a series, from training rows only."""
    tr = series[train_mask]
    g = tr.groupby(tr.index.dayofyear).mean().reindex(range(1, 367)).interpolate(
        limit_direction="both")
    return g.rolling(window, center=True, min_periods=1).mean()


def prior_forecast(series, origin_pos, horizon, climo):
    """The endpoint's seasonal fallback, at a region's own level: climo scaled to recent 30d."""
    recent = series.iloc[max(0, origin_pos - 30):origin_pos]
    scale = (recent.mean() + 1.0) / (climo.reindex(recent.index.dayofyear).mean() + 1.0)
    target = pd.date_range(series.index[origin_pos - 1] + pd.Timedelta(days=1), periods=horizon)
    return climo.reindex(target.dayofyear).to_numpy() * scale


def seasonal_naive(series, origin_pos, horizon, period=364):
    """Same day-of-year a year earlier: the classic seasonal-naive benchmark."""
    out = []
    for h in range(1, horizon + 1):
        t = series.index[origin_pos - 1] + pd.Timedelta(days=h)
        past = t - pd.Timedelta(days=period)
        out.append(float(series[series.index == past].iloc[0]) if (series.index == past).any() else 0.0)
    return np.array(out, dtype=float)


def _naive_scale(series, train_mask):
    d = series.diff().abs()[train_mask]
    v = float(d.mean())
    return v if v > 1e-9 else 1e-9


# ------------------------------------------------------------------------- backtest
def spatial_backtest(Y, horizons=HORIZONS, origin_step=14, log=None, params=None,
                     rounds=600, max_blocks=12):
    """Coarse-tile spatial block hold-out: fit without a block of ground, score on it.

    A different question from the time folds: can a model fitted on the rest of the planet
    predict a region it has never seen?  Blocks are 30-degree tiles, largest first and
    capped so the run stays bounded.  A panel that occupies fewer than two tiles cannot be
    split this way and reports that honestly rather than scoring a degenerate fold.
    """
    log = log or (lambda *a: None)
    folds, kind = spatial_folds(Y)
    out = {"applicable": bool(folds), "blocks": len(folds), "kind": kind,
           "block_deg": None if kind == "curated regions" else SPATIAL_BLOCK_DEG,
           "names": [name for name, _, _ in folds],
           "horizons": list(horizons), "by_horizon": {}}
    if not folds:
        out["note"] = "the panel occupies a single spatial block; no held-out ground to score"
        return out
    folds = sorted(folds, key=lambda f: -int(np.asarray(f[2]).sum()))[:max_blocks]
    # The block is held out in space, but the model still must not read the evaluation
    # window: the held-out cells' climatology and the prior baseline come from dates before
    # it.  Scoring runs on the last year of the record.
    eval_start = Y.index.max() - pd.Timedelta(days=365)
    pre = np.asarray(Y.index < eval_start, dtype=bool)
    err = {h: {"lgbm": [], "prior": [], "naive": []} for h in horizons}
    scale = None
    for name, train_cells, test_cells in folds:
        train_cells = np.asarray(train_cells, dtype=bool)
        test_cells = np.asarray(test_cells, dtype=bool)
        Ytr = Y.loc[:, Y.columns[train_cells]]
        booster, _, _ = fit_model(Ytr, lg.climo_table(Ytr, None),
                                  np.ones(len(Ytr), dtype=bool),
                                  params=params, rounds=rounds, log=log)
        sub = Y.loc[:, Y.columns[test_cells]]
        climo_te = lg.climo_table(sub[pre], None)      # test cells, pre-evaluation dates only
        series = sub.sum(axis=1)
        climo_g = _doy_curve(series, pre)
        scale = _naive_scale(series, pre)
        origins = np.flatnonzero(~pre)[::origin_step]
        for pos in origins:
            pos = int(pos)
            if pos < 30 or pos + max(horizons) > len(series):
                continue
            _, path = lg.predict_path(sub.iloc[:pos], climo_te, booster, max(horizons))
            pf = prior_forecast(series, pos, max(horizons), climo_g)
            nf = seasonal_naive(series, pos, max(horizons))
            for h in horizons:
                actual = float(series.iloc[pos + h - 1])
                for k, v in (("lgbm", path[h - 1]), ("prior", pf[h - 1]), ("naive", nf[h - 1])):
                    err[h][k].append(abs(v - actual))
        log(f"  spatial block {name}: {int(test_cells.sum())} held-out cells")
    if scale:
        for h in horizons:
            if err[h]["lgbm"]:
                out["by_horizon"][str(h)] = {k: round(float(np.mean(err[h][k])) / scale, 4)
                                              for k in ("lgbm", "prior", "naive")} | {"n": len(err[h]["lgbm"])}
    return out


def backtest(Y, horizons=HORIZONS, origin_step=7, log=None, params=None, rounds=600):
    """Leave-one-fire-season-out MASE for LightGBM, the seasonal prior and seasonal-naive.

    Evaluated on the region's own daily total -- the quantity `/forecast` reports -- so the
    three forecasts are directly comparable.  LightGBM rolls forward recursively from each
    origin; the prior and seasonal-naive are direct.  Scored per curated region and for the
    whole panel ('overall', which is what the serving gate reads).
    """
    log = log or (lambda *a: None)
    folds = time_folds(Y)
    groups = {"overall": np.arange(Y.shape[1])}
    for key in regions.REGIONS:
        idx = cells_in_box(Y.columns, regions.region_box(key))
        if idx.size:
            groups[key] = idx
    region_na = [k for k in regions.REGIONS if k not in groups]

    err = {(g, h): {"lgbm": [], "prior": [], "naive": []} for g in groups for h in horizons}
    scales = {}
    for name, train_mask, test_mask in folds:
        train_mask = np.asarray(train_mask, dtype=bool)
        climo = lg.climo_table(Y, train_mask)
        booster, _, _ = fit_model(Y, climo, train_mask, params=params, rounds=rounds, log=log)
        test_positions = np.flatnonzero(np.asarray(test_mask, dtype=bool))
        origins = test_positions[::origin_step]
        for g, cols in groups.items():
            series = Y.iloc[:, cols].sum(axis=1)
            climo_g = _doy_curve(series, train_mask)
            scales.setdefault(g, _naive_scale(series, train_mask))
            sub = Y.iloc[:, cols]
            for pos in origins:
                pos = int(pos)
                if pos < 30 or pos + max(horizons) > len(series):
                    continue
                hist = sub.iloc[:pos]
                _, path = lg.predict_path(hist, climo, booster, max(horizons))
                pf = prior_forecast(series, pos, max(horizons), climo_g)
                nf = seasonal_naive(series, pos, max(horizons))
                for h in horizons:
                    actual = float(series.iloc[pos + h - 1])
                    for k, v in (("lgbm", path[h - 1]), ("prior", pf[h - 1]), ("naive", nf[h - 1])):
                        err[(g, h)][k].append(abs(v - actual))
        log(f"  fold {name}: {len(origins)} origins, "
            f"{len([g for g in groups])} group(s)")

    def mase(cell, g, h):
        vals = cell[(g, h)]
        if not vals["lgbm"]:
            return None
        return {k: round(float(np.mean(vals[k])) / scales[g], 4) for k in ("lgbm", "prior", "naive")} \
            | {"n": len(vals["lgbm"])}

    by_region = {}
    for g in groups:
        by_region[g] = {str(h): mase(err, g, h) for h in horizons}
    by_horizon = {str(h): mase(err, "overall", h) for h in horizons}
    return {
        "method": {"time": "leave-one-fire-season-out", "spatial": "region/tile block hold-out",
                   "random_split": False, "origin_step_days": origin_step,
                   "folds": [name for name, _, _ in folds]},
        "horizons": list(horizons),
        "naive_scale_overall": {k: round(v, 4) for k, v in scales.items()},
        "by_horizon": by_horizon,
        "by_region": by_region,
        "spatial": spatial_backtest(Y, horizons=horizons, origin_step=max(origin_step, 14),
                                    log=log, params=params, rounds=rounds),
        "regions_without_panel_cells": region_na,
        "notes": ([f"{len(region_na)} curated region(s) have no panel cells in this archive: "
                   + ", ".join(region_na)] if region_na else []),
    }


# ------------------------------------------------------------------------ uncertainty
def _split_conformal_quantile(vals, alpha):
    """The (1-alpha) conformal quantile with the finite-sample rank correction.

    Split conformal calibration is a quantile of held-out absolute residuals; the rank is
    `ceil((n+1)(1-alpha))`, not the plain empirical quantile, because that is the order
    statistic whose coverage guarantee holds for finite n.  No conformal library is used:
    this is the whole method, and pulling in MAPIE (which itself pulls scikit-learn and a
    typing stack) for one order statistic would be the heavier dependency for no more
    correctness.  That trade is recorded in ADR 0004.
    """
    n = len(vals)
    if n == 0:
        return None
    k = int(np.ceil((n + 1) * (1.0 - alpha))) - 1
    k = min(max(k, 0), n - 1)
    return float(np.sort(np.asarray(vals, dtype=float))[k])


def conformal_calibration(Y, alpha=0.1, horizon_max=30, cal_days=365, test_days=365,
                          origin_step=2, params=None, rounds=600, log=None):
    """Split-conformal intervals, calibrated on a time block later than the training block.

    The record is cut into three consecutive blocks: train (everything before the
    calibration window), calibration, then test.  The model is fitted on `train` only, the
    per-horizon relative-error quantiles come from `calibration` only, and the reported
    empirical coverage is measured on `test` only -- so the number the docs quote was not
    fitted for, and the band was calibrated on a block strictly earlier than the one it is
    scored on.

    Residuals are relative (`log1p(actual) - log1p(predicted)`), so one table transfers to
    an AOI of any size, and they are pooled across the curated regions and the whole panel
    to get enough samples for a per-horizon quantile.  Blocks are time-ordered, which is the
    honest approximation for a series whose points are not exchangeable.
    """
    log = log or (lambda *a: None)
    end = Y.index.max()
    test_start = end - pd.Timedelta(days=int(test_days))
    cal_start = test_start - pd.Timedelta(days=int(cal_days))
    train_mask = np.asarray(Y.index < cal_start, dtype=bool)
    cal_mask = np.asarray((Y.index >= cal_start) & (Y.index < test_start), dtype=bool)
    test_mask = np.asarray(Y.index >= test_start, dtype=bool)
    if train_mask.sum() < int(cal_days) or cal_mask.sum() < 60 or test_mask.sum() < 60:
        return {"applicable": False, "nominal": 1.0 - alpha,
                "note": f"needs a train block of >= {cal_days} days before a {cal_days}-day "
                        f"calibration block and a {test_days}-day test block; the record has "
                        f"{len(Y)} days"}
    groups = {"overall": np.arange(Y.shape[1])}
    for key in regions.REGIONS:
        idx = cells_in_box(Y.columns, regions.region_box(key))
        if idx.size:
            groups[key] = idx
    climo = lg.climo_table(Y, train_mask)
    booster, _, _ = fit_model(Y, climo, train_mask, params=params, rounds=rounds, log=log)

    def residuals(mask):
        pooled = {h: [] for h in range(1, horizon_max + 1)}
        per = {}
        for p in np.flatnonzero(mask)[::origin_step]:
            p = int(p)
            if p < max(lg.LAGS) + 1 or p + horizon_max > len(Y):
                continue
            _, M = lg.path_matrix(Y.iloc[:p], climo, booster, horizon_max)
            for g, cols in groups.items():
                pred = M[:, cols].sum(axis=1)
                actual = Y.iloc[p:p + horizon_max, cols].to_numpy().sum(axis=1)
                r = np.log1p(actual) - np.log1p(np.clip(pred, 0.0, None))
                for h in range(1, horizon_max + 1):
                    v = abs(float(r[h - 1]))
                    pooled[h].append(v)
                    per.setdefault((g, h), []).append(v)
        return pooled, per

    cal_pooled, _ = residuals(cal_mask)
    quantiles = {str(h): _split_conformal_quantile(cal_pooled[h], alpha)
                 for h in range(1, horizon_max + 1)}
    quantiles = {k: v for k, v in quantiles.items() if v is not None}
    _, test_per = residuals(test_mask)

    def empirical(per, g, h):
        q = quantiles.get(str(h))
        vals = per.get((g, h), [])
        if q is None or not vals:
            return None
        return round(float(np.mean([v <= q for v in vals])), 4)

    emp = {str(h): empirical(test_per, "overall", h) for h in range(1, horizon_max + 1)}
    by_region = {g: {str(h): empirical(test_per, g, h) for h in range(1, horizon_max + 1)}
                 for g in groups}
    by_region = {g: {h: v for h, v in row.items() if v is not None} for g, row in by_region.items()}
    out = {
        "applicable": True,
        "method": "split conformal on log1p relative error, per horizon, in-repo",
        "alpha": alpha, "nominal": 1.0 - alpha, "horizon_max": horizon_max,
        "blocks": {"train": [str(Y.index[train_mask].min().date()), str(Y.index[train_mask].max().date())],
                   "calibration": [str(Y.index[cal_mask].min().date()), str(Y.index[cal_mask].max().date())],
                   "test": [str(Y.index[test_mask].min().date()), str(Y.index[test_mask].max().date())]},
        "n_calibration": int(cal_mask.sum()), "n_test": int(test_mask.sum()),
        "origin_step_days": origin_step,
        "pooled_series": sorted(groups),
        "quantiles": {k: round(v, 6) for k, v in quantiles.items()},
        "coverage": {"empirical": {k: v for k, v in emp.items() if v is not None},
                     "by_region": by_region},
    }
    dev = [abs(float(v) - out["nominal"]) for v in out["coverage"]["empirical"].values()]
    out["within_tolerance"] = bool(max(dev) <= 0.05) if dev else None
    log(f"  conformal (alpha {alpha}): calibrated {int(cal_mask.sum())} days, scored "
        f"{int(test_mask.sum())}, coverage {out['coverage']['empirical']}")
    return out


# ------------------------------------------------------------------------- checkpoint
def library_versions():
    out = {}
    for name in ("lightgbm", "numpy", "pandas"):
        try:
            out[name] = md.version(name)
        except md.PackageNotFoundError:
            out[name] = None
    return out


def run(data_dir=None, out=lg.model_dir(), chunk=CHUNK, limit=0, rounds=600,
        origin_step=7, use_backtest=True, use_conformal=True, alpha=0.1,
        use_panel_cache=True, min_cell_days=MIN_CELL_DAYS, log=print):
    """The whole job: scan, build the panel, fit, backtest, write.  Returns the metrics."""
    root = fm.data_dir(data_dir)
    if root is None:
        raise SystemExit(f"no training directory found (looked for {', '.join(fm.DATA_DIRS)})")
    paths = find_csvs(root)
    if not paths:
        raise SystemExit(f"{root} holds no CSV files")

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    panel_path = out / lg.PANEL_FILE
    t0 = time.time()

    source = None
    if use_panel_cache and panel_path.is_file():
        Y = pd.read_parquet(panel_path)
        Y.columns = Y.columns.astype("int64")
        log(f"reused the cached panel {panel_path.name} ({Y.shape[0]} days x {Y.shape[1]} cells)")
    else:
        log(f"training on {len(paths)} CSV file(s) in {root}")
        Y, scanned, factors = panel_from_csv(paths, chunk=chunk, limit=limit,
                                             min_cell_days=min_cell_days, log=log)
        if Y.empty:
            raise SystemExit("the archive produced no cells above the activity floor")
        Y.to_parquet(panel_path)
        log(f"panel: {Y.shape[0]} days x {Y.shape[1]} cells -> {panel_path.name}")
        # `cell_days` is the whole long-form frame -- not something to keep in the metrics.
        source = {k: v for k, v in scanned.items() if k != "cell_days"}
        source["factors"] = {str(k): round(float(v), 6) for k, v in (factors or {}).items()}
    if source is None:
        source = {"dir": str(root), "files": len(paths), "limit": limit or None,
                  "note": "reused a cached panel; archive not re-read"}

    # The longest lag is undefined for the panel's opening max(LAGS) rows, so a record that
    # short has no usable training row at all and `fit_model` would fail with an internal
    # "no training rows" -- a traceback that says nothing about the archive being too short.
    # That is exactly the shape a bare FIRMS download arrives in (the open feeds are 7 days),
    # so the count, the dates and the remedy are named here instead.
    warmup = max(lg.LAGS)
    if len(Y) <= warmup:
        raise SystemExit(
            f"the archive spans {len(Y)} day(s) ({Y.index.min().date()} to "
            f"{Y.index.max().date()}), but the model's longest feature is a {warmup}-day lag "
            f"and is undefined for the panel's first {warmup} days, so {len(Y)} days leaves no "
            "usable training row at all. Point --data at a longer record -- "
            "firecal/backend/fetch_archive.py builds one from the FIRMS area API."
        )

    # The stored climatology is the full-archive one: at serve time "training years" is the
    # whole archive.  Backtest folds build their own from the fold's training rows.
    climo = lg.climo_table(Y, None)
    booster, best, n_train = fit_model(Y, climo, np.ones(len(Y), dtype=bool),
                                       rounds=rounds, log=log)

    metrics = {
        "trained_by": "firecal/backend/train_forecast.py",
        "grid_deg": fm.GRID_DEG,
        "objective": DEFAULT_PARAMS["objective"],
        "tweedie_variance_power": TWEEDIE_POWER,
        "params": {k: v for k, v in DEFAULT_PARAMS.items() if k != "num_threads"},
        "best_iteration": int(best),
        "train_rows": n_train,
        "library": library_versions(),
        "panel": {"rows": int(Y.shape[0]), "cells": int(Y.shape[1]),
                  "start": str(Y.index.min().date()), "end": str(Y.index.max().date()),
                  "seasons": sorted(set(Y.index.year.tolist())),
                  "min_cell_days": min_cell_days},
        "source": source,
    }
    if use_backtest:
        bt = backtest(Y, origin_step=origin_step, log=log, rounds=rounds)
        metrics["backtest"] = bt
        # Ask the gate itself rather than repeating its comparison: a second transcription
        # of the rule is how this block came to disagree with the scores it reports on.
        metrics["serving"] = {"beats_prior_at": {
            str(h): lg.gate(metrics, h)[0] for h in HORIZONS}}
    if use_conformal:
        metrics["conformal"] = conformal_calibration(
            Y, alpha=alpha, horizon_max=max(HORIZONS), rounds=rounds, log=log)
        metrics.setdefault("serving", {})["conformal"] = bool(metrics["conformal"].get("applicable"))
    metrics["seconds"] = round(time.time() - t0, 1)   # the whole job, backtest included
    lg.save(booster, Y.columns.to_numpy(), climo, metrics, explicit=out)
    return metrics


def cli(argv=None):
    ap = argparse.ArgumentParser(description="Train the Pyro-Harmony LightGBM forecaster.")
    ap.add_argument("--data", default=None, help=f"training directory (default: auto, one of {fm.DATA_DIRS})")
    ap.add_argument("--out", default=str(lg.model_dir()), help="where the checkpoint is written")
    ap.add_argument("--chunk", type=int, default=CHUNK)
    ap.add_argument("--limit", type=int, default=0, help="rows per file; 0 reads each file whole")
    ap.add_argument("--rounds", type=int, default=600, help="max boosting rounds")
    ap.add_argument("--origin-step", type=int, default=7, help="days between backtest origins")
    ap.add_argument("--min-cell-days", type=int, default=MIN_CELL_DAYS)
    ap.add_argument("--no-backtest", action="store_true", help="fit and write, skip the backtest")
    ap.add_argument("--no-conformal", action="store_true", help="skip the conformal calibration")
    ap.add_argument("--alpha", type=float, default=0.1, help="conformal miscoverage (0.1 -> 90%% intervals)")
    ap.add_argument("--no-cache", action="store_true", help="ignore a cached panel and rescan")
    ap.add_argument("--inventory", action="store_true", help="list the files that would be read, then stop")
    args = ap.parse_args(argv)

    root = fm.data_dir(args.data)
    if root is None:
        raise SystemExit(f"no training directory found (looked for {', '.join(fm.DATA_DIRS)})")
    if args.inventory:
        paths = find_csvs(root)
        total = sum(p.stat().st_size for p in paths)
        for p in paths:
            print(f"  {p.stat().st_size / 1e6:>9.1f} MB  {p.parent.name}/{p.name}")
        print(f"  {len(paths)} file(s), {total / 1e9:.2f} GB in {root}")
        return 0

    m = run(data_dir=args.data, out=args.out, chunk=args.chunk, limit=args.limit,
            rounds=args.rounds, origin_step=args.origin_step, use_backtest=not args.no_backtest,
            use_conformal=not args.no_conformal, alpha=args.alpha,
            use_panel_cache=not args.no_cache, min_cell_days=args.min_cell_days)
    print(f"\npanel: {m['panel']['rows']} days x {m['panel']['cells']} cells "
          f"({m['panel']['start']} -> {m['panel']['end']}, {len(m['panel']['seasons'])} season(s))")
    print(f"fit: {m['train_rows']:,} rows, best iteration {m['best_iteration']}")
    if "backtest" in m:
        print("MASE at horizon 1/7/14/30 (LightGBM / prior / naive):")
        for h in HORIZONS:
            r = m["backtest"]["by_horizon"].get(str(h))
            if r:
                print(f"  h={h:<3} {r['lgbm']:>6.3f} / {r['prior']:>6.3f} / {r['naive']:>6.3f}   n={r['n']}")
        print("regions without panel cells:", ", ".join(m["backtest"]["regions_without_panel_cells"]) or "none")
        print("serving gate (beats prior):", m["serving"]["beats_prior_at"])
    if "conformal" in m:
        cf = m["conformal"]
        if cf.get("applicable"):
            print(f"conformal {cf['nominal']:.0%}: half-widths h=1/7/14/30 "
                  f"{cf['quantiles'].get('1')}/{cf['quantiles'].get('7')}/"
                  f"{cf['quantiles'].get('14')}/{cf['quantiles'].get('30')}, "
                  f"empirical coverage {cf['coverage']['empirical']}")
            print("within tolerance:", cf.get("within_tolerance"))
        else:
            print("conformal: not applicable —", cf.get("note"))
    print(f"wrote {Path(args.out) / lg.MODEL_FILE}, {Path(args.out) / lg.CLIMO_FILE}, "
          f"{Path(args.out) / lg.METRICS_FILE} in {m['seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
