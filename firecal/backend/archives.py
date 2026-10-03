"""The FIRMS archives on this machine, as datasets the console can open.

`.data/` is where the real exports live -- the directory `train.py` reads, roughly
10 GB of MODIS C6.1 and VIIRS S-NPP / NOAA-20 / NOAA-21 area downloads. The console holds its
dataset in memory and one of those files is 1.4-1.8 GB, so selecting one opens a *bounded
slice*: the reader stops the moment it has the rows it was asked for, and the response reports
what was read, so the number on screen is never a guess about the rest of it.

Reading the head of the file would make that slice two weeks of one global sensor -- and this
console is a *calendar*: its climatology, its anomalies and its forecast are all asked to
compare days across seasons and years, which two weeks cannot answer. So the slice is taken
from evenly spaced byte offsets across the whole file instead, one pass of `limit` rows over a
file of ten million. FIRMS exports are one record per line with no quoted fields, so a seek
plus a discarded partial line is a safe way in, and the frames are checked for the FIRMS
columns before they are trusted -- a seek that landed badly falls back to reading in sequence.

Two rules this module exists to keep:

  * **A client string never becomes a path.** A dataset is addressed by an id from the
    inventory `scan()` just built, and `find()` resolves that id against the same inventory
    before anything is opened -- the rule `/upload` and `/archive` already follow.
  * **A missing directory is not an error.** None of this ships with the repository (the
    archives are git-ignored and gigabytes), so every function here answers "nothing found"
    rather than raising. The console has an upload path and a live feed without it.
"""
import subprocess
from pathlib import Path

import pandas as pd

# What the download folder's product code means. FIRMS names its exports
# `fire_<archive|nrt>_<product>_<download id>.csv`, and the product code is the only place the
# sensor is stated -- C2 is the 375 m VIIRS product (VNP14IMG/VJ114IMG/VJ214IMG), C6.1 the 1 km
# MODIS collection.
SENSORS = {
    "J1V-C2": "VIIRS NOAA-20",
    "J2V-C2": "VIIRS NOAA-21",
    "SV-C2": "VIIRS S-NPP",
    "M-C61": "MODIS C6.1",
    "M-C6": "MODIS C6.1",
    "ALL": "MODIS+VIIRS",         # the merged year export (hf_export.py), every sensor
}

# The bucket this console also reads from. `hf sync` runs both ways; here the bucket is the
# source and `<root>/hf` the destination, so a machine with no `.data/` (every fresh clone,
# every CI run with network) still has the harmonized year to open -- the database case.
HF_BUCKET = "hf://buckets/hriishiibanerjee/FIRMS_DATA"
HF_CACHE = "hf"                       # cache dir name under a root; inventoried like the rest
HF_SYNC_TIMEOUT = 600                 # first pull is a few hundred MB; later ones are no-ops

# What a frame must carry to be trusted as this API's record: either a raw FIRMS export or
# the harmonized shape `harmonize()` produces (what the bucket stores).
HARMONIZED_COLUMNS = {"lat", "lon", "time", "date", "sensor", "conf"}

KINDS = {"archive": "archive", "nrt": "near-real-time"}

# The columns every FIRMS export carries. A frame missing any of them did not come from a
# clean line boundary, and the caller must not be handed it.
REQUIRED_COLUMNS = {"latitude", "longitude", "acq_date", "confidence"}

# Rows per sequential read. Big enough that the per-chunk overhead disappears next to the
# parse, small enough that a slice is never held twice.
CHUNK_ROWS = 250_000

# How much of a file one selection reads by default: ~750k detections parses in seconds and is
# a fraction of the 2M-row in-memory cap, so the panels' own frames still fit beside it.
DEFAULT_LIMIT = 750_000
MIN_LIMIT = 1_000

# Evenly spaced offsets a spread read starts from, and the fewest rows worth a seek. A step
# costs an open and a partial-line discard, so more steps mean a finer spread through the file
# for the same number of rows parsed. 24 steps over a year is a sample every fortnight.
SPREAD_STEPS_MAX = 24
ROWS_PER_STEP_MIN = 20_000

