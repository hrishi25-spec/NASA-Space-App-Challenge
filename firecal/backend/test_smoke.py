"""API smoke test: runs every endpoint end-to-end against synthetic demo data."""
import ast
import io
import subprocess
import sys
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
    import statistics

    an = client.get("/anomalies").json()
    assert an["anomalies"] and an["monthly"]
    assert all("date" in a and "z" in a for a in an["anomalies"])
    # The monthly profile the Anomalies chart draws: twelve calendar slots, in order, with a
    # critical-month threshold the chart's line can use without re-deriving mean + 1σ.
    monthly = an["monthly"]
    assert [m["month"] for m in monthly] == list(range(1, 13))
    assert all(m["avg"] >= 0 for m in monthly)
    avgs = [m["avg"] for m in monthly]
    assert abs(an["threshold"] - (statistics.mean(avgs) + statistics.stdev(avgs))) <= 0.2
    critical = {c["month"] for c in an["critical"]}
    assert critical <= {m["month"] for m in monthly if m["avg"] >= an["threshold"] - 0.1}
    assert {m["month"] for m in monthly if m["avg"] >= an["threshold"] + 0.1} <= critical


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


def test_a_platform_name_is_not_a_sensor():
    """FIRMS names the instrument differently per product: `instrument` is `VIIRS` in the
    NOAA-20/21 C2 files but `SNPP` in the S-NPP ones, which names the satellite. Taken
    literally that made VIIRS S-NPP a third sensor -- invisible to `/diagnostic`, rescaled
    against itself, and handed MODIS's 1 km nadir cell by `_esfp`, so its footprint area came
    out 7.1x too large. Three satellites, one instrument: they are counted as one.
    """
    snpp = RAW.copy()
    snpp["instrument"] = "SNPP"        # a real S-NPP export: one product, one value throughout
    d = main.harmonize(snpp)
    assert set(d.sensor) == {"VIIRS"}
    assert main.sensor_of("SNPP") == "VIIRS"
    assert main.sensor_of("viirs") == "VIIRS"          # case is not a distinction
    assert main.sensor_of("N20") == "VIIRS"            # and the platform column's spelling
    assert main.sensor_of("MODIS") == "MODIS"
    # The nadir cell follows the instrument: an S-NPP detection is a 375 m one, so a wide-scan
    # detection is worth several standard pixels -- not the 1.0 a MODIS cell would have given.
    assert d["esfp"].max() > 5.0
    # An unrecognized product string still passes through, as it always has.
    assert main.sensor_of("SLSTR") == "SLSTR"


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


# ------------------------------------------------------- a real FIRMS export, verbatim
# These bytes are captured as-is from the four `fire_nrt_*` downloads in `.data/`
# (the 2026-10-04 pull): the literal header FIRMS writes and three of its rows, for
# MODIS C6.1, VIIRS S-NPP and VIIRS NOAA-20. They are pinned here because `.data/` is
# git-ignored and CI has none: if FIRMS renames, adds, drops or reshuffles a column,
# these tests fail in the build instead of surfacing months later as a training run
# that ingests a different quantity than the endpoint serves.
REAL_FIRMS_MODIS_CSV = (b"latitude,longitude,brightness,scan,track,acq_date,acq_time,"
                        b"satellite,confidence,version,bright_t31,frp,daynight\n"
                        b"-13.60052,49.60114,301.4,1.43,1.18,2026-10-04,0033,A,38,6.1NRT,288.65,8.77,N\n"
                        b"32.24827,51.42755,311.08,1.5,1.21,2026-10-04,0020,A,82,6.1NRT,278.94,23.82,N\n"
                        b"-15.20455,48.98621,301.27,1.37,1.16,2026-10-04,0033,A,39,6.1NRT,288.67,8.25,N\n")
REAL_FIRMS_SNPP_CSV = (b"latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,"
                       b"satellite,confidence,version,bright_ti5,frp,daynight\n"
                       b"-29.78994,27.11075,299.44,0.5,0.49,2026-10-04,0001,N,nominal,2.0NRT,279.07,0.68,N\n"
                       b"65.02583,56.72539,305.3,0.47,0.64,2026-10-04,0111,N,nominal,2.0NRT,266.75,0.97,N\n"
                       b"65.04215,56.67452,332.27,0.47,0.64,2026-10-04,0111,N,nominal,2.0NRT,268.01,2.56,N\n")
REAL_FIRMS_N20_CSV = (b"latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,"
                      b"satellite,confidence,version,bright_ti5,frp,daynight\n"
                      b"42.93438,18.87675,367,0.37,0.58,2026-10-04,0001,N20,high,2.0NRT,286.87,7.38,N\n"
                      b"42.93413,18.88209,324.51,0.37,0.58,2026-10-04,0001,N20,nominal,2.0NRT,280.52,7.83,N\n"
                      b"42.93463,18.87132,296.2,0.37,0.58,2026-10-04,0001,N20,nominal,2.0NRT,279.73,7.38,N\n")

