"""Tests for the local-archive inventory and the bounded slice reader.

These run against a temporary directory of small FIRMS-shaped CSVs rather than the real
`.data/`, which is 10 GB, git-ignored, and absent in CI: what matters here is the
reader's contract -- what it reports, what it refuses, and what it does when there are no
archives at all -- not the contents of one machine's downloads.

Module order note: this module runs first (alphabetically before test_security and test_smoke),
and test_smoke.py reloads the standard demo in its session fixture, so the datasets swapped in
here do not leak into it.
"""
import io
import json
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import archives
import main
from main import app

client = TestClient(app)

# The real pull, captured before any fixture stubs it: the network tests below put it back.
_REAL_HF_PULL = archives.hf_pull

HEADER = "latitude,longitude,acq_date,acq_time,confidence,frp,brightness,satellite,instrument\n"

NRT_ID = "DL_FIRE_J1V-C2_814284/fire_nrt_J1V-C2_814284.csv"
ARCHIVE_ID = "DL_FIRE_M-C61_814283/fire_archive_M-C61_814283.csv"
# The real S-NPP exports say `instrument = SNPP` where the NOAA-20/21 ones say `VIIRS`, so the
# fixture carries that spelling too: a merge of three files has to produce two sensors.
SNPP_ID = "DL_FIRE_SV-C2_814285/fire_archive_SV-C2_814285.csv"