# How much of the file is read to learn its column names and how wide one record is. 1 MiB is
# tens of thousands of bytes-per-record measurements, so the estimate is stable.
HEAD_BYTES = 1 << 20
ENCODINGS = ("utf-8-sig", "latin-1")   # the local files are machine-written; latin-1 is the net


def roots(base: Path) -> list[Path]:
    """The local archive directory, relative to the repository root."""
    return [base / ".data"]


def _describe(path: Path, root: Path) -> dict:
    """One inventory entry. `id` is the path relative to its root and is the only handle the
    API accepts; the file itself never leaves this process."""
    name = path.name
    low = name.lower()
    stem = name[:-4] if low.endswith(".csv") else name[:-8] if low.endswith(".parquet") else name
    parts = stem.split("_")
    kind = KINDS.get(parts[1], parts[1]) if len(parts) > 1 else "archive"
    code = parts[2] if len(parts) > 2 else ""
    sensor = SENSORS.get(code, code or "unknown sensor")
    download = parts[3] if len(parts) > 3 else ""
    label = f"{sensor} · {kind}" + (f" · {download}" if download else "")
    try:
        size = path.stat().st_size
    except OSError:                                   # vanished between walk and stat
        size = 0
    return {
        "id": path.relative_to(root).as_posix(),
        "name": name,
        "folder": path.parent.name,
        "root": root.name,
        "sensor": sensor,
        "kind": kind,
        "label": label,
        "bytes": size,
        "mb": round(size / 1e6),
        # Private: the handle this process opens, and the directory it was found in. `public()`
        # drops both before an entry ever reaches a response body.
        "_path": path,
        "_root": root.resolve(),
    }


def scan(root: Path) -> list[dict]:
    """Every FIRMS CSV under `root`, smallest first.

    Smallest first on purpose: FIRMS `fire_nrt_*` exports are a few days of one sensor (a
    couple of MB, instant to open), while the area archives are gigabytes. The picker puts the
    ones that open immediately at the top.
    """
    try:
        found = sorted([*root.rglob("*.csv"), *root.rglob("*.parquet")])
    except OSError:                                   # unreadable or not a directory
        return []
    items = [_describe(path, root) for path in found if path.is_file()]
    return sorted(items, key=lambda item: item["bytes"])


def scan_all(dirs: list[Path]) -> list[dict]:
    """The inventory across every root, de-duplicated, smallest first."""
    seen, items = set(), []
    for root in dirs:
        for item in scan(root):
            key = str(item["_path"].resolve())
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return sorted(items, key=lambda item: item["bytes"])


def public(item: dict) -> dict:
    """An entry as the API publishes it: no filesystem paths, not even relative ones."""
    return {key: value for key, value in item.items() if not key.startswith("_")}


def find(items: list[dict], dataset_id: str) -> dict | None:
    """The inventory entry with this id, or None.

    This is the only way an id becomes a file. Matching against entries the walk produced means
    a traversal attempt (`../../etc/passwd`), an absolute path, or a file that exists but was
    never inventoried all resolve to "no such dataset" -- there is no path built from the input
    to escape from in the first place. Resolving once more against the root is belt and braces
    for a symlink that points outside.
    """
    for item in items:
        if item["id"] != dataset_id:
            continue
        path = item["_path"].resolve()
        if not path.is_relative_to(item["_root"]):
            return None
        return {**item, "_path": path}
    return None


def _shape(path: Path) -> tuple[list[str], float, int]:
    """Column names, average bytes per record, and file size -- without reading the file.

    Parquet answers from its footer: exact row count, exact schema, zero row data touched.
    """
    size = path.stat().st_size
    if path.suffix.lower() == ".parquet":
        import pyarrow.parquet as pq
        try:
            meta = pq.ParquetFile(path).metadata
        except Exception as e:                        # corrupt or not parquet at all
            raise ValueError(f"unreadable parquet: {e}") from e
        columns = [field.name for field in pq.ParquetFile(path).schema_arrow]
        rows = meta.num_rows
        return columns, (size / rows) if rows else 0.0, size
    with open(path, "rb") as fh:
        head = fh.read(HEAD_BYTES)
    lines = head.count(b"\n")
    width = (len(head) / lines) if lines else 0.0
    last = None
    for encoding in ENCODINGS:
        try:
            return list(pd.read_csv(path, nrows=5, low_memory=False, encoding=encoding).columns), width, size
        except UnicodeDecodeError as e:
            last = e
    raise ValueError(f"could not decode the CSV as text ({last})")