REAL_FIRMS_PRODUCTS = {
    "MODIS_C6.1": (REAL_FIRMS_MODIS_CSV, ("latitude", "longitude", "brightness", "scan",
                   "track", "acq_date", "acq_time", "satellite", "confidence",
                   "version", "bright_t31", "frp", "daynight"), "MODIS"),
    "VIIRS_S-NPP": (REAL_FIRMS_SNPP_CSV, ("latitude", "longitude", "bright_ti4", "scan",
                    "track", "acq_date", "acq_time", "satellite", "confidence",
                    "version", "bright_ti5", "frp", "daynight"), "VIIRS"),
    "VIIRS_NOAA-20": (REAL_FIRMS_N20_CSV, ("latitude", "longitude", "bright_ti4", "scan",
                      "track", "acq_date", "acq_time", "satellite", "confidence",
                      "version", "bright_ti5", "frp", "daynight"), "VIIRS"),
}

# The working-frame schema `harmonize()` produces -- the exact columns, in the exact
# order, that `/upload`, `/archive`, `train.py` and `train_forecast.py` all read.
HARMONIZED_COLUMNS = ["lat", "lon", "time", "date", "sensor", "sat", "conf", "frp", "bt",
                      "scan", "track", "daynight", "esfp", "pixel_km2"]


@pytest.mark.parametrize("product", ("MODIS_C6.1", "VIIRS_S-NPP", "VIIRS_NOAA-20"))
def test_a_real_firms_export_keeps_its_columns(product):
    """`read_firms_csv` must not reorder, rename or drop a single FIRMS column.

    This is the guard against schema drift on NASA's side: the column list is FIRMS's
    own export order, spelled exactly as the real downloads write it.
    """
    csv, expected_cols, _ = REAL_FIRMS_PRODUCTS[product]
    raw = main.read_firms_csv(csv)
    assert list(raw.columns) == list(expected_cols)


@pytest.mark.parametrize("product", ("MODIS_C6.1", "VIIRS_S-NPP", "VIIRS_NOAA-20"))
def test_a_real_firms_export_harmonizes_to_every_row(product):
    """Every row of a real export survives `harmonize()` with the working schema.

    Three real detections per product go in; no confidence, byte or value drops any of
    them out, they all stamp to FIRMS's own 2026-10-04, the platform column travels
    through `sat` unchanged, and the columns out are exactly the working frame's.
    """
    csv, _, sensor = REAL_FIRMS_PRODUCTS[product]
    d = main.harmonize(main.read_firms_csv(csv))
    assert list(d.columns) == HARMONIZED_COLUMNS
    assert len(d) == 3 and set(d.sensor) == {sensor}
    assert (d.date == pd.Timestamp("2026-10-04")).all()
    assert set(d.sat) <= {"A", "N", "N20"}          # the platform column, passed through


def test_a_real_modis_export_harmonizes_to_pinned_values():
    """The first real MODIS C6.1 row, harmonized by hand as the expectation.

    Pinned end-to-end: the timestamp build from `acq_date`+`acq_time`, the numeric
    confidence at the >= 30 floor, MODIS's 1 km nadir cell, and `sat` = platform `A`
    (Aqua) passing through untouched.
    """
    d = main.harmonize(main.read_firms_csv(REAL_FIRMS_MODIS_CSV))
    row = d.iloc[0]
    assert row.lat == pytest.approx(-13.60052) and row.lon == pytest.approx(49.60114)
    assert row.time == pd.Timestamp("2026-10-04 00:33:00")
    assert row.conf == 38.0 and row.frp == pytest.approx(8.77) and row.bt == pytest.approx(301.4)
    assert row.sensor == "MODIS" and row.sat == "A" and row.daynight == "N"
    assert row.scan == pytest.approx(1.43) and row.track == pytest.approx(1.18)
    assert row.esfp == pytest.approx(1.43 * 1.18)          # area / 1.0 km nadir cell
    assert row.pixel_km2 == pytest.approx(1.43 * 1.18)


def test_a_real_viirs_export_harmonizes_to_pinned_values():
    """The first real S-NPP row, harmonized by hand as the expectation.

    Two VIIRS facts are load-bearing here and pinned at once: the letter confidence
    (`nominal`) maps to 60 through `CONF_MAP`, and the 375 m nadir cell (0.140625 km²)
    sets the ESFP scale -- the platform column, `N` for Suomi NPP, is *not* the sensor.
    """
    d = main.harmonize(main.read_firms_csv(REAL_FIRMS_SNPP_CSV))
    row = d.iloc[0]
    assert row.time == pd.Timestamp("2026-10-04 00:01:00")   # acq_time "0001" = 1 minute
    assert row.conf == 60.0                                  # "nominal" -> CONF_MAP
    assert row.sensor == "VIIRS" and row.sat == "N"
    assert row.bt == pytest.approx(299.44) and row.frp == pytest.approx(0.68)
    assert row.pixel_km2 == pytest.approx(0.5 * 0.49)
    assert row.esfp == pytest.approx(0.5 * 0.49 / main.NADIR_KM2["VIIRS"])


