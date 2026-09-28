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
    assert m["hfi"] > 0 and m["esfp"] > 0 and m["pixels"] == m["n"]


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
    assert all("sensors" in c and "duration_h" in c for c in cl)


def test_climatology():
    c = client.get("/climatology").json()
    assert c["years"] and c["doy"] and len(c["envelope"]) > 20
    assert all(k in e for e in c["envelope"] for k in ("p10", "p50", "p90", "p95"))
    s = c["summary"]
    assert s and 1 <= s["peak_doy"] <= 366
    assert 1 <= s["onset_doy"] <= s["cessation_doy"] <= 366
    # envelope percentiles ordered
    assert all(e["p10"] <= e["p50"] <= e["p90"] <= e["p95"] for e in c["envelope"][:50])


def test_diagnostic_standard_demo():
    """2020-2024 demo has no pre-2012 era: growth is None, stats still work."""
    d = client.get("/diagnostic").json()
    assert d["series"] and d["stats"]["hfi"] > 0
    assert d["observed_growth_pct"] is None
    assert d["calibration"] is None


def test_diagnostic_transition_demo():
    """2002-2024 transition demo: observed growth >> adjusted growth."""
    r = client.post("/demo", params={"mode": "transition"})
    assert r.status_code == 200
    assert r.json()["n"] > 50000
    d = client.get("/diagnostic").json()
    assert d["observed_growth_pct"] is not None
    assert d["adjusted_growth_pct"] is not None
    assert d["observed_growth_pct"] > 100          # raw record surges after 2012
    assert d["adjusted_growth_pct"] < 25           # harmonized record is stable
    assert d["calibration"] and d["calibration"]["r2"] is not None
    client.post("/demo")  # restore the standard demo for the remaining tests


def test_live():
    """Hits real NASA FIRMS 24h feeds; skipped if the network is unavailable."""
    r = client.get("/live", params={"region": "South_America"})
    if r.status_code == 502:
        pytest.skip("FIRMS feeds unreachable")
    j = r.json()
    assert j["n"] > 0 and j["feeds"]
    assert all(k in j for k in ("sensors", "hfi", "rows", "clusters"))
    assert len(j["rows"]) <= 15000


def test_briefing_json_and_markdown():
    b = client.get("/briefing").json()
    assert b["threat"]["level"] in ("Low", "Watch", "Elevated", "Critical")
    assert isinstance(b["streaks"], list) and isinstance(b["biomes"], list)
    assert all(k in s for s in b["streaks"] for k in ("start", "end", "days", "max_z", "total"))
    assert all(k in x for x in b["biomes"] for k in ("kind", "n", "mean_frp", "centroid"))
    assert b["recommendations"]
    r = client.get("/briefing", params={"format": "markdown"})
    assert r.status_code == 200 and "Briefing" in r.text


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
