# Burning Activity Calendar (NASA Space Apps 2026)

React + FastAPI app that harmonizes MODIS and VIIRS active-fire hotspots (NASA FIRMS archive CSVs) into a burning calendar.

## Run
    ./start.sh                       # one command: installs deps, runs backend :8000 + frontend :5173, Ctrl+C stops both

Manual, two terminals:

    cd backend && pip install -r requirements.txt && uvicorn main:app --reload      # :8000
    cd frontend && npm install && npm run dev                                       # :5173

Download CSVs from https://firms.modaps.eosdis.nasa.gov/download/ (MODIS C6.1 and/or VIIRS SNPP/NOAA-20, same country/region), then use **Upload FIRMS CSVs**. Upload several years for anomalies/forecast (needs > 1 year).

Set `ALLOW_ORIGINS` (comma-separated origins) to restrict CORS when deploying; defaults to `*` for local dev. Uploads are capped at 200 MB per file and rows at 2 M; malformed CSVs return HTTP 400 with the reason.

### Demo data
Click **Load demo data** in the app (synthetic MODIS + VIIRS, 2020-2023, seasonal peak around March, a bad 2023 season, 6 planted anomaly days). Or run `python demo.py` in `backend/` to write `demo_modis.csv` / `demo_viirs.csv` and upload them like real FIRMS files.

## Method
- **Harmonization**: unified confidence (MODIS 0-100, VIIRS l/n/h→20/60/90), low-confidence dropped, UTC timestamps, dedupe; per-sensor daily counts rescaled to the best-covered sensor over the overlap period (VIIRS 375 m yields more detections than MODIS 1 km).
- **Calendar**: daily harmonized counts per year, filterable by drawn bounding box.
- **Clusters**: DBSCAN on projected metres + scaled time (eps 550 m, minPts 3, 12 h), convex-hull polygons.
- **Anomalies**: z-score vs same-day (±7d) climatology from other years; critical months = monthly mean > mean+1σ.
- **Forecast**: 30-day LSTM (install `torch`) with seasonal features; falls back to scaled climatology.
