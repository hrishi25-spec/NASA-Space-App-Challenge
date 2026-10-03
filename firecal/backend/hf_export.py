"""Build the harmonized one-year FIRMS record and stage it in `./data` for `hf sync`.

    firecal/backend/.venv/bin/python firecal/backend/hf_export.py

Reads every CSV under `.data/` (MODIS C6.1 and VIIRS S-NPP / NOAA-20 / NOAA-21, archive and
nrt exports), keeps the rows whose `acq_date` falls in 2024-09-30 .. 2025-09-29, runs them
through the *same* `harmonize()` the API and `train.py` use (so the stored record and a live
load are the same quantity), de-duplicates on (lat, lon, time, sensor) and writes one zstd
parquet plus a manifest and a README to `data/`. Streamed in both directions: chunks in
(bounded memory on a 9.6 GB folder), parquet out (PyArrow `ParquetWriter` appends row groups).

A full run is ~30 minutes of CPU on a machine with 7 GB of RAM, so it has to be resumable:

    # resume an interrupted run: skip what is already in the file, keep deduping against it
    hf_export.py --seed data/fire_archive_ALL_2024-09-30_2025-09-29.parquet \
                 --out fire_archive_ALL_2024-09-30_2025-09-29_part2.parquet \
                 --files SV-C2_814492,SV-C2_814496
    # then fold the parts back into the one canonical file
    hf_export.py --merge data/<part1>.parquet,data/<part2>.parquet

Both modes hold the de-duplication keys, not the rows: a sorted uint64 array searched with
`searchsorted` (one `union1d` per source file). The Python-set version of this cost several GB
on tens of millions of rows and was the first thing to fall over on this machine.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

from main import harmonize  # noqa: E402  the canonical harmonizer — train/serving/export share it

ROOT = BACKEND.parent.parent          # repository root
SRC = ROOT / ".data"                  # the 9.6 GB download folder
DST = ROOT / "data"                   # what `hf sync ./data ...` ships
NAME = "fire_archive_ALL_2024-09-30_2025-09-29.parquet"
README = "fire_archive_ALL_2024-09-30_2025-09-29"

DATE_FROM, DATE_TO = "2024-09-30", "2025-09-29"
CHUNK_ROWS = 200_000
ROW_GROUP = 250_000                   # one row group ≈ a month of one export

# Canonical column dtypes. `harmonize()` derives dtypes from whatever it was handed, so an
# all-integer `conf` in one export arrives as int64 and a float one in the next as double --
# and ParquetWriter refuses a second schema (that silent skip cost the MODIS window archive in
# a first run). Pinning every numeric to float64 and every timestamp to us makes every table
# identical before it reaches the writer, and the writer still gets the cast below.
EXPORT_DTYPES = {
    "lat": "float64", "lon": "float64", "conf": "float64", "frp": "float64",
    "bt": "float64", "scan": "float64", "track": "float64",
    "esfp": "float64", "pixel_km2": "float64",
    "time": "datetime64[us]", "date": "datetime64[us]",
    "sensor": "object", "sat": "object", "daynight": "object",
}

# Fixed label -> integer table for the dedupe key, so a key is a pure function of the row's
# values and not of how some reader happened to store its strings.
SENSOR_CODES = {"MODIS": 1, "VIIRS": 2}


def _keys(frame: pd.DataFrame) -> np.ndarray:
    """The dedupe key of each row: a 64-bit row hash over (lat, lon, time, sensor).

    Kept as a sorted uint64 array rather than a Python set on purpose -- these files hold
    tens of millions of rows in the window, and a set of that many int objects is several GB
    where the array is a few hundred MB. Sorted means membership is `searchsorted` and each
    file's merge is one `union1d`.

    Every hashed column is cast to a plain number first, and that is not decoration: pandas 3
    gives a read-back string column its `str` dtype with whichever storage backend the reader
    chose, and `hash_pandas_object` hashes those differently -- so keys computed in memory
    did not match the same rows read back out of a parquet, which would silently break a
    resume's de-duplication. A sensor label becomes an integer from a fixed table
    (`harmonize()` only ever emits MODIS or VIIRS, and anything unexpected codes to 0),
    which is identical in any process, on any storage backend.
    """
    canonical = pd.DataFrame({
        "lat": frame["lat"].astype("float64"),
        "lon": frame["lon"].astype("float64"),
        "time": frame["time"].astype("datetime64[us]").astype("int64"),
        "sensor": frame["sensor"].astype(str).map(SENSOR_CODES).fillna(0).astype("uint64"),
    })
    return pd.util.hash_pandas_object(canonical, index=False).to_numpy(dtype="uint64")


def _key_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Just the four key columns, in order -- `_keys` does the canonicalisation."""
    return frame[["lat", "lon", "time", "sensor"]]