def test_a_firms_schema_drift_fails_loudly_not_silently():
    """A renamed FIRMS column must raise, naming what it lost.

    This is what a future FIRMS change does to a quiet pipeline: rows arrive missing
    `acq_date`/`acq_time` and every one would be dropped with `lat`/`time` = NaT -- a
    wall of zeros, nobody wiser. `harmonize` refuses the frame instead.
    """
    drifted = REAL_FIRMS_MODIS_CSV.replace(b"acq_date", b"date").replace(b"acq_time", b"time")
    with pytest.raises(ValueError) as e:
        main.harmonize(main.read_firms_csv(drifted))
    assert "missing required columns" in str(e.value)
    assert "acq_date" in str(e.value) and "acq_time" in str(e.value)


def test_a_real_export_ingests_through_upload():
    """The real bytes go through the same `/upload` path the console drives.

    The store counts exactly the three MODIS rows, all one sensor, and the response's
    provenance block (`sensors`) says so -- the whole pipeline from bytes to calendar
    input, unchanged.
    """
    before_meta = client.get("/meta").json()
    before_n, before_sensors = before_meta["n"], before_meta["sensors"]
    csv = ("files", ("fire_nrt_M-C61_real.csv", io.BytesIO(REAL_FIRMS_MODIS_CSV), "text/csv"))
    r = client.post("/upload", files=[csv])
    assert r.status_code == 200, r.text
    assert r.json()["sensors"]["MODIS"] == before_sensors["MODIS"] + 3
    assert client.get("/meta").json()["n"] == before_n + 3


