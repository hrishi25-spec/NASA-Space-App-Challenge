"""API smoke test: runs every endpoint end-to-end against synthetic demo data."""
import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import main
from main import LIVE_REGIONS, REGIONS, app, firms_area_url, parse_env

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


def test_scipy_and_sklearn_are_imported_only_inside_the_guard():
    """Every heavy import goes through `heavy()`, or two threads can race a cold one.

    One screen pulls both in at once -- the map asks /clusters while the rail asks /briefing
    -- and two concurrent cold imports of the same C-extension package collide on CPython's
    per-module import lock. That is not a theoretical race: loading the console against a
    freshly started server answered

        500 /clusters  _DeadlockError: deadlock detected by
                       _ModuleLock('scipy.linalg.cython_lapack')
    """
    import ast

    tree = ast.parse(Path(main.__file__).read_text(encoding="utf-8"))
    sites = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.ImportFrom) and (inner.module or "").split(".")[0] in ("scipy", "sklearn"):
                sites.add(node.name)
    assert sites, "no guarded scipy/sklearn import found — did it move back to module scope?"
    assert sites == {"heavy"}, f"unguarded heavy import inside {sorted(sites)}"


def test_heavy_imports_resolve_to_the_real_classes():
    """The guard caches the symbol, not the module, and hands the same one to every caller."""
    import concurrent.futures as cf

    with main._HEAVY_LOCK:
        main._HEAVY.clear()
    wanted = ["hull", "dbscan", "kmeans"] * 3
    with cf.ThreadPoolExecutor(max_workers=len(wanted)) as pool:
        got = list(pool.map(main.heavy, wanted))
    assert [c.__name__ for c in got] == ["ConvexHull", "DBSCAN", "KMeans"] * 3
    assert main.heavy("hull") is got[0]
    assert main.heavy("dbscan") is main._HEAVY["dbscan"]


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
    assert d["artifact_pct"] > 0                   # and the removal goes one way
    assert d["viirs_scaling"] > 1                  # the VIIRS era inflates the raw count
    assert d["calibration"] and d["calibration"]["r2"] is not None
    # ESFP is a per-sensor expansion ratio, so after nadir normalization the two
    # sensors' footprint distributions have to agree.  It read 1.739 when VIIRS was
    # being divided by the 750 m M-band cell instead of the 375 m I-band one.
    assert 0.8 < d["calibration"]["esfp_ratio_viirs_to_modis"] < 1.25
    client.post("/demo")  # restore the standard demo for the remaining tests


def test_esfp_nadir_cells():
    """One standard pixel is the floor: 1.0 at each sensor's own nadir cell.

    NASA's FIRMS attribute table for the VIIRS feed: "The algorithm produces
    approximately 375 m pixels at nadir. Scan and track reflect actual pixel size."
    So the I-band cell (0.375 x 0.375 = 0.140625 km²) is the divisor -- not the 750 m
    M-band cell, which understated every VIIRS footprint by exactly 4x.
    """
    assert main.NADIR_KM2["VIIRS"] == pytest.approx(0.140625)
    assert main.NADIR_KM2["MODIS"] == pytest.approx(1.0)
    assert main._esfp(pd.Series([0.375]), pd.Series([0.375]), "VIIRS")[0].iloc[0] == pytest.approx(1.0)
    assert main._esfp(pd.Series([1.0]), pd.Series([1.0]), "MODIS")[0].iloc[0] == pytest.approx(1.0)
    # edge of scan: ~9.7x the nadir area for either sensor, and never below 1.0
    assert main._esfp(pd.Series([1.166]), pd.Series([1.166]), "VIIRS")[0].iloc[0] == pytest.approx(9.67, rel=0.02)
    assert main._esfp(pd.Series([0.1]), pd.Series([0.1]), "VIIRS")[0].iloc[0] == 1.0


def test_demo_footprints_are_product_shaped():
    """Synthetic scan/track must sit in the real per-sensor ranges, or ESFP is fiction."""
    assert client.post("/demo", params={"mode": "transition"}).status_code == 200
    d = main.DF
    v, m = d[d.sensor == "VIIRS"], d[d.sensor == "MODIS"]
    assert 0.375 <= v.scan.min() and v.scan.max() <= 1.17     # 375 m I-band -> ~1.17 km
    assert 1.0 <= m.scan.min() and m.scan.max() <= 4.84       # 1 km -> 4.83 km along-scan
    assert (d.esfp >= 1).all() and (d.pixel_km2 > 0).all()
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


