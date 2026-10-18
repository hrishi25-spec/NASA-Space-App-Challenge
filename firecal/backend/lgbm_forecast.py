"""The LightGBM forecast model's shared half: features, checkpoint IO and serving.

This module is imported by `main.py` (which serves `/forecast`) and by
`train_forecast.py` (which fits the model on the FIRMS archive). It exists so the feature
vector the model is *trained* on and the one it is *served* are built by the same function:
a second implementation of the lag/rolling/climatology arithmetic would train the model on
one quantity and predict another, which is the same failure mode the two harmonizers are
forbidden from having.

`lightgbm` is imported **lazily**, inside the functions that use it, for the same reason
`torch` and `scikit-learn` are: the app's start-up budget is ~2 s and lightgbm drags in a
compiled booster the server only needs the first time a forecast is actually fitted from
the checkpoint. Importing this module must not import lightgbm -- `test_smoke.py` asserts
that with an AST scan, so the rule cannot drift silently.

What lives where
----------------
  * `model/lgbm_forecast.txt` -- the booster, as LightGBM's own text format.
  * `model/lgbm_climo.npz`    -- the per-cell x day-of-year climatology the features use,
    computed from *training* years only, so a backtest fold cannot read its own future.
  * `model/lgbm_metrics.json` -- schema version, the feature list, library versions, the
    training range/row counts and the backtest scores the serving gate reads.

The directory is `forecast_model.MODEL_DIR` (gitignored, built by `train_forecast.py`).
A missing, truncated, foreign-schema or unreadable checkpoint is never an error: every
loader here returns None and the endpoint answers with the seasonal prior instead.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import forecast_model as fm

# Bumped whenever a change would make an older checkpoint misleading rather than merely
# incomplete.  `load()` refuses anything it does not recognize instead of guessing, so a
# checkpoint written by a different feature set degrades to the prior rather than being
# fed a feature vector in the wrong order.
SCHEMA = 1

# Cells are the same 2-degree grid the seasonal prior uses (`forecast_model.cell_bins`), so
# a LightGBM cell id and a prior cell id name the same patch of ground.
GRID_DEG = fm.GRID_DEG
DOY_BINS = fm.DOY_BINS

MODEL_FILE = "lgbm_forecast.txt"
CLIMO_FILE = "lgbm_climo.npz"
METRICS_FILE = "lgbm_metrics.json"
PANEL_FILE = "lgbm_panel.parquet"      # the cached cell-day panel, so folds need one scan

# The feature vector, in the order it is stacked.  This list is written into the checkpoint
# and re-checked on load: a checkpoint whose feature list differs is refused.
FEATURES = ("doy_sin", "doy_cos", "lat", "lon",
            "lag_1", "lag_7", "lag_14", "lag_28", "roll_7", "roll_28", "climo")
LAGS = (1, 7, 14, 28)
ROLLS = (7, 28)

# Serving sums a recursive per-cell forecast over the AOI.  A global request touches every
# cell in the frame, so the work is bounded by taking the most active cells: a top-N by
# detections covers essentially all of the activity while keeping one /forecast call cheap.
MAX_CELLS = 2000


def model_dir(explicit=None) -> Path:
    return Path(fm.MODEL_DIR if explicit is None else explicit)


def paths(explicit=None):
    """(booster, climo, metrics) paths inside a model directory."""
    d = model_dir(explicit)
    return d / MODEL_FILE, d / CLIMO_FILE, d / METRICS_FILE


# --------------------------------------------------------------------------- features
def cell_center(cells):
    """Latitude/longitude of the 2-degree cell centred on each flattened cell id."""
    la, lo = np.divmod(np.asarray(cells, dtype=np.int64), fm.LON_BINS)
    return (la + 0.5) * GRID_DEG - 90.0, (lo + 0.5) * GRID_DEG - 180.0


def doy_angles(doy):
    """sin/cos of the day of year: two smooth features instead of a saw-tooth 1..366."""
    a = 2.0 * np.pi * np.asarray(doy, dtype=float) / 365.25
    return np.sin(a), np.cos(a)


def climo_table(Y, train_mask=None):
    """Per-cell day-of-year climatology, in log1p space, from `train_mask` rows only.

    `Y` is a (dates x cells) frame of daily counts.  When `train_mask` is given the
    climatology is computed from those rows alone -- this is the leakage guard: a backtest
    fold must not see the season it is predicting.  Missing day-of-years (a short record,
    or a fold that drops one year) are interpolated across the year so the feature is
    always defined; cells with no data at all stay 0.
    """
    if train_mask is not None:
        Y = Y[train_mask]
    if not len(Y):
        raise ValueError("climo_table: no rows to build a climatology from")
    doy = Y.index.dayofyear.to_numpy()
    grouped = Y.groupby(doy).mean()
    tab = pd.DataFrame(np.nan, index=np.arange(1, DOY_BINS + 1),
                       columns=Y.columns, dtype=float)
    tab.loc[grouped.index, :] = grouped.to_numpy()
    tab = tab.interpolate(axis=0, limit_direction="both")
    return np.log1p(tab.fillna(0.0))


def build_features(Y, climo):
    """Long-form feature matrix for a (dates x cells) count frame.

    Returns (X, y, ok): `X` is (rows x len(FEATURES)) in FEATURES order, `y` the raw
    counts, and `ok` a boolean mask dropping the opening max(LAGS) rows, where the longest
    lag is still undefined -- so a panel of T days has T - max(LAGS) usable rows, and a panel
    shorter than that has none.  Rollings use min_periods=1 so they are defined from row 0.
    """
    T, C = Y.shape
    vals = Y.to_numpy(dtype=np.float64)
    logy = np.log1p(vals)
    sin, cos = doy_angles(Y.index.dayofyear.to_numpy())
    la, lo = cell_center(np.asarray(Y.columns, dtype=np.int64))

    cols = {}
    cols["doy_sin"] = np.repeat(sin[:, None], C, axis=1)
    cols["doy_cos"] = np.repeat(cos[:, None], C, axis=1)
    cols["lat"] = np.tile(la[None, :], (T, 1))
    cols["lon"] = np.tile(lo[None, :], (T, 1))
    for k in LAGS:
        sh = np.full_like(logy, np.nan)
        if T > k:
            sh[k:] = logy[:-k]
        cols[f"lag_{k}"] = sh
    for k in ROLLS:
        roll = pd.DataFrame(vals).rolling(k, min_periods=1).mean().to_numpy()
        cols[f"roll_{k}"] = np.log1p(roll)
    climo_vals = climo.to_numpy(dtype=np.float64)           # (DOY_BINS x C)
    cols["climo"] = climo_vals[Y.index.dayofyear.to_numpy() - 1]

    X = np.stack([cols[f].ravel() for f in FEATURES], axis=1)
    ok = ~np.isnan(X).any(axis=1)
    return X, vals.ravel(), ok


def path_matrix(Y_hist, climo, booster, horizon):
    """Recursively roll the booster forward `horizon` days over every cell in `Y_hist`.

    `Y_hist` is the observed (dates x cells) frame; each step builds the same feature row
    `build_features` would, appends the prediction to the history and continues.  Returns
    (dates, M) with M a (horizon x cells) matrix, so a caller can sum the cells it cares
    about -- the AOI total for serving, or a curated region for calibration -- without
    re-running the model once per group.
    """
    Y = Y_hist.astype(float).copy()
    if not len(Y.columns):
        raise ValueError("path_matrix: no cells")
    cells = np.asarray(Y.columns, dtype=np.int64)
    la, lo = cell_center(cells)
    n = len(cells)
    last = Y.index[-1]
    dates, rows = [], []
    for h in range(1, int(horizon) + 1):
        d = last + pd.Timedelta(days=h)
        vals = Y.to_numpy(dtype=float)
        logy = np.log1p(vals)
        row = {}
        for k in LAGS:
            row[f"lag_{k}"] = logy[-k] if len(logy) >= k else np.zeros(n)
        for k in ROLLS:
            row[f"roll_{k}"] = np.log1p(vals[-k:].mean(axis=0))
        sin, cos = doy_angles([d.dayofyear])
        row["doy_sin"] = np.full(n, float(sin[0]))
        row["doy_cos"] = np.full(n, float(cos[0]))
        row["lat"] = la
        row["lon"] = lo
        row["climo"] = climo.loc[d.dayofyear, Y.columns].to_numpy(dtype=float)
        Xf = np.stack([np.atleast_1d(row[f]).astype(float) for f in FEATURES], axis=1)
        pred = np.clip(np.asarray(booster.predict(Xf), dtype=float), 0.0, None)
        Y.loc[d] = pred
        dates.append(d)
        rows.append(pred)
    return dates, np.asarray(rows, dtype=float)


def predict_path(Y_hist, climo, booster, horizon):
    """The AOI total per day: `path_matrix` summed over its cells.

    The same quantity `/forecast` reports and `daily()` produces.
    """
    dates, M = path_matrix(Y_hist, climo, booster, horizon)
    return dates, [float(v) for v in M.sum(axis=1)]


# ------------------------------------------------------------------ conformal bands
def half_widths(conformal, horizon):
    """Per-day log1p half-widths from a checkpoint's conformal quantiles, or None.

    A horizon longer than the calibrated window reuses the widest calibrated width rather
    than inventing one -- the band is honest about the range it was measured over.
    """
    q = (conformal or {}).get("quantiles") or {}
    if not q:
        return None
    present = sorted(int(k) for k in q)
    last = str(present[-1])
    return np.asarray([float(q.get(str(h), q[last])) for h in range(1, int(horizon) + 1)],
                      dtype=float)


def band(totals, conformal, horizon):
    """(lower, upper) for a forecast, or (None, None) when there is no calibration.

    The band is split-conformal on the *relative* error in log1p space: the interval is
    `expm1(log1p(y) +/- q_h)`, so it scales with the level (an AOI ten times as busy gets a
    ten-times-wider band) and can never go negative.  A relative band is what makes one
    calibration table transfer from a curated region to a hand-drawn AOI of any size -- a
    band measured in absolute detections would not.
    """
    w = half_widths(conformal, horizon)
    if w is None:
        return None, None
    t = np.log1p(np.clip(np.asarray(totals, dtype=float), 0.0, None))
    return np.expm1(np.clip(t - w, 0.0, None)), np.expm1(t + w)


def coverage(conformal, tol=0.05):
    """The nominal vs empirically measured coverage, and whether they agree.

    `within_tolerance` is False when any horizon's measured coverage is more than `tol`
    away from nominal; the panel is required to say so rather than implying the band is
    calibrated when it is not.
    """
    if not conformal or conformal.get("nominal") is None:
        return None
    emp = ((conformal.get("coverage") or {}).get("empirical")) or {}
    nom = float(conformal["nominal"])
    worst = max((abs(float(v) - nom) for v in emp.values() if v is not None), default=None)
    return {"nominal": nom, "empirical": emp,
            "within_tolerance": None if worst is None else bool(worst <= tol + 1e-9),
            "max_deviation": None if worst is None else round(float(worst), 4)}


def frame_cell_series(d, cells_keep=None):
    """Per-cell daily harmonized counts for a detection frame, as (dates x cells).

    Blocks come from the frame's own detections, and the per-sensor rescale is the server's
    single `main.sensor_factors` -- so this is the same quantity the panel was trained on,
    not a fresh approximation of it.
    """
    import main  # local: main imports this module, so the import has to be deferred

    if d is None or d.empty:
        return pd.DataFrame()
    cell = fm.cell_bins(d.lat.values, d.lon.values)
    piv = (d.assign(cell=cell)
             .groupby(["date", "cell", "sensor"], observed=True).size()
             .rename("n").reset_index()
             .pivot_table(index=["date", "cell"], columns="sensor", values="n",
                          fill_value=0, aggfunc="sum"))
    if piv.empty:
        return pd.DataFrame()
    factors = main.sensor_factors(
        d.groupby(["date", "sensor"], observed=True).size().unstack(fill_value=0))
    piv = piv.mul(pd.Series(factors), axis="columns").sum(axis=1).unstack(fill_value=0.0)
    piv = piv.sort_index().sort_index(axis=1)
    piv.columns = piv.columns.astype("int64")
    if cells_keep is not None:
        keep = [c for c in piv.columns if int(c) in cells_keep]
        if not keep:
            return pd.DataFrame()
        piv = piv[keep]
    # Reindex to a contiguous daily range: the lag/rolling features count *days*, and a
    # frame with a gap would otherwise let the 28-day mean reach across it as if it were 28
    # consecutive days.  A missing day is a zero-detection day, which is the same value
    # `harmonized_daily` fills the served series with.
    full = pd.date_range(piv.index.min(), piv.index.max())
    return piv.reindex(full, fill_value=0.0).sort_index(axis=1)


# ------------------------------------------------------------------------ checkpoint IO
_CACHE = {}


def clear_cache():
    """Forget loaded checkpoints.  `train_forecast.py` and the tests both need this."""
    _CACHE.clear()


def available(explicit=None) -> bool:
    b, c, m = paths(explicit)
    return b.is_file() and c.is_file() and m.is_file()


def load_metrics(explicit=None):
    """The checkpoint's metrics.json, or None.  Never raises."""
    _, _, mpath = paths(explicit)
    try:
        meta = json.loads(Path(mpath).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if int(meta.get("schema", 0)) != SCHEMA:
        return None
    if list(meta.get("features", [])) != list(FEATURES):
        return None
    return meta


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(explicit=None, use_cache=True):
    """Load (booster, metrics, climo), or None when there is no usable checkpoint.

    Never raises.  A checkpoint is a local artifact a user can half-delete, half-copy or
    write with an older build; a broken one must degrade to the seasonal prior, not take
    `/forecast` down.  lightgbm is imported here, inside the function, so the cost is paid
    on the first served forecast and not at start-up.

    The booster is verified *before* LightGBM sees it.  LightGBM's C++ model parser does
    not raise on a truncated file -- it calls `Log::Fatal` and aborts the process, taking
    the whole server with it -- so the integrity check has to happen in Python: the file's
    length and SHA-256 must match what `save()` recorded, and the verified bytes are fed to
    the parser as a string rather than re-read from disk.
    """
    if not available(explicit):
        return None
    key = str(model_dir(explicit))
    if use_cache and key in _CACHE:
        return _CACHE[key]
    bpath, cpath, _ = paths(explicit)
    try:
        meta = load_metrics(explicit)
        if meta is None:
            return None
        raw = Path(bpath).read_bytes()
        # No recorded digest (an older or hand-written checkpoint) is untrusted by design.
        if not meta.get("booster_sha256") or meta.get("booster_bytes") != len(raw):
            return None
        if _sha256(raw) != meta["booster_sha256"]:
            return None
        text = raw.decode("utf-8")           # a truncated/garbled file fails here, not in C++
        if "end of trees" not in text:
            return None
        import lightgbm as lgb
        booster = lgb.Booster(model_str=text)
        with np.load(cpath) as npz:
            cells = np.asarray(npz["cells"], dtype=np.int64)
            climo = pd.DataFrame(np.asarray(npz["climo"], dtype=np.float64),
                                 index=np.arange(1, DOY_BINS + 1), columns=cells)
        obj = {"booster": booster, "metrics": meta, "climo": climo}
    except Exception:      # lightgbm's own error types included: a bad booster is not a 500
        return None
    if use_cache:
        _CACHE[key] = obj
    return obj


def save(booster, cells, climo, meta, explicit=None):
    """Write booster + climatology + metrics, atomically enough to never half-load."""
    bpath, cpath, mpath = paths(explicit)
    bpath.parent.mkdir(parents=True, exist_ok=True)
    meta = dict(meta)
    meta["schema"] = SCHEMA
    meta["features"] = list(FEATURES)
    meta.setdefault("generated", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    booster.save_model(str(bpath))
    raw = bpath.read_bytes()
    meta["booster_bytes"] = len(raw)
    meta["booster_sha256"] = _sha256(raw)      # `load()` refuses anything that does not match
    tmp = cpath.with_name(cpath.name + ".tmp.npz")
    np.savez_compressed(tmp, cells=np.asarray(cells, dtype=np.int64),
                        climo=np.asarray(climo, dtype=np.float64))
    tmp.replace(cpath)
    mpath.write_text(json.dumps(meta, separators=(",", ":")), encoding="utf-8")
    clear_cache()
    return meta


# ------------------------------------------------------------------------- serving gate
def gate(metrics, horizon):
    """Whether the LightGBM model may be served for a horizon, and why.

    The rule is the honest one the model was asked to earn: LightGBM is served only at a
    horizon whose stored backtest MASE is strictly better than the seasonal prior's.  A
    tie -- or a horizon the backtest could not score -- keeps the prior.
    """
    if not metrics:
        return False, "no checkpoint"
    scores = (metrics.get("backtest") or {}).get("by_horizon") or {}
    row = scores.get(str(int(horizon)))
    if not row:
        return False, f"no backtest score for horizon {int(horizon)}"
    # `backtest()` writes these under the same names the three forecasts are scored by;
    # a row that does not carry them cannot be judged and must keep the prior.
    lm, pm = row.get("lgbm"), row.get("prior")
    if lm is None or pm is None:
        return False, "backtest score incomplete"
    if lm < pm:
        return True, f"backtest MASE {lm:.3f} beats seasonal prior {pm:.3f}"
    return False, f"seasonal prior {pm:.3f} <= LightGBM {lm:.3f}"


def earned_days(metrics, horizon):
    """Which of a `horizon`-day request the stored backtest earned, one day at a time.

    Scoring is discrete (h=1/7/14/30), so each day is judged by the nearest measured horizon
    *at least as long* as it: winning at 7 days is evidence for day 3, losing at 1 day is not
    evidence for day 3, and losing at 30 days withdraws every day from 15 on. A day past the
    last measured horizon has no evidence behind it and keeps the prior rather than borrowing
    the longest score's verdict.

    This is what lets one checkpoint serve part of a request: a model that won 7 and 14 but
    lost 1 and 30 answers days 2-14 and the prior answers the rest, instead of one horizon's
    verdict deciding the whole response. Returns a list of booleans, day 1 first.
    """
    scores = sorted(int(k) for k in ((metrics or {}).get("backtest") or {}).get("by_horizon") or {})
    if not scores:
        return [False] * max(0, int(horizon))
    verdict = {h: gate(metrics, h)[0] for h in scores}
    out = []
    for day in range(1, int(horizon) + 1):
        nxt = next((h for h in scores if h >= day), None)
        out.append(bool(verdict[nxt]) if nxt is not None else False)
    return out
