"""API smoke test: runs every endpoint end-to-end against synthetic demo data."""
import io

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def demo_data():
    r = client.post("/demo")
    assert r.status_code == 200
    assert r.json()["n"] > 1000


def test_meta():
    m = client.get("/meta").json()
    assert m["n"] > 1000 and m["start"] <= m["end"]
    assert set(m["sensors"]) == {"MODIS", "VIIRS"}
    assert len(m["bounds"]) == 4


def test_calendar_full_and_bbox():
    days = client.get("/calendar").json()
    assert len(days) > 400
    assert days[0]["count"] >= 0 and "raw" in days[0] and "frp" in days[0]
    boxed = client.get("/calendar", params={"bbox": "17.5,98.5,19.5,100.5"}).json()
    assert 0 < len(boxed) <= len(days)


def test_points_clamp():
    assert len(client.get("/points", params={"limit": 10}).json()) == 10
    assert len(client.get("/points", params={"limit": 999999}).json()) <= 20000


def test_clusters():
    cl = client.get("/clusters").json()
    assert cl and all(len(c["hull"]) >= 1 and c["n"] >= 3 for c in cl)
    assert len(cl) <= 300


def test_anomalies():
    an = client.get("/anomalies").json()
    assert an["anomalies"] and an["monthly"]
    assert all("date" in a and "z" in a for a in an["anomalies"])


def test_forecast():
    fc = client.get("/forecast").json()
    assert fc["model"] and len(fc["forecast"]) == 30
    assert all(f["count"] >= 0 for f in fc["forecast"])


def test_bad_bbox_returns_400():
    assert client.get("/calendar", params={"bbox": "1,2,3"}).status_code == 400
    assert client.get("/calendar", params={"bbox": "999,0,999,1"}).status_code == 400


def test_bad_csv_returns_400():
    bad = ("files", ("bad.csv", io.BytesIO(b"foo,bar\n1,2\n"), "text/csv"))
    r = client.post("/upload", files=[bad])
    assert r.status_code == 400
    assert "missing required columns" in r.json()["detail"]


def test_good_csv_merges():
    before = client.get("/meta").json()["n"]
    good = ("files", ("one.csv", io.BytesIO(
        b"latitude,longitude,acq_date,acq_time,confidence,frp,brightness\n"
        b"1.0,2.0,2022-01-01,1345,55,10.5,330\n"), "text/csv"))
    r = client.post("/upload", files=[good])
    assert r.status_code == 200 and r.json()["n"] == before + 1


def test_clear():
    assert client.delete("/data").json()["n"] == 0
    assert client.get("/meta").json()["n"] == 0
