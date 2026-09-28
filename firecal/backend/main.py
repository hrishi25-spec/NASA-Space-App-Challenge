"""Burning Activity Calendar / Pyro-Harmony API.

Harmonizes FIRMS MODIS + VIIRS CSVs and serves the four poster pillars:
  1. Multi-decadal burning-activity calendar    -> /climatology
  2. "Sensor Transition Illusion" diagnostic    -> /diagnostic
  3. Geospatial hotspot clustering + live feed  -> /live
  4. Incident Commander wildfire briefing       -> /briefing
plus the original calendar / map / anomaly / forecast endpoints.
"""
import io
import math
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import numpy as np
import pandas as pd
import requests
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from scipy.spatial import ConvexHull
from sklearn.cluster import DBSCAN, KMeans

from demo import make_demo, make_transition_demo

MAX_FILE_BYTES = 200 * 1024 * 1024  # per uploaded CSV
MAX_ROWS = 2_000_000                # in-memory safety cap
LIVE_MAX_ROWS = 200_000             # safety cap for one live ingest

app = FastAPI(title="Pyro-Harmony — Burning Activity Calendar")
app.add_middleware(CORSMiddleware,
                   allow_origins=[o.strip() for o in os.environ.get("ALLOW_ORIGINS", "*").split(",") if o.strip()],
                   allow_methods=["*"], allow_headers=["*"])
DF = pd.DataFrame()
CONF_MAP = {"l": 20, "low": 20, "n": 60, "nominal": 60, "h": 90, "high": 90}
REQUIRED = {"latitude", "longitude", "acq_date", "acq_time"}

# Live NASA FIRMS open NRT feeds (public, no key needed) — poster pillar 3.
FIRMS_24H = ("https://firms.modaps.eosdis.nasa.gov/data/active_fire/")
LIVE_FEEDS = {
    "MODIS_C6.1": FIRMS_24H + "modis-c6.1/csv/MODIS_C6_1_{region}_24h.csv",
    "VIIRS_S-NPP": FIRMS_24H + "suomi-viirs-c2/csv/SUOMI_VIIRS_C2_{region}_24h.csv",
    "VIIRS_NOAA-20": FIRMS_24H + "noaa-20-viirs-c2/csv/J1_VIIRS_C2_{region}_24h.csv",
    "VIIRS_NOAA-21": FIRMS_24H + "noaa-20-viirs-c2/csv/J2_VIIRS_C2_{region}_24h.csv",
}
LIVE_REGIONS = ["Global", "South_East_Asia", "South_America", "North_and_Central_America",
                "Africa", "Europe", "Northern_and_Central_Australia", "South_Asia"]
LIVE_USER_AGENT = {"User-Agent": "pyro-harmony/1.0 (NASA Space Apps 2026 prototype)"}


# ---------------------------------------------------------------- harmonization
def _esfp(scan, track, sensor):
    """Equivalent Standard Fire Pixels (nadir-normalized expansion ratio)
    and the physical footprint area (km²) of each detection.

    FIRMS reports the instantaneous footprint extent per detection via the
    `scan` / `track` columns (already in km).  Normalizing by each sensor's
    nadir cell (MODIS 1x1 km, VIIRS 0.75x0.75 km) yields the expansion ratio
    A(theta): up to ~10x for MODIS at scan edge vs ~2-3x for VIIRS — the
    pixel-growth effect behind the Sensor Transition Illusion.
    """
    sensor = str(sensor).upper()
    area_km2 = scan.clip(0.1, 20) * track.clip(0.1, 20)
    nadir = 0.5625 if sensor == "VIIRS" else 1.0
    return area_km2 / nadir, area_km2


