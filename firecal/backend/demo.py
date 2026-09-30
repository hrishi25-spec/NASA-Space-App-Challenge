"""Synthetic FIRMS-style data (northern-Thailand-like region, 2020-2024).

Emits raw MODIS and VIIRS frames in the real FIRMS column layouts so the
normal harmonization pipeline is exercised end to end.

`make_demo` produces the short 2020-2024 set used by the dashboard.
`make_transition_demo` produces a 2002-2024 set that reproduces the
"Sensor Transition Illusion": a 20-year MODIS-only era, a VIIRS ramp-up
after its 2012 launch, and a stable-burn regime afterwards so the
diagnostic has a true trend to recover.
"""
import numpy as np
import pandas as pd

BOX = (17.0, 98.0, 20.0, 101.0)  # minlat, minlon, maxlat, maxlon

# FIRMS reports the *actual* footprint of every detection, so the synthetic rows have
# to be sensor-shaped or the footprint math is meaningless (a 10 km VIIRS pixel does
# not exist).  Nadir cells and edge-of-scan dimensions are the published ones:
#   MODIS 1 km nadir -> 4.83 km along-scan / 2.01 km along-track (Giglio, C6 user guide)
#   VIIRS 375 m nadir -> ~1.17 km both ways, i.e. ~9.7x the nadir area (Schroeder 2014;
#                       2026 VIIRS footprint studies put the edge area at ~9.67x nadir)
NADIR_KM = {"MODIS": 1.0, "VIIRS": 0.375}
EDGE_GROWTH = {"MODIS": (4.83, 2.01), "VIIRS": (3.11, 3.11)}


def _footprint(r, sensor):
    """(scan, track) in km for one detection: nadir-sized near the swath centre, growing
    toward the edge of scan.  Cubed random biases the draw toward nadir, as real swaths
    are (most of a 2,330-3,040 km swath is nowhere near the edge)."""
    gs, gt = EDGE_GROWTH[sensor]
    nadir = NADIR_KM[sensor]
    scan = nadir * (1 + (gs - 1) * r.random() ** 3)
    track = nadir * (1 + (gt - 1) * r.random() ** 3)
    return round(float(scan), 3), round(float(track), 3)


def _center(r, box, margin=0.65):
    """A cluster centre well inside the box: margin > max cluster scatter + detection scatter,
    so a generated row can never land outside the AOI it was requested for."""
    return r.uniform(box[0] + margin, box[2] - margin), r.uniform(box[1] + margin, box[3] - margin)


def _make_fire_rows(r, days, year_mult, spikes, viirs_frac=0.05, cluster=True, scale=1.0,
                    box=BOX):
    """Shared generator body: returns (modis_rows, viirs_rows) lists of tuples.

    `scale` thins fire events globally (used to keep the 23-year transition
    dataset small enough to harmonize in a couple of seconds).  `box` is
    minlat, minlon, maxlat, maxlon -- the preset catalogs pass their own AOI so
    "load demo here" works for any region.
    """
    modis, viirs = [], []
    centers = [_center(r, box) for _ in range(24)]
    for i, d in enumerate(days):
        base = (np.exp(-((d.dayofyear - 75) / 22) ** 2) * 18 + 0.15) * year_mult.get(d.year, 1.0) * scale
        n_ev = r.poisson(base * (5 if i in spikes else 1))
        for _ in range(n_ev):
            if cluster:
                clat, clon = centers[r.integers(0, len(centers))]
                clat += float(np.clip(r.normal(0, 0.25), -0.6, 0.6))
                clon += float(np.clip(r.normal(0, 0.25), -0.6, 0.6))
            else:
                clat, clon = _center(r, box)
            hour = int(np.clip(r.normal(13, 3), 0, 23)); minute = int(r.integers(0, 60))
            acq = hour * 100 + minute
            night = int(r.random() < 0.25)
            for rows, n, sig, sensor in ((viirs, r.integers(3, 14), 300, "VIIRS"),
                                         (modis, r.integers(1, 4), 500, "MODIS")):
                if sensor == "VIIRS" and r.random() < viirs_frac:
                    continue
                scan, track = _footprint(r, sensor)
                lat = clat + np.clip(r.normal(0, sig / 110540, n), -0.01, 0.01)
                lon = clon + np.clip(r.normal(0, sig / 111320, n), -0.01, 0.01)
                for la, lo in zip(lat, lon):
                    rows.append((la, lo, d.strftime("%Y-%m-%d"), acq, r.gamma(2, 6) + 1,
                                 scan, track, night))
    return modis, viirs