def _read_sequential(path: Path, limit: int, chunk: int):
    """Chunks from the top of the file, stopping at exactly `limit` rows.

    The last chunk is trimmed to the limit rather than kept whole: `limit` is what the caller
    asked for, and reporting a quarter of a million rows for a request of forty thousand would
    make the response's own accounting wrong. Returns the frames, the rows read, and whether
    the limit is what stopped the read (i.e. the file had more).
    """
    frames, rows = [], 0
    for encoding in ENCODINGS:
        try:
            reader = pd.read_csv(path, encoding=encoding, chunksize=chunk, low_memory=False)
            frames, rows = [], 0
            for frame in reader:
                room = limit - rows
                if len(frame) > room:
                    frame = frame.iloc[:room]
                frames.append(frame)
                rows += len(frame)
                if rows >= limit:
                    return frames, rows, True
            return frames, rows, False
        except UnicodeDecodeError:
            continue
    raise ValueError("could not decode the CSV as text")


def _read_spread(path: Path, columns: list[str], per_step: int, steps: int, size: int):
    """`per_step` rows from each of `steps` evenly spaced byte offsets.

    Offsets are byte positions, so every step is a seek, a discarded partial line and a bounded
    parse. The rows that come back are checked for the FIRMS columns: if a seek landed inside a
    record that does not end where this format says it does, the caller gets nothing and falls
    back to reading in sequence rather than being handed mangled columns.
    """
    frames = []
    for step in range(steps):
        offset = step * size // steps
        try:
            with open(path, "rb") as fh:
                fh.seek(offset)
                fh.readline()              # the header at offset 0, a partial record elsewhere
                frame = pd.read_csv(fh, nrows=per_step, header=None, names=columns,
                                    low_memory=False, encoding="utf-8-sig")
        except (UnicodeDecodeError, pd.errors.ParserError, OSError):
            return [], 0
        # A seek that did not land on a record start shifts every field one place along, which
        # stops `latitude` being a number. Checking that is the whole test: with `names=` the
        # column *labels* are always right, whatever the file underneath them turned out to be.
        if pd.to_numeric(frame["latitude"], errors="coerce").notna().mean() < 0.9:
            return [], 0
        frames.append(frame)
    return frames, sum(len(frame) for frame in frames)