def harmonize(raw: pd.DataFrame) -> pd.DataFrame:
    d = raw.copy(); d.columns = [c.strip().lower() for c in d.columns]
    missing = REQUIRED - set(d.columns)
    if missing:
        raise ValueError(f"missing required columns: {', '.join(sorted(missing))}")
    viirs = "bright_ti4" in d.columns
    sensor = "VIIRS" if viirs else "MODIS"
    if "instrument" in d.columns and d["instrument"].notna().any():
        sensor = str(d["instrument"].dropna().iloc[0]).upper()
    # numeric confidence if parseable (MODIS 0-100), else l/n/h map (VIIRS); unknown -> dropped
    conf = pd.to_numeric(d["confidence"], errors="coerce")
    if conf.isna().any():
        conf = conf.fillna(d["confidence"].astype(str).str.strip().str.lower().map(CONF_MAP))
    at = pd.to_numeric(d["acq_time"], errors="coerce")  # "HHMM", 1345.0, or missing -> NaT below
    t = pd.to_datetime(d["acq_date"], errors="coerce") + pd.to_timedelta(at // 100, unit="h") + pd.to_timedelta(at % 100, unit="m")
    scan_raw = d["scan"] if "scan" in d.columns else pd.Series(np.nan, index=d.index)
    track_raw = d["track"] if "track" in d.columns else pd.Series(np.nan, index=d.index)
    scan = pd.to_numeric(scan_raw, errors="coerce").fillna(1.0)
    track = pd.to_numeric(track_raw, errors="coerce").fillna(1.0)
    esfp, area = _esfp(scan, track, sensor)
    out = pd.DataFrame({
        "lat": pd.to_numeric(d["latitude"], errors="coerce"),
        "lon": pd.to_numeric(d["longitude"], errors="coerce"),
        "time": t, "date": t.dt.normalize(),
        "sensor": sensor, "sat": d.get("satellite", pd.Series(sensor, index=d.index)).astype(str),
        "conf": conf, "frp": pd.to_numeric(d.get("frp", 0), errors="coerce").fillna(0),
        "bt": d["bright_ti4"] if viirs else d["brightness"],
        "scan": scan.clip(0.1, 20), "track": track.clip(0.1, 20),
        "daynight": d.get("daynight", pd.Series(0, index=d.index)),
        "esfp": esfp, "pixel_km2": area})
    out = out.dropna(subset=["lat", "lon", "time", "conf", "bt"])
    out = out[out.lat.between(-90, 90) & out.lon.between(-180, 180)]
    return out[out.conf >= 30]  # drop low-confidence detections for all sensors


@app.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    global DF
    if not files:
        raise HTTPException(400, "No files uploaded")
    parts = [DF] if len(DF) else []
    for f in files:
        blob = await f.read()
        if (f.filename or "") == "demo_transition.csv":  # poster: 2002-2024 illusion scenario
            parts += _transition_frames()
            continue
        if len(blob) > MAX_FILE_BYTES:
            raise HTTPException(400, f"{f.filename}: file exceeds {MAX_FILE_BYTES // (1024 * 1024)} MB limit")
        try:
            raw = pd.read_csv(io.BytesIO(blob))
        except Exception as e:
            raise HTTPException(400, f"{f.filename}: not a readable CSV ({e})")
        try:
            h = harmonize(raw)
        except ValueError as e:
            raise HTTPException(400, f"{f.filename}: {e}")
        if not h.empty:
            parts.append(h)
    if not parts:
        raise HTTPException(400, "No usable rows found: need FIRMS-style CSVs with "
                                 "latitude/longitude/acq_date/acq_time and confidence >= 30")
    DF = pd.concat(parts).drop_duplicates(["lat", "lon", "time", "sensor"]).reset_index(drop=True)
    if len(DF) > MAX_ROWS:
        DF = DF.tail(MAX_ROWS).reset_index(drop=True)
    return meta()


@app.post("/demo")
def demo(mode: str = "standard"):
    global DF
    frames = _transition_frames() if mode == "transition" else [harmonize(x) for x in make_demo()]
    DF = pd.concat(frames).reset_index(drop=True)
    return meta()


_TRANSITION_CACHE = None


def _transition_frames():
    """Generate + harmonize the 2002-2024 illusion dataset once (it is heavy)."""
    global _TRANSITION_CACHE
    if _TRANSITION_CACHE is None:
        _TRANSITION_CACHE = [harmonize(x) for x in make_transition_demo()]
    return _TRANSITION_CACHE


@app.delete("/data")
def clear():
    global DF; DF = pd.DataFrame(); return meta()


@app.get("/meta")
def meta():
    if DF.empty: return {"n": 0}
    return {"n": len(DF), "start": str(DF.date.min().date()), "end": str(DF.date.max().date()),
            "sensors": DF.groupby("sensor").size().to_dict(),
            "bounds": [DF.lat.min(), DF.lon.min(), DF.lat.max(), DF.lon.max()],
            "hfi": round(float(DF.frp.mul(DF.esfp).sum()), 1),
            "esfp": round(float(DF.esfp.sum()), 1),
            "pixels": int(len(DF))}


def parse_bbox(bbox):
    if not bbox: return None
    try:
        a, b, c, e = [float(x) for x in bbox.split(",")]  # minlat,minlon,maxlat,maxlon
    except ValueError:
        raise HTTPException(400, "bbox must be minlat,minlon,maxlat,maxlon (numbers)")
    if not (-90 <= a <= 90 and -90 <= c <= 90 and -180 <= b <= 180 and -180 <= e <= 180):
        raise HTTPException(400, "bbox coordinates out of range")
    return min(a, c), min(b, e), max(a, c), max(b, e)


def subset(bbox, start=None, end=None):
    d = DF
    box = parse_bbox(bbox)
    if box:
        a, b, c, e = box
        d = d[(d.lat >= a) & (d.lat <= c) & (d.lon >= b) & (d.lon <= e)]
    if start: d = d[d.date >= start]
    if end: d = d[d.date <= end]
    return d


def daily(d):
    """Daily counts; sensors rescaled to the best-covered sensor over their overlap period."""
    if d.empty: return pd.DataFrame(columns=["count", "raw", "frp"])
    piv = d.groupby(["date", "sensor"]).size().unstack(fill_value=0)
    ref = (piv > 0).sum().idxmax(); adj = piv.astype(float)
    for s in piv.columns:
        if s == ref: continue
        ov = (piv[ref] > 0) & (piv[s] > 0)
        if ov.sum() >= 5: adj[s] = piv[s] * piv.loc[ov, ref].sum() / piv.loc[ov, s].sum()
    out = pd.DataFrame({"count": adj.sum(axis=1), "raw": piv.sum(axis=1), "frp": d.groupby("date").frp.sum()})
    return out.reindex(pd.date_range(out.index.min(), out.index.max()), fill_value=0)


@app.get("/calendar")
def calendar(bbox: str = None, start: str = None, end: str = None):
    s = daily(subset(bbox, start, end))
    return [{"date": str(i.date()), "count": round(r["count"], 1), "raw": int(r["raw"]), "frp": round(r["frp"], 1)} for i, r in s.iterrows()]


@app.get("/points")
def points(bbox: str = None, start: str = None, end: str = None, limit: int = 6000):
    d = subset(bbox, start, end)
    limit = min(max(limit, 1), 20000)
    if len(d) > limit: d = d.sample(limit, random_state=0)
    return d[["lat", "lon", "frp", "sensor"]].round(4).to_dict("records")


@app.get("/clusters")
def clusters(bbox: str = None, start: str = None, end: str = None, eps: float = 550, min_pts: int = 3, hours: float = 12):
    eps = min(max(eps, 10), 5000); min_pts = min(max(min_pts, 1), 100); hours = min(max(hours, 0.5), 720)
    return _cluster_payload(subset(bbox, start, end), eps, min_pts, hours)


def _cluster_payload(d, eps, min_pts, hours):
    if len(d) < min_pts: return []
    d = d.head(60000)
    lat0 = np.deg2rad(d.lat.mean())
    X = np.c_[(d.lon.values * 111320 * np.cos(lat0)), d.lat.values * 110540,
              (d.time.astype("int64").values / 3.6e12) / hours * eps]  # time scaled so `hours` ~ eps metres
    lab = DBSCAN(eps=eps, min_samples=min_pts).fit_predict(X)
    d = d.assign(c=lab); d = d[d.c >= 0]; res = []
    for cid, g in d.groupby("c"):
        pts = g[["lat", "lon"]].values
        try: hull = pts[ConvexHull(pts).vertices].tolist()
        except Exception: hull = pts.tolist()
        res.append({"id": int(cid), "n": len(g), "frp": round(g.frp.sum(), 1), "lat": g.lat.mean(), "lon": g.lon.mean(),
                    "start": str(g.time.min()), "end": str(g.time.max()), "hull": hull,
                    "sensors": sorted(set(g.sensor)), "duration_h": round((g.time.max() - g.time.min()).total_seconds() / 3600, 1)})
    return sorted(res, key=lambda r: -r["n"])[:300]


# ------------------------------------------- 1. multi-decadal DOY climatology
def _doy_matrix(s):
    return {int(d): [None if pd.isna(v) else round(float(v), 2) for v in vals]
            for d, vals in s.groupby(s.index.dayofyear)}


@app.get("/climatology")
def climatology(bbox: str = None, window: int = 15, step: int = 5):
    """Day-of-Year climatology + percentile envelope (poster pillar 1)."""
    window = min(max(window, 3), 45); step = min(max(step, 1), 30)
    s = daily(subset(bbox))["count"]
    if len(s) < 60:
        return {"years": {}, "doy": {}, "envelope": [], "summary": None, "note": "Need at least ~60 days of data"}
    years = {int(y): [None if pd.isna(v) else round(float(v), 2) for v in g]
             for y, g in s.groupby(s.index.year)}
    qs = s.rolling(window, center=True, min_periods=3).quantile
    env = pd.DataFrame({"p10": qs(0.10), "p50": qs(0.50), "p90": qs(0.90), "p95": qs(0.95)}, index=s.index)
    doy = env.groupby(env.index.dayofyear).mean()
    picks = list(range(1, 366, step)) or [1]
    envelope = [{"doy": int(d),
                 "p10": round(doy.p10.get(d, float("nan")), 2), "p50": round(doy.p50.get(d, float("nan")), 2),
                 "p90": round(doy.p90.get(d, float("nan")), 2), "p95": round(doy.p95.get(d, float("nan")), 2)}
                for d in picks if not pd.isna(doy.p50.get(d, float("nan")))]
    p95 = s.rolling(window, center=True, min_periods=3).quantile(0.95)
    doy95 = p95.groupby(p95.index.dayofyear).mean()
    peak_doy = int(doy95.idxmax()) if len(doy95) else None
    onset = next((int(d) for d in range(1, 366) if (doy95.get(d, 0) or 0) >= 0.5 * (doy95.max() or 0)), None)
    cess = next((int(d) for d in range(365, 0, -1) if (doy95.get(d, 0) or 0) >= 0.5 * (doy95.max() or 0)), None)
    summary = {"peak_doy": peak_doy, "peak_p95": round(float(doy95.max()), 2) if len(doy95) else None,
               "onset_doy": onset, "cessation_doy": cess,
               "median_daily": round(float(s.median()), 2),
               "max_mean_doy": int(s.groupby(s.index.dayofyear).mean().idxmax()) if len(s) else None}
    return {"years": years, "doy": _doy_matrix(s), "envelope": envelope, "summary": summary}


# --------------------------------------- 2. the "Sensor Transition Illusion"
@app.get("/diagnostic")
def diagnostic(bbox: str = None):
    """Unmask the post-2012 VIIRS deployment artifact (poster pillar 2)."""
    d = subset(bbox)
    if d.empty:
        return {"series": [], "note": "No data loaded"}
    per = daily(d)["count"]
    raw = d.groupby([d.date.dt.year, "sensor"]).size().unstack(fill_value=0)
    for c in ("MODIS", "VIIRS"):
        if c not in raw: raw[c] = 0
    adj = per.groupby(per.index.year).sum()
    series = [{"year": int(y),
               "modis": int(raw.MODIS.get(y, 0)), "viirs": int(raw.VIIRS.get(y, 0)),
               "raw_total": int(raw.MODIS.get(y, 0) + raw.VIIRS.get(y, 0)),
               "adjusted": round(float(adj.get(y, 0.0)), 1)} for y in sorted(set(raw.index) | set(adj.index))]
    pre = d[d.date.dt.year < 2012]
    post = d[(d.date.dt.year >= 2012) & (d.date.dt.year <= 2015)]
    cal = {}
    if not pre.empty and not post.empty:
        # Both sensors in the overlap window (VIIRS era); pre-2012 has MODIS only.
        cal_d = pd.concat([pre, post])
        cm, cv = cal_d[cal_d.sensor == "MODIS"], cal_d[cal_d.sensor == "VIIRS"]
        if len(cm) and len(cv):
            a = float(cv.frp.sum() / max(len(cv), 1) / max(cm.frp.sum() / max(len(cm), 1), 1e-9))
            b = float(cv.esfp.mean() / max(cm.esfp.mean(), 1e-9))
            pair = pd.DataFrame({"m": cm.groupby("date").size(), "v": cv.groupby("date").size()}).dropna()
            if len(pair) >= 10 and pair.v.var() > 0:
                r2 = float(np.corrcoef(pair.m, pair.v)[0, 1] ** 2)
                if not np.isfinite(r2): r2 = None
                k = float(pair.m.sum() / max(pair.v.sum(), 1))
                rmse = float(np.sqrt(((pair.m - k * pair.v) ** 2).mean()))
            else:
                r2, rmse, k = None, None, None
            cal = {"matched_fires": int(min(len(cm), len(cv))), "frp_ratio_viirs_to_modis": round(a, 3),
                   "esfp_ratio_viirs_to_modis": round(b, 3), "r2": None if r2 is None else round(r2, 3),
                   "rmse_mw": None if rmse is None else round(rmse, 2), "daily_count_ratio": None if k is None else round(k, 3)}
        else:
            cal = {}
    pre_n = int((d.date.dt.year < 2012).sum()); post_n = int(((d.date.dt.year >= 2012) & (d.date.dt.year <= 2015)).sum())
    pre_s = per[per.index.year < 2012]
    post_s = per[(per.index.year >= 2012) & (per.index.year <= 2015)]
    pre_c = float(pre_s.mean()) if len(pre_s) else 0.0
    post_c = float(post_s.mean()) if len(post_s) else 0.0
    pre_frp = float(pre.frp.mean()) if len(pre) else 0.0
    post_frp = float(post.frp.mean()) if len(post) else 0.0
    growth = round((post_c / pre_c - 1) * 100, 1) if pre_c > 0 else None
    m_last = d[(d.sensor == "MODIS") & (d.date.dt.year < 2012)]
    v_first = d[(d.sensor == "VIIRS") & (d.date.dt.year >= 2012) & (d.date.dt.year <= 2015)]
    if not m_last.empty and not v_first.empty:
        yl = m_last[m_last.date.dt.year == m_last.date.dt.year.max()]
        scale = float(v_first.frp.mean() / max(yl.frp.mean(), 1e-9)) * float(v_first.esfp.mean() / max(m_last.esfp.mean(), 1e-9))
        adj_growth = round((post_c / (pre_c * scale) - 1) * 100, 1) if pre_c > 0 else None
    else:
        scale, adj_growth = None, None
    return {"series": series, "observed_growth_pct": growth, "adjusted_growth_pct": adj_growth,
            "viirs_scaling": None if scale is None else round(scale, 3),
            "artifact_pct": None if (growth is None or adj_growth is None) else round(growth - adj_growth, 1),
            "calibration": cal or None,
            "stats": {"hfi": round(float(d.frp.mul(d.esfp).sum()), 1),
                      "esfp": round(float(d.esfp.sum()), 1), "pixels": int(len(d))},
            "pre_2012_days": pre_n, "post_2012_days": post_n,
            "pre_mean_daily": round(pre_c, 2), "post_mean_daily": round(post_c, 2),
            "pre_mean_frp": round(pre_frp, 2), "post_mean_frp": round(post_frp, 2)}


# --------------------------------- 3. live NASA FIRMS feeds + on-the-fly clustering
def _fetch_feed(url, timeout=90):
    r = requests.get(url, headers=LIVE_USER_AGENT, timeout=timeout)
    if r.status_code != 200 or len(r.content) < 80:
        raise RuntimeError(f"HTTP {r.status_code}")
    df = pd.read_csv(io.BytesIO(r.content))
    if "latitude" not in df.columns:
        raise RuntimeError("unrecognized CSV layout")
    return df


@app.get("/live")
def live(region: str = "Global", bbox: str = None, eps: float = 550, min_pts: int = 3,
         hours: float = 12, crop: bool = False):
    """Pull 24h global FIRMS CSVs, harmonize on the fly, cluster, and return them."""
    eps = min(max(eps, 50), 10000); min_pts = min(max(min_pts, 1), 100); hours = min(max(hours, 0.5), 48)
    parts, feeds, errors = [], [], []

    def fetch_one(item):
        name, tpl = item
        try:
            h = harmonize(_fetch_feed(tpl.format(region=region)))
            box = parse_bbox(bbox) if crop else None
            if box:
                a, b, c, e = box
                h = h[(h.lat >= a) & (h.lat <= c) & (h.lon >= b) & (h.lon <= e)]
            return name, h, None
        except Exception as e:
            return name, None, f"{name}: {e}"

    with ThreadPoolExecutor(max_workers=4) as ex:   # feeds download in parallel
        for name, h, e in ex.map(fetch_one, LIVE_FEEDS.items()):
            if e:
                errors.append(e)
            else:
                feeds.append(name)
                if len(h):
                    parts.append(h)
            if sum(len(p) for p in parts) > LIVE_MAX_ROWS:
                break
    if not parts:
        raise HTTPException(502, "No FIRMS feeds reachable: " + ("; ".join(errors) or "unknown error"))
    d = pd.concat(parts).drop_duplicates(["lat", "lon", "time", "sensor"]).reset_index(drop=True)
    cl = _cluster_payload(d, eps, min_pts, hours)
    by_sensor = d.groupby("sensor").size().to_dict()
    return {"feeds": feeds, "errors": errors, "region": region, "n": len(d),
            "sensors": {k: int(v) for k, v in by_sensor.items()},
            "hfi": round(float(d.frp.mul(d.esfp).sum()), 1),
            "rows": d[["lat", "lon", "frp", "sensor", "conf", "time"]].head(15000)
                    .assign(time=lambda x: x.time.astype(str)).round(4).to_dict("records"),
            "clusters": cl[:150]}


# ------------------------------------------- 4. Incident Commander briefing
def _zstats(s):
    """Day-level z-scores vs the same ±7-day DOY window in *other* years.

    Vectorized via shifted series (one copy per offset, -7..+7) instead of a
    per-row window query, so multi-decadal records stay fast.
    """
    idx = s.index
    v = s.values.astype(float)
    yr = idx.year.values
    n = len(v)
    acc = np.zeros(n); acc2 = np.zeros(n); cnt = np.zeros(n)
    for off in range(-7, 8):
        if off == 0: continue
        shifted = np.full(n, np.nan)
        if off > 0:
            shifted[off:] = v[:-off]
        else:
            shifted[:off] = v[-off:]
        shifted[(idx + pd.Timedelta(days=off)).year == yr] = np.nan   # exclude same year
        m = ~np.isnan(shifted)
        acc[m] += shifted[m]; acc2[m] += shifted[m] ** 2; cnt[m] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        mu = np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)
        var = np.maximum(acc2 / np.maximum(cnt, 1) - mu ** 2, 0)
        sd = np.where(cnt > 1, np.sqrt(var), np.nan)
        z = np.where((cnt > 1) & (sd > 0), (v - mu) / np.maximum(sd, 1e-9), np.nan)
    return pd.DataFrame({"v": v, "mu": mu, "sd": sd, "z": z}, index=idx)