@pytest.fixture
def trained(tmp_path, monkeypatch):
    """A checkpoint built by the real pipeline from a tiny archive inside the demo box."""
    import forecast_model as fm
    import train

    archive = tmp_path / ".data"
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
    manifest = train.run(data_dir=archive, out=out, log=lambda *a: None)
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
    the blend being wired up rather than about a number moving. With a LightGBM checkpoint
    in `model/` the answer is that blend *plus* whatever days the model earned, so the name
    is asserted by what must be in it -- the archive prior -- not by where it starts.
    """
    main._invalidate()
    fc = client.get("/forecast", params={"bbox": "17.0,98.0,20.0,101.0"}).json()
    assert "archive prior" in fc["model"]
    assert all(r["method"] in ("lgbm", "prior") for r in fc["forecast"])
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
    # ...and with no checkpoint the endpoint answers exactly as it did before training existed.
    # The LightGBM model is a second forecast source, and on a machine that has trained it the
    # endpoint would answer with the days it earned -- so this test silences that loader too and
    # asserts the archive-prior path it is actually about (a CI checkout has neither checkpoint).
    monkeypatch.setattr(main.lgbm_forecast, "load", lambda *a, **k: None)
    main._invalidate()
    fc = client.get("/forecast").json()
    assert fc["model"].startswith("Seasonal climatology")


def test_forecast_has_no_nan_when_a_day_of_year_is_missing():
    """A record that wraps the year end never contains every day-of-year.

    Real FIRMS downloads are a rolling window (e.g. 2025-09-30 -> 2026-09-22), so the
    forecast horizon can start inside day-of-years the record simply has no rows for --
    the archive/NRT seam.  Reindexing the seasonal climatology there produced NaN values
    (and a NaN scale factor, poisoning the whole horizon).
    """
    saved = main.DF
    try:
        days = pd.date_range("2023-10-01", periods=200)   # wraps into 2024, so DOY 109+ is absent
        main.DF = pd.DataFrame({
            "lat": 10.0, "lon": 20.0, "time": days, "date": days.normalize(),
            "sensor": "VIIRS", "sat": "N20", "conf": 80.0, "frp": 10.0, "bt": 330.0,
            "scan": 0.5, "track": 0.5, "daynight": "N", "esfp": 0.444, "pixel_km2": 0.25})
        main._invalidate()
        fc = client.get("/forecast", params={"horizon": 30}).json()
        assert fc["model"] and len(fc["forecast"]) == 30
        counts = [f["count"] for f in fc["forecast"]]
        assert all(c == c and c >= 0 for c in counts), counts   # NaN != NaN
    finally:
        main.DF = saved
        main._invalidate()


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


def test_real_firms_instrument_labels_collapse_to_sensor_families():
    """Suomi-NPP downloads say instrument="SNPP" where NOAA-20/21 say "VIIRS".

    Both are the same 375 m sensor family, and the ESFP nadir / per-sensor rescaling /
    illusion diagnostic only know "MODIS" and "VIIRS".  A raw platform label used to leak
    through as a third sensor and then get normalised with the MODIS 1 km nadir, so these
    three real-world labels must land in exactly two buckets.
    """
    headers = ("latitude,longitude,acq_date,acq_time,confidence,frp,brightness,"
               "instrument,satellite\n")
    def one(fname, instrument, sat, lat):
        row = f"{lat},20.0,2022-05-05,1030,80,12.0,330,{instrument},{sat}\n".encode()
        return ("files", (fname, io.BytesIO(headers.encode() + row), "text/csv"))
    # One file per product, which is how FIRMS ships them.
    files = [one("snpp.csv", "SNPP", "SNPP", 10.0),
             one("n20.csv", "VIIRS", "N20", 10.1),
             one("modis.csv", "MODIS", "Terra", 10.2)]
    before = client.get("/meta").json()["sensors"]
    r = client.post("/upload", files=files)
    assert r.status_code == 200, r.text
    sensors = r.json()["sensors"]
    assert set(sensors) == {"MODIS", "VIIRS"}
    assert sensors["VIIRS"] == before["VIIRS"] + 2
    assert sensors["MODIS"] == before["MODIS"] + 1


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


def test_upload_reports_what_every_file_contributed():
    """PRD gap 8: a file whose rows all fail harmonization is named, not silently dropped.

    One good file beside one that harmonizes to nothing, against the dataset already on
    screen: the merge goes through and the response says, per file, what arrived and what
    did not. The old behaviour was a 200 that never mentioned the second file at all.
    """
    before = client.get("/meta").json()["n"]
    good = ("files", ("good.csv", io.BytesIO(
        b"latitude,longitude,acq_date,acq_time,confidence,frp,brightness\n"
        b"7.0,8.0,2022-04-04,1200,60,11.0,335\n"), "text/csv"))
    # Parses cleanly, but confidence 10 is under the floor: harmonize() drops the only row.
    quiet = ("files", ("lowconf.csv", io.BytesIO(
        b"latitude,longitude,acq_date,acq_time,confidence,frp,brightness\n"
        b"7.5,8.5,2022-04-04,1200,10,11.0,335\n"), "text/csv"))
    r = client.post("/upload", files=[good, quiet])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n"] == before + 1
    report = body["upload"]
    assert (report["accepted"], report["rejected"], report["rows"]) == (1, 1, 1)
    by_name = {f["file"]: f for f in report["files"]}
    assert by_name["good.csv"]["status"] == "accepted" and by_name["good.csv"]["rows"] == 1
    assert by_name["lowconf.csv"]["status"] == "rejected" and by_name["lowconf.csv"]["rows"] == 0
    assert "confidence" in by_name["lowconf.csv"]["reason"]
    # The report describes the response, not the dataset: a later /meta must not carry it.
    assert "upload" not in client.get("/meta").json()


def test_a_file_that_contributes_nothing_is_refused_not_ignored():
    """Against an existing dataset, an all-dropped file used to answer 200 and change nothing."""
    before = client.get("/meta").json()["n"]
    junk = ("files", ("nothing.csv", io.BytesIO(
        b"latitude,longitude,acq_date,acq_time,confidence,frp,brightness\n"
        b"9.0,9.0,2022-05-05,0100,5,1.0,300\n"), "text/csv"))
    r = client.post("/upload", files=[junk])
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "nothing.csv" in detail and "usable rows" in detail
    assert client.get("/meta").json()["n"] == before   # ...and the dataset really is untouched


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


# --------------------------------------------------------- the LightGBM forecaster
# `train_forecast.py` fits a global Tweedie booster on a 2-degree cell x day panel and
# `lgbm_forecast.py` serves it.  The archive is not in the repository, so these build a
# tiny panel in memory and push it through the *real* feature / fit / save / load path.

def _tiny_panel(seed=0):
    """A (dates x cells) harmonized-count panel with a learnable annual season."""
    import forecast_model as fm

    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-01", "2023-12-31")
    cells = np.array([fm.cell_bins([18.5], [99.5])[0], fm.cell_bins([-33.0], [147.0])[0]],
                     dtype="int64")
    doy = idx.dayofyear.to_numpy()
    base = 5.0 + 8.0 * np.exp(-((doy - 75) / 25) ** 2)
    vals = np.stack([base * (1.0 + 0.3 * rng.standard_normal(len(idx))) for _ in cells], axis=1)
    return pd.DataFrame(np.clip(vals, 0, None), index=idx, columns=cells)


def _tiny_detections(index, cells):
    """One harmonize-shaped detection per cell per day, so `main.DF` drives the endpoint."""
    import lgbm_forecast as lg

    la, lo = lg.cell_center(np.asarray(cells, dtype="int64"))
    rows = [{"lat": float(a), "lon": float(b), "time": d, "date": d.normalize(),
             "sensor": "VIIRS", "sat": "N20", "conf": 80.0, "frp": 10.0, "bt": 330.0,
             "scan": 0.5, "track": 0.5, "daynight": "N", "esfp": 0.444, "pixel_km2": 0.25}
            for d in index for a, b in zip(la, lo)]
    return pd.DataFrame(rows)


def test_a_record_shorter_than_the_longest_lag_says_so(tmp_path):
    """Seven days of real detections is the shape a bare FIRMS pull arrives in, and `lag_28`
    is undefined for the panel's first 28 days -- so that record has no training row at all.
    The failure has to name the archive, because the alternative is an internal
    "fit_model: no training rows" traceback that says nothing about what is wrong."""
    import train_forecast as tf

    header = "latitude,longitude,acq_date,acq_time,confidence,frp,brightness,satellite,instrument"
    rows = [header] + [f"18.5,99.5,2024-01-{day:02d},1015,80,9.5,320,NOAA-20,VIIRS"
                       for day in range(1, 8)]
    (tmp_path / "fire_nrt_M-C61_700001.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        tf.run(data_dir=tmp_path, out=tmp_path / "mdl", use_backtest=False,
               use_conformal=False, use_panel_cache=False, log=lambda *a: None)
    message = str(exit_info.value)
    assert "7 day(s)" in message and "28-day lag" in message and "fetch_archive.py" in message


def test_sensor_factors_are_the_one_harmonizer():
    """`harmonized_daily` and the cell-day panel must share exactly one rescale.

    The panel applies `main.sensor_factors()` per cell; if that ever drifted from the
    ratio `harmonized_daily` measures, the model would be fit on a different quantity
    from the one `/forecast` serves.
    """
    piv = pd.DataFrame({"MODIS": [10, 20, 30, 0, 5], "VIIRS": [40, 80, 120, 0, 20]},
                       index=pd.date_range("2020-01-01", periods=5))
    factors = main.sensor_factors(piv)
    adj = piv.astype(float).mul(pd.Series(factors), axis="columns").sum(axis=1)
    out = main.harmonized_daily(piv, pd.Series(0.0, index=piv.index))
    assert np.allclose(adj.values, out["count"].values)
    assert set(factors) == {"MODIS", "VIIRS"} and factors["MODIS"] == 1.0
    # one sensor is its own reference: no scaling, factor 1.0
    assert main.sensor_factors(piv[["MODIS"]]) == {"MODIS": 1.0}


def test_lgbm_features_use_only_past_and_training_years():
    """Lags come from before the origin and the climatology from training years only."""
    import lgbm_forecast as lg

    Y = _tiny_panel()
    T, C = Y.shape
    climo = lg.climo_table(Y, np.ones(T, dtype=bool))
    X, y, ok = lg.build_features(Y, climo)
    assert X.shape == (T * C, len(lg.FEATURES)) and len(y) == T * C
    # the longest lag defines the first row with every feature defined
    assert ok.sum() == (T - max(lg.LAGS)) * C
    i = lg.FEATURES.index("lag_1")
    assert np.isclose(X[100 * C, i], np.log1p(Y.iloc[99, 0]))   # yesterday, never today
    # drop a season from the climatology and its value at a DOY must move
    climo_wo = lg.climo_table(Y, Y.index.year.to_numpy() != 2023)
    assert not np.allclose(climo.to_numpy()[74], climo_wo.to_numpy()[74])


def test_lgbm_checkpoint_round_trip(tmp_path):
    """Fit, save, load, predict; the gate reads the stored backtest, not a live score."""
    import lgbm_forecast as lg
    import train_forecast as tf

    Y = _tiny_panel()
    climo = lg.climo_table(Y, None)
    booster, best, n = tf.fit_model(Y, climo, np.ones(len(Y), dtype=bool), rounds=40)
    assert best > 0 and n > 0
    meta = lg.save(booster, Y.columns.to_numpy(), climo, {"panel": {"seasons": [2021, 2022, 2023]}},
                   explicit=tmp_path)
    assert meta["schema"] == lg.SCHEMA and list(meta["features"]) == list(lg.FEATURES)
    lg.clear_cache()
    ck = lg.load(tmp_path)
    assert ck is not None and ck["metrics"]["schema"] == lg.SCHEMA
    assert list(ck["climo"].columns) == list(Y.columns)
    dates, totals = lg.predict_path(Y, ck["climo"], ck["booster"], 5)
    assert len(dates) == len(totals) == 5 and all(v >= 0 for v in totals)
    # the serving gate: strictly better MASE wins, a tie or a loss keeps the prior
    win = {"backtest": {"by_horizon": {"30": {"lgbm": 0.5, "prior": 0.9}}}}
    lose = {"backtest": {"by_horizon": {"30": {"lgbm": 1.5, "prior": 0.9}}}}
    tie = {"backtest": {"by_horizon": {"30": {"lgbm": 0.9, "prior": 0.9}}}}
    use, why = lg.gate(win, 30)
    assert use is True and "MASE" in why
    assert lg.gate(lose, 30)[0] is False and lg.gate(tie, 30)[0] is False
    assert lg.gate(win, 7)[0] is False            # an unscored horizon keeps the prior
    assert lg.gate(None, 30)[0] is False          # no checkpoint, no model
    # the gate must read what `backtest()` actually writes, not a second spelling of it;
    # a trainer-shaped row that won must be served (this is the round-trip that was broken)
    bt = tf.backtest(Y, horizons=(30,), origin_step=60, rounds=10, log=lambda *a: None)
    row = bt["by_horizon"]["30"]
    assert {"lgbm", "prior", "naive"} <= set(row)
    use, why = lg.gate({"backtest": bt}, 30)
    assert "incomplete" not in why
    assert use is (row["lgbm"] < row["prior"])
    # ...and the verdict is per day: a day is judged by the nearest measured horizon at least
    # as long as it, so a request can be part model and part prior rather than all of one.
    four = {"backtest": {"by_horizon": {
        "1": {"lgbm": 2.0, "prior": 1.0}, "7": {"lgbm": 0.5, "prior": 0.9},
        "14": {"lgbm": 0.6, "prior": 0.9}, "30": {"lgbm": 3.0, "prior": 1.0}}}}
    assert lg.earned_days(four, 30) == [False] + [True] * 13 + [False] * 16
    assert lg.earned_days(four, 5) == [False] + [True] * 4      # judged by the h=7 score
    assert lg.earned_days(four, 40) == lg.earned_days(four, 30) + [False] * 10   # no evidence past 30
    inside = {"backtest": {"by_horizon": {"7": {"lgbm": 0.5, "prior": 0.9}}}}
    assert lg.earned_days(inside, 10) == [True] * 7 + [False] * 3
    assert lg.earned_days(None, 3) == [False] * 3               # no checkpoint, no days
    lg.clear_cache()


def test_lgbm_broken_checkpoints_fall_back(tmp_path, monkeypatch):
    """Missing, truncated and foreign-schema checkpoints are no checkpoint, not a 500."""
    import json
    import lgbm_forecast as lg
    import train_forecast as tf

    assert lg.load(tmp_path) is None              # missing
    Y = _tiny_panel()
    climo = lg.climo_table(Y, None)
    booster, _, _ = tf.fit_model(Y, climo, np.ones(len(Y), dtype=bool), rounds=20)
    lg.save(booster, Y.columns.to_numpy(), climo, {}, explicit=tmp_path)
    bpath, _, mpath = lg.paths(tmp_path)
    good = bpath.read_text(encoding="utf-8")
    bpath.write_text(good[: max(1, len(good) // 2)], encoding="utf-8")   # truncated booster
    lg.clear_cache()
    assert lg.load(tmp_path) is None
    bpath.write_text(good, encoding="utf-8")
    mpath.write_text(json.dumps({"schema": 99, "features": list(lg.FEATURES)}), encoding="utf-8")
    lg.clear_cache()
    assert lg.load(tmp_path) is None              # foreign schema
    mpath.write_text(json.dumps({"schema": lg.SCHEMA, "features": ["doy_sin"]}), encoding="utf-8")
    lg.clear_cache()
    assert lg.load(tmp_path) is None              # our schema, a different feature set
    # and the endpoint still answers with the seasonal prior, whatever the checkpoint said
    monkeypatch.setattr(main.lgbm_forecast, "load", lambda *a, **k: None)
    main._invalidate()
    fc = client.get("/forecast").json()
    assert fc["method"] == "prior" and fc["forecast"] and fc["model"].startswith("Seasonal climatology")


def test_lgbm_validation_never_splits_randomly():
    """The validation code holds out whole seasons and blocks of ground, in order."""
    import train_forecast as tf

    src = Path(main.__file__).resolve().parent / "train_forecast.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    banned = {"train_test_split", "shuffle", "random_state", "ShuffleSplit", "KFold", "sample"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            assert ast.unparse(node.func).split(".")[-1] not in banned, ast.unparse(node.func)
        if isinstance(node, ast.keyword):
            assert node.arg not in {"shuffle", "random_state"}, node.arg
    Y = _tiny_panel()
    seen = np.zeros(len(Y), dtype=int)
    folds = tf.time_folds(Y)
    assert len(folds) == 3
    for _, tr, te in folds:
        tr, te = np.asarray(tr), np.asarray(te)
        assert not (tr & te).any() and tr.any() and te.any()
        seen += te.astype(int)
    assert (seen == 1).all()                      # every day held out exactly once
    blocks, kind = tf.spatial_folds(Y)
    assert kind in ("curated regions", "coarse tiles")
    for _, tr, te in blocks:
        assert not (np.asarray(tr) & np.asarray(te)).any()


def test_lightgbm_is_imported_lazily():
    """Neither the server nor the trainer may import lightgbm at module scope.

    Start-up is ~2 s and the model is only needed once a forecast is actually fitted from
    the checkpoint.  A module-scope import would tax every launch and every test.
    """
    backend = Path(main.__file__).resolve().parent
    for name in ("main.py", "lgbm_forecast.py", "train_forecast.py"):
        tree = ast.parse((backend / name).read_text(encoding="utf-8"))
        for node in tree.body:                    # module scope only
            if isinstance(node, ast.Import):
                assert all(a.name.split(".")[0] != "lightgbm" for a in node.names), name
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != "lightgbm", name
    out = subprocess.run([sys.executable, "-c",
                          "import sys,os;sys.path.insert(0,os.getcwd());import main;"
                          "print('lightgbm' in sys.modules)"],
                         cwd=backend, capture_output=True, text=True)
    assert out.stdout.strip() == "False", out.stderr


def test_forecast_contract_is_backward_compatible():
    """`/forecast` still answers {model, forecast[]}; the new keys are additive only."""
    main._invalidate()
    r = client.get("/forecast")
    assert r.status_code == 200
    fc = r.json()
    assert {"model", "forecast"} <= set(fc)
    assert len(fc["forecast"]) == 30
    for row in fc["forecast"]:
        assert set(row) >= {"date", "count"} and row["count"] >= 0
    # `blend` is the additive third value: some days earned by the model, the rest the prior
    assert fc["method"] in ("lgbm", "prior", "blend")
    assert all(r.get("method") in ("lgbm", "prior") for r in fc["forecast"])


def test_lgbm_is_served_when_it_earns_the_horizon(monkeypatch):
    """When the stored backtest says LightGBM wins a horizon and the AOI holds cells it
    trained on, `/forecast` serves it -- the gate is not decoration. And when it wins only
    some horizons, the response is part model, part prior: the earned days are served and
    the rest fall back, so one verdict never decides the whole request."""
    import lgbm_forecast as lg
    import train_forecast as tf

    Y = _tiny_panel()
    climo = lg.climo_table(Y, None)
    booster, _, _ = tf.fit_model(Y, climo, np.ones(len(Y), dtype=bool), rounds=30)
    ck = {"booster": booster, "climo": climo,
          "metrics": {"generated": "test", "panel": {"seasons": [2021, 2022, 2023]},
                      "backtest": {"by_horizon": {"30": {"lgbm": 0.1, "prior": 0.9}}}}}
    monkeypatch.setattr(main.lgbm_forecast, "load", lambda *a, **k: ck)
    saved = main.DF
    try:
        main.DF = _tiny_detections(Y.index, Y.columns)
        main._invalidate()
        fc = client.get("/forecast", params={"horizon": 30}).json()
        assert fc["method"] == "lgbm" and "LightGBM" in fc["model"]
        assert len(fc["forecast"]) == 30 and all(f["count"] >= 0 for f in fc["forecast"])
        assert fc["checkpoint"]["matched_cells"] >= 1
        assert fc["checkpoint"]["days"] == list(range(1, 31))   # every day earned

        # The mixed case: wins at 7 and 14, loses at 1 and 30 -- days 2-14 are the model's,
        # day 1 and 15-30 are the prior's, and every row says which one drew it.
        ck["metrics"] = {"generated": "test", "panel": {"seasons": [2021, 2022, 2023]},
                         "backtest": {"by_horizon": {
                             "1": {"lgbm": 2.0, "prior": 1.0},
                             "7": {"lgbm": 0.5, "prior": 0.9},
                             "14": {"lgbm": 0.6, "prior": 0.9},
                             "30": {"lgbm": 3.0, "prior": 1.0}}}}
        main._invalidate()
        fc = client.get("/forecast", params={"horizon": 30}).json()
        assert fc["method"] == "blend" and "LightGBM" in fc["model"] and "prior" in fc["model"].lower()
        assert len(fc["forecast"]) == 30
        kinds = [r["method"] for r in fc["forecast"]]
        assert kinds == ["prior"] + ["lgbm"] * 13 + ["prior"] * 16
        assert fc["checkpoint"]["days"] == list(range(2, 15))
        assert [r["date"] for r in fc["forecast"]] == sorted(r["date"] for r in fc["forecast"])
    finally:
        main.DF = saved
        main._invalidate()


def test_lgbm_falls_back_when_the_frame_has_no_trained_cells(monkeypatch):
    """A global model has nothing to say about ground it never saw: fall back, don't guess."""
    import forecast_model as fm
    import lgbm_forecast as lg

    Y = _tiny_panel()
    climo = lg.climo_table(Y, None)
    ck = {"booster": object(), "climo": climo,
          "metrics": {"backtest": {"by_horizon": {"30": {"lgbm": 0.1, "prior": 0.9}}}}}
    monkeypatch.setattr(main.lgbm_forecast, "load", lambda *a, **k: ck)
    saved = main.DF
    try:
        far = np.array([fm.cell_bins([-9.5], [-58.5])[0]], dtype="int64")   # the Amazon
        main.DF = _tiny_detections(Y.index, far)
        main._invalidate()
        fc = client.get("/forecast", params={"horizon": 30}).json()
        assert fc["method"] == "prior" and "LightGBM" not in (fc["model"] or "")
    finally:
        main.DF = saved
        main._invalidate()


