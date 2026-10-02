#!/usr/bin/env python3
"""Train the forecast model on every FIRMS CSV under the training directory.

    python train.py                     # the whole archive (a 10 GB run takes minutes)
    python train.py --limit 200000      # first 200k rows of each file, for a smoke test
    python train.py --inventory         # list what would be read and stop
    python train.py --no-lstm           # seasonal prior only, no neural pass

What it produces
----------------
`model/forecast.json`, `model/cells.npz` and -- when torch is installed -- `model/lstm.pt`,
which `/forecast` picks up on its next start. Delete `model/` and the API goes back to
climatology fitted per request; the checkpoint is an upgrade, never a dependency.

How it reads the archive
------------------------
Chunked, never all at once: the directory is ~10 GB of detections and the largest export is
1.8 GB, so nothing here holds a file in memory. Each chunk goes through the same
`harmonize()` the upload endpoint calls, and the resulting daily series is assembled by the
same `harmonized_daily()` the calendar endpoint uses -- a model trained on a differently
harmonized series would be predicting a different quantity from the one served.

Two reductions happen per chunk, and they are the reason a 10 GB scan is worth doing:

  * a (2-degree cell x day-of-year) count grid, which is what the seasonal prior is, and
  * a (date x sensor) count table, which becomes the daily series the LSTM trains on.

Pass `--limit` to read only the head of each file: fast, and the shape of the output is
identical, which is what the tests use.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forecast_model as fm  # noqa: E402
import main  # noqa: E402  (the archive is harmonized with the server's own rules)

# Only what `harmonize(geometry=False)` reads. Dropping `scan`, `track`, `version`,
# `bright_t31`, `type` and `daynight` is most of the parse cost of a 1.8 GB export.
NEEDED = {"latitude", "longitude", "acq_date", "acq_time", "confidence",
          "brightness", "bright_ti4", "frp", "satellite", "instrument"}

CHUNK = 1_000_000


def find_csvs(data_dir):
    """Every CSV in the archive, in a stable order so two runs agree."""
    return sorted(p for p in Path(data_dir).rglob("*.csv") if p.is_file())


def inventory(paths):
    """Name, size and directory per file -- the fast `--inventory` listing."""
    rows = []
    for p in paths:
        rows.append({"file": str(p.name), "batch": p.parent.name, "bytes": p.stat().st_size})
    return rows


def scan(paths, chunk=CHUNK, limit=0, log=None):
    """Stream the archive and reduce it to a cell grid plus a (date x sensor) table.

    `limit` caps the rows read from each file, so a smoke run costs seconds instead of
    minutes while producing exactly the same shape of output.
    """
    log = log or (lambda *a: None)
    grid = fm.new_grid()
    parts, frp_parts = [], []
    files, sensors, rows, kept, total_bytes = [], {}, 0, 0, 0
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
            # The prior: one count per cell and calendar day across the whole record.
            fm.accumulate(grid, fm.cell_bins(h.lat.values, h.lon.values), h.date.dt.dayofyear.values)
            # The series: per-day counts kept split by sensor, because `harmonized_daily`
            # needs the two sensors side by side to measure their overlap ratio.
            by_day = h.groupby(["date", "sensor"], observed=True)
            parts.append(pd.DataFrame({"n": by_day.size(), "frp": by_day.frp.sum()}).reset_index())
            lo, hi = h.date.min(), h.date.max()
            start = lo if start is None or lo < start else start
            end = hi if end is None or hi > end else end
            for s, n in h.sensor.value_counts().items():
                sensors[s] = sensors.get(s, 0) + int(n)
        rows += f_rows
        kept += f_kept
        files.append({"file": path.name, "batch": path.parent.name, "bytes": size,
                      "rows": f_rows, "kept": f_kept})
        log(f"  [{i}/{len(paths)}] {path.name:<40} {f_rows:>10,} rows  "
            f"{size / 1e6:>7.1f} MB  {time.time() - t0:>6.1f}s")

    if parts:
        merged = pd.concat(parts).groupby(["date", "sensor"], observed=True).sum()
        piv = merged["n"].unstack(fill_value=0).astype("int64")
        frp = merged["frp"].groupby("date").sum()
    else:
        piv = pd.DataFrame(); frp = pd.Series(dtype=float)
    return {"grid": grid, "piv": piv, "frp": frp, "files": files,
            "rows": rows, "kept": kept, "bytes": total_bytes,
            "sensors": sensors,
            "start": None if start is None else str(start.date()),
            "end": None if end is None else str(end.date())}


def build(scan_result, cfg):
    """Turn a scan into the checkpoint's manifest plus its two arrays."""
    series = main.harmonized_daily(scan_result["piv"], scan_result["frp"]) if len(scan_result["piv"]) else None
    cells, shape, level = fm.cells_from_grid(scan_result["grid"], fm.MIN_CELL_DAYS)
    dates = [str(d.date()) for d in series.index] if series is not None else []
    counts = [round(float(v), 2) for v in series["count"]] if series is not None else []
    y = np.log1p(np.asarray(counts, dtype=float)) if counts else np.zeros(1)
    manifest = {
        "trained_by": "firecal/backend/train.py",
        "grid_deg": fm.GRID_DEG,
        "min_cell_days": fm.MIN_CELL_DAYS,
        "window": fm.WINDOW,
        "source": {"dir": str(cfg["data"]), "files": len(scan_result["files"]),
                   "bytes": scan_result["bytes"], "rows": scan_result["rows"],
                   "kept": scan_result["kept"], "start": scan_result["start"],
                   "end": scan_result["end"], "seconds": round(cfg["seconds"], 1),
                   "limit": cfg["limit"]},
        "sensors": scan_result["sensors"],
        "level": {"mu": round(float(y.mean()), 6), "sd": round(float(y.std()), 6)},
        "series": {"days": len(dates), "dates": dates, "counts": counts},
        "cells": {"file": fm.CELL_GRID.name, "count": int(len(cells)),
                  "min_days": fm.MIN_CELL_DAYS,
                  "mean_level": round(float(level.mean()), 3) if len(level) else 0.0},
    }
    return manifest, cells, shape, level, series


