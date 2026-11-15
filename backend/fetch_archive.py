#!/usr/bin/env python3
"""Download real FIRMS area exports into `.data/`, where `train.py` and `train_forecast.py`
expect to find them.

    python fetch_archive.py --dry-run                 # the plan, no network and no key needed
    python fetch_archive.py --regions amazon --years 2024 --sources MODIS_C6.1 --max-windows 2
    python fetch_archive.py                           # 3 regions x 2 years x 2 sensors
    python fetch_archive.py --regions world --from 2022-09-30 --to 2023-09-29   # one season

A fire season is not a calendar year, and this archive is season-shaped: its files run
30 September to 29 September. `--from/--to` names a closed date range so an extension can
abut the archive exactly -- tiling a calendar year instead would either refetch days the
archive already holds (double-counting them, because the training target counts detections)
or skip days between the ranges (which the panel fills with zeros). `--regions world` fetches
the whole globe, because the panel this archive feeds is global and a season fetched for a
few boxes would leave everywhere else reading zero.

Why this exists
---------------
The open FIRMS feeds (`data/active_fire/...`) are rolling windows -- 24 h, 48 h, 7 d. Their
multi-year siblings are not published as open files at all, so a record long enough to train a
seasonal model has to come from the *area* API: one AOI, 1-5 days at a time, and a free
`FIRMS_MAP_KEY`. This walks every 5-day window of the requested years, for every requested
region and sensor, and appends them into one CSV per (region, sensor, year).

`main.firms_area_url` builds each URL and `regions.region_box` supplies the AOI, so the request
made here is the request `POST /archive` makes -- the archive written is the same quantity the
endpoint serves, which is exactly the property the trainer depends on. Nothing in this file
re-derives either.

Resumable on purpose
--------------------
This is hours of downloading over a link that measures tens of KB/s. A window is appended only
after a complete response, and completed windows are recorded in a progress file, so an
interrupted run continues where it stopped instead of starting over -- or, worse, double-counting
rows into a count-based target. `--budget-minutes` stops cleanly at a window boundary for the
same reason.

The key is read from the environment (`.env` is loaded by `main` on import, and a real
environment variable wins over it) and is never printed: the URL carries it, so nothing here
logs a URL, only the region/sensor/date it was for.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main        # noqa: E402  (loads .env on import; owns the area-API contract)
import regions     # noqa: E402

# The area API takes at most 5 days per request, and the maximum is what keeps the round-trip
# count down on a slow link.
WINDOW_DAYS = 5
DEFAULT_REGIONS = ("amazon", "australia", "california")
DEFAULT_YEARS = (2024, 2025)
DEFAULT_SOURCES = ("MODIS_C6.1", "VIIRS_S-NPP")

# Fetch-only targets: a box with no curated preset behind it. `world` is what an extension of
# this archive has to use -- the panel holds 3,928 cells spread over every longitude, so a
# season fetched for three boxes would train the model on a year of quiet everywhere else.
BOXES = {"world": [-90.0, -180.0, 90.0, 180.0]}

# The product code that names the sensor inside a FIRMS filename -- the same mapping the
# inventory reads back out of it (`archives.SENSORS`), so a fetched file is labelled correctly
# by GET /datasets without a special case.
PRODUCT = {"MODIS_C6.1": "M-C61", "VIIRS_S-NPP": "SV-C2",
           "VIIRS_NOAA-20": "J1V-C2", "VIIRS_NOAA-21": "J2V-C2"}

HEADER = ("latitude,longitude,acq_date,acq_time,confidence,frp,brightness,satellite,"
          "instrument")
PROGRESS_FILE = ".firms_fetch.json"
RETRIES = 3
USER_AGENT = {"User-Agent": "pyro-harmony/1.0 (NASA Space Apps 2026 prototype)"}


def windows_between(first: date, last: date, days: int = WINDOW_DAYS) -> list[tuple[date, int]]:
    """Every (start, span) that tiles [first, last] inclusive, in order, none overlapping."""
    out = []
    while first <= last:
        span = min(days, (last - first).days + 1)
        out.append((first, span))
        first += timedelta(days=span)
    return out


def windows(year: int, days: int = WINDOW_DAYS) -> list[tuple[date, int]]:
    """Every (start, span) that tiles one calendar year, in order, none overlapping."""
    return windows_between(date(year, 1, 1), date(year, 12, 31), days)


def target_box(region: str):
    """The AOI for a fetch target: a curated preset, or a fetch-only box like `world`."""
    return regions.region_box(region) or BOXES.get(region)


def range_tag(start: date, end: date) -> str:
    """The name a `--from/--to` span is filed under, in place of a year."""
    return f"{start:%Y%m%d}_{end:%Y%m%d}"


def target_dir(root: Path, region: str, product: str, tag: str) -> Path:
    """Where one (region, sensor, span) export lives, in the FIRMS download-folder shape."""
    return root / f"DL_FIRE_{product}_{region}_{tag}"


def target_file(directory: Path, region: str, product: str, tag: str) -> Path:
    """One CSV per (region, sensor, span). The name is the app's own convention:
    `fire_<archive|nrt>_<product>_<download id>.csv`, which is how the sensor gets labelled,
    and `tag` is a year or a `--from/--to` range."""
    return directory / f"fire_archive_{product}_{region}{tag}.csv"


def load_progress(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_progress(path: Path, progress: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(progress, indent=0, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def area_rows(session, key: str, source: str, box, start: date, span: int,
              timeout: int = 240) -> tuple[list[str] | None, str]:
    """One area-API window: (CSV rows without the header, "") or (None, reason).

    FIRMS answers a rejected key or a bad AOI with HTTP 200 and a human-readable body rather
    than a status code, so the header is the only honest check on a response. The body of the
    request carries the key, so a failure is reported by its reason and never by its URL.
    """
    url = main.firms_area_url(key, source, box, span, start.isoformat())
    reason = "no attempt made"
    for attempt in range(1, RETRIES + 1):
        try:
            response = session.get(url, timeout=timeout, headers=USER_AGENT)
            text = response.text
            if response.status_code != 200:
                reason = f"HTTP {response.status_code}"
            elif text.lstrip().startswith("latitude,"):
                rows = text.splitlines()[1:]
                return rows, ""
            else:
                first = text.strip().splitlines()[0][:160] if text.strip() else "empty body"
                if "map_key" in text.lower() or "invalid" in text.lower():
                    return None, first          # a rejected key is not worth retrying
                reason = first
        except Exception as e:                  # network, DNS, timeout, decode
            reason = f"{type(e).__name__}: {e}"
        if attempt < RETRIES:
            time.sleep(min(30, 3 * attempt))
    return None, reason


def spans(args: argparse.Namespace) -> list[tuple[str, list[tuple[date, int]]]]:
    """The date spans to fetch: one tag per calendar year, or the single `--from/--to` range."""
    if args.start is not None:
        return [(range_tag(args.start, args.end), windows_between(args.start, args.end))]
    return [(str(year), windows(year)) for year in args.years]


def run(args: argparse.Namespace) -> int:
    root = Path(args.out)
    if (args.start is None) != (args.end is None):
        print("--from and --to name one closed range; pass both or neither")
        return 2
    if args.start is not None and args.end < args.start:
        print(f"--to {args.end} is before --from {args.start}")
        return 2
    root.mkdir(parents=True, exist_ok=True)
    progress_path = root / PROGRESS_FILE
    progress = load_progress(progress_path)

    plan, total_calls = [], 0
    for region in args.regions:
        if target_box(region) is None:
            print(f"unknown region '{region}' — known: {', '.join(regions.region_keys())}"
                  f", or a fetch-only target: {', '.join(BOXES)}")
            return 2
    if any(source not in PRODUCT for source in args.sources):
        print(f"unknown source — known: {', '.join(PRODUCT)}")
        return 2
    todo_spans = spans(args)
    for region in args.regions:
        for source in args.sources:
            for tag, ws in todo_spans:
                done = progress.keys()
                todo = [w for w in ws if f"{region}|{source}|{tag}|{w[0]}" not in done]
                plan.append((region, source, tag, todo, len(ws)))
                total_calls += len(todo)

    print(f"plan: {len(args.regions)} regions x {len(args.sources)} sensors x "
          f"{len(todo_spans)} span(s) -> {total_calls} area-API request(s) "
          f"({WINDOW_DAYS}-day windows) into {root}")
    for region, source, tag, todo, total in plan:
        print(f"  {region:<12} {source:<14} {tag:<18} {len(todo):>3} to fetch"
              f"{f' ({total - len(todo)} already done)' if total - len(todo) else ''}")
    if args.dry_run:
        return 0

    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key:
        print("\nFIRMS_MAP_KEY is not set, so nothing can be fetched. Get a free key at\n"
              "  https://firms.modaps.eosdis.nasa.gov/api/map_key/\n"
              "then put it in .env at the repo root (git-ignored) as\n"
              "  FIRMS_MAP_KEY=yourkey\n"
              "or export it in the shell. Re-run --dry-run to see the plan without one.")
        return 2

    session = requests.Session()
    started = time.time()
    deadline = started + args.budget_minutes * 60 if args.budget_minutes else None
    fetched = rows_total = failures = 0
    stopped = False
    for region, source, tag, todo, _total in plan:
        if not todo:
            continue
        box = target_box(region)
        product = PRODUCT[source]
        directory = target_dir(root, region, product, tag)
        directory.mkdir(parents=True, exist_ok=True)
        path = target_file(directory, region, product, tag)
        print(f"\n== {region} / {source} / {tag} -> {path.relative_to(root)}")
        for start, span in todo:
            if deadline and time.time() >= deadline:
                stopped = True
                break
            if args.max_windows and fetched >= args.max_windows:
                stopped = True
                break
            rows, reason = area_rows(session, key, source, box, start, span)
            if rows is None:
                failures += 1
                print(f"   {start} span={span}: FAILED — {reason}")
                continue
            # Append only after a complete response: a half-written window would bias a target
            # that counts detections.
            fresh = not path.exists() or path.stat().st_size == 0
            with path.open("a", encoding="utf-8", newline="") as fh:
                if fresh:
                    fh.write(HEADER + "\n")
                for row in rows:
                    fh.write(row.rstrip("\r\n") + "\n")
            progress[f"{region}|{source}|{tag}|{start}"] = len(rows)
            save_progress(progress_path, progress)
            fetched += 1
            rows_total += len(rows)
            rate = rows_total / max(1.0, time.time() - started)
            print(f"   {start} span={span}: {len(rows):>6} rows "
                  f"(total {rows_total:,}, {rate:.0f} rows/s)")
        if stopped:
            break
    elapsed = time.time() - started
    print(f"\n{fetched} window(s), {rows_total:,} rows in {elapsed / 60:.1f} min; "
          f"{failures} failure(s)")
    if stopped:
        print("stopped early (budget or --max-windows); re-run to continue — completed "
              "windows are recorded and skipped")
    return 1 if failures and not fetched else 0


def _day(text: str) -> date:
    """An ISO date from the command line, rejected as usage rather than as a traceback."""
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {text!r}")


def main_cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--regions", default=",".join(DEFAULT_REGIONS),
                        help=f"comma-separated preset keys (default: {','.join(DEFAULT_REGIONS)})")
    parser.add_argument("--years", default=",".join(str(y) for y in DEFAULT_YEARS),
                        help=f"comma-separated years (default: {','.join(str(y) for y in DEFAULT_YEARS)})")
    parser.add_argument("--from", dest="start", type=_day, default=None,
                        metavar="YYYY-MM-DD",
                        help="first day of a closed range, with --to (a season, not a year)")
    parser.add_argument("--to", dest="end", type=_day, default=None, metavar="YYYY-MM-DD",
                        help="last day of the range, inclusive (with --from)")
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES),
                        help=f"comma-separated area-API sources (default: {','.join(DEFAULT_SOURCES)})")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / ".data"),
                        help="archive directory (default: the repo's .data/)")
    parser.add_argument("--max-windows", type=int, default=0,
                        help="stop after this many windows, for a smoke run")
    parser.add_argument("--budget-minutes", type=float, default=0,
                        help="stop at a window boundary after this long (0 = no limit)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and the counts, touch no network")
    args = parser.parse_args(argv)
    args.regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    args.years = [int(y) for y in args.years.split(",") if y.strip()]
    args.sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    return run(args)


if __name__ == "__main__":
    sys.exit(main_cli())
