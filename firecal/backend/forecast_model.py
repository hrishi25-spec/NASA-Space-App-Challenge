"""The forecast model's shared half: the archive-trained prior and the checkpoint that
carries it from `train.py` to `/forecast`.

`train.py` streams every FIRMS CSV under the training directory through the same
`harmonize()` the upload endpoint uses, and reduces ~10 GB of raw detections to two small
objects:

  * a day-of-year *shape* per 2-degree cell, mean-normalized so it carries seasonality
    and no absolute level, and
  * the harmonized daily series the whole record adds up to.

Both are written to `model/`, beside this file and outside version control: they are
derived from an archive that is itself ~10 GB of local data, so neither one belongs in the
repository. Delete `model/` and the API behaves exactly as it did before -- the checkpoint
is an upgrade, never a dependency.

`/forecast` imports this module to read the checkpoint back.  The shape is a *prior*, not
an answer: `profile_for_bbox()` returns the archive's seasonal curve for whatever box was
asked for, and the endpoint rescales that curve to the level of the operator's own frame.
Levels are the one thing the two datasets need not agree on -- a 2-degree cell and a
hand-drawn AOI never hold the same number of detections -- so the prior is stored
mean-normalized and only its shape is ever used.

With torch installed the same checkpoint warm-starts the LSTM, so the weights begin at the
archive's shape instead of at noise.  torch stays optional (`requirements.txt`), which is
why nothing in this module imports it at the top level.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Bumped whenever a change would make an older checkpoint misleading rather than merely
# incomplete.  `load()` refuses anything it does not recognize instead of guessing.
SCHEMA = 1

# 2 degrees is ~200 km: wide enough that a cell holds hundreds of detections per active
# day instead of a handful, narrow enough that a Mediterranean cell and a boreal one do
# not end up sharing a season.
GRID_DEG = 2.0
LAT_BINS = int(round(180.0 / GRID_DEG))
LON_BINS = int(round(360.0 / GRID_DEG))
DOY_BINS = 366

# A cell earns a stored profile only if it burned on at least this many distinct days
# across the record.  Below that the curve is a handful of coincidences, and the endpoint
# is better off with no prior at all than with a noisy one.
MIN_CELL_DAYS = 25

# Sequence length the LSTM sees; the endpoint builds the same window when it fine-tunes.
WINDOW = 30

# Where the archive normally lives.  Searched in this order, relative to the repository
# root, this file's directory, and the working directory -- the download folder comes out
# of a browser as `Data Training`, but a script may well have made `data_training`.
DATA_DIRS = ("Data Training", "data_training", "data-training")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MODEL_DIR = HERE / "model"
CHECKPOINT = MODEL_DIR / "forecast.json"
CELL_GRID = MODEL_DIR / "cells.npz"
LSTM_WEIGHTS = MODEL_DIR / "lstm.pt"


def data_dir(explicit=None):
    """The training archive's directory, or None when there is not one.

    Returns None rather than raising: callers report it as a setup step, and a missing
    archive is the normal state of a fresh clone.
    """
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_dir() else None
    for name in DATA_DIRS:
        for base in (ROOT, HERE, Path.cwd()):
            candidate = base / name
            if candidate.is_dir():
                return candidate
    return None


# ----------------------------------------------------------------- the cell x DOY grid
def cell_bins(lat, lon):
    """Flattened (lat_bin, lon_bin) cell id for each detection.

    Clipped rather than wrapped: a polygon sliver can round to exactly 90N or 180E, and a
    bin index one past the end of the axis silently wraps to the opposite edge of the map.
    """
    la = np.clip(((np.asarray(lat, dtype=float) + 90.0) / GRID_DEG).astype(np.int64), 0, LAT_BINS - 1)
    lo = np.clip(((np.asarray(lon, dtype=float) + 180.0) / GRID_DEG).astype(np.int64), 0, LON_BINS - 1)
    return la * LON_BINS + lo


def new_grid():
    """An all-zero count grid: one row of 366 day-of-year bins per 2-degree cell."""
    return np.zeros((LAT_BINS * LON_BINS, DOY_BINS), dtype=np.int32)


def accumulate(counts, bins, doy):
    """Add one detection per (cell, day-of-year) pair, in place.

    `bincount` rather than `np.add.at`: the latter is a Python-level loop over the index
    array and ran ~40x slower here, which on ~80M detections is the difference between a
    coffee break and an afternoon.
    """
    if len(bins) == 0:
        return counts
    flat = np.asarray(bins, dtype=np.int64) * DOY_BINS + (np.asarray(doy, dtype=np.int64) - 1)
    counts += np.bincount(flat, minlength=counts.size).reshape(counts.shape).astype(np.int32)
    return counts


def cells_from_grid(counts, min_days=MIN_CELL_DAYS):
    """Split a count grid into the cells worth keeping and their mean-normalized shapes.

    Returns (cell_ids, shapes, levels): `cell_ids` indexes the flattened grid, `shapes` is
    (n, 366) with mean 1.0 so a cell's absolute level cancels out, and `levels` is the mean
    detections per day that cell saw, kept for the report rather than for arithmetic.
    """
    active = (counts > 0).sum(axis=1)
    keep = np.flatnonzero(active >= min_days)
    if not keep.size:
        return keep, np.zeros((0, DOY_BINS), dtype=np.float32), np.zeros(0, dtype=np.float32)
    sub = counts[keep].astype(np.float64)
    total = sub.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        shape = np.where(total[:, None] > 0, sub * DOY_BINS / np.maximum(total[:, None], 1.0), 0.0)
    return keep, shape.astype(np.float32), (total / DOY_BINS).astype(np.float32)


def bbox_cells(bbox):
    """Every cell id a (minlat, minlon, maxlat, maxlon) box touches."""
    minlat, minlon, maxlat, maxlon = bbox
    la0, lo0 = divmod(int(cell_bins([minlat], [minlon])[0]), LON_BINS)
    la1, lo1 = divmod(int(cell_bins([maxlat], [maxlon])[0]), LON_BINS)
    return (np.arange(la0, la1 + 1)[:, None] * LON_BINS + np.arange(lo0, lo1 + 1)[None, :]).ravel()


# ------------------------------------------------------------------------ checkpoint IO
_CACHE = {}


def clear_cache():
    """Forget loaded checkpoints.  `train.py` and the tests both need this."""
    _CACHE.clear()


def is_trained(path=None):
    path = CHECKPOINT if path is None else Path(path)
    return Path(path).is_file() and Path(path).with_name(CELL_GRID.name).is_file()


def load(path=None):
    """Load and cache a checkpoint; `{}` when there is none, or it is not one of ours.

    Never raises.  A checkpoint is an optional local artifact that a user can half-delete,
    half-copy or write with an older build, and a broken one must degrade to the endpoint's
    own climatology rather than take the API down at import.

    `path` defaults to `CHECKPOINT` resolved at call time, not at import, so a test -- or a
    `train.py --out` run -- can point the loader somewhere else without a module reload.

    Only a *found* checkpoint is cached.  Caching the miss as well would freeze a server
    that started before training: a run finishing an hour into the session would stay
    invisible until the next restart, and the directory it reads is a local artifact whose
    whole lifecycle is "train when you feel like it".
    """
    path = Path(CHECKPOINT if path is None else path)
    key = str(path)
    if key in _CACHE:
        return _CACHE[key]
    ck = {}
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
        grid_path = path.with_name(CELL_GRID.name)
        with np.load(grid_path) as npz:
            meta["_cells"] = np.asarray(npz["cells"])
            meta["_shape"] = np.asarray(npz["shape"], dtype=np.float32)
            meta["_level"] = np.asarray(npz["level"], dtype=np.float32)
        if int(meta.get("schema", 0)) != SCHEMA:
            meta = {}
    except (OSError, ValueError, KeyError, EOFError):
        meta = {}
    if meta:
        _CACHE[key] = meta
    return meta


def save(meta, cells, shape, level, path=None):
    """Write a checkpoint atomically enough that a half-written one is never loaded."""
    path = Path(CHECKPOINT if path is None else path)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = dict(meta)
    meta["schema"] = SCHEMA
    meta.setdefault("generated", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    tmp = path.with_name(path.name + ".npz.tmp")
    with open(tmp, "wb") as fh:
        np.savez_compressed(fh, cells=np.asarray(cells, dtype=np.int64),
                            shape=np.asarray(shape, dtype=np.float32),
                            level=np.asarray(level, dtype=np.float32))
    tmp.replace(path.with_name(CELL_GRID.name))
    path.write_text(json.dumps(meta, separators=(",", ":")), encoding="utf-8")
    clear_cache()
    return path


def profile_for_bbox(bbox, ck=None):
    """The archive's seasonal shape for a box, or None when the archive has nothing there.

    One curve averaged over the cells the box touches: a hand-drawn AOI is usually smaller
    than a cell grid, and at that size the cells it overlaps describe it better than any
    interpolation would.  The result is still mean-normalized -- callers scale it.
    """
    ck = load() if ck is None else ck
    ids, shape = ck.get("_cells"), ck.get("_shape")
    if ids is None or not len(ids) or bbox is None:
        return None
    want = bbox_cells(bbox)
    pos = np.clip(np.searchsorted(ids, want), 0, len(ids) - 1)
    pos = pos[ids[pos] == want]          # `ids` ascends, so searchsorted lands on the cell
    if not pos.size:
        return None
    picked = shape[pos]
    return {
        "doy": picked.mean(axis=0),
        "cells": int(pos.size),
        "level": float(ck["_level"][pos].mean()) if "_level" in ck else None,
        "generated": ck.get("generated"),
        "source_days": (ck.get("series") or {}).get("days"),
    }


def doy_series(profile, floor=0.0):
    """Turn a stored shape into a pandas Series indexed by 1..366."""
    import pandas as pd

    return pd.Series(np.maximum(np.asarray(profile, dtype=float), floor),
                     index=np.arange(1, DOY_BINS + 1), dtype=float)