def _streaks(df, zthr):
    hot = df[(df.z >= zthr) & (df.v >= 3)].sort_index()
    out, cur = [], None
    for i, r in hot.iterrows():
        if cur is not None and (i - cur["end"]).days <= 2:
            cur["end"] = i; cur["days"] += 1; cur["max_z"] = max(cur["max_z"], float(r.z)); cur["total"] += float(r.v)
        else:
            if cur is not None: out.append(cur)
            cur = {"start": i, "end": i, "days": 1, "max_z": float(r.z), "total": float(r.v)}
    if cur is not None: out.append(cur)
    for st in out:
        st["start"] = str(st["start"].date()); st["end"] = str(st["end"].date())
        st["total"] = round(st["total"], 1); st["max_z"] = round(st["max_z"], 1)
    return sorted(out, key=lambda x: -x["max_z"])[:10]


def _threat(streaks, recent_mean):
    if not streaks or recent_mean <= 0: return {"level": "Low", "score": 1}
    top, days = streaks[0]["max_z"], sum(s["days"] for s in streaks)
    score = top + 0.5 * days + min(2.0, recent_mean / 25)
    level = "Critical" if score >= 6 else ("Elevated" if score >= 3.5 else "Watch")
    return {"level": level, "score": round(score, 1)}


def _biomes(d, k=4):
    if len(d) < k * 3: return []
    X = np.c_[d.lon.values * 111.32 * math.cos(math.radians(d.lat.mean())), d.lat.values * 110.57, d.frp.values]
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
    d = d.assign(z=km.labels_)
    rank = {lab: i for i, lab in enumerate(d.groupby("z").frp.sum().sort_values(ascending=False).index)}
    kinds = ["Forest", "Agricultural Crop Residue", "Savanna", "Mediterranean Shrubland"]
    out = []
    for lab, g in d.groupby("z"):
        lat_s, lon_s = g.lat.std() + 1e-6, g.lon.std() + 1e-6
        out.append({"kind": kinds[rank[lab] % len(kinds)], "n": len(g),
                    "mean_frp": round(g.frp.mean(), 1), "total_frp": round(g.frp.sum(), 1),
                    "centroid": [round(g.lat.mean(), 3), round(g.lon.mean(), 3)],
                    "spread_km": round(float(np.sqrt(lat_s ** 2 + lon_s ** 2) * 111.32), 1)})
    return sorted(out, key=lambda b: -b["total_frp"])