# ------------------------------------------------------------------- training the model
# `train.py` reduces ~10 GB of FIRMS exports to the seasonal prior `/forecast` blends in.
# The archive is not in the repository and never will be, so these build a few dozen
# synthetic rows and push them through the *real* scan/build/save/load path.
RAW = pd.DataFrame({
    "latitude": [37.0, 39.5, 39.5, 40.0, 999.0],
    "longitude": [-121.0, -122.0, -122.0, -123.0, 0.0],
    "acq_date": ["2025-09-30", "2025-09-30", "2025-10-01", "2025-10-01", "2025-10-01"],
    "acq_time": [1740, 1809, 1019, 1200, 1200],
    # numeric MODIS confidence, VIIRS l/n/h letters, and one below the floor
    "confidence": ["69", "n", "h", "l", "80"],
    "brightness": [315.9, 300.74, 297.41, 296.0, 310.0],
    "instrument": ["MODIS", "VIIRS", "VIIRS", "VIIRS", "MODIS"],
    "frp": [9.2, 0.44, 0.47, 1.0, 2.0],
    "scan": [1.0, 0.49, 0.45, 0.4, 1.0],
    "track": [1.0, 0.4, 0.47, 0.4, 1.0],
})


def test_harmonize_without_geometry_counts_the_same():
    """The training pass skips the footprint columns to avoid ~80M wasted clip passes.

    Everything that decides *whether and when* a detection counts has to stay identical,
    or `train.py` fits one series and `/forecast` predicts another.
    """
    full = main.harmonize(RAW)
    lean = main.harmonize(RAW, geometry=False)
    assert list(lean.columns) == [c for c in full.columns if c not in ("scan", "track", "esfp", "pixel_km2")]
    pd.testing.assert_frame_equal(lean, full[list(lean.columns)])
    # the below-floor and out-of-range rows were dropped by both, and by the same rule:
    # confidence 69 kept, "n"/"h" mapped to 60/90, "l" (20) and the 999-degree latitude gone
    assert list(lean.conf) == [69.0, 60.0, 90.0]
    pd.testing.assert_series_equal(main.daily(lean)["count"], main.daily(full)["count"])


@pytest.fixture
def trained(tmp_path, monkeypatch):
    """A checkpoint built by the real pipeline from a tiny archive inside the demo box."""
    import forecast_model as fm
    import train

    archive = tmp_path / "Data Training"
    archive.mkdir()
    days, rows = [], []
    for year in (2024, 2025):                       # a season, twice, so the cell is storable
        for i in range(40):
            day = f"{year}-03-{i + 1:02d}" if i < 31 else f"{year}-04-{i - 30:02d}"
            days.append(day)
            rows.append(f"18.5,99.5,{day},1000,69,300.1,4.0,MODIS")
            rows.append(f"18.6,99.4,{day},1000,n,301.2,0.4,VIIRS")
    head = "latitude,longitude,acq_date,acq_time,confidence,brightness,frp,instrument\n"
    (archive / "fire_archive_M-C61_1.csv").write_text(head + "\n".join(rows[::2]) + "\n", encoding="utf-8")
    (archive / "fire_nrt_J1V-C2_2.csv").write_text(head + "\n".join(rows[1::2]) + "\n", encoding="utf-8")

    out = tmp_path / "model"
    manifest = train.run(data_dir=archive, out=out, use_lstm=False, log=lambda *a: None)
    monkeypatch.setattr(fm, "CHECKPOINT", out / fm.CHECKPOINT.name)
    monkeypatch.setattr(fm, "CELL_GRID", out / fm.CELL_GRID.name)
    fm.clear_cache()
    yield manifest
    fm.clear_cache()
    main._invalidate()


