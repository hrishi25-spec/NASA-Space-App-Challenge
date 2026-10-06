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
    and opens. (The CLI is faked because the real one would dial out; the sync *call* is real.)"""
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


def test_no_hf_cli_is_an_empty_answer_not_an_error(tmp_path, monkeypatch):
    """No `hf` on PATH is the normal state of a CI machine: (False, reason), and the caller
    keeps answering "nothing found" the way every other missing-database case here does."""
    monkeypatch.setenv("PATH", str(tmp_path / "no-bin-here"))
    monkeypatch.setattr(archives, "hf_pull", _REAL_HF_PULL)
    ok, message = archives.hf_pull(tmp_path / ".data")
    assert ok is False and "not installed" in message