@app.get("/briefing")
def briefing(bbox: str = None, z: float = 2.0, min_days: int = 2, format: str = "json"):
    z = min(max(z, 1.0), 5.0); min_days = min(max(min_days, 1), 14)
    d = subset(bbox)
    s = daily(d)["count"]
    if len(s) < 60:
        return {"note": "Need at least ~60 days of data", "threat": {"level": "Unknown", "score": 0},
                "streaks": [], "biomes": [], "recommendations": []}
    df = _zstats(s)
    streaks = [x for x in _streaks(df, z) if x["days"] >= min_days]
    recent = s[-30:]
    recent_mean = float(recent.mean())
    thr = _threat(streaks, recent_mean)
    biomes = _biomes(d)
    recs = []
    if thr["level"] in ("Elevated", "Critical"):
        recs.append("Stage aerial retardant and preposition crews ahead of the next burning window.")
    if not streaks:
        recs.append("No sustained anomaly streaks at the chosen z-threshold; routine monitoring is sufficient.")
    for b in biomes[:2]:
        if b["kind"] == "Agricultural Crop Residue":
            recs.append(f"Agricultural residue burning dominates cluster activity near "
                        f"({b['centroid'][0]}, {b['centroid'][1]}) — consider a temporary burn ban and farmer outreach.")
        elif b["kind"] == "Forest":
            recs.append(f"Forest fuel cluster near ({b['centroid'][0]}, {b['centroid'][1]}) "
                        f"carries the highest total FRP ({b['total_frp']} MW) — prioritize patrols and firebreak checks.")
        elif b["kind"] == "Savanna":
            recs.append(f"Savanna burns near ({b['centroid'][0]}, {b['centroid'][1]}) are spreading fast but low intensity — "
                        f"early dry-season suppression is most cost-effective.")
        else:
            recs.append(f"Mediterranean shrubland fires near ({b['centroid'][0]}, {b['centroid'][1]}) "
                        f"pose high crown-fire risk during wind events — issue red-flag warnings if winds exceed 30 km/h.")
    if recent_mean > float(s.mean()):
        recs.append("The last 30 days are running above the record mean — heighten early-warning dissemination.")
    result = {"threat": thr, "streaks": streaks, "biomes": biomes,
              "recent": {"window_days": 30, "mean_daily": round(recent_mean, 1), "max_daily": round(float(recent.max()), 1)},
              "record": {"mean_daily": round(float(s.mean()), 1), "days": len(s)},
              "recommendations": recs[:6]}
    if format == "markdown":
        lines = [f"# Wildfire Intelligence Briefing", "",
                 f"**Threat level:** {thr['level']} (score {thr['score']})  ",
                 f"**Record window:** {result['record']['days']} days · mean {result['record']['mean_daily']} fires/day  ",
                 f"**Last 30 days:** mean {result['recent']['mean_daily']}/day · peak {result['recent']['max_daily']}", "",
                 f"## Critical burning periods (Z ≥ {z}σ, ≥ {min_days}d)"]
        if streaks:
            for st in streaks:
                lines.append(f"- **{st['start']} → {st['end']}** — {st['days']} day(s), peak z={st['max_z']}, total {st['total']} fires")
        else:
            lines.append("- None detected at this threshold.")
        lines += ["", "## Dominant fuel biomes (K-means stratification)"]
        if biomes:
            for b in biomes:
                lines.append(f"- **{b['kind']}** — {b['n']} fires, mean FRP {b['mean_frp']} MW, "
                             f"total {b['total_frp']} MW, spread ~{b['spread_km']} km")
        else:
            lines.append("- Not enough clustered detections to stratify.")
        lines += ["", "## Recommendations"]
        lines += [f"- {r}" for r in (recs or ["No actions flagged — conditions within climatological norms."])]
        return PlainTextResponse("\n".join(lines), media_type="text/markdown; charset=utf-8")
    return result


