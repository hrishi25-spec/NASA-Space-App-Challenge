#!/usr/bin/env python3
"""Run every Pyro-Harmony model on a folder of real FIRMS CSVs, and report what trained.

The API keeps its dataset in a process-global frame, so "training on your own data" through
the UI means uploading and then watching the panels.  This script does the same thing
headlessly and repeatably: it loads the CSVs through the *exact* `read_firms_csv` +
`harmonize` path `/upload` uses, installs the result as the live dataset, then calls each
model endpoint and writes a Markdown report saying which models were trainable on the
supplied data and which need a longer record (anomalies need >1 year, the illusion
diagnostic needs the pre-2012 MODIS era).

Usage (from the project root):

    python firecal/backend/train_data.py ~/Downloads/DL_FIRE_*
    python firecal/backend/train_data.py ./my_csvs --demo-compare

Positional arguments are files or directories; directories are scanned for *.csv.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import date
from pathlib import Path

import pandas as pd

BACKEND = Path(__file__).resolve().parent
ROOT = BACKEND.parents[1]
sys.path.insert(0, str(BACKEND))

import main  # noqa: E402  (needs the backend dir on sys.path first)

TRAINED, PARTIAL, SKIPPED = "TRAINED", "PARTIAL", "SKIPPED"


def collect(paths) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        p = Path(p).expanduser()
        if p.is_dir():
            out += sorted(p.glob("*.csv"))
        elif p.is_file():
            out.append(p)
        else:
            print(f"skipping {p}: no such file or directory")
    # Deduplicate while keeping order (a glob can overlap an explicit file).
    seen, uniq = set(), []
    for f in out:
        if f.resolve() not in seen:
            seen.add(f.resolve())
            uniq.append(f)
    return uniq


def load(files: list[Path]):
    """Parse + harmonize each CSV the way /upload does; return (frame, inventory)."""
    parts, inventory = [], []
    for f in files:
        try:
            raw = main.read_firms_csv(f.read_bytes())
            h = main.harmonize(raw)
        except Exception as e:  # noqa: BLE001 - report bad files instead of dying
            inventory.append((f.name, 0, 0, "-", f"rejected: {e}"))
            continue
        span = f"{h.date.min().date()} .. {h.date.max().date()}" if len(h) else "-"
        inventory.append((f.name, len(raw), len(h), span, ""))
        if len(h):
            parts.append(h)
    if not parts:
        raise SystemExit("no usable rows: need FIRMS-style CSVs with confidence >= 30")
    df = pd.concat(parts).drop_duplicates(["lat", "lon", "time", "sensor"]).reset_index(drop=True)
    return df.tail(main.MAX_ROWS).reset_index(drop=True), inventory


def run_models(df, args) -> list[tuple[str, str, list[str]]]:
    """Call every model in main.py and collect (title, status, detail lines)."""
    main.DF = df
    main._invalidate()
    out: list[tuple[str, str, list[str]]] = []

    # --- harmonized daily record (what every other model consumes) -------------
    days = main.daily(main.subset(None))
    line = (f"{len(days)} days, mean {days['count'].mean():.1f} fires/day, "
            f"peak {days['count'].max():.1f} on {days['count'].idxmax().date()}")
    out.append(("Burning-activity calendar (harmonized daily record)", TRAINED, [line]))

    # --- DBSCAN hotspot clustering (pillar 3) ---------------------------------
    cl = main.clusters(bbox=None, eps=args.eps, min_pts=args.min_pts, hours=args.hours)
    detail = [f"{len(cl)} clusters at eps={args.eps} m, minPts={args.min_pts}, {args.hours} h window"]
    for c in cl[:3]:
        detail.append(f"top cluster {c['id']}: {c['n']} detections, {c['frp']} MW, "
                      f"{c['duration_h']} h, sensors {', '.join(c['sensors'])}")
    out.append(("DBSCAN clusters into fire events", TRAINED if cl else SKIPPED, detail))

    # --- seasonal climatology (pillar 1) --------------------------------------
    clima = main.climatology(bbox=None)
    if clima.get("summary"):
        s = clima["summary"]
        detail = [f"years present: {sorted(clima['years'])}",
                  f"peak day-of-year {s['peak_doy']} (p95 {s['peak_p95']}/day)",
                  f"fire season DOY {s['onset_doy']} -> {s['cessation_doy']}, "
                  f"median {s['median_daily']} fires/day"]
        if len(clima["years"]) < 3:
            detail.append("note: fewer than 3 calendar years, so the percentile envelope is a "
                          "single-season shape, not a multi-decadal climatology")
        out.append(("Seasonal climatology + percentile envelope", PARTIAL if len(clima["years"]) < 3 else TRAINED, detail))
    else:
        out.append(("Seasonal climatology + percentile envelope", SKIPPED, [clima.get("note", "")]))

    # --- Incident Commander briefing (pillar 4) -------------------------------
    br = main.briefing(bbox=None)
    if br.get("note"):
        out.append(("Incident Commander briefing", SKIPPED, [br["note"]]))
    else:
        rec, streaks = br["record"], br["streaks"]
        detail = [f"threat {br['threat']['level']} (score {br['threat']['score']}), "
                  f"record mean {rec['mean_daily']} fires/day over {rec['days']} days",
                  f"z-streaks: {len(streaks)}" + ("" if streaks else
                   " (a z-score needs the same day-of-year in *other* years)"),
                  f"fuel-biome strata: {len(br['biomes'])}"]
        for b in br["biomes"]:
            detail.append(f"biome {b['kind']}: {b['n']} detections, mean FRP {b['mean_frp']} MW, "
                          f"centroid {[round(float(v), 3) for v in b['centroid']]}, "
                          f"spread ~{b['spread_km']} km")
        detail += [f"recommendation: {r}" for r in br["recommendations"]]
        status = TRAINED if streaks else PARTIAL
        out.append(("Incident Commander briefing (K-means biomes + z-streaks)", status, detail))

    # --- anomalies ------------------------------------------------------------
    an = main.anomalies(bbox=None)
    if an.get("note"):
        out.append(("Anomalous days vs other years", SKIPPED, [an["note"]]))
    else:
        out.append(("Anomalous days vs other years", TRAINED,
                    [f"{len(an['anomalies'])} anomalous days, "
                     f"{len(an['critical'])} critical months"]))

    # --- forecast -------------------------------------------------------------
    fc = main.forecast(bbox=None, horizon=args.horizon, epochs=args.epochs)
    if not fc.get("model"):
        out.append(("Forecast (LSTM or seasonal fallback)", SKIPPED, ["needs >= 120 days of data"]))
    else:
        vals = [f["count"] for f in fc["forecast"]]
        out.append(("Forecast (LSTM or seasonal fallback)", TRAINED,
                    [f"method: {fc['model']}, horizon {len(vals)} days",
                     f"first {fc['forecast'][0]['date']}: {vals[0]}, "
                     f"last {fc['forecast'][-1]['date']}: {vals[-1]}, mean {sum(vals) / len(vals):.1f} fires/day"]))

    # --- sensor transition illusion (pillar 2) --------------------------------
    dg = main.diagnostic(bbox=None)
    detail = []
    if dg.get("series"):
        for row in dg["series"]:
            detail.append(f"{row['year']}: MODIS {row['modis']}, VIIRS {row['viirs']}, "
                          f"raw {row['raw_total']}, harmonized {row['adjusted']}")
    if dg.get("observed_growth_pct") is None:
        detail.append("observed/adjusted post-2012 growth unavailable: the record has no "
                      "pre-2012 MODIS era and no 2012-2015 sensor overlap, which is what this "
                      "diagnostic calibrates against (use the 2002-2024 demo dataset for it)")
        status = PARTIAL if dg.get("series") else SKIPPED
    else:
        detail.append(f"observed growth {dg['observed_growth_pct']}%, "
                      f"adjusted {dg['adjusted_growth_pct']}%, artifact {dg['artifact_pct']} pp")
        if dg.get("calibration"):
            c = dg["calibration"]
            detail.append(f"2012-2015 calibration: R2 {c['r2']}, RMSE {c['rmse_mw']} MW, "
                          f"FRP ratio {c['frp_ratio_viirs_to_modis']}, "
                          f"ESFP ratio {c['esfp_ratio_viirs_to_modis']}")
        status = TRAINED
    out.append(("Sensor Transition Illusion diagnostic", status, detail))
    return out


def render(args, inventory, meta, models, briefing_md, demo) -> str:
    n_sensors = ", ".join(f"{k} {v}" for k, v in sorted((meta.get("sensors") or {}).items()))
    days = (pd.Timestamp(meta["end"]) - pd.Timestamp(meta["start"])).days + 1
    L = [f"# Pyro-Harmony - training run on real FIRMS downloads", "",
         f"Run on {date.today().isoformat()} by `firecal/backend/train_data.py`.",
         f"PyTorch present: {'yes' if importlib.util.find_spec('torch') else 'no (forecast uses the seasonal fallback)'}", "",
         "## 1. Data", "",
         "| file | raw rows | harmonized | span | note |", "|---|---:|---:|---|---|"]
    for name, raw_n, kept, span, note in inventory:
        L.append(f"| `{name}` | {raw_n} | {kept} | {span} | {note} |")
    L += ["", "### Harmonized store", "",
          f"- detections: **{meta['n']}** over **{meta['start']} -> {meta['end']}** ({days} days)",
          f"- sensors: {n_sensors}",
          f"- bounds: {[round(float(x), 4) for x in meta['bounds']]} (minlat, minlon, maxlat, maxlon)",
          f"- HFII (sum FRP*ESFP): {meta['hfi']}, equivalent standard pixels: {meta['esfp']}", "",
          "### Detections per platform", "", "| sensor family | platform | detections |", "|---|---|---:|"]
    for (fam, sat), k in sorted((meta.get("platforms") or {}).items()):
        L.append(f"| {fam} | {sat} | {k} |")
    L += ["", "## 2. Models", ""]
    for title, status, detail in models:
        L += [f"### {title} - {status}", ""] + [f"- {x}" for x in detail] + [""]
    L += ["## 3. What this record can and cannot support", "",
          "- **Clustering, the calendar and the forecast** work from a single continuous year;",
          "- **anomalies and z-score streaks** compare each day against the same +/-7-day window in",
          "  *other* years, so they need more than one year of overlapping dates;",
          "- **the Sensor Transition Illusion** is calibrated against the pre-2012 MODIS era and the",
          "  2012-2015 MODIS/VIIRS overlap, so it needs the multi-decadal record.", ""]
    if demo:
        L += ["## 4. Appendix - the same diagnostic on the 2002-2024 dataset", "", *[f"- {x}" for x in demo], ""]
    if briefing_md:
        L += ["## 5. Incident Commander briefing (exported from this data)", "", "```markdown",
              briefing_md.strip(), "```", ""]
    return "\n".join(L)


def main_cli() -> int:
    ap = argparse.ArgumentParser(description="Train/run the Pyro-Harmony models on real FIRMS CSVs.")
    ap.add_argument("paths", nargs="+", help="CSV files and/or directories to scan for *.csv")
    ap.add_argument("--out", default=str(ROOT / "TRAINING_REPORT.md"), help="Markdown report path")
    ap.add_argument("--briefing-out", default=str(ROOT / "TRAINING_BRIEFING.md"),
                    help="where to write the Markdown briefing for this data")
    ap.add_argument("--horizon", type=int, default=30, help="forecast horizon in days (1-90)")
    ap.add_argument("--epochs", type=int, default=40, help="LSTM epochs when torch is installed")
    ap.add_argument("--eps", type=float, default=550.0, help="DBSCAN eps in metres (10-5000)")
    ap.add_argument("--min-pts", type=int, default=3, help="DBSCAN minPts")
    ap.add_argument("--hours", type=float, default=12.0, help="DBSCAN time window in hours")
    ap.add_argument("--demo-compare", action="store_true",
                    help="also run the illusion diagnostic on the 2002-2024 demo for contrast")
    args = ap.parse_args()

    files = collect(args.paths)
    if not files:
        print("no CSV files found")
        return 1
    df, inventory = load(files)
    main.DF = df
    main._invalidate()
    meta = main.meta()
    meta["platforms"] = {tuple(k): int(v) for k, v in df.groupby(["sensor", "sat"]).size().items()}
    print(f"loaded {meta['n']} detections from {len(files)} file(s): "
          f"{meta['start']} -> {meta['end']}, sensors {meta['sensors']}")

    real = df
    models = run_models(df, args)

    briefing_md = ""
    try:
        briefing_md = main.briefing(bbox=None, format="markdown").body.decode()
    except Exception as e:  # noqa: BLE001
        print(f"briefing export skipped: {e}")

    demo = []
    if args.demo_compare:
        main.demo(mode="transition")
        dg = main.diagnostic(bbox=None)
        demo = [f"observed growth {dg['observed_growth_pct']}% -> adjusted "
                f"{dg['adjusted_growth_pct']}% ({dg['artifact_pct']} pp of the jump was the "
                f"sensor change)",
                f"VIIRS scaling factor {dg['viirs_scaling']}, "
                f"pre-2012 days {dg['pre_2012_days']}, overlap-era days {dg['post_2012_days']}"]
        if dg.get("calibration"):
            c = dg["calibration"]
            demo.append(f"2012-2015 calibration: R2 {c['r2']}, RMSE {c['rmse_mw']} MW")
        main.DF = real                                    # leave the real data loaded
        main._invalidate()

    out = Path(args.out).expanduser()
    out.write_text(render(args, inventory, meta, models, briefing_md, demo), encoding="utf-8")
    if briefing_md:
        Path(args.briefing_out).expanduser().write_text(briefing_md, encoding="utf-8")

    for title, status, _ in models:
        print(f"[{status:7s}] {title}")
    print(f"report -> {out}")
    print("NOTE: this script's process owns the dataset it loads; re-run the app to serve it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