def _tiny_uncertainty_panel(seed=0, days=600):
    """A contiguous daily panel long enough for a train / calibration / test cut."""
    import forecast_model as fm

    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", periods=days)
    cells = np.array([fm.cell_bins([18.5], [99.5])[0], fm.cell_bins([-33.0], [147.0])[0]],
                     dtype="int64")
    doy = idx.dayofyear.to_numpy()
    base = 6.0 + 9.0 * np.exp(-((doy - 75) / 25) ** 2)
    vals = np.stack([base * (1.0 + 0.4 * rng.standard_normal(len(idx))) for _ in cells], axis=1)
    return pd.DataFrame(np.clip(vals, 0, None), index=idx, columns=cells)


def test_conformal_band_is_bounded_and_reuses_the_widest_width():
    """The band is relative (log1p), never negative, contains the point, and does not invent
    a width for a horizon it was never calibrated at."""
    import lgbm_forecast as lg
    import train_forecast as tf

    cf = {"nominal": 0.9, "quantiles": {"1": 0.2, "7": 0.5}}
    totals = [0.0, 10.0, 100.0]
    lo, hi = lg.band(totals, cf, 3)
    assert lo is not None and len(lo) == len(hi) == 3
    assert all(a >= 0 for a in lo)
    assert all(a <= c <= b for a, c, b in zip(lo, totals, hi))
    # past the calibrated window the widest width is reused rather than extrapolated
    assert lg.half_widths(cf, 3)[2] == cf["quantiles"]["7"]
    assert lg.band(totals, None, 3) == (None, None)          # no calibration, no band
    # the split-conformal quantile is the rank-corrected order statistic, not numpy's quantile
    assert tf._split_conformal_quantile([1, 2, 3, 4], 0.25) == 4.0
    # and the coverage verdict flags a band more than a few points off nominal
    ok = lg.coverage({"nominal": 0.9, "coverage": {"empirical": {"1": 0.88, "30": 0.92}}})
    bad = lg.coverage({"nominal": 0.9, "coverage": {"empirical": {"1": 0.9, "30": 0.74}}})
    assert ok["within_tolerance"] is True and bad["within_tolerance"] is False
    assert lg.coverage(None) is None