def test_train_writes_a_usable_checkpoint(trained):
    import forecast_model as fm

    assert trained["source"]["files"] == 2 and trained["source"]["kept"] == 160
    assert trained["series"]["days"] == len(trained["series"]["dates"]) > 300
    ck = fm.load()
    assert ck and ck["schema"] == fm.SCHEMA
    assert ck["cells"]["count"] >= 1 and ck["grid_deg"] == 2.0
    box = (17.0, 98.0, 20.0, 101.0)
    prior = fm.profile_for_bbox(box)
    assert prior is not None and len(prior["doy"]) == fm.DOY_BINS
    # a box the archive never covered has no prior, and the endpoint must say so by omission
    assert fm.profile_for_bbox((-40.0, -70.0, -35.0, -65.0)) is None


def test_forecast_blends_the_archive_prior(trained):
    """With a checkpoint on disk the endpoint reports it, and a short frame leans on it.

    Three years of the frame's own record match the archive's evidence, so a long frame
    keeps its own season; the demo covers five, which is why the assertion here is about
    the blend being wired up rather than about a number moving.
    """
    main._invalidate()
    fc = client.get("/forecast", params={"bbox": "17.0,98.0,20.0,101.0"}).json()
    assert fc["model"].startswith("Seasonal climatology + archive prior")
    assert len(fc["forecast"]) == 30 and all(f["count"] >= 0 for f in fc["forecast"])

    # One season of frame data is one sample per day: there the prior is most of the curve.
    short = pd.Series(np.linspace(0, 40, 400), index=pd.date_range("2024-01-01", periods=400))
    curve, prior = main._seasonal_climatology(short, (17.0, 98.0, 20.0, 101.0))
    assert prior is not None and len(curve) == main.forecast_model.DOY_BINS
    own = short.groupby(short.index.dayofyear).mean()
    assert not np.allclose(curve.values, own.reindex(curve.index).fillna(0).values)


def test_broken_checkpoint_falls_back(tmp_path, monkeypatch):
    """A half-written, truncated or foreign checkpoint is no checkpoint, not a 500."""
    import forecast_model as fm

    broken = tmp_path / "forecast.json"
    monkeypatch.setattr(fm, "CHECKPOINT", broken)
    monkeypatch.setattr(fm, "CELL_GRID", tmp_path / "cells.npz")
    fm.clear_cache()
    assert fm.load() == {}
    broken.write_text("{not json at all", encoding="utf-8")
    fm.clear_cache()
    assert fm.load() == {}
    # a checkpoint written by a *newer* build: recognized as one of ours, then refused
    newer = tmp_path / "newer.json"
    fm.save({}, np.array([1]), np.zeros((1, fm.DOY_BINS), "float32"), np.array([1.0]), path=newer)
    newer.write_text('{"schema": 99}', encoding="utf-8")
    fm.clear_cache()
    assert fm.load(newer) == {}
    # ...and with no checkpoint the endpoint answers exactly as it did before training existed
    main._invalidate()
    fc = client.get("/forecast").json()
    assert fc["model"].startswith("Seasonal climatology")


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


def test_upload_cp1252_csv():
    """Excel on Windows exports cp1252: that must not be rejected as unreadable."""
    before = client.get("/meta").json()["n"]
    text = ("latitude,longitude,acq_date,acq_time,confidence,frp,brightness,satellite\n"
            "3.0,4.0,2022-02-02,0900,80,12.5,340,AQUA-VIIRS \u00e9\n")
    csv = ("files", ("cp1252.csv", io.BytesIO(text.encode("cp1252")), "text/csv"))
    r = client.post("/upload", files=[csv])
    assert r.status_code == 200, r.text
    assert r.json()["n"] == before + 1


def test_upload_utf16_csv():
    """Excel on macOS can emit UTF-16 with a BOM."""
    before = client.get("/meta").json()["n"]
    text = ("latitude,longitude,acq_date,acq_time,confidence,frp,brightness,satellite\n"
            "5.0,6.0,2022-03-03,1015,70,9.5,320,NOAA-20\n")
    csv = ("files", ("utf16.csv", io.BytesIO(text.encode("utf-16")), "text/csv"))
    r = client.post("/upload", files=[csv])
    assert r.status_code == 200, r.text
    assert r.json()["n"] == before + 1


def test_clear():
    assert client.delete("/data").json()["n"] == 0
    assert client.get("/meta").json()["n"] == 0


