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
}

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
    parts = name[:-4].split("_") if name.lower().endswith(".csv") else name.split("_")
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
        found = sorted(root.rglob("*.csv"))
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
    """Column names, average bytes per record, and file size -- without reading the file."""
    size = path.stat().st_size
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


def read_slice(path: Path, limit: int, chunk: int = CHUNK_ROWS,
               spread: bool = True) -> dict:
    """About `limit` rows from `path`, spread evenly over it when it is bigger than that.

    Reports the frames, the rows actually read, whether the file had more to give, whether the
    read was spread, and an estimate of the file's total rows -- so the console can say
    "750,000 of ~10.4M rows, spread across the file" instead of implying it holds the whole
    thing. A file without the FIRMS columns raises ValueError, which the endpoint turns into a
    400 naming the missing columns.
    """
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