def test_conformal_calibrates_on_a_later_block_than_training():
    """Train / calibration / test are consecutive, ordered blocks -- the band is calibrated on
    a block strictly later than training and scored on one strictly later than calibration."""
    import train_forecast as tf

    Y = _tiny_uncertainty_panel()
    cf = tf.conformal_calibration(Y, alpha=0.1, horizon_max=7, cal_days=90, test_days=90,
                                  origin_step=5, rounds=40, log=lambda *a: None)
    assert cf["applicable"] is True and cf["nominal"] == 0.9
    tr, cal, te = cf["blocks"]["train"], cf["blocks"]["calibration"], cf["blocks"]["test"]
    assert tr[1] < cal[0] and cal[1] < te[0]                 # no overlap, no random split
    assert set(cf["quantiles"]) == {str(h) for h in range(1, 8)}
    assert all(q >= 0 for q in cf["quantiles"].values())
    assert all(0.0 <= v <= 1.0 for v in cf["coverage"]["empirical"].values())
    assert isinstance(cf["within_tolerance"], bool)
    assert "in-repo" in cf["method"]                        # no MAPIE dependency


def test_conformal_is_not_applicable_on_a_short_record():
    """A record too short for three consecutive blocks says so instead of scoring a fold."""
    import train_forecast as tf

    cf = tf.conformal_calibration(_tiny_uncertainty_panel(days=200), rounds=20,
                                  log=lambda *a: None)
    assert cf["applicable"] is False and "note" in cf and cf["note"]


