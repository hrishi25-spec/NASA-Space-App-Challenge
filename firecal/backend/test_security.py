"""Regression tests for the input-handling hardening.

Each test here corresponds to a way the API used to accept attacker-shaped input:
an unvalidated region that reached an outbound URL, an upload that was buffered before
its size was checked, a client-controlled *filename* that selected server behaviour,
and reflected filenames/log text. They are written to fail loudly if any of that
behaviour comes back.

Note on ordering: this module runs before test_smoke.py (alphabetical), which reloads the
standard demo in its session fixture, so the datasets swapped in here do not leak.
"""
import io

import pandas as pd
import pytest
import requests
from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)


def _csv(name, rows="5.0,6.0,2022-03-03,1015,70,9.5,320,NOAA-20\n"):
    text = ("latitude,longitude,acq_date,acq_time,confidence,frp,brightness,satellite\n" + rows)
    return ("files", (name, io.BytesIO(text.encode()), "text/csv"))


@pytest.fixture(scope="module", autouse=True)
def data_loaded():
    assert client.post("/demo").status_code == 200
    yield
    client.post("/demo")


# ----------------------------------------------------------- outbound URL allowlist
def test_live_rejects_unknown_region_without_fetching(monkeypatch):
    """`region` is interpolated into the FIRMS URL, so anything off the allowlist must be
    refused -- and refused *before* any outbound request happens."""
    def boom(*_a, **_k):
        raise AssertionError("the server attempted an outbound fetch for a bad region")

    monkeypatch.setattr(main, "_fetch_feed", boom)
    r = client.get("/live", params={"region": "ZZZ_NOT_A_REGION"})
    assert r.status_code == 400
    assert "unknown region" in r.json()["detail"]


@pytest.mark.parametrize("region", [
    "Global/../../../../etc/passwd",
    "../../../../etc/passwd",
    "Global?x=",
    "Global#",
    "https://evil.example/",
    "",
    "global",                      # allowlist is case-sensitive on purpose
])
def test_live_rejects_traversal_and_host_injection(monkeypatch, region):
    monkeypatch.setattr(main, "_fetch_feed", lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("outbound fetch attempted")))
    assert client.get("/live", params={"region": region}).status_code == 400


def test_live_accepts_allowlisted_region(monkeypatch):
    """The happy path still works (and the allowlist matches what the UI offers).
    The stub returns a raw FIRMS-shaped frame, because the endpoint harmonizes what the
    fetch hands back."""
    def fake_feed(url, timeout=90):
        assert url.startswith("https://firms.modaps.eosdis.nasa.gov/data/active_fire/")
        assert "South_Asia" in url
        return pd.DataFrame({
            "latitude": [5.0], "longitude": [6.0], "acq_date": ["2022-03-03"],
            "acq_time": [1015], "confidence": [70], "frp": [9.5],
            "brightness": [320], "satellite": ["NOAA-20"],
        })

    monkeypatch.setattr(main, "_fetch_feed", fake_feed)
    r = client.get("/live", params={"region": "South_Asia"})
    assert r.status_code == 200, r.text
    assert r.json()["region"] == "South_Asia"
    assert r.json()["n"] > 0


def test_live_refuses_to_stack_concurrent_ingests():
    """Each call is four downloads plus clustering; overlapping calls must not pile up."""
    assert main._LIVE_SLOTS.acquire(blocking=False)
    assert main._LIVE_SLOTS.acquire(blocking=False)
    try:
        r = client.get("/live", params={"region": "Global"})
        assert r.status_code == 429
        assert "already running" in r.json()["detail"]
    finally:
        main._LIVE_SLOTS.release()
        main._LIVE_SLOTS.release()


# ----------------------------------------------------------------- upload bounds
def test_oversize_request_is_refused_before_it_is_read(monkeypatch):
    """A declared Content-Length past the cap must 413 without the body being consumed."""
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 256)
    r = client.post("/upload", files=[_csv("big.csv", "5.0,6.0,2022-03-03,1015,70,9.5,320,NOAA-20\n" * 20)])
    assert r.status_code == 413
    assert "upload too large" in r.json()["detail"]


def test_oversize_single_file_is_refused(monkeypatch):
    monkeypatch.setattr(main, "MAX_FILE_BYTES", 64)
    r = client.post("/upload", files=[_csv("big.csv", "5.0,6.0,2022-03-03,1015,70,9.5,320,NOAA-20\n" * 20)])
    assert r.status_code == 400
    assert "exceeds" in r.json()["detail"]