def test_responses_are_gzipped():
    """The analytics payloads are big; they must go over the wire compressed.

    (test_clear runs just before this, so load data again -- the middleware has a
    1 KiB floor under which compressing costs more than it saves.)
    """
    client.post("/demo")
    big = client.get("/calendar", headers={"Accept-Encoding": "gzip"})
    assert big.status_code == 200
    assert len(big.json()) > 400
    # httpx decodes transparently, so compare headers rather than len(big.content):
    # the middleware only sets this header when it actually compressed (~87 KB -> ~9 KB).
    assert big.headers.get("content-encoding") == "gzip"
    # ...and it must leave tiny payloads alone (the 1 KiB floor).
    small = client.get("/meta", headers={"Accept-Encoding": "gzip"})
    assert small.headers.get("content-encoding") is None


def test_cached_analytics_not_stale_after_data_change():
    """A memoized response must never outlive the dataset it was computed from."""
    client.post("/demo")
    assert len(client.get("/calendar").json()) > 400      # fills the cache
    client.delete("/data")                                # must bust it
    assert client.get("/meta").json()["n"] == 0
    assert client.get("/calendar").json() == []            # a stale cache would answer here
    client.post("/demo")
    assert len(client.get("/calendar").json()) > 400      # and it refills correctly


# ---------------------------------------------------------------- region presets
def test_regions_catalog():
    r = client.get("/regions")
    assert r.status_code == 200
    regions = r.json()
    keys = [x["key"] for x in regions]
    assert len(regions) >= 5 and len(keys) == len(set(keys))
    assert "california" in keys
    for x in regions:
        a, b, c, e = x["bbox"]                       # minlat, minlon, maxlat, maxlon
        assert -90 <= a < c <= 90 and -180 <= b < e <= 180
        assert x["peak_months"] and all(1 <= m <= 12 for m in x["peak_months"])
        assert x["biome"] and x["events"]
        # A preset's live region must stay on the allowlist, or "pull live" would 400.
        assert x["firms_region"] in LIVE_REGIONS
        lat, lon = x["center"]
        assert a <= lat <= c and b <= lon <= e


def test_demo_per_region_stays_inside_its_bbox():
    r = client.post("/demo", params={"region": "california"})
    assert r.status_code == 200
    m = r.json()
    assert m["n"] > 1000
    a, b, c, e = REGIONS["california"]["bbox"]
    assert a <= m["bounds"][0] and m["bounds"][2] <= c
    assert b <= m["bounds"][1] and m["bounds"][3] <= e
    days = client.get("/calendar", params={"bbox": f"{a},{b},{c},{e}"}).json()
    assert len(days) > 400                            # the AOI really carries the record
    assert client.post("/demo").json()["n"] > 1000   # restore the default demo


def test_demo_unknown_region_400():
    r = client.post("/demo", params={"region": "atlantis"})
    assert r.status_code == 400 and "unknown region" in r.json()["detail"]


def test_region_seed_is_stable_and_region_specific():
    """The generator ignores the box for event counts, so the seed is what keeps two
    presets from showing identical statistics; the default demo must keep its own seed."""
    assert main._region_seed(None, 7) == 7
    assert main._region_seed("california", 7) == main._region_seed("california", 7)
    assert main._region_seed("california", 7) != main._region_seed("amazon", 7)


def test_env_file_parsing():
    parsed = parse_env("# comment\n"
                       "FIRMS_MAP_KEY=abc123\n"
                       "export FOO=bar\n"
                       'QUOTED="a b"\n'
                       "SINGLE='c d'\n"
                       "\n"
                       "nonsense\n")
    assert parsed["FIRMS_MAP_KEY"] == "abc123"
    assert parsed["FOO"] == "bar" and parsed["QUOTED"] == "a b" and parsed["SINGLE"] == "c d"
    assert "nonsense" not in parsed


def test_archive_validates_the_request_before_the_key():
    """A bad request must not depend on whether a MAP_KEY happens to be configured."""
    assert client.post("/archive", params={"source": "NOPE"}).status_code == 400
    assert client.post("/archive", params={"region": "atlantis"}).status_code == 400
    assert client.post("/archive").status_code == 400                  # no region, no bbox
    assert client.post("/archive", params={"bbox": "1,2,3"}).status_code == 400
    assert client.post("/archive", params={"region": "california", "date": "yesterday"}).status_code == 400