def test_forecast_rows_carry_a_band_only_when_calibrated(monkeypatch):
    """The band is additive and honest: absent without a calibration, present and containing
    the point forecast when the checkpoint was calibrated."""
    import lgbm_forecast as lg
    import train_forecast as tf

    Y = _tiny_panel()
    climo = lg.climo_table(Y, None)
    booster, _, _ = tf.fit_model(Y, climo, np.ones(len(Y), dtype=bool), rounds=30)
    base_metrics = {"backtest": {"by_horizon": {"30": {"lgbm": 0.1, "prior": 0.9}}}}
    saved = main.DF
    try:
        main.DF = _tiny_detections(Y.index, Y.columns)
        monkeypatch.setattr(main.lgbm_forecast, "load",
                            lambda *a, **k: {"booster": booster, "climo": climo, "metrics": base_metrics})
        main._invalidate()
        fc = client.get("/forecast", params={"horizon": 30}).json()
        assert fc["method"] == "lgbm"
        assert "lower" not in fc["forecast"][0] and "coverage" not in fc

        metrics = dict(base_metrics, conformal={
            "nominal": 0.9, "quantiles": {"1": 0.3, "30": 0.9},
            "coverage": {"empirical": {"1": 0.9, "30": 0.88}}})
        monkeypatch.setattr(main.lgbm_forecast, "load",
                            lambda *a, **k: {"booster": booster, "climo": climo, "metrics": metrics})
        main._invalidate()
        fc = client.get("/forecast", params={"horizon": 30}).json()
        assert fc["coverage"]["nominal"] == 0.9 and fc["coverage"]["within_tolerance"] is True
        for row in fc["forecast"]:
            assert row["lower"] >= 0 and row["lower"] <= row["count"] <= row["upper"]
    finally:
        main.DF = saved
        main._invalidate()