def train_lstm(series, epochs=60, window=fm.WINDOW, hidden=32, log=None):
    """Fit the LSTM on the archive's daily series and return a state dict, or None.

    torch is deliberately optional in `requirements.txt`, so its absence is a normal
    outcome: the seasonal prior is still written and `/forecast` still improves. The last
    90 days are held out so the run reports a number that was not fitted for.
    """
    log = log or (lambda *a: None)
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        log("  torch not installed — skipping the LSTM pass (the seasonal prior is unaffected)")
        return None, {}
    if len(series) < window + 120:
        log(f"  only {len(series)} days of series — too few to fit a {window}-day window")
        return None, {}

    y = np.log1p(series["count"].values).astype("float32")
    split = max(window + 1, len(y) - 90)
    mu, sd = float(y[:split].mean()), float(y[:split].std() + 1e-6)
    z = (y - mu) / sd
    doy = np.c_[np.sin(2 * np.pi * series.index.dayofyear / 365.25),
                np.cos(2 * np.pi * series.index.dayofyear / 365.25)].astype("float32")
    feat = np.c_[z, doy]
    X = np.stack([feat[i:i + window] for i in range(split - window)])
    Y = z[window:split]

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.l = nn.LSTM(3, hidden, batch_first=True)
            self.o = nn.Linear(hidden, 1)

        def forward(self, x):
            return self.o(self.l(x)[0][:, -1]).squeeze(-1)

    net = Net()
    opt = torch.optim.Adam(net.parameters(), 1e-2)
    Xt, Yt = torch.tensor(X), torch.tensor(Y)
    t0 = time.time()
    for epoch in range(1, max(1, epochs) + 1):
        opt.zero_grad()
        loss = nn.functional.mse_loss(net(Xt), Yt)
        loss.backward()
        opt.step()
        if epoch % 10 == 0 or epoch == epochs:
            log(f"  epoch {epoch:>3}/{epochs}  train mse {loss.item():.4f}  ({time.time() - t0:.1f}s)")

    # One-step-ahead on the held-out tail: the honest number, because every step of the
    # recursive forecast would otherwise inherit its own error.
    with torch.no_grad():
        err = []
        for i in range(split, len(z)):
            pred = net(torch.tensor(feat[i - window:i][None]))[0].item()
            err.append(abs(pred - z[i]))
    meta = {"window": window, "hidden": hidden, "epochs": int(epochs),
            "mu": mu, "sd": sd, "tail_days": len(err)}
    if err:
        mae_mw = float(np.mean(err)) * sd
        meta["tail_mae"] = round(float(np.mean(err)), 5)
        meta["tail_mae_detections"] = round(mae_mw, 2)
        log(f"  held-out tail (last {len(err)} days): mae {mae_mw:.2f} detections/day "
            f"({meta['tail_mae']:.4f} standardised)")
    return net.state_dict(), meta