def seed_keys(paths: list[Path]) -> np.ndarray:
    """Every dedupe key already inside existing parquet shards, sorted.

    Read one row group at a time: seeding from the whole file in one call would pull 36 M
    rows of strings into memory, which is the thing this script is built to avoid.
    """
    parts = []
    for path in paths:
        handle = pq.ParquetFile(path)
        for batch in handle.iter_batches(batch_size=ROW_GROUP,
                                         columns=["lat", "lon", "time", "sensor"]):
            parts.append(_keys(_key_frame(batch.to_pandas())))
        print(f"seeded {path.name}: {handle.metadata.num_rows:,} rows", flush=True)
    return np.unique(np.concatenate(parts)) if parts else np.empty(0, dtype="uint64")


def merge_shards(shards: list[Path], out_path: Path) -> int:
    """Rewrite shards into one file, a row group at a time (bounded memory, same schema)."""
    writer, rows = None, 0
    for shard in shards:
        handle = pq.ParquetFile(shard)
        for group in range(handle.metadata.num_row_groups):
            table = handle.read_row_group(group)
            if writer is None:
                writer = pq.ParquetWriter(out_path, table.schema, compression="zstd")
            table = table.cast(writer.schema)
            writer.write_table(table)
            rows += table.num_rows
        print(f"merged {shard.name}: {handle.metadata.num_rows:,} rows "
              f"({rows:,} total)", flush=True)
    if writer is not None:
        writer.close()
    return rows