# ---------------------------------------------------------------- legacy panels
@app.get("/anomalies")
def anomalies(bbox: str = None, z: float = 2.0):
    z = min(max(z, 0.5), 10)
    s = daily(subset(bbox))["count"]
    if len(s) < 400: return {"anomalies": [], "critical": [], "note": "Need >1 year of data"}
    df = _zstats(s)
    an = df[(df.z > z) & (df.v >= 5)].sort_values("z", ascending=False).head(50)
    mo = s.groupby(s.index.month).mean(); thr = mo.mean() + mo.std()
    return {"anomalies": [{"date": str(i.date()), "count": round(r.v, 1), "expected": round(r.mu, 1), "z": round(r.z, 1)} for i, r in an.iterrows()],
            "critical": [{"month": int(m), "avg": round(v, 1)} for m, v in mo.items() if v >= thr],
            "monthly": [{"month": int(m), "avg": round(v, 1)} for m, v in mo.items()]}


@app.get("/forecast")
def forecast(bbox: str = None, horizon: int = 30, epochs: int = 40):
    horizon = min(max(horizon, 1), 90); epochs = min(max(epochs, 1), 200)
    s = daily(subset(bbox))["count"]
    if len(s) < 120: return {"model": None, "forecast": []}
    idx = pd.date_range(s.index[-1] + pd.Timedelta(days=1), periods=horizon)
    try:
        import torch, torch.nn as nn
        y = np.log1p(s.values).astype("float32"); mu, sd = y.mean(), y.std() + 1e-6; y = (y - mu) / sd
        W = 30; doy = lambda ix: np.c_[np.sin(2*np.pi*ix.dayofyear/365.25), np.cos(2*np.pi*ix.dayofyear/365.25)].astype("float32")
        feat = np.c_[y, doy(s.index)]
        Xs = np.stack([feat[i:i+W] for i in range(len(y)-W)]); Ys = y[W:]
        class M(nn.Module):
            def __init__(s): super().__init__(); s.l = nn.LSTM(3, 32, batch_first=True); s.o = nn.Linear(32, 1)
            def forward(s, x): return s.o(s.l(x)[0][:, -1]).squeeze(-1)
        m = M(); opt = torch.optim.Adam(m.parameters(), 1e-2); Xt, Yt = torch.tensor(Xs), torch.tensor(Ys)
        for _ in range(epochs): opt.zero_grad(); nn.functional.mse_loss(m(Xt), Yt).backward(); opt.step()
        win, dz, out = feat[-W:].copy(), doy(idx), []
        for k in range(horizon):
            p = m(torch.tensor(win[None])).item(); out.append(p); win = np.vstack([win[1:], [p, *dz[k]]])
        vals = np.expm1(np.array(out) * sd + mu).clip(0); model = "LSTM (PyTorch)"
    except ImportError:  # seasonal fallback: same-day climatology scaled to recent level
        dfp = pd.DataFrame({"v": s.values, "doy": s.index.dayofyear}, index=s.index)
        clim = dfp.groupby("doy").v.mean().rolling(15, center=True, min_periods=1).mean()
        scale = (s[-30:].mean() + 1) / (clim.reindex(s[-30:].index.dayofyear).mean() + 1)
        vals = clim.reindex(idx.dayofyear).values * scale; model = "Seasonal climatology (install torch for LSTM)"
    return {"model": model, "forecast": [{"date": str(i.date()), "count": round(float(v), 1)} for i, v in zip(idx, vals)]}