def run(data_dir=None, out=fm.MODEL_DIR, chunk=CHUNK, limit=0, epochs=60,
        use_lstm=True, log=print):
    """The whole job: scan, reduce, fit, write. Returns the manifest it wrote."""
    root = fm.data_dir(data_dir)
    if root is None:
        raise SystemExit(f"no training directory found (looked for {', '.join(fm.DATA_DIRS)})")
    paths = find_csvs(root)
    if not paths:
        raise SystemExit(f"{root} holds no CSV files")
    log(f"training on {len(paths)} CSV file(s) in {root}")
    t0 = time.time()
    scanned = scan(paths, chunk=chunk, limit=limit, log=log)
    manifest, cells, shape, level, series = build(scanned, {
        "data": root, "limit": limit or None, "seconds": time.time() - t0})

    if use_lstm and series is not None:
        state, meta = train_lstm(series, epochs=epochs, log=log)
        if state is not None:
            import torch
            out = Path(out)
            out.mkdir(parents=True, exist_ok=True)
            torch.save(state, out / fm.LSTM_WEIGHTS.name)
            manifest["lstm"] = dict(meta, file=fm.LSTM_WEIGHTS.name)
    fm.save(manifest, cells, shape, level, path=Path(out) / fm.CHECKPOINT.name)
    return manifest


def cli(argv=None):
    ap = argparse.ArgumentParser(description="Train the Pyro-Harmony forecast model on the FIRMS archive.")
    ap.add_argument("--data", default=None, help=f"training directory (default: auto, one of {fm.DATA_DIRS})")
    ap.add_argument("--out", default=str(fm.MODEL_DIR), help="where the checkpoint is written")
    ap.add_argument("--chunk", type=int, default=CHUNK, help="rows per read (default 1,000,000)")
    ap.add_argument("--limit", type=int, default=0, help="rows per file; 0 reads each file whole")
    ap.add_argument("--epochs", type=int, default=60, help="LSTM epochs (default 60)")
    ap.add_argument("--no-lstm", action="store_true", help="write the seasonal prior only")
    ap.add_argument("--inventory", action="store_true", help="list the files that would be read, then stop")
    args = ap.parse_args(argv)

    root = fm.data_dir(args.data)
    if root is None:
        raise SystemExit(f"no training directory found (looked for {', '.join(fm.DATA_DIRS)})")
    if args.inventory:
        paths = find_csvs(root)
        total = sum(p.stat().st_size for p in paths)
        for row in inventory(paths):
            print(f"  {row['bytes'] / 1e6:>9.1f} MB  {row['batch']}/{row['file']}")
        print(f"  {len(paths)} file(s), {total / 1e9:.2f} GB in {root}")
        return 0

    manifest = run(data_dir=args.data, out=args.out, chunk=args.chunk, limit=args.limit,
                   epochs=args.epochs, use_lstm=not args.no_lstm)
    src, ser, cel = manifest["source"], manifest["series"], manifest["cells"]
    print(f"\nread {src['rows']:,} rows ({src['bytes'] / 1e9:.2f} GB) from {src['files']} file(s) "
          f"in {src['seconds']:.0f}s")
    print(f"kept {src['kept']:,} detections, {src['start']} -> {src['end']} ({ser['days']} days)")
    print(f"sensors: " + ", ".join(f"{k} {v:,}" for k, v in sorted(manifest["sensors"].items())))
    print(f"prior: {cel['count']:,} cells at {manifest['grid_deg']} deg "
          f"(mean {cel['mean_level']} detections/day/cell)")
    if "lstm" in manifest:
        print(f"lstm: {manifest['lstm']['epochs']} epochs, held-out mae "
              f"{manifest['lstm'].get('tail_mae_detections')} detections/day")
    print(f"wrote {Path(args.out) / fm.CHECKPOINT.name}, {Path(args.out) / fm.CELL_GRID.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