def test_too_many_files_is_refused(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_FILES", 3)
    r = client.post("/upload", files=[_csv(f"f{i}.csv") for i in range(4)])
    assert r.status_code == 400
    assert "too many files" in r.json()["detail"]


def test_sane_upload_still_works():
    before = client.get("/meta").json()["n"]
    r = client.post("/upload", files=[_csv("ok.csv")])
    assert r.status_code == 200, r.text
    assert r.json()["n"] == before + 1


# ------------------------------------------------- filename must not be a command
def test_filename_cannot_summon_the_demo_dataset():
    """Uploading junk named demo_transition.csv used to silently load the 2002-2024 demo
    and ignore the bytes entirely. A filename is client input, not a command."""
    r = client.post("/upload", files=[("files", ("demo_transition.csv", io.BytesIO(b"not a csv\n"), "text/csv"))])
    assert r.status_code == 400
    body = r.json()
    # rejected as data (whichever parser complains first), never answered with a dataset
    assert "demo_transition.csv" in body["detail"]
    assert "n" not in body


def test_demo_transition_is_an_explicit_flag():
    r = client.post("/upload", params={"demo_transition": True}, files=[_csv("anything.csv")])
    assert r.status_code == 200, r.text
    assert r.json()["n"] > 40000          # the 2002-2024 illusion dataset
    client.post("/demo")                   # restore the standard demo


# ------------------------------------------------------- reflected input safety
def test_filename_in_error_body_is_sanitised():
    """Filenames come back in JSON detail strings, so paths and control characters are
    stripped rather than echoed."""
    # a parseable CSV that is missing the required columns, so the error path runs
    r = client.post("/upload", files=[("files", ("../../../../etc/passwd.csv",
                                                    io.BytesIO(b"foo,bar\n1,2\n"), "text/csv"))])
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "passwd.csv" in detail
    assert ".." not in detail and "/" not in detail


def test_safe_name_strips_directories_controls_and_length():
    assert main._safe_name("../../etc/shadow") == "shadow"
    assert main._safe_name("a\\b\\c.csv") == "c.csv"
    assert main._safe_name("evil\nINFO: forged log line.csv") == "evilINFO: forged log line.csv"
    assert main._safe_name("x" * 500) == "x" * 80
    assert main._safe_name(None) == "upload"
    assert main._safe_name("") == "upload"


# ------------------------------------------------------------------- CORS default
def test_archive_failure_never_reflects_the_map_key(monkeypatch):
    """The area-API URL embeds FIRMS_MAP_KEY, and `requests` puts the whole URL in its
    own exception text, so the 502 detail used to hand the operator's key to the caller.
    """
    sentinel = "SENTINELKEY123"
    monkeypatch.setenv("FIRMS_MAP_KEY", sentinel)

    def boom(url, **_kw):
        raise requests.exceptions.ConnectionError(f"Max retries exceeded with url: {url}")

    monkeypatch.setattr(main.requests, "get", boom)
    r = client.post("/archive", params={"region": "california", "days": 1})
    assert r.status_code == 502
    assert sentinel not in r.text and "SENTINEL" not in r.text
    assert "ConnectionError" in r.json()["detail"]          # still diagnosable


def test_foreign_origin_cannot_drive_a_write():
    """CORS stops a foreign page reading the response, never sending the request: a form
    POST is not preflighted, so before this guard any open page could replace the dataset.
    """
    evil = {"Origin": "https://evil.example"}
    assert client.post("/demo", headers=evil).status_code == 403
    assert client.post("/upload", files=[_csv("ok.csv")], headers=evil).status_code == 403
    assert client.delete("/data", headers=evil).status_code == 403
    assert client.get("/meta", headers=evil).status_code == 200        # reads stay open
    # same host, an allowlisted dev origin, and a no-Origin caller all still write
    assert client.post("/demo", headers={"Origin": "http://testserver"}).status_code == 200
    assert client.post("/demo", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 200
    assert client.post("/demo").status_code == 200


def test_cors_default_is_local_only():
    """`*` let any visited web page drive /upload and /demo against the operator's data."""
    allowed = client.get("/meta", headers={"Origin": "http://127.0.0.1:5173"})
    assert allowed.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
    hostile = client.get("/meta", headers={"Origin": "https://evil.example"})
    assert hostile.headers.get("access-control-allow-origin") is None


def test_cors_is_not_credentialed():
    """No cookies or auth exist here, so a wildcard must never be paired with credentials."""
    r = client.get("/meta", headers={"Origin": "http://127.0.0.1:5173"})
    assert r.headers.get("access-control-allow-credentials") is None