def test_archive_requires_a_key(monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    r = client.post("/archive", params={"region": "california"})
    assert r.status_code == 400 and "FIRMS_MAP_KEY" in r.json()["detail"]


def test_archive_url_builder():
    box = REGIONS["california"]["bbox"]               # minlat, minlon, maxlat, maxlon
    url = firms_area_url("KEY123", "MODIS_C6.1", box, 3, "2024-08-01")
    # ...and the area API wants west,south,east,north, i.e. minlon,minlat,maxlon,maxlat.
    assert url == ("https://firms.modaps.eosdis.nasa.gov/api/area/csv/KEY123/MODIS_C6_1/"
                   "-124.4,32.5,-114.1,42.0/3/2024-08-01")
    assert firms_area_url("KEY123", "VIIRS_S-NPP", box, 1).endswith("/1")


def test_archive_appends_rows_and_clips_to_the_aoi(monkeypatch):
    """The network call is stubbed; the endpoint contract is what is under test."""
    monkeypatch.setenv("FIRMS_MAP_KEY", "TESTKEY123")
    frame = pd.DataFrame({
        "latitude": [37.0, 37.5, 13.7],               # the last row is outside California
        "longitude": [-120.0, -119.0, 100.5],
        "acq_date": ["2024-08-01"] * 3, "acq_time": ["1315", "1320", "0900"],
        "confidence": [80, 90, 70], "frp": [12.0, 8.0, 4.0],
        "brightness": [330.0, 335.0, 325.0],
        "satellite": ["Terra", "Aqua", "NPP"],
    })
    monkeypatch.setattr(main, "_fetch_feed", lambda url, timeout=90: frame)
    before = client.get("/meta").json()["n"]
    r = client.post("/archive", params={"region": "california", "days": 2})
    assert r.status_code == 200, r.text
    assert r.json()["n"] == before + 2               # out-of-AOI row dropped
    assert r.json()["source"] == "VIIRS_S-NPP" and r.json()["days"] == 2
    client.delete("/data")
    client.post("/demo")


def test_archive_can_replace_instead_of_append(monkeypatch):
    """append=false means "this window is now the record", so the load must swap, not merge."""
    monkeypatch.setenv("FIRMS_MAP_KEY", "TESTKEY123")
    frame = pd.DataFrame({
        "latitude": [37.0], "longitude": [-120.0], "acq_date": ["2024-08-02"],
        "acq_time": ["1315"], "confidence": [80], "frp": [12.0],
        "brightness": [330.0], "satellite": ["Terra"],
    })
    monkeypatch.setattr(main, "_fetch_feed", lambda url, timeout=90: frame)
    before = client.get("/meta").json()["n"]
    r = client.post("/archive", params={"region": "california", "append": False})
    assert r.status_code == 200, r.text
    assert r.json()["n"] == 1 < before                 # replaced, not merged
    assert client.delete("/data").json()["n"] == 0     # ...and the analytics caches were dropped
    assert client.get("/calendar").json() == []
    client.post("/demo")


def test_api_prefix_is_transparent():
    """The image has no proxy in front of it: the browser calls /api/... while curl, these
    tests and the launcher use the bare paths. Both spellings have to reach the same endpoint,
    and a same-origin write through the prefix has to clear the cross-origin gate."""
    assert client.get("/api/meta").json() == client.get("/meta").json()
    assert (client.get("/api/points", params={"limit": 3}).json()
            == client.get("/points", params={"limit": 3}).json())
    # 422 (no files on the request), never 403: the write was refused by the endpoint, not by
    # the same-origin middleware, which is the half of this that the prefix could break.
    assert client.post("/api/upload", headers={"origin": "http://testserver"},
                       content=b"").status_code == 422


def test_console_mount_follows_the_build():
    """Dockerfile builds the console into firecal/frontend/dist and copies it next to the API,
    which is what turns a single uvicorn into the whole deployment. The mount is conditional so
    a development checkout -- where Vite serves the console -- does not 404 on /."""
    built = (Path(main.__file__).resolve().parent.parent / "frontend" / "dist" / "index.html").is_file()
    mounted = any(getattr(route, "name", "") == "console" for route in app.routes)
    assert mounted == built