def _frame(rows, viirs_fmt, r):
    a = np.array(rows, dtype=object)
    n = len(rows)
    if n == 0:  # possible with extreme seeds / spike draws
        return pd.DataFrame({c: [] for c in ("latitude", "longitude", "acq_date", "acq_time",
                                             "frp", "scan", "track", "daynight")})
    df = pd.DataFrame({
        "latitude": a[:, 0].astype(float), "longitude": a[:, 1].astype(float),
        "acq_date": a[:, 2], "acq_time": a[:, 3].astype(int), "frp": a[:, 4].astype(float),
        "scan": a[:, 5].astype(float), "track": a[:, 6].astype(float), "daynight": a[:, 7].astype(int)})
    if viirs_fmt:
        df["bright_ti4"] = r.normal(345, 12, n); df["bright_ti5"] = r.normal(300, 5, n)
        df["confidence"] = r.choice(["l", "n", "h"], n, p=[0.1, 0.7, 0.2])
        df["satellite"] = r.choice(["N", "J1"], n)   # S-NPP + NOAA-20
        df["instrument"] = "VIIRS"
        df["version"] = "2.0NRT"
    else:
        df["brightness"] = r.normal(335, 15, n); df["bright_t31"] = r.normal(300, 5, n)
        df["confidence"] = np.clip(r.normal(65, 20, n), 0, 100).astype(int)
        df["satellite"] = r.choice(["Terra", "Aqua"], n)
        df["instrument"] = "MODIS"
        df["version"] = "6.1NRT"
    return df


def make_demo(seed: int = 7, box=BOX):
    r = np.random.default_rng(seed)
    days = pd.date_range("2020-01-01", "2024-06-30")
    year_mult = {2020: 0.8, 2021: 0.6, 2022: 1.0, 2023: 1.6, 2024: 1.2}  # 2023 = bad year
    spikes = set(r.choice(len(days), 7, replace=False))                   # planted anomalies
    modis, viirs = _make_fire_rows(r, days, year_mult, spikes, box=box)
    return [_frame(modis, False, r), _frame(viirs, True, r)]


def make_transition_demo(seed: int = 11, box=BOX):
    """2002-2024: MODIS-only era, VIIRS ramp after its 2012 launch, gentle true trend.

    VIIRS rows are kept per-year with a rising availability curve, so raw daily
    counts jump after 2012 purely from the new sensor -- the illusion the
    /diagnostic endpoint is designed to unmask.
    """
    r = np.random.default_rng(seed)
    days = pd.date_range("2002-01-01", "2024-12-31")
    year_mult = {y: 1.0 + 0.02 * (y - 2002) for y in range(2002, 2025)}   # gentle true trend
    spikes = set(r.choice(len(days), 15, replace=False))

    def keep_viirs(date_str):
        y = int(date_str[:4])
        if y < 2012: return False       # pre-VIIRS: no VIIRS rows at all
        if y == 2012: return r.random() < 0.60   # partial launch year
        if y == 2013: return r.random() < 0.75
        if y == 2014: return r.random() < 0.88
        return True                     # 2015+: full VIIRS coverage

    modis, viirs = _make_fire_rows(r, days, year_mult, spikes, viirs_frac=0.0, scale=0.45, box=box)
    viirs = [row for row in viirs if keep_viirs(row[2])]
    return [_frame(modis, False, r), _frame(viirs, True, r)]


if __name__ == "__main__":
    m, v = make_demo()
    m.to_csv("demo_modis.csv", index=False)
    v.to_csv("demo_viirs.csv", index=False)
    print(len(m), "MODIS rows,", len(v), "VIIRS rows written (2020-2024 demo)")