def _read_parquet(path: Path, limit: int, spread: bool = True) -> dict:
    """`limit` rows from a parquet file -- columnar, so the byte-seek games are unnecessary.

    A parquet read is already bounded by row groups: the sequential branch pulls batches until
    `limit` rows are in hand (the rest of the file is never decompressed), and the spread
    branch picks row groups *by their time statistics* instead of byte offsets -- the bucket's
    file is one block per source export, so positional sampling would hand a calendar whichever
    sensor was written first, while the footers' min/max let it choose `steps` groups covering
    the record's actual span. The estimate is the footer's exact row count, not a guess.
    """
    import pyarrow.parquet as pq
    try:
        pf = pq.ParquetFile(path)
    except Exception as e:
        raise ValueError(f"unreadable parquet: {e}") from e
    columns = [field.name for field in pf.schema_arrow]
    if not REQUIRED_COLUMNS <= set(columns) and not HARMONIZED_COLUMNS <= set(columns):
        missing = sorted((REQUIRED_COLUMNS | HARMONIZED_COLUMNS) - set(columns))
        raise ValueError(f"missing required columns: {', '.join(missing)}")
    total = pf.metadata.num_rows
    groups = pf.metadata.num_row_groups
    if not spread or total <= limit or groups <= 1:
        frames, rows = [], 0
        for batch in pf.iter_batches(batch_size=CHUNK_ROWS):
            frames.append(batch.to_pandas())
            rows += len(batch)
            if rows >= limit:
                break
        while rows > limit:                           # trim the last frame to exactly `limit`
            over, last = rows - limit, frames[-1]
            if len(last) <= over:
                rows -= len(last)
                frames.pop()
            else:
                frames[-1] = last.iloc[: len(last) - over]
                rows -= over
        return {"frames": frames, "rows": rows, "capped": total > limit,
                "spread": False, "estimate": total}
    steps = max(1, min(SPREAD_STEPS_MAX, groups, limit // ROWS_PER_STEP_MIN))
    per = max(1, limit // steps)
    frames, rows = [], 0
    for group in _spread_groups(pf, columns, steps):
        part = pf.read_row_group(group).to_pandas()
        if len(part) > per:
            part = part.iloc[:per]
        frames.append(part)
        rows += len(part)
    return {"frames": frames, "rows": rows, "capped": True,
            "spread": True, "estimate": total}


def _stride_groups(groups: int, steps: int) -> list[int]:
    """Evenly spaced row-group indices -- the positional fallback for the spread read."""
    return [step * groups // steps for step in range(steps)]


def _spread_groups(pf, columns: list[str], steps: int) -> list[int]:
    """Row-group indices covering `steps` moments evenly across the record's time range.

    Every row group in a parquet footer carries min/max statistics for each column, and
    `time` is one of them -- so the spread can ask the *data* where the moments are instead of
    assuming the file's layout says. `steps` bins from first detection to last; each bin takes
    the first not-yet-chosen group whose [min, max] overlaps it, falling back to any unchosen
    group (bins can be narrower than a group). If any group has no statistics, or there is no
    `time` column to ask, the answer is the positional stride -- the same shape the CSV spread
    takes over byte offsets.
    """
    groups = pf.metadata.num_row_groups
    if "time" not in columns or steps > groups:
        return _stride_groups(groups, steps)
    index = columns.index("time")
    ranges: list[tuple[int, int] | None] = []
    for group in range(groups):
        try:
            stats = pf.metadata.row_group(group).column(index).statistics
            if stats is None or not stats.has_min_max:
                ranges.append(None)
            else:
                ranges.append((pd.Timestamp(stats.min).value, pd.Timestamp(stats.max).value))
        except Exception:                       # a footer without usable statistics
            ranges.append(None)
    if any(span is None for span in ranges):
        return _stride_groups(groups, steps)
    lo = min(span[0] for span in ranges)
    hi = max(span[1] for span in ranges)
    if hi <= lo:
        return _stride_groups(groups, steps)
    span, chosen, taken = hi - lo, [], set()
    for step in range(steps):
        start = lo + span * step // steps
        end = lo + span * (step + 1) // steps
        pick = next((g for g, r in enumerate(ranges)
                     if g not in taken and r[0] <= end and start <= r[1]), None)
        if pick is None:
            pick = next((g for g in range(groups) if g not in taken), None)
        if pick is None:
            break
        taken.add(pick)
        chosen.append(pick)
    return chosen


def read_slice(path: Path, limit: int, chunk: int = CHUNK_ROWS,
               spread: bool = True) -> dict:
    """About `limit` rows from `path`, spread evenly over it when it is bigger than that.

    Reports the frames, the rows actually read, whether the file had more to give, whether the
    read was spread, and an estimate of the file's total rows -- so the console can say
    "750,000 of ~10.4M rows, spread across the file" instead of implying it holds the whole
    thing. A file without the FIRMS columns raises ValueError, which the endpoint turns into a
    400 naming the missing columns. Parquet files go through `_read_parquet` first -- the
    bucket's format -- and CSVs take the byte-offset path below.
    """
    if path.suffix.lower() == ".parquet":
        return _read_parquet(path, limit, spread)
    columns, width, size = _shape(path)
    missing = REQUIRED_COLUMNS - set(columns)
    if missing:
        raise ValueError(f"missing required columns: {', '.join(sorted(missing))}")
    estimate = int(size / width) if width else 0
    if not spread or estimate <= limit:
        frames, rows, hit_limit = _read_sequential(path, limit, chunk)
        return {"frames": frames, "rows": rows, "capped": hit_limit,
                "spread": False, "estimate": max(estimate, rows)}

    steps = max(1, min(SPREAD_STEPS_MAX, limit // ROWS_PER_STEP_MIN))
    per_step = max(1, limit // steps)
    frames, rows = _read_spread(path, columns, per_step, steps, size)
    if not rows:                                     # a seek landed badly: read in sequence
        frames, rows, hit_limit = _read_sequential(path, limit, chunk)
        return {"frames": frames, "rows": rows, "capped": hit_limit, "spread": False,
                "estimate": max(estimate, rows)}
    return {"frames": frames, "rows": rows, "capped": True, "spread": True,
            "estimate": max(estimate, rows)}


def hf_pull(root: Path, timeout: int = HF_SYNC_TIMEOUT) -> tuple[bool, str]:
    """Pull the Hugging Face bucket into `<root>/hf`; answer (ok, message), never raise.

    This is the "database" half: `.data/` is a download folder on *this* machine, the bucket
    is the shared record, and when the inventory comes up empty (fresh clone, container,
    another laptop) this is how the console gets something to open. Every failure mode -- no
    `hf` CLI, no network, no auth, a timeout -- is a reason string, because a machine that
    cannot reach the database is in the same state as one that has no archives: nothing found.
    """
    dest = root / HF_CACHE
    try:
        dest.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(["hf", "sync", HF_BUCKET, str(dest)], capture_output=True,
                              text=True, timeout=timeout)
    except FileNotFoundError:
        return False, "hf CLI not installed"
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"{type(e).__name__}: {e}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        return False, detail[-400:]
    return True, f"synced {HF_BUCKET} -> {dest}"


def allocate(items: list[dict], limit: int) -> list[tuple[dict, int]]:
    """Split a row budget across the inventory, in proportion to file size.

    Two properties matter, and the size weighting is what buys both.

    An equal split would be wrong by two orders of magnitude here: a 136 KB near-real-time
    export and a 1.87 GB yearly archive cover the *same months of the same sensor*, so an equal
    share would spend most of the budget reading the small file whole and still never reach
    the big one's first winter. Weighting by bytes reads each file in proportion to what it
    actually holds, which is also the only split that keeps the merged record's per-sensor
    balance from being decided by which export was downloaded first.

    The sum is the caller's, not the directory's: shares are floored, so they never total more
    than `limit`, and each file that is smaller than its share is simply read whole by
    `read_slice` (it returns early when its estimate is under the limit).
    """
    if not items:
        return []
    total = sum(item["bytes"] for item in items)
    if total <= 0:                                   # unreadable sizes: split evenly
        per = max(1, limit // len(items))
        return [(item, per) for item in items]
    shares = [(item, int(limit * item["bytes"] / total)) for item in items]
    return [(item, max(1, share)) for item, share in shares]


def read_merge(items: list[dict], limit: int, chunk: int = CHUNK_ROWS,
               spread: bool = True) -> dict:
    """A bounded slice of *every* archive at once -- the record the whole directory describes.

    One pass per file, each bounded by its own share of `limit`, so the cost is set by the
    budget and not by the 10 GB behind it. Per-file accounting is kept (`files`, `skipped`)
    because "what came out of each export" is the only honest way to describe a merged sample:
    a 1.8 GB VIIRS archive and a 136 KB one contribute very different amounts, and a reader who
    is told only the total cannot see that.

    One unreadable export is skipped and named, rather than failing the merge: the directory
    is a download folder, and a truncated CSV in it should not cost the other fourteen.
    """
    frames, files, skipped = [], [], []
    rows = estimate = 0
    for item, share in allocate(items, limit):
        try:
            sliced = read_slice(item["_path"], share, chunk, spread)
        except (ValueError, OSError) as e:
            skipped.append({"file": item["name"], "reason": str(e)})
            continue
        frames.extend(sliced["frames"])
        rows += sliced["rows"]
        estimate += sliced["estimate"]
        files.append({
            "file": item["name"], "sensor": item["sensor"], "kind": item["kind"],
            "mb": item["mb"], "rows_read": sliced["rows"],
            "rows_estimate": sliced["estimate"], "spread": sliced["spread"],
        })
    return {
        "frames": frames, "rows": rows, "estimate": max(estimate, rows),
        "files": files, "skipped": skipped,
        "spread": bool(files) and all(entry["spread"] for entry in files),
    }