def write_sidecars(out_path: Path, manifest: dict) -> None:
    """The manifest and the dataset card. The manifest is written *from* the parquet's own
    statistics (row count, size, schema) plus what this run measured -- never by hand, so the
    bucket never describes a file that is not there."""
    stats = pq.ParquetFile(out_path).metadata
    manifest = {**manifest, "file": out_path.name, "rows": stats.num_rows,
                "bytes": out_path.stat().st_size, "row_groups": stats.num_row_groups,
                "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (DST / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    rows, sensors = manifest["rows"], ", ".join(manifest["sensors"])
    (DST / "README.md").write_text(
        f"""# FIRMS harmonized year {DATE_FROM} → {DATE_TO}

MODIS C6.1 + VIIRS (S-NPP, NOAA-20, NOAA-21 — all versions) detections for
**{DATE_FROM} through {DATE_TO}**, merged, harmonized and de-duplicated.

- **File:** `{out_path.name}` — one parquet (zstd) in row groups of 250,000 rows. Rows are
  chronological within each source export, and each row group carries `time` statistics, so
  a date-range or spread query decompresses only the row groups it needs.
- **Rows:** {rows:,} (from {manifest['rows_scanned']:,} rows scanned across every local FIRMS export)
- **Sensors:** {sensors}
- **Columns:** `lat lon time date sensor sat conf frp bt scan track daynight esfp pixel_km2`
- **Rules:** the console's own `harmonize()` — confidence ≥ 30 for all sensors, required
  columns enforced, lat/lon bounds checked — then deduped on `(lat, lon, time, sensor)`.

This bucket is the database: the console pulls it on demand
(`hf sync hf://buckets/hriishiibanerjee/FIRMS_DATA`) when no local archive answers.

Rebuild: `firecal/backend/.venv/bin/python firecal/backend/hf_export.py`
""")


def build(args: argparse.Namespace) -> int:
    DST.mkdir(exist_ok=True)
    files = sorted(SRC.rglob("*.csv"))
    if args.files:
        wanted = [t for t in args.files.split(",") if t]
        files = [f for f in files if any(t in str(f) for t in wanted)]
    if not files:
        print(f"no CSVs matched under {SRC}", file=sys.stderr)
        return 1
    started = time.time()
    seen = seed_keys([Path(p) for p in args.seed.split(",") if p]) if args.seed \
        else np.empty(0, dtype="uint64")
    written = scanned = 0
    sensors: set[str] = set()
    writer = None
    out_path = DST / (args.out or NAME)
    for i, path in enumerate(files, 1):
        file_kept = 0
        file_parts: list[np.ndarray] = []
        try:
            for chunk in pd.read_csv(path, chunksize=CHUNK_ROWS, low_memory=False):
                scanned += len(chunk)
                dates = chunk["acq_date"].astype(str) if "acq_date" in chunk.columns else None
                if dates is None:
                    continue
                window = chunk[(dates >= DATE_FROM) & (dates <= DATE_TO)]
                if window.empty:
                    continue
                h = harmonize(window)
                if h.empty:
                    continue
                h = h.drop_duplicates(["lat", "lon", "time", "sensor"])
                h = h.astype({k: v for k, v in EXPORT_DTYPES.items() if k in h.columns})
                for col in ("sensor", "sat", "daynight"):   # harmonize leaves these as whatever
                    if col in h.columns:                     # the chunk's dtypes happened to be
                        h[col] = h[col].astype(str)
                keys = _keys(h)
                if seen.size:                   # rows an earlier file already wrote
                    pos = np.searchsorted(seen, keys)
                    hit = np.zeros(keys.size, dtype=bool)
                    valid = pos < seen.size
                    hit[valid] = seen[pos[valid]] == keys[valid]
                    h = h[~hit]
                    if h.empty:
                        continue
                    keys = keys[~hit]
                file_parts.append(keys)
                sensors.update(h["sensor"].unique())
                table = pa.Table.from_pandas(h, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(out_path, table.schema, compression="zstd")
                try:
                    table = table.cast(writer.schema)      # belt and braces above EXPORT_DTYPES
                except (pa.ArrowInvalid, pa.ArrowTypeError, pa.ArrowNotImplementedError) as e:
                    raise ValueError(f"schema mismatch: {e}") from e
                writer.write_table(table, row_group_size=ROW_GROUP)
                written += len(h)
                file_kept += len(h)
        except (UnicodeDecodeError, pd.errors.ParserError, ValueError) as e:
            print(f"skip {path.name}: {e}", file=sys.stderr)
            continue
        if file_parts:                          # one merge per file, not one per chunk
            seen = np.union1d(seen, np.concatenate(file_parts))
        print(f"[{i}/{len(files)}] {path.name}: +{file_kept:,} (total {written:,})", flush=True)

    if writer is None:
        print("no rows in window — nothing written", file=sys.stderr)
        return 1
    writer.close()
    seconds = time.time() - started
    print(f"\n{written:,} rows -> {out_path} "
          f"({out_path.stat().st_size / 1e6:.1f} MB) in {seconds:.0f}s; "
          f"sensors: {', '.join(sorted(sensors))}")
    if out_path.name == NAME:                   # sidecars describe the canonical dataset only
        write_sidecars(out_path, {
            "dataset": README,
            "window": {"from": DATE_FROM, "to": DATE_TO},
            "sensors": sorted(sensors),
            "rows_scanned": scanned,
            "source": "NASA FIRMS area exports (.data/), MODIS C6.1 + VIIRS S-NPP/NOAA-20/NOAA-21",
            "harmonizer": "firecal/backend/main.py:harmonize (confidence >= 30, geometry kept)",
            "dedupe": ["lat", "lon", "time", "sensor"],
            "format": "parquet+zstd; rows chronological within each source export, row groups of "
                      "250000; the spread read picks row groups by their time statistics",
            "build_seconds": round(seconds, 1),
        })
    return 0


def merge(args: argparse.Namespace) -> int:
    shards = [Path(p) for p in args.merge.split(",") if p]
    out_path = DST / (args.out or NAME)
    started = time.time()
    rows = merge_shards(shards, out_path)
    if not rows:
        print("nothing merged", file=sys.stderr)
        return 1
    previous = {}
    try:
        previous = json.loads((DST / "manifest.json").read_text())
    except (OSError, ValueError):
        pass
    print(f"{rows:,} rows -> {out_path} ({out_path.stat().st_size / 1e6:.1f} MB) "
          f"in {time.time() - started:.0f}s")
    write_sidecars(out_path, {**previous, "dataset": README,
                              "window": previous.get("window", {"from": DATE_FROM, "to": DATE_TO}),
                              "sensors": previous.get("sensors", ["MODIS", "VIIRS"]),
                              "rows_scanned": previous.get("rows_scanned", 0)})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", default="", metavar="PARQUET[,PARQUET]",
                        help="shards whose keys count as already written (resume)")
    parser.add_argument("--files", default="", metavar="SUBSTR[,SUBSTR]",
                        help="only source files whose path contains one of these")
    parser.add_argument("--out", default="", metavar="NAME",
                        help=f"output file name in {DST.name}/ (default {NAME})")
    parser.add_argument("--merge", default="", metavar="PARQUET[,PARQUET]",
                        help="rewrite these shards into --out instead of reading .data/")
    args = parser.parse_args(argv)
    return merge(args) if args.merge else build(args)


if __name__ == "__main__":
    raise SystemExit(main())
