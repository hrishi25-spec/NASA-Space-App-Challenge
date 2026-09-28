"""Burning Activity Calendar API: harmonizes FIRMS MODIS + VIIRS CSVs."""
import io
import os

import numpy as np, pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sklearn.cluster import DBSCAN
from scipy.spatial import ConvexHull
from demo import make_demo

MAX_FILE_BYTES = 200 * 1024 * 1024  # per uploaded CSV
MAX_ROWS = 2_000_000                # in-memory safety cap

app = FastAPI(title="Burning Activity Calendar")
app.add_middleware(CORSMiddleware,
                   allow_origins=[o.strip() for o in os.environ.get("ALLOW_ORIGINS", "*").split(",") if o.strip()],
                   allow_methods=["*"], allow_headers=["*"])
DF = pd.DataFrame()
CONF_MAP = {"l": 20, "low": 20, "n": 60, "nominal": 60, "h": 90, "high": 90}
REQUIRED = {"latitude", "longitude", "acq_date", "acq_time"}


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
    out = pd.DataFrame({
        "lat": pd.to_numeric(d["latitude"], errors="coerce"),
        "lon": pd.to_numeric(d["longitude"], errors="coerce"),
        "time": t, "date": t.dt.normalize(),
        "sensor": sensor, "sat": d.get("satellite", pd.Series(sensor, index=d.index)).astype(str),
        "conf": conf, "frp": pd.to_numeric(d.get("frp", 0), errors="coerce").fillna(0),
        "bt": d["bright_ti4"] if viirs else d["brightness"]})
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
def demo():
    global DF
    DF = pd.concat([harmonize(x) for x in make_demo()]).reset_index(drop=True)
    return meta()


@app.delete("/data")
def clear():
    global DF; DF = pd.DataFrame(); return meta()


@app.get("/meta")
def meta():
    if DF.empty: return {"n": 0}
    return {"n": len(DF), "start": str(DF.date.min().date()), "end": str(DF.date.max().date()),
            "sensors": DF.groupby("sensor").size().to_dict(),
            "bounds": [DF.lat.min(), DF.lon.min(), DF.lat.max(), DF.lon.max()]}


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
    d = subset(bbox, start, end)
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
                    "start": str(g.time.min()), "end": str(g.time.max()), "hull": hull})
    return sorted(res, key=lambda r: -r["n"])[:300]


@app.get("/anomalies")
def anomalies(bbox: str = None, z: float = 2.0):
    z = min(max(z, 0.5), 10)
    s = daily(subset(bbox))["count"]
    if len(s) < 400: return {"anomalies": [], "critical": [], "note": "Need >1 year of data"}
    df = pd.DataFrame({"v": s, "doy": s.index.dayofyear, "yr": s.index.year})
    def stats(row):
        m = df[(((df.doy - row.doy + 183) % 366 - 183).abs() <= 7) & (df.yr != row.yr)].v
        return pd.Series({"mu": m.mean(), "sd": m.std()})
    st = df.apply(stats, axis=1); df = df.join(st)
    df["z"] = (df.v - df.mu) / df.sd.replace(0, np.nan)
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
        df = pd.DataFrame({"v": s.values, "doy": s.index.dayofyear}, index=s.index)
        clim = df.groupby("doy").v.mean().rolling(15, center=True, min_periods=1).mean()
        scale = (s[-30:].mean() + 1) / (clim.reindex(s[-30:].index.dayofyear).mean() + 1)
        vals = clim.reindex(idx.dayofyear).values * scale; model = "Seasonal climatology (install torch for LSTM)"
    return {"model": model, "forecast": [{"date": str(i.date()), "count": round(float(v), 1)} for i, v in zip(idx, vals)]}
