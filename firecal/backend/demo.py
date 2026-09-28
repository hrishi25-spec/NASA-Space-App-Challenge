"""Synthetic FIRMS-style data (northern-Thailand-like region, 2020-2023).
Emits raw MODIS and VIIRS frames in the real FIRMS column layouts so the
normal harmonization pipeline is exercised end to end."""
import numpy as np, pandas as pd

BOX = (17.0, 98.0, 20.0, 101.0)  # minlat, minlon, maxlat, maxlon

def make_demo(seed: int = 7):
    r = np.random.default_rng(seed)
    days = pd.date_range("2020-01-01", "2023-12-31")
    year_mult = {2020: 0.8, 2021: 0.6, 2022: 1.0, 2023: 1.6}  # 2023 = bad year
    spikes = set(r.choice(len(days), 6, replace=False))       # planted anomalies
    modis, viirs = [], []
    for i, d in enumerate(days):
        base = (np.exp(-((d.dayofyear - 75) / 22) ** 2) * 18 + 0.15) * year_mult[d.year]
        n_ev = r.poisson(base * (5 if i in spikes else 1))
        for _ in range(n_ev):
            clat, clon = r.uniform(BOX[0], BOX[2]), r.uniform(BOX[1], BOX[3])
            hour = int(np.clip(r.normal(13, 3), 0, 23)); minute = int(r.integers(0, 60))
            acq = hour * 100 + minute
            for rows, n, sig, sensor in ((viirs, r.integers(3, 14), 300, "VIIRS"), (modis, r.integers(1, 4), 500, "MODIS")):
                if sensor == "VIIRS" and r.random() < 0.05: continue
                lat = clat + r.normal(0, sig / 110540, n); lon = clon + r.normal(0, sig / 111320, n)
                for la, lo in zip(lat, lon):
                    rows.append((la, lo, d.strftime("%Y-%m-%d"), acq, r.gamma(2, 6) + 1))
    def frame(rows, viirs_fmt):
        a = np.array(rows, dtype=object); n = len(rows)
        if n == 0:  # possible with extreme seeds / spike draws
            return pd.DataFrame({"latitude": [], "longitude": [], "acq_date": [], "acq_time": [], "frp": []})
        df = pd.DataFrame({"latitude": a[:, 0].astype(float), "longitude": a[:, 1].astype(float),
                           "acq_date": a[:, 2], "acq_time": a[:, 3].astype(int), "frp": a[:, 4].astype(float)})
        if viirs_fmt:
            df["bright_ti4"] = r.normal(345, 12, n); df["bright_ti5"] = r.normal(300, 5, n)
            df["confidence"] = r.choice(["l", "n", "h"], n, p=[0.1, 0.7, 0.2]); df["satellite"] = "N"
            df["instrument"] = "VIIRS"
        else:
            df["brightness"] = r.normal(335, 15, n); df["bright_t31"] = r.normal(300, 5, n)
            df["confidence"] = np.clip(r.normal(65, 20, n), 0, 100).astype(int); df["satellite"] = "Terra"
            df["instrument"] = "MODIS"
        return df
    return [frame(modis, False), frame(viirs, True)]

if __name__ == "__main__":  # write CSVs you can upload through the UI
    m, v = make_demo(); m.to_csv("demo_modis.csv", index=False); v.to_csv("demo_viirs.csv", index=False)
    print(len(m), "MODIS rows,", len(v), "VIIRS rows written")
