"""Burning Activity Calendar / Pyro-Harmony API.

Harmonizes FIRMS MODIS + VIIRS CSVs and serves the four poster pillars:
  1. Multi-decadal burning-activity calendar    -> /climatology
  2. "Sensor Transition Illusion" diagnostic    -> /diagnostic
  3. Geospatial hotspot clustering + live feed  -> /live
  4. Incident Commander wildfire briefing       -> /briefing
plus the original calendar / map / anomaly / forecast endpoints.
"""
import functools
import io
import math
import os
import re
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
import requests
from fastapi import FastAPI, UploadFile, File, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from demo import BOX, make_demo, make_transition_demo
from regions import REGIONS, region_box, region_keys


# ------------------------------------------------------------ local configuration
def parse_env(text: str) -> dict:
    """Parse the `KEY=VALUE` subset of a .env file: comments, blanks, `export`, quotes."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def load_env_file():
    """Load the first .env found next to this file, in firecal/, or at the repo root.

    Real environment variables always win (`setdefault`), so exporting FIRMS_MAP_KEY in
    the shell keeps working exactly as before.  Searching the parents means the launcher
    -- which runs uvicorn from firecal/backend -- still finds a repo-root .env.
    """
    here = Path(__file__).resolve().parent
    for candidate in (here / ".env", here.parent / ".env", here.parent.parent / ".env"):
        if candidate.is_file():
            for key, value in parse_env(candidate.read_text(encoding="utf-8", errors="replace")).items():
                os.environ.setdefault(key, value)
            return candidate
    return None


load_env_file()

MAX_FILE_BYTES = 200 * 1024 * 1024  # per uploaded CSV
MAX_UPLOAD_BYTES = 400 * 1024 * 1024  # whole upload request (all files + multipart overhead)
MAX_UPLOAD_FILES = 20               # a request carrying 50 files is not a use case
UPLOAD_CHUNK = 1 << 20              # read uploads in 1 MiB slices
MAX_ROWS = 2_000_000                # in-memory safety cap
LIVE_MAX_ROWS = 200_000             # safety cap for one live ingest
MAX_FEED_BYTES = 64 * 1024 * 1024   # safety cap on one outbound FIRMS download
CLUSTER_MAX_POINTS = 60_000         # detections fed to one DBSCAN pass (strided above this)
CLUSTER_RETURN = 300                # clusters returned; only these get a convex hull

# The dev server proxies /api to this process, so the browser talks same-origin and needs
# no CORS grant at all. Defaulting to `*` let any web page the operator visits drive
# /upload and /demo against their dataset, so the default is now the local origins only.
# Deploying the console elsewhere means setting ALLOW_ORIGINS explicitly.
DEFAULT_ORIGINS = "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4173,http://localhost:4173"

app = FastAPI(title="Pyro-Harmony — Burning Activity Calendar")
# The JSON endpoints are mostly text (dates, sensor names, repeated keys) and compress
# 3-9x, which matters a lot on the day/bbox re-fetches while exploring the map.
# 1 KiB floor: below that gzip costs more than it saves.
app.add_middleware(GZipMiddleware, minimum_size=1024)
# Registered before CORS so a rejected upload still comes back inside the CORS grant.


@app.middleware("http")
async def cap_upload_body(request, call_next):
    """Refuse an oversized upload before any of it is buffered.

    The multipart parser spools the whole body to disk while the request is being
    received, so checking size inside the handler is far too late -- it only sees the
    file after everything has landed. This reads the declared Content-Length and bails
    early. Chunked requests without a Content-Length fall through to the per-file cap.
    """
    if request.url.path.endswith("/upload"):
        try:
            declared = int(request.headers.get("content-length") or 0)
        except ValueError:
            declared = 0
        if declared > MAX_UPLOAD_BYTES:
            return JSONResponse(
                {"detail": f"upload too large: {declared} bytes (limit {MAX_UPLOAD_BYTES})"},
                status_code=413)
    return await call_next(request)


ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOW_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def same_origin_writes(request, call_next):
    """Refuse writes a foreign page drove, which CORS alone does not stop.

    CORS decides whether a foreign origin may *read* a response; it never stops the
    request itself.  A form POST, and a fetch with a simple content type, are sent
    without a preflight, so restricting allow_origins left every write endpoint
    (/upload, /demo, /archive, /live) drivable by any page the operator had open.  A
    write now has to come from this host or from an explicit ALLOW_ORIGINS entry; a
    request with no Origin at all (curl, pytest, the launcher's health checks) is
    untouched, and GETs are never gated.
    """
    origin = request.headers.get("origin")
    if origin and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        host = request.headers.get("host", "")
        if urlsplit(origin).netloc != host and origin not in ALLOWED_ORIGINS:
            return JSONResponse({"detail": "cross-origin write refused"}, status_code=403)
    return await call_next(request)
CONF_MAP = {"l": 20, "low": 20, "n": 60, "nominal": 60, "h": 90, "high": 90}
REQUIRED = {"latitude", "longitude", "acq_date", "acq_time", "confidence"}

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

# FIRMS area API: real per-AOI windows (1-5 days) for one chosen source. Unlike the open
# 24h CSVs it needs a free MAP_KEY, so /archive explains how to get one instead of
# guessing.  Its source names differ from the open-feed keys, hence the mapping.
FIRMS_AREA_API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
AREA_SOURCES = {"MODIS_C6.1": "MODIS_C6_1", "VIIRS_S-NPP": "VIIRS_SNPP_C2",
                "VIIRS_NOAA-20": "VIIRS_NOAA20_C2", "VIIRS_NOAA-21": "VIIRS_NOAA21_C2"}
MAP_KEY_RE = re.compile(r"[A-Za-z0-9]{6,64}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def firms_area_url(key, source, box, days, date=None):
    """Build an area-API URL. `box` is minlat,minlon,maxlat,maxlon; the API wants
    west,south,east,north. The key comes from the operator's environment, never a request."""
    a, b, c, e = box
    url = f"{FIRMS_AREA_API}/{key}/{AREA_SOURCES[source]}/{b},{a},{e},{c}/{days}"
    return f"{url}/{date}" if date else url


# ------------------------------------------------------- derived-data caches
# Every analytics endpoint is a pure function of the loaded dataset, so memoize its
# response until the dataset changes.  These recomputations (DBSCAN, rolling
# percentiles, K-means) are the difference between instant and a multi-second freeze
# on every click on a low-end machine.
_AGG_CACHE: dict = {}
_CACHE_MAX = 256


def _invalidate() -> None:
    """Drop every derived cache. Call after DF changes."""
    _AGG_CACHE.clear()


def cached(func):
    """Memoize an endpoint keyed by its own arguments; cleared by _invalidate()."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        key = (func.__name__, args, tuple(sorted(kwargs.items())))
        hit = _AGG_CACHE.get(key)
        if hit is not None:
            return hit
        value = func(*args, **kwargs)
        if isinstance(value, Response):      # already-serialized body: don't reuse it
            return value
        if len(_AGG_CACHE) >= _CACHE_MAX:    # keep memory bounded on small machines
            _AGG_CACHE.clear()
        _AGG_CACHE[key] = value
        return value
    return wrapper


def read_firms_csv(blob: bytes) -> pd.DataFrame:
    """Decode a FIRMS-style CSV no matter which OS or editor produced it.

    pandas assumes UTF-8, but Excel on Windows writes cp1252 and Excel on macOS
    can emit UTF-16, so a perfectly good export would otherwise be rejected as
    "not a readable CSV".  latin-1 last, because it decodes any byte.
    """
    if blob[:2] in (b"\xff\xfe", b"\xfe\xff"):            # UTF-16 little/big endian BOM
        return pd.read_csv(io.BytesIO(blob), encoding="utf-16")
    last = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(blob), encoding=enc)
        except UnicodeDecodeError as e:
            last = e
    raise ValueError(f"could not decode the CSV as text ({last})")


# ---------------------------------------------------------------- harmonization
# Nadir cell of the product FIRMS actually distributes.  MODIS is 1x1 km; the VIIRS
# feed is the I-band 375 m product (VNP14IMG / VJ114IMG / VJ214IMG), *not* the 750 m
# M-band one, so its cell is 0.375x0.375 km -- 0.140625 km², four times smaller than
# the 0.5625 km² (0.75 km) cell this used to assume.  NASA Earthdata's FIRMS attribute
# table is explicit: "The algorithm produces approximately 375 m pixels at nadir.
# Scan and track reflect actual pixel size."
NADIR_KM2 = {"MODIS": 1.0, "VIIRS": 0.140625}


def _esfp(scan, track, sensor):
    """Equivalent Standard Fire Pixels (footprint expansion ratio) and the physical
    footprint area (km²) of each detection.

    FIRMS reports the instantaneous footprint extent per detection via the
    `scan` / `track` columns (already in km).  Dividing by the sensor's own nadir
    cell yields A(theta), the expansion ratio: 1.0 at nadir, up to ~9.7x at the
    edge of scan for either sensor (Giglio 2016 for MODIS; Schroeder 2014 and the
    2026 VIIRS studies for the I-band).  One detection is therefore never worth
    less than one standard pixel, which is what the clip below enforces.
    """
    sensor = str(sensor).upper()
    nadir = NADIR_KM2.get(sensor, 1.0)
    area_km2 = scan.clip(0.1, 20) * track.clip(0.1, 20)
    return area_km2.clip(lower=nadir) / nadir, area_km2


def harmonize(raw: pd.DataFrame) -> pd.DataFrame:
    d = raw.copy(); d.columns = [c.strip().lower() for c in d.columns]
    missing = REQUIRED - set(d.columns)
    if missing:
        raise ValueError(f"missing required columns: {', '.join(sorted(missing))}")
    viirs = "bright_ti4" in d.columns
    bt_col = "bright_ti4" if viirs else "brightness"
    sensor = "VIIRS" if viirs else "MODIS"
    if "instrument" in d.columns and d["instrument"].notna().any():
        sensor = str(d["instrument"].dropna().iloc[0]).upper()
    #    numeric confidence if parseable (MODIS 0-100), else l/n/h map (VIIRS); unknown -> dropped
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
        "bt": d[bt_col] if bt_col in d.columns else pd.Series(np.nan, index=d.index),
        "scan": scan.clip(0.1, 20), "track": track.clip(0.1, 20),
        "daynight": d.get("daynight", pd.Series(0, index=d.index)),
        "esfp": esfp, "pixel_km2": area})
    out = out.dropna(subset=["lat", "lon", "time", "conf", "bt"])
    out = out[out.lat.between(-90, 90) & out.lon.between(-180, 180)]
    return out[out.conf >= 30]  # drop low-confidence detections for all sensors


# Empty-but-typed frame: a cleared store still answers [] instead of 500.
EMPTY_DF = harmonize(pd.DataFrame(columns=["latitude", "longitude", "acq_date", "acq_time",
                                           "confidence", "brightness", "frp", "satellite"]))
DF = EMPTY_DF.copy()


def _safe_name(name, limit: int = 80) -> str:
    """Make a client-supplied filename safe to echo back in an error body.

    Filenames are attacker-controlled and end up in JSON detail strings and server logs,
    so strip directories, control characters and newlines (which would otherwise let a
    crafted name forge extra log lines) and cap the length.
    """
    flat = (name or "upload").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(c for c in flat if c.isprintable())
    return cleaned[:limit] or "upload"


async def _read_capped(f: UploadFile, limit: int) -> bytes:
    """Read an upload in slices and abort the moment it passes `limit`.

    `await f.read()` buffers the entire body in RAM first and only then lets the caller
    compare len(blob), so one request with a multi-gigabyte body would exhaust memory
    before the size check ever ran.
    """
    buf = bytearray()
    while True:
        chunk = await f.read(UPLOAD_CHUNK)
        if not chunk:
            return bytes(buf)
        buf += chunk
        if len(buf) > limit:
            raise HTTPException(400, f"{_safe_name(f.filename)}: file exceeds "
                                     f"{limit // (1024 * 1024)} MB limit")


@app.post("/upload")
async def upload(files: list[UploadFile] = File(...), demo_transition: bool = False):
    global DF
    if not files:
        raise HTTPException(400, "No files uploaded")
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(400, f"too many files: {len(files)} (limit {MAX_UPLOAD_FILES} per request)")
    parts = [DF] if len(DF) else []
    # The poster's 2002-2024 illusion dataset used to load whenever a file happened to be
    # *named* demo_transition.csv. A filename is client-controlled input and must never
    # select server behaviour: that made the upload's real content irrelevant, and anyone
    # with a legitimate file of that name silently got the demo instead. Now it is an
    # explicit, documented flag.
    if demo_transition:
        return demo("transition")
    for f in files:
        name = _safe_name(f.filename)
        blob = await _read_capped(f, MAX_FILE_BYTES)
        try:
            raw = read_firms_csv(blob)
        except Exception as e:
            raise HTTPException(400, f"{name}: not a readable CSV ({e})")
        try:
            h = harmonize(raw)
        except ValueError as e:
            raise HTTPException(400, f"{name}: {e}")
        if not h.empty:
            parts.append(h)
    if not parts:
        raise HTTPException(400, "No usable rows found: need FIRMS-style CSVs with "
                                 "latitude/longitude/acq_date/acq_time and confidence >= 30")
    DF = pd.concat(parts).drop_duplicates(["lat", "lon", "time", "sensor"]).reset_index(drop=True)
    if len(DF) > MAX_ROWS:
        DF = DF.tail(MAX_ROWS).reset_index(drop=True)
    _invalidate()
    return meta()


@app.post("/demo")
def demo(mode: str = "standard", region: str = None):
    """Generate the synthetic demo record. `region` scopes it to a preset AOI, so the
    demo -- and therefore every panel -- works for any region in the catalog."""
    global DF
    if region is not None and region not in REGIONS:
        raise HTTPException(400, f"unknown region {region!r}; expected one of: {region_keys()}")
    frames = _transition_frames(region) if mode == "transition" else _demo_frames(region)
    DF = pd.concat(frames).reset_index(drop=True)
    _invalidate()
    return meta()


# One generated record per (mode, region). The catalog has five presets plus the default
# Thailand-shaped box, and each entry is built at most once.
_DEMO_CACHE, _TRANSITION_CACHE = {}, {}


def _region_seed(region, base):
    """Stable per-region seed so two presets don't present identical demo statistics.

    The generator draws the same number of events whatever the box is, so without this
    California and the Amazon would differ only in geography. crc32 (not hash()) keeps it
    reproducible across processes and machines, and the default demo -- the one whose
    numbers the README quotes -- keeps its original seed.
    """
    return base if region is None else base + zlib.crc32(region.encode()) % 997


def _demo_frames(region=None):
    """Generate + harmonize the 2020-2024 demo once per region (seconds of CPU)."""
    if region not in _DEMO_CACHE:
        box = region_box(region) or BOX
        _DEMO_CACHE[region] = [harmonize(x) for x in make_demo(seed=_region_seed(region, 7), box=box)]
    return _DEMO_CACHE[region]


def _transition_frames(region=None):
    """Generate + harmonize the 2002-2024 illusion dataset once per region (it is heavy)."""
    if region not in _TRANSITION_CACHE:
        box = region_box(region) or BOX
        _TRANSITION_CACHE[region] = [harmonize(x) for x in
                                     make_transition_demo(seed=_region_seed(region, 11), box=box)]
    return _TRANSITION_CACHE[region]


@app.post("/archive")
def archive(region: str = None, bbox: str = None, source: str = "VIIRS_S-NPP",
            days: int = 3, date: str = None, append: bool = True):
    """Load a real FIRMS window for an AOI through the area API -- needs FIRMS_MAP_KEY.

    The 24h open feeds make every AOI look like a single day; this pulls 1-5 days for one
    source and region (or an explicit bbox) so the console can hold real fire records.
    Rows are appended to whatever is loaded, exactly like an upload.
    """
    global DF
    if source not in AREA_SOURCES:
        raise HTTPException(400, f"unknown source {source!r}; expected one of: {', '.join(AREA_SOURCES)}")
    if region is not None and region not in REGIONS:
        raise HTTPException(400, f"unknown region {region!r}; expected one of: {region_keys()}")
    box = parse_bbox(bbox) if bbox else (region_box(region) if region else None)
    if box is None:
        raise HTTPException(400, "provide ?region=<preset> or ?bbox=minlat,minlon,maxlat,maxlon")
    if date and not DATE_RE.fullmatch(date):
        raise HTTPException(400, "date must be YYYY-MM-DD")
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key:
        raise HTTPException(400, "FIRMS_MAP_KEY is not set. Get a free key at "
                                 "https://firms.modaps.eosdis.nasa.gov/api/map_key/ then copy "
                                 ".env.example to .env (repo root or firecal/backend), or export FIRMS_MAP_KEY.")
    if not MAP_KEY_RE.fullmatch(key):
        raise HTTPException(400, "FIRMS_MAP_KEY looks malformed (expected 6-64 letters/digits)")
    days = min(max(days, 1), 5)          # the area API accepts 1-5 days per request
    try:
        raw = _fetch_feed(firms_area_url(key, source, box, days, date))
    except Exception as e:
        # `e` is sanitised by _fetch_feed: this detail reaches the client, so nothing that
        # could contain the key (or the URL that carries it) may be echoed here.
        raise HTTPException(502, f"FIRMS area API request failed: {e}")
    h = harmonize(raw)
    a, b, c, e = box
    # Trust the API's AREA filter, then verify: an unexpected layout must not smuggle
    # rows outside the requested AOI into every later query.
    h = h[(h.lat >= a) & (h.lat <= c) & (h.lon >= b) & (h.lon <= e)]
    if not len(h):
        raise HTTPException(400, "FIRMS returned no usable rows for that window "
                                 "(all low-confidence, outside the AOI, or an empty day range)")
    DF = (pd.concat([DF, h]) if append and len(DF) else h) \
        .drop_duplicates(["lat", "lon", "time", "sensor"]).reset_index(drop=True)
    if len(DF) > MAX_ROWS:
        DF = DF.tail(MAX_ROWS).reset_index(drop=True)
    _invalidate()
    m = meta()
    m.update({"source": source, "region": region, "days": days})
    return m


@app.delete("/data")
def clear():
    global DF; DF = EMPTY_DF.copy(); _invalidate(); return meta()


@app.get("/meta")
def meta():
    if DF.empty: return {"n": 0}
    return {"n": len(DF), "start": str(DF.date.min().date()), "end": str(DF.date.max().date()),
            "sensors": DF.groupby("sensor").size().to_dict(),
            "bounds": [DF.lat.min(), DF.lon.min(), DF.lat.max(), DF.lon.max()],
            "hfi": round(float(DF.frp.mul(DF.esfp).sum()), 1),
            "esfp": round(float(DF.esfp.sum()), 1),
            "pixels": int(len(DF))}


@app.get("/regions")
def list_regions():
    """Curated AOI presets: bbox, biome, peak season and notable past fire events."""
    return [{"key": key, **region} for key, region in REGIONS.items()]


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
    if d.empty: return d
    if box:
        a, b, c, e = box
        d = d[(d.lat >= a) & (d.lat <= c) & (d.lon >= b) & (d.lon <= e)]
    if start: d = d[d.date >= start]
    if end: d = d[d.date <= end]
    return d


def daily(d):
    """Daily counts; sensors rescaled to the best-covered sensor over their overlap period."""
    if d.empty:
        return pd.DataFrame({"count": pd.Series(dtype=float), "raw": pd.Series(dtype=float),
                             "frp": pd.Series(dtype=float)}, index=pd.DatetimeIndex([]))
    piv = d.groupby(["date", "sensor"]).size().unstack(fill_value=0)
    ref = (piv > 0).sum().idxmax(); adj = piv.astype(float)
    for s in piv.columns:
        if s == ref: continue
        ov = (piv[ref] > 0) & (piv[s] > 0)
        if ov.sum() >= 5: adj[s] = piv[s] * piv.loc[ov, ref].sum() / piv.loc[ov, s].sum()
    out = pd.DataFrame({"count": adj.sum(axis=1), "raw": piv.sum(axis=1), "frp": d.groupby("date").frp.sum()})
    return out.reindex(pd.date_range(out.index.min(), out.index.max()), fill_value=0)


@app.get("/calendar")
@cached
def calendar(bbox: str = None, start: str = None, end: str = None):
    s = daily(subset(bbox, start, end))
    return [{"date": str(i.date()), "count": round(r["count"], 1), "raw": int(r["raw"]), "frp": round(r["frp"], 1)} for i, r in s.iterrows()]


@app.get("/points")
@cached
def points(bbox: str = None, start: str = None, end: str = None, limit: int = 6000):
    d = subset(bbox, start, end)
    limit = min(max(limit, 1), 20000)
    if len(d) > limit: d = d.sample(limit, random_state=0)
    return d[["lat", "lon", "frp", "sensor"]].round(4).to_dict("records")


@app.get("/clusters")
@cached
def clusters(bbox: str = None, start: str = None, end: str = None, eps: float = 550, min_pts: int = 3, hours: float = 12):
    eps = min(max(eps, 10), 5000); min_pts = min(max(min_pts, 1), 100); hours = min(max(hours, 0.5), 720)
    return _cluster_payload(subset(bbox, start, end), eps, min_pts, hours)


def _cluster_payload(d, eps, min_pts, hours):
    # scipy + scikit-learn are the two heaviest imports in the app (~2.5-3.5 s of cold
    # start and a chunk of the baseline RSS), and only this function and the briefing's
    # fuel stratification need them. Imported on first use so the API answers /meta -- and
    # the launcher can open the browser -- that much sooner; later calls hit the module
    # cache, so the cost is paid once, off the start-up path.
    from scipy.spatial import ConvexHull
    from sklearn.cluster import DBSCAN
    if len(d) < min_pts: return []
    # ponytail: stride-sample above 60k detections (an exact pass would be a per-day
    # clustering rewrite). head() kept the OLDEST rows, so a big upload silently showed a
    # map biased to the past; a stride keeps the whole period covered.
    if len(d) > CLUSTER_MAX_POINTS:
        d = d.sort_values("time")
        d = d.iloc[:: max(1, -(-len(d) // CLUSTER_MAX_POINTS))]
    lat0 = np.deg2rad(d.lat.mean())
    X = np.c_[(d.lon.values * 111320 * np.cos(lat0)), d.lat.values * 110540,
              (d.time.astype("int64").values / 3.6e12) / hours * eps]  # time scaled so `hours` ~ eps metres
    lab = DBSCAN(eps=eps, min_samples=min_pts).fit_predict(X)
    d = d.assign(c=lab); d = d[d.c >= 0]
    if not len(d): return []
    # Rank first, hull second. Only the 300 biggest clusters are returned, but this used to
    # build a convex hull (or a full point dump) for every cluster and discard ~98% of them:
    # on a 59k-row 23-year record that was ~20k hulls and a 33 s first click. DBSCAN itself
    # is 0.8 s of that.
    grouped = d.groupby("c")
    res = []
    for cid in grouped.size().nlargest(CLUSTER_RETURN).index:
        g = grouped.get_group(cid)
        pts = g[["lat", "lon"]].values
        try: hull = pts[ConvexHull(pts).vertices].tolist()
        except Exception: hull = pts.tolist()
        res.append({"id": int(cid), "n": len(g), "frp": round(g.frp.sum(), 1), "lat": g.lat.mean(), "lon": g.lon.mean(),
                    "start": str(g.time.min()), "end": str(g.time.max()), "hull": hull,
                    "sensors": sorted(set(g.sensor)), "duration_h": round((g.time.max() - g.time.min()).total_seconds() / 3600, 1)})
    return sorted(res, key=lambda r: -r["n"])


# ------------------------------------------- 1. multi-decadal DOY climatology
def _doy_matrix(s):
    return {int(d): [None if pd.isna(v) else round(float(v), 2) for v in vals]
            for d, vals in s.groupby(s.index.dayofyear)}


@app.get("/climatology")
@cached
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
@cached
def diagnostic(bbox: str = None):
    """Unmask the post-2012 VIIRS deployment artifact (poster pillar 2).

    The artifact is a *sampling* effect: over the same fires VIIRS resolves several
    times more detections than MODIS, so the combined count jumps the day it arrives.
    The correction is therefore measured from counts in the collocated window.

    Footprint ratios cannot do this job.  ESFP is a per-sensor expansion ratio (≈1
    for both sensors once each is divided by its own nadir cell) and mean FRP per
    detection is comparable between the sensors, so an earlier version that
    multiplied the two ratios together was multiplying two numbers that carry no
    sampling information -- its factor of 1.73 was just the 750 m/375 m unit error
    (1/0.5625 = 1.778) echoing through the payload.
    """
    d = subset(bbox)
    if d.empty:
        return {"series": [], "note": "No data loaded"}
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
    # --- the comparable record ----------------------------------------------------
    # A fire both sensors saw must not be counted twice, so each day keeps the larger
    # of the two counts expressed in MODIS-detection units (`k`, the collocated-period
    # ratio -- one MODIS detection is worth 1/k VIIRS detections).  Summing them, or
    # rescaling and summing them, is what made the record surge after 2012.
    k = cal.get("daily_count_ratio")
    per = daily(d)["count"]        # the app-wide calendar series, for reference/fallback
    if k:
        by_sensor = d.groupby([d.date, "sensor"]).size().unstack(fill_value=0)
        zero = pd.Series(0.0, index=by_sensor.index)
        modis = by_sensor.get("MODIS", zero)
        viirs = by_sensor.get("VIIRS", zero) * float(k)
        comparable = pd.concat([modis, viirs], axis=1).max(axis=1)
    else:
        comparable = per
    raw = d.groupby([d.date.dt.year, "sensor"]).size().unstack(fill_value=0)
    for c in ("MODIS", "VIIRS"):
        if c not in raw: raw[c] = 0
    adj = comparable.groupby(comparable.index.year).sum()
    series = [{"year": int(y),
               "modis": int(raw.MODIS.get(y, 0)), "viirs": int(raw.VIIRS.get(y, 0)),
               "raw_total": int(raw.MODIS.get(y, 0) + raw.VIIRS.get(y, 0)),
               "adjusted": round(float(adj.get(y, 0.0)), 1)} for y in sorted(set(raw.index) | set(adj.index))]
    pre_n = int((d.date.dt.year < 2012).sum()); post_n = int(((d.date.dt.year >= 2012) & (d.date.dt.year <= 2015)).sum())
    raw_day = d.groupby("date").size()          # what an unharmonized analyst counts
    ry, cy = raw_day.index.year, comparable.index.year
    pre_c = float(raw_day[ry < 2012].mean()) if len(pre) else 0.0
    post_c = float(raw_day[(ry >= 2012) & (ry <= 2015)].mean()) if len(post) else 0.0
    pre_k = float(comparable[cy < 2012].mean()) if len(pre) else 0.0
    post_k = float(comparable[(cy >= 2012) & (cy <= 2015)].mean()) if len(post) else 0.0
    pre_frp = float(pre.frp.mean()) if len(pre) else 0.0
    post_frp = float(post.frp.mean()) if len(post) else 0.0
    growth = round((post_c / pre_c - 1) * 100, 1) if pre_c > 0 else None
    adj_growth = round((post_k / pre_k - 1) * 100, 1) if pre_k > 0 else None
    scale = round(post_c / post_k, 3) if post_k > 0 else None   # era inflation of the raw count
    return {"series": series, "observed_growth_pct": growth, "adjusted_growth_pct": adj_growth,
            "viirs_scaling": scale,
            "artifact_pct": None if (growth is None or adj_growth is None) else round(growth - adj_growth, 1),
            "calibration": cal or None,
            "stats": {"hfi": round(float(d.frp.mul(d.esfp).sum()), 1),
                      "esfp": round(float(d.esfp.sum()), 1), "pixels": int(len(d))},
            "pre_2012_days": pre_n, "post_2012_days": post_n,
            "pre_mean_daily": round(pre_c, 2), "post_mean_daily": round(post_c, 2),
            "pre_mean_frp": round(pre_frp, 2), "post_mean_frp": round(post_frp, 2)}


# --------------------------------- 3. live NASA FIRMS feeds + on-the-fly clustering
def _fetch_feed(url, timeout=90):
    # Streamed with a hard ceiling. r.content buffered whatever came back with no limit,
    # so a huge or unexpected response would be pulled into memory in full.
    #
    # The URL can carry the operator's FIRMS_MAP_KEY (every /archive pull does) and
    # requests' own exception text embeds the full URL, so a transport failure must not
    # propagate that text: it used to reach the caller in the 502 detail /archive returns.
    try:
        with requests.get(url, headers=LIVE_USER_AGENT, timeout=timeout, stream=True) as r:
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            buf = bytearray()
            for chunk in r.iter_content(1 << 20):
                buf += chunk
                if len(buf) > MAX_FEED_BYTES:
                    raise RuntimeError(f"feed exceeded {MAX_FEED_BYTES // (1024 * 1024)} MB")
    except requests.RequestException as e:
        raise RuntimeError(f"request failed: {type(e).__name__}") from None
    if len(buf) < 80:
        raise RuntimeError(f"HTTP {r.status_code}")
    try:
        df = read_firms_csv(bytes(buf))
    except ValueError as e:
        raise RuntimeError(str(e))
    if "latitude" not in df.columns:
        raise RuntimeError("unrecognized CSV layout")
    return df


# One live ingest costs four outbound downloads plus DBSCAN/K-means. Unauthenticated and
# uncached, so overlapping calls were free CPU and bandwidth amplification: N requests
# meant 4N outbound fetches. Refuse to stack them instead of queueing.
_LIVE_SLOTS = threading.BoundedSemaphore(2)


@app.get("/live")
def live(region: str = "Global", bbox: str = None, eps: float = 550, min_pts: int = 3,
         hours: float = 12, crop: bool = False):
    """Pull 24h global FIRMS CSVs, harmonize on the fly, cluster, and return them."""
    eps = min(max(eps, 50), 10000); min_pts = min(max(min_pts, 1), 100); hours = min(max(hours, 0.5), 48)
    # `region` is interpolated straight into the outbound FIRMS URL, so an unvalidated value
    # let a caller drive which URL this server requests (and, with a `?`, which query string).
    # The allowlist is the one the UI already offers.
    if region not in LIVE_REGIONS:
        raise HTTPException(400, f"unknown region {region!r}; expected one of: {', '.join(LIVE_REGIONS)}")
    if not _LIVE_SLOTS.acquire(blocking=False):
        raise HTTPException(429, "a live FIRMS ingest is already running; retry in a moment")
    try:
        return _live_ingest(region, bbox, eps, min_pts, hours, crop)
    finally:
        _LIVE_SLOTS.release()


def _live_ingest(region, bbox, eps, min_pts, hours, crop):
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
    from sklearn.cluster import KMeans    # same start-up reason as _cluster_payload
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
@cached
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
                 # Lowercase z: the statistic symbol stays lowercase everywhere in the UI
                 # (the cards read "z 3.1", "z=3"), so the exported markdown matches.
                 f"## Critical burning periods (z ≥ {z}σ, ≥ {min_days}d)"]
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
@cached
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
@cached
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


# ----------------------------------------------------------- single-origin serving (image)
# In development the console is served by Vite, which proxies /api to this process and strips
# the prefix on the way through (see firecal/frontend/vite.config.js). A container has no proxy
# in front of it: one uvicorn serves the built console *and* the API, so the browser's /api/...
# calls arrive with the prefix still attached and have to be peeled off before routing. No
# endpoint starts with /api, so the rewrite cannot shadow one -- and the unprefixed paths keep
# working, which is what curl, the tests and the launcher's readiness probe use.
#
# Registered last, which makes it the outermost middleware: gzip, CORS and the upload cap then
# all see the same un-prefixed path they were written against.
API_PREFIX = "/api"


@app.middleware("http")
async def strip_api_prefix(request, call_next):
    path = request.url.path
    if path == API_PREFIX or path.startswith(API_PREFIX + "/"):
        scope = request.scope
        scope["path"] = path[len(API_PREFIX):] or "/"
        if scope.get("raw_path"):
            scope["raw_path"] = scope["raw_path"][len(API_PREFIX):] or b"/"
    return await call_next(request)


# The built console, when there is one. Development has no build -- Vite serves the console
# there -- so the mount is conditional rather than a 404 waiting to happen. `docker build`
# always produces one, and that is what makes `docker run` the whole deployment story.
CONSOLE_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if (CONSOLE_DIST / "index.html").is_file():
    app.mount("/", StaticFiles(directory=CONSOLE_DIST, html=True), name="console")