def _write_firms(path, days, per_day, start="2024-01-01", satellite="NOAA-20", instrument="VIIRS"):
    """A FIRMS-shaped export: `per_day` detections on each of `days` consecutive days."""
    origin = pd.Timestamp(start)
    rows = []
    for i in range(days * per_day):
        day = (origin + pd.Timedelta(days=i // per_day)).strftime("%Y-%m-%d")
        rows.append(f"{10 + i % 80}.0,{-100 + i % 170}.0,{day},1015,80,9.5,320,{satellite},{instrument}\n")
    path.write_text(HEADER + "".join(rows), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def archive_root(tmp_path_factory):
    """Three archives where they belong, across two instruments: a tiny near-real-time
    NOAA-20 export, a small S-NPP one, and a year-long MODIS archive.

    400,000 rows over 400 days (~22 MB, written once for the module) is deliberately far denser
    per day than a head read can walk in a bounded slice, which is the difference the spread
    read exists to make. The S-NPP file exists to be the awkward one: it names the platform
    (`SNPP`) where the others name the instrument, so a merge that produced three sensors
    instead of two would fail here rather than on this machine's 10 GB of real exports.
    """
    root = tmp_path_factory.mktemp("archives") / ".data"
    for folder in ("DL_FIRE_J1V-C2_814284", "DL_FIRE_M-C61_814283", "DL_FIRE_SV-C2_814285"):
        (root / folder).mkdir(parents=True)
    # 12 rows: opens whole, whatever the cap.
    _write_firms(root / NRT_ID, days=3, per_day=4)
    _write_firms(root / SNPP_ID, days=10, per_day=100, satellite="SNPP", instrument="SNPP")
    _write_firms(root / ARCHIVE_ID, days=400, per_day=1000, satellite="Terra", instrument="MODIS")
    return root


@pytest.fixture(autouse=True)
def point_at_fixture_archives(archive_root, monkeypatch):
    """Point the API at the fixture archives for every test in this module."""
    monkeypatch.setattr(main, "ARCHIVE_ROOTS", [archive_root])


@pytest.fixture(autouse=True)
def bucket_pull_cannot_reach_the_network(monkeypatch):
    """`hf sync` dials out to the real bucket; tests answer "unreachable" instead.

    Every pull path in main.py exists to make an empty inventory ask the database -- which is
    exactly what a CI root is -- so without this stub a passing test run would download the
    bucket. The tests that exercise the pull put the real function back and fake the `hf` CLI.
    """
    monkeypatch.setattr(
        archives, "hf_pull",
        lambda root, timeout=archives.HF_SYNC_TIMEOUT: (False, "tests: bucket is unreachable"))


# ------------------------------------------------------------------ the inventory
def test_inventory_describes_what_it_found(archive_root):
    items = client.get("/datasets").json()["items"]
    assert [item["id"] for item in items] == [NRT_ID, SNPP_ID, ARCHIVE_ID]   # smallest first
    by_id = {item["id"]: item for item in items}
    assert by_id[SNPP_ID]["sensor"] == "VIIRS S-NPP"
    assert by_id[NRT_ID]["sensor"] == "VIIRS NOAA-20"
    assert by_id[NRT_ID]["kind"] == "near-real-time"
    assert by_id[ARCHIVE_ID]["sensor"] == "MODIS C6.1"
    assert by_id[ARCHIVE_ID]["kind"] == "archive"


def test_inventory_publishes_no_filesystem_paths(archive_root):
    """A directory listing is one thing; the paths inside it are another, and a response body
    is not where they belong -- not even the roots the search walked."""
    body = json.dumps(client.get("/datasets").json())
    assert str(archive_root) not in body
    for item in client.get("/datasets").json()["items"]:
        assert not item["id"].startswith("/")
        assert "\\" not in item["id"]
        assert not any(key.startswith("_") for key in item)


def test_no_archives_is_an_empty_list(monkeypatch, tmp_path):
    """The normal case in CI, on a fresh clone and in the container: nothing to offer, not an
    error, and the console falls back to uploads."""
    monkeypatch.setattr(main, "ARCHIVE_ROOTS", [tmp_path / ".data"])  # an empty root
    r = client.get("/datasets")
    assert r.status_code == 200 and r.json() == {"items": []}


def test_a_csv_that_is_not_firms_is_refused(monkeypatch, tmp_path):
    """Its own directory, not the shared fixture: a test that writes junk into a module-scoped
    fixture corrupts every test that runs after it, and the merge below reads all of them."""
    root = tmp_path / ".data" / "DL_FIRE_M-C61_814283"
    root.mkdir(parents=True)
    (root / "fire_nrt_M-C61_814283.csv").write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    monkeypatch.setattr(main, "ARCHIVE_ROOTS", [tmp_path / ".data"])
    r = client.post("/datasets/load", params={"id": "DL_FIRE_M-C61_814283/fire_nrt_M-C61_814283.csv"})
    assert r.status_code == 400
    assert "missing required columns" in r.json()["detail"]


# ------------------------------------------------------------------ opening one
def test_opening_an_archive_reports_the_slice(archive_root):
    m = client.post("/datasets/load", params={"id": NRT_ID}).json()
    assert m["n"] == 12 and m["load"]["rows_kept"] == 12
    assert m["load"]["sensor"] == "VIIRS NOAA-20"
    assert m["load"]["capped"] is False            # the whole file fit under the cap
    assert [m["start"], m["end"]] == ["2024-01-01", "2024-01-03"]
    # and every other endpoint now answers from this dataset
    assert len(client.get("/calendar").json()) == 3


def test_a_bounded_slice_reads_only_what_it_was_asked_for(archive_root):
    """The cap is rows *read*: the reader stops at it, so a 1.5 GB file costs about what a
    small one does."""
    m = client.post("/datasets/load", params={"id": ARCHIVE_ID, "limit": 1000}).json()
    assert m["load"]["rows_read"] == 1000
    assert m["load"]["capped"] is True
    assert m["load"]["limit"] == 1000


def test_the_slice_note_survives_a_reload_and_does_not_outlive_the_slice(archive_root):
    """A browser refresh asks `/meta`, not `/datasets/load`, so the note has to be a fact about
    the dataset rather than a fact about the response that installed it -- otherwise a refresh
    silently drops the one line that says what the numbers on screen are a sample of."""
    client.post("/datasets/load", params={"id": NRT_ID})
    later = client.get("/meta").json()
    assert later["load"]["file"] == Path(NRT_ID).name
    assert later["load"]["rows_kept"] == 12
    # Any other way of replacing the dataset must take the note with it: an upload merges into
    # a different record, so the archive it came from is no longer what is on screen.
    client.post("/upload", files=_upload("fresh.csv"))
    assert "load" not in client.get("/meta").json()
    # ... and so must clearing it.
    client.post("/datasets/load", params={"id": NRT_ID})
    client.delete("/data")
    assert "load" not in client.get("/meta").json()


def _upload(name):
    body = HEADER + "5.0,6.0,2022-03-03,1015,80,9.5,320,NOAA-20\n"
    return [("files", (name, io.BytesIO(body.encode()), "text/csv"))]


# ------------------------------------------------------------------ merging them all
def test_every_archive_merges_into_one_record_over_every_file(archive_root):
    """The point of `all=true`: one dataset, both sensors, and a span that is the union of the
    exports rather than whichever one was opened."""
    m = client.post("/datasets/load", params={"all": True, "limit": 60_000}).json()
    assert m["load"]["merged"] is True
    assert m["load"]["archives"] == 3
    assert m["load"]["sensors"] == ["MODIS C6.1", "VIIRS NOAA-20", "VIIRS S-NPP"]
    assert len(m["load"]["files"]) == 3
    # Three files, four platforms -- and *two* sensors in the record, because S-NPP and NOAA-20
    # are the same instrument. A merge that let the platform string through would report three.
    assert set(m["sensors"]) == {"MODIS", "VIIRS"}
    # Every file is accounted for, and the year-long export contributed most of it.
    by_file = {f["file"]: f for f in m["load"]["files"]}
    assert set(by_file) == {Path(NRT_ID).name, Path(ARCHIVE_ID).name, Path(SNPP_ID).name}
    assert by_file[Path(ARCHIVE_ID).name]["rows_read"] > by_file[Path(SNPP_ID).name]["rows_read"]
    # And the record spans the year rather than one file's opening fortnight -- the merge has to
    # be the union of the exports, not the head of the biggest one. Compared against the same
    # budget spent on a head read, because "spans the year" depends on the budget and the ratio
    # does not. (The last slice of a file is never sampled, so this asks for most of the span.)
    head = client.post("/datasets/load", params={"id": ARCHIVE_ID, "limit": 60_000,
                                                 "spread": False}).json()
    merged_span = (pd.Timestamp(m["end"]) - pd.Timestamp(m["start"])).days
    head_span = (pd.Timestamp(head["end"]) - pd.Timestamp(head["start"])).days
    assert m["start"] == "2024-01-01"
    assert merged_span >= 180
    assert merged_span > 2 * head_span


def test_the_merge_budget_follows_file_size_not_an_equal_split():
    """The split is by bytes, and it never exceeds what the caller asked for. An equal split
    would spend most of the budget on a 136 KB export while a 1.87 GB year got the same few
    thousand rows as a file holding a hundred times as much."""
    items = [{"file": "small", "bytes": 1}, {"file": "big", "bytes": 99}]
    shares = dict((item["file"], share) for item, share in archives.allocate(items, 1000))
    assert shares == {"small": 10, "big": 990}
    assert sum(archives.allocate(items, 1_000)[i][1] for i in range(2)) <= 1_000
    # Rounding down cannot lose a file entirely: every entry keeps at least one row.
    assert all(share >= 1 for _, share in archives.allocate(items, 3))
    # No bytes to weigh (a directory whose files vanished mid-walk) still splits evenly.
    assert [s for _, s in archives.allocate([{"bytes": 0}, {"bytes": 0}], 100)] == [50, 50]


def test_one_broken_export_does_not_sink_the_merge(archive_root):
    """`.data/` is a download folder. A truncated CSV in it should cost its own row of
    the table, not the other fourteen files' worth of merge."""
    junk = archive_root / "DL_FIRE_J1V-C2_814284" / "fire_archive_J1V-C2_814284.csv"
    junk.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    m = client.post("/datasets/load", params={"all": True, "limit": 5_000}).json()
    assert m["n"] > 0
    assert [f["file"] for f in m["load"]["skipped"]] == [junk.name]
    assert "missing required columns" in m["load"]["skipped"][0]["reason"]
    assert junk.name not in [f["file"] for f in m["load"]["files"]]


def test_merging_nothing_is_a_400(monkeypatch, tmp_path):
    """The normal case in CI and on a fresh clone: nothing to merge is not a crash, and it is
    not a 404 pretending an id was mistyped."""
    monkeypatch.setattr(main, "ARCHIVE_ROOTS", [tmp_path / "nothing here"])
    r = client.post("/datasets/load", params={"all": True})
    assert r.status_code == 400 and "no local archives" in r.json()["detail"]


def test_a_merge_still_needs_an_id_when_it_is_not_a_merge(archive_root):
    """`all=false` with no id is the old 404, not a silent merge of everything."""
    assert client.post("/datasets/load").status_code == 404


def test_a_merge_is_a_gated_write(archive_root):
    """Opening every archive replaces everyone's dataset just as one archive does."""
    r = client.post("/datasets/load", params={"all": True},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_a_spread_slice_covers_the_file_instead_of_its_opening_days(archive_root):
    """The reason the default read is spread: a console that compares days across a season
    cannot do it from the first fortnight of a chronological export, and one pass over the
    offsets costs the same as reading the head."""
    spread = client.post("/datasets/load", params={"id": ARCHIVE_ID, "limit": 40_000}).json()
    assert spread["load"]["spread"] is True
    assert spread["load"]["rows_read"] <= 40_000
    span = pd.Timestamp(spread["end"]) - pd.Timestamp(spread["start"])
    assert span.days >= 150

    dense = client.post("/datasets/load", params={"id": ARCHIVE_ID, "limit": 20_000,
                                                  "spread": False}).json()
    assert dense["load"]["capped"] is True
    dense_span = pd.Timestamp(dense["end"]) - pd.Timestamp(dense["start"])
    assert dense_span.days < 30, "a head read is the opening days, by definition"
    assert span.days > dense_span.days


def test_the_slice_is_labelable_against_the_whole_file(archive_root):
    """`rows_estimate` is what lets the console say "40,000 of about 400,000 rows" rather than
    imply the file it sampled from is the dataset it holds. Measured from the file's size and
    its own record width, so the test pins it as an estimate: within a tenth of the 400,000
    rows the fixture actually has."""
    m = client.post("/datasets/load", params={"id": ARCHIVE_ID, "limit": 40_000}).json()
    assert 360_000 <= m["load"]["rows_estimate"] <= 440_000
    assert m["load"]["rows_estimate"] > m["load"]["rows_read"]


# ------------------------------------------------------------------ what may be opened
@pytest.mark.parametrize("bad", [
    "../../etc/passwd",
    "../../../.data/DL_FIRE_M-C61_814283/fire_archive_M-C61_814283.csv",
    "/etc/passwd",
    "DL_FIRE_M-C61_814283/../fire_archive_M-C61_814283.csv",
    "fire_archive_M-C61_814283.csv",
    "",
])
def test_ids_that_are_not_in_the_inventory_are_refused(archive_root, bad):
    """An id selects a file, so it is resolved *inside* the inventory the walk produced: there
    is no path built from the request for a traversal to escape from."""
    assert client.post("/datasets/load", params={"id": bad}).status_code == 404


def test_an_inventoried_id_cannot_reach_a_file_outside_its_root(archive_root, tmp_path):
    """Belt and braces: a real CSV one directory up from the root is still not the entry the
    inventory holds, so it is not openable."""
    outside = _write_firms(tmp_path / "secret.csv", days=1, per_day=1)
    assert outside.exists()
    for bad in (str(outside), "../secret.csv", "DL_FIRE_J1V-C2_814284/../../secret.csv"):
        assert client.post("/datasets/load", params={"id": bad}).status_code == 404


def test_opening_an_archive_is_a_gated_write(archive_root):
    """It replaces every user's dataset, so it is a write like /upload and /demo: a foreign
    page must not be able to drive it without a preflight."""
    r = client.post("/datasets/load", params={"id": NRT_ID},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_the_scan_survives_a_root_that_is_a_file(tmp_path):
    """`.data` replaced by a file, or unreadable: no archives, no traceback."""
    root = tmp_path / ".data"
    root.write_text("not a directory", encoding="utf-8")
    assert archives.scan(root) == []


# --------------------------------------------------- the Hugging Face bucket as a database
# The filename hf_export.py ships: `_ALL_` is the sensor code the inventory publishes as
# "MODIS+VIIRS" (archives.SENSORS), and the two dates are the record's window.
from hf_export import NAME as BUCKET_PARQUET  # noqa: E402


def _bucket_parquet(csv_path, out_path, days, per_day, row_group=0):
    """A parquet in the bucket's shape: FIRMS rows through the real `harmonize()`, written
    the way `hf_export.py` writes them."""
    _write_firms(csv_path, days=days, per_day=per_day)
    frame = main.harmonize(pd.read_csv(csv_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out_path, row_group_size=row_group or None, compression="zstd")
    return out_path


def test_the_bucket_parquet_is_inventoried_and_opens(tmp_path, monkeypatch):
    """The stored record is *already* harmonized, so opening it must pass through -- not die
    on the FIRMS columns it no longer carries. Same inventory, same slice report, same
    calendar as any CSV archive: the bucket is a database, not a special case in the UI."""
    root = tmp_path / ".data"
    parquet = _bucket_parquet(tmp_path / "raw.csv", root / "hf" / BUCKET_PARQUET,
                              days=3, per_day=4)
    monkeypatch.setattr(main, "ARCHIVE_ROOTS", [root])
    items = client.get("/datasets").json()["items"]
    assert [item["id"] for item in items] == [f"hf/{BUCKET_PARQUET}"]
    item = items[0]
    assert item["sensor"] == "MODIS+VIIRS" and item["kind"] == "archive"
    m = client.post("/datasets/load", params={"id": item["id"]}).json()
    assert m["n"] == 12 and m["load"]["rows_kept"] == 12
    assert m["load"]["capped"] is False and m["load"]["spread"] is False
    assert m["load"]["rows_estimate"] == 12      # the footer's exact count, not an estimate
    assert [m["start"], m["end"]] == ["2024-01-01", "2024-01-03"]


def test_a_parquet_slice_samples_row_groups_instead_of_reading_the_head(tmp_path, monkeypatch):
    """Parquet replaces the byte-seek spread with a row-group spread: the file is time-sorted,
    so evenly spaced row groups are the same fortnight sampling the CSV reader does by byte
    offset -- and a console comparing seasons must not be handed the first 60,000 rows only."""
    root = tmp_path / ".data"
    # 200,000 rows in 10 row groups of 20,000: far more groups than the spread takes, so
    # which groups it lands on is observable in the record's span.
    parquet = _bucket_parquet(tmp_path / "raw.csv", root / "hf" / BUCKET_PARQUET,
                              days=400, per_day=500, row_group=20_000)
    monkeypatch.setattr(main, "ARCHIVE_ROOTS", [root])
    spread = client.post("/datasets/load", params={"id": f"hf/{BUCKET_PARQUET}",
                                                   "limit": 60_000}).json()
    assert spread["load"]["spread"] is True
    assert spread["load"]["rows_read"] == 60_000
    assert spread["load"]["rows_estimate"] == 200_000
    dense = client.post("/datasets/load", params={"id": f"hf/{BUCKET_PARQUET}",
                                                  "limit": 60_000, "spread": False}).json()
    assert dense["load"]["spread"] is False
    spread_span = (pd.Timestamp(spread["end"]) - pd.Timestamp(spread["start"])).days
    dense_span = (pd.Timestamp(dense["end"]) - pd.Timestamp(dense["start"])).days
    assert spread_span > dense_span, "row-group spread must reach further into the year"


def test_an_empty_local_folder_pulls_the_bucket(tmp_path, monkeypatch):
    """The database path end to end: nothing on disk, a fake `hf` CLI that answers like the
    real one does after login, and the bucket's file arrives in the cache, is inventoried,
    and opens. (The CLI is faked because the real one would dial out; the sync *call* is real.)

    The Python client is switched off here on purpose: this is the *fallback* -- a machine
    that has the `hf` CLI and not the library -- and it must keep working."""
    monkeypatch.setattr(archives, "hub_client", lambda: None)
    bucket = tmp_path / "bucket"
    _bucket_parquet(tmp_path / "raw.csv", bucket / BUCKET_PARQUET, days=3, per_day=4)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # A fake CLI per OS: a POSIX shell script where shebangs run, a batch file where
    # PATHEXT does (`hf_pull` resolves the command through shutil.which, so a .bat is found).
    if os.name == "nt":
        fake = bin_dir / "hf.bat"
        fake.write_text("@echo off\r\nif not exist \"%~3\" mkdir \"%~3\"\r\n"
                        "copy /Y \"%FAKE_BUCKET%\\*\" \"%~3\\\" >NUL\r\n", encoding="utf-8")
    else:
        fake = bin_dir / "hf"
        fake.write_text("#!/bin/sh\n# argv: sync SOURCE DEST\nmkdir -p \"$3\"\n"
                        "cp \"$FAKE_BUCKET\"/* \"$3\"/\n", encoding="utf-8")
        fake.chmod(0o755)
    monkeypatch.setenv("FAKE_BUCKET", str(bucket))
    # Prepend only: the fake must win over any real `hf`, and the platform's own PATH
    # (with os.pathsep, not a hardcoded `:`) supplies everything else the shim needs.
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")]))
    monkeypatch.setattr(archives, "hf_pull", _REAL_HF_PULL)     # undo the no-network stub
    root = tmp_path / ".data"
    monkeypatch.setattr(main, "ARCHIVE_ROOTS", [root])

    ok, message = archives.hf_pull(root)
    assert ok is True and str(root / "hf") in message
    items = client.get("/datasets").json()["items"]
    assert [item["id"] for item in items] == [f"hf/{BUCKET_PARQUET}"]
    m = client.post("/datasets/load", params={"id": items[0]["id"]}).json()
    assert m["n"] == 12


def test_no_hf_client_at_all_is_an_empty_answer_not_an_error(tmp_path, monkeypatch):
    """No Python client and no `hf` on PATH -- a bare CI machine -- is still (False, reason),
    and the caller keeps answering "nothing found" the way every other missing-database case
    here does. The reason names the fix rather than the symptom."""
    monkeypatch.setenv("PATH", str(tmp_path / "no-bin-here"))
    monkeypatch.setattr(archives, "hub_client", lambda: None)
    monkeypatch.setattr(archives, "hf_pull", _REAL_HF_PULL)
    ok, message = archives.hf_pull(tmp_path / ".data")
    assert ok is False and "huggingface_hub" in message and "hf CLI" in message


# ------------------------------------------------------------------ the bucket, as a database
# `hf_pull` reads the bucket through the Python client when it is importable and through the
# `hf` CLI otherwise. Proving the first path needs a client object, and a test must never get
# the real one -- it would dial out.
class _BucketEntry:
    """One entry of a bucket listing. `hf_pull` reads `type` and counts the entries."""
    type = "file"

    def __init__(self, path, size):
        self.path, self.size = path, size


class _CountingHub:
    """A client that records every listing, so a test can see whether it was asked again."""

    def __init__(self, inner, calls):
        self.inner, self.calls = inner, calls

    def list_bucket_tree(self, bucket, recursive=False):
        self.calls.append(bucket)
        return self.inner.list_bucket_tree(bucket, recursive=recursive)

    def sync_bucket(self, source, dest):
        return self.inner.sync_bucket(source, dest)


class _FakeHub:
    """A `huggingface_hub` shaped exactly like the part of it `hf_pull` uses.

    `source` stands in for the bucket's contents: `sync` copies what is in it, the way a real
    sync would, so the file that lands in the cache is a real parquet the reader can open.
    """

    def __init__(self, bucket, source=None, error=None):
        self.bucket = bucket
        self.source = Path(source) if source else None
        self.error = error
        self.synced = []

    def list_bucket_tree(self, bucket, recursive=False):
        assert bucket == self.bucket, f"listed {bucket}, expected {self.bucket}"
        if self.error is not None:
            raise self.error
        if self.source is None:
            return []
        return [_BucketEntry(str(p.relative_to(self.source)), p.stat().st_size)
                for p in sorted(self.source.rglob("*")) if p.is_file()]

    def sync_bucket(self, source, dest):
        assert source == f"hf://buckets/{self.bucket}", source
        self.synced.append((source, str(dest)))
        for path in sorted(self.source.rglob("*")) if self.source else []:
            if path.is_file():
                target = Path(dest) / path.relative_to(self.source)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())


def test_the_dataset_card_is_written_as_utf8(tmp_path, monkeypatch):
    """The card the bucket carries is not ASCII -- it quotes an arrow -- and Windows' default
    text encoding is cp1252, which has no arrow in it. So the sidecar write has to name its
    encoding: without this it is a hard UnicodeEncodeError on the platform this app actually
    ships on, and the export dies after it has written the parquet."""
    import hf_export
    monkeypatch.setattr(hf_export, "DST", tmp_path)
    out = tmp_path / BUCKET_PARQUET
    pd.DataFrame({"lat": [1.0], "lon": [2.0], "time": [1], "date": ["2025-01-01"],
                  "sensor": ["MODIS C6.1"], "conf": [80]}).to_parquet(out, compression="zstd")
    hf_export.write_sidecars(out, {"sensors": ["MODIS C6.1"], "rows_scanned": 12,
                                   "dataset": "x", "source": "y"})
    card = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "→" in card                       # the character that cp1252 cannot hold
    assert (tmp_path / "manifest.json").read_text(encoding="utf-8").endswith("\n")


def test_the_bucket_can_be_pointed_elsewhere_from_the_environment(monkeypatch):
    """A bucket that moves is a config change, not a code change. Both spellings are accepted
    -- `ns/name` and the `hf://buckets/ns/name` form -- because both are what gets pasted, and
    the shipped default stands when nothing is set."""
    monkeypatch.delenv(archives.HF_BUCKET_ENV, raising=False)
    assert archives.bucket_id() == archives.HF_BUCKET.removeprefix(archives.HF_BUCKET_PREFIX)
    monkeypatch.setenv(archives.HF_BUCKET_ENV, "someone-else/FIRMS_2026")
    assert archives.bucket_id() == "someone-else/FIRMS_2026"
    monkeypatch.setenv(archives.HF_BUCKET_ENV, "hf://buckets/someone-else/FIRMS_2026/")
    assert archives.bucket_id() == "someone-else/FIRMS_2026"


def test_the_client_pulls_the_bucket_with_no_hf_cli_anywhere(tmp_path, monkeypatch):
    """The CLI-free path end to end: no `hf` on PATH at all and no CLI installed, only the
    Python client -- and the bucket's file still arrives in the cache, is inventoried, and
    opens. This is the state of a machine that installed the app and nothing else."""
    staged = tmp_path / "staged"
    _bucket_parquet(tmp_path / "raw.csv", staged / BUCKET_PARQUET, days=3, per_day=4)
    hub = _FakeHub("someone-else/FIRMS_2026", staged)
    monkeypatch.setenv(archives.HF_BUCKET_ENV, "hf://buckets/someone-else/FIRMS_2026")
    monkeypatch.setenv("PATH", str(tmp_path / "no-bin-here"))
    monkeypatch.setattr(archives, "hub_client", lambda: hub)
    monkeypatch.setattr(archives, "hf_pull", _REAL_HF_PULL)     # undo the no-network stub
    root = tmp_path / ".data"
    monkeypatch.setattr(main, "ARCHIVE_ROOTS", [root])

    ok, message = archives.hf_pull(root)
    assert ok is True and str(root / "hf") in message and "1 file" in message
    assert hub.synced == [("hf://buckets/someone-else/FIRMS_2026", str(root / "hf"))]
    # The pulled record is a dataset like any other: inventoried, listed, opened.
    items = client.get("/datasets").json()["items"]
    assert [item["id"] for item in items] == [f"hf/{BUCKET_PARQUET}"]
    assert client.post("/datasets/load", params={"id": items[0]["id"]}).json()["n"] == 12


def test_an_empty_bucket_says_it_is_empty(tmp_path, monkeypatch):
    """The state this project is actually in, and the reason the answer must be specific: the
    bucket exists and answers, it just holds nothing. Reported as itself rather than as a
    network failure, and it does not sync an empty bucket."""
    hub = _FakeHub("someone/FIRMS_DATA")           # lists no files
    monkeypatch.setenv(archives.HF_BUCKET_ENV, "someone/FIRMS_DATA")
    monkeypatch.setattr(archives, "hub_client", lambda: hub)
    monkeypatch.setattr(archives, "hf_pull", _REAL_HF_PULL)
    ok, message = archives.hf_pull(tmp_path / ".data")
    assert ok is False and "empty" in message and "0 files" in message
    assert hub.synced == []


def test_a_failed_pull_is_remembered_and_a_running_one_is_not_stacked(tmp_path, monkeypatch):
    """An empty local folder makes /datasets start a bucket pull on *every* request, and each
    one is a network listing (or an `hf` subprocess with a 600 s timeout) behind an
    unauthenticated GET. So: one pull at a time, and a failure is answered from memory for a
    minute instead of dialled out again. A *success* is never remembered -- a bucket filled a
    second later has to be found on the next request.
    """
    calls = []
    hub = _FakeHub("someone/FIRMS_DATA", error=PermissionError("401 Client Error"))
    monkeypatch.setenv(archives.HF_BUCKET_ENV, "someone/FIRMS_DATA")
    monkeypatch.setattr(archives, "hub_client", lambda: _CountingHub(hub, calls))
    monkeypatch.setattr(archives, "hf_pull", _REAL_HF_PULL)     # undo the no-network stub
    archives.forget_bucket_attempts()
    root = tmp_path / ".data"

    first = archives.hf_pull(root)
    second = archives.hf_pull(root)
    assert first == second and first[0] is False and "PermissionError" in first[1]
    assert calls == ["someone/FIRMS_DATA"], "a remembered failure must not dial out again"

    # A pull already in flight answers the colliding caller instead of starting a second sync.
    assert archives._PULL_LOCK.acquire(blocking=False)
    try:
        busy = archives.hf_pull(tmp_path / "elsewhere" / ".data")
    finally:
        archives._PULL_LOCK.release()
    assert busy[0] is False and "already running" in busy[1]

    # The memo is what makes that cheap, and forgetting it is how the next real attempt runs.
    archives.forget_bucket_attempts()
    archives.hf_pull(root)
    assert len(calls) == 2


def test_a_bucket_that_cannot_be_read_reports_why(tmp_path, monkeypatch):
    """A private bucket, a wrong id and no network all reach the same contract: (False,
    reason) with the exception named, never a raise."""
    hub = _FakeHub("someone/FIRMS_DATA", error=PermissionError("401 Client Error: Unauthorized"))
    monkeypatch.setenv(archives.HF_BUCKET_ENV, "someone/FIRMS_DATA")
    monkeypatch.setattr(archives, "hub_client", lambda: hub)
    monkeypatch.setattr(archives, "hf_pull", _REAL_HF_PULL)
    ok, message = archives.hf_pull(tmp_path / ".data")
    assert ok is False and "PermissionError" in message and "401" in message


def test_a_missing_archive_says_why_the_bucket_did_not_answer(tmp_path, monkeypatch):
    """The reason has to reach the caller to be worth computing: an id the inventory does not
    hold is a 404 about the absence, and the bucket's own state belongs in it -- otherwise the
    reader is left re-deriving why the database was silent."""
    monkeypatch.setattr(main, "ARCHIVE_ROOTS", [tmp_path / ".data"])
    monkeypatch.setattr(
        archives, "hf_pull",
        lambda root, timeout=archives.HF_SYNC_TIMEOUT: (False, "someone/FIRMS_DATA is empty (0 files)"))
    r = client.post("/datasets/load", params={"id": "hf/nothing_here.parquet"})
    assert r.status_code == 404
    assert "someone/FIRMS_DATA is empty (0 files)" in r.json()["detail"]


def test_a_fetch_range_tiles_a_season_with_no_gap_and_no_overlap(tmp_path, monkeypatch):
    """A fire season is 30 September to 29 September, so `--years` cannot express the
    extension this archive needs: tiling 2022 stops at 31 December, leaving January to
    September 2023 empty, and the panel fills an empty day with zeros -- a year of false
    quiet that the model would learn as real. `--from/--to` tiles the season exactly and
    abuts the archive's first day (2023-09-30) with neither a doubled row nor a missing one,
    and `world` supplies a box for a global panel that has no curated preset behind it."""
    import fetch_archive as fa

    asked = []

    def fake_area_rows(session, key, source, box, start, span, timeout=240):
        asked.append((str(start), tuple(box)))
        return ["18.5,99.5,2022-10-01,1015,80,9.5,320,NOAA-20,VIIRS"], ""

    monkeypatch.setattr(fa, "area_rows", fake_area_rows)
    monkeypatch.setenv("FIRMS_MAP_KEY", "a-test-key")
    out = tmp_path / ".data"
    argv = ["--regions", "world", "--from", "2022-09-30", "--to", "2023-09-29",
            "--sources", "MODIS_C6.1", "--out", str(out), "--max-windows", "2"]

    assert fa.main_cli(argv) == 0
    path = (out / "DL_FIRE_M-C61_world_20220930_20230929"
            / "fire_archive_M-C61_world20220930_20230929.csv")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("latitude,") and len(lines) == 3   # a header, two windows
    assert asked == [("2022-09-30", (-90.0, -180.0, 90.0, 180.0)),
                     ("2022-10-05", (-90.0, -180.0, 90.0, 180.0))]

    # the span is the season, not a calendar year: 73 five-day windows that stop one day
    # before the archive begins, so the extension neither overlaps nor skips a day
    ws = fa.windows_between(date(2022, 9, 30), date(2023, 9, 29))
    assert len(ws) == 73
    assert ws[-1][0] + timedelta(days=ws[-1][1]) == date(2023, 9, 30)

    # the file still reads back as a MODIS archive, so the sensor label does not depend on
    # the tag being a year
    [entry] = archives.scan(out)
    assert entry["sensor"] == "MODIS C6.1" and entry["kind"] == "archive"

    assert fa.main_cli(["--from", "2022-09-30", "--out", str(out)]) == 2      # half a range
    assert fa.main_cli(["--regions", "nowhere", "--from", "2022-09-30",
                        "--to", "2023-09-29", "--out", str(out)]) == 2      # unknown box


def test_the_firms_puller_resumes_instead_of_refetching(tmp_path, monkeypatch):
    """`fetch_archive.py` is hours long, so a re-run has to continue rather than start over:
    a window fetched twice adds its rows twice, and the training target *counts* detections,
    so that would bias the panel rather than merely waste bandwidth. The area call is stubbed
    (the real one needs a key and dials out), so what is pinned here is the accounting: the
    header once, one row per window, and each window asked for exactly once."""
    import fetch_archive as fa

    asked = []

    def fake_area_rows(session, key, source, box, start, span, timeout=240):
        asked.append(str(start))
        return ["18.5,99.5,2024-01-01,1015,80,9.5,320,NOAA-20,VIIRS"], ""

    monkeypatch.setattr(fa, "area_rows", fake_area_rows)
    monkeypatch.setenv("FIRMS_MAP_KEY", "a-test-key")
    out = tmp_path / ".data"
    argv = ["--regions", "amazon", "--years", "2024", "--sources", "MODIS_C6.1",
            "--out", str(out), "--max-windows", "2"]
    csv_path = out / "DL_FIRE_M-C61_amazon_2024" / "fire_archive_M-C61_amazon2024.csv"

    assert fa.main_cli(argv) == 0
    first = csv_path.read_text(encoding="utf-8").splitlines()
    assert first[0].startswith("latitude,") and len(first) == 3      # a header, two windows

    assert fa.main_cli(argv) == 0                                    # the same command again
    second = csv_path.read_text(encoding="utf-8").splitlines()
    assert len(second) == 5                                          # four windows, one header
    assert sum(1 for line in second if line.startswith("latitude")) == 1
    assert asked == ["2024-01-01", "2024-01-06", "2024-01-11", "2024-01-16"]
    assert (out / fa.PROGRESS_FILE).is_file()
