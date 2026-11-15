# Pyro-Harmony - training run on real FIRMS downloads

Run on 2026-09-29 by `firecal/backend/train_data.py`.
PyTorch present: no (forecast uses the seasonal fallback)

## 1. Data

| file | raw rows | harmonized | span | note |
|---|---:|---:|---|---|
| `fire_archive_M-C61_814283.csv` | 2326 | 2200 | 2025-09-30 .. 2026-06-30 |  |
| `fire_nrt_M-C61_814283.csv` | 1528 | 1443 | 2026-07-01 .. 2026-09-22 |  |
| `fire_archive_SV-C2_814286.csv` | 12006 | 11439 | 2025-09-30 .. 2026-06-30 |  |
| `fire_nrt_SV-C2_814286.csv` | 7199 | 6768 | 2026-07-01 .. 2026-09-22 |  |
| `fire_archive_J1V-C2_814284.csv` | 14846 | 14067 | 2025-09-30 .. 2026-06-30 |  |
| `fire_nrt_J1V-C2_814284.csv` | 7610 | 7176 | 2026-07-01 .. 2026-09-22 |  |
| `fire_nrt_J2V-C2_814285.csv` | 21559 | 20345 | 2025-09-30 .. 2026-09-22 |  |

### Harmonized store

- detections: **63438** over **2025-09-30 -> 2026-09-22** (358 days)
- sensors: MODIS 3643, VIIRS 59795
- bounds: [32.5663, -124.381, 42.0036, -114.3055] (minlat, minlon, maxlat, maxlon)
- HFII (sum FRP*ESFP): 848159.2, equivalent standard pixels: 31234.0

### Detections per platform

| sensor family | platform | detections |
|---|---|---:|
| MODIS | Aqua | 1966 |
| MODIS | Terra | 1677 |
| VIIRS | N20 | 21243 |
| VIIRS | N21 | 20345 |
| VIIRS | SNPP | 18207 |

## 2. Models

### Burning-activity calendar (harmonized daily record) - TRAINED

- 358 days, mean 323.1 fires/day, peak 2007.4 on 2026-08-30

### DBSCAN clusters into fire events - TRAINED

- 300 clusters at eps=550.0 m, minPts=3, 12.0 h window
- top cluster 585: 2654 detections, 42530.4 MW, 899.5 h, sensors MODIS, VIIRS
- top cluster 609: 1619 detections, 55022.4 MW, 483.8 h, sensors MODIS, VIIRS
- top cluster 630: 1587 detections, 44875.0 MW, 8341.7 h, sensors MODIS, VIIRS

### Seasonal climatology + percentile envelope - PARTIAL

- years present: [2025, 2026]
- peak day-of-year 235 (p95 1583.42/day)
- fire season DOY 132 -> 309, median 239.5 fires/day
- note: fewer than 3 calendar years, so the percentile envelope is a single-season shape, not a multi-decadal climatology

### Incident Commander briefing (K-means biomes + z-streaks) - PARTIAL

- threat Low (score 1), record mean 323.1 fires/day over 358 days
- z-streaks: 0 (a z-score needs the same day-of-year in *other* years)
- fuel-biome strata: 4
- biome Forest: 15889 detections, mean FRP 18.7 MW, centroid [36.62, -120.499], spread ~143.3 km
- biome Agricultural Crop Residue: 18526 detections, mean FRP 11.7 MW, centroid [38.805, -121.686], spread ~116.2 km
- biome Savanna: 20117 detections, mean FRP 6.5 MW, centroid [34.08, -117.764], spread ~126.7 km
- biome Mediterranean Shrubland: 8906 detections, mean FRP 13.1 MW, centroid [40.867, -122.454], spread ~149.1 km
- recommendation: No sustained anomaly streaks at the chosen z-threshold; routine monitoring is sufficient.
- recommendation: Forest fuel cluster near (36.62, -120.499) carries the highest total FRP (296440.8 MW) — prioritize patrols and firebreak checks.
- recommendation: Agricultural residue burning dominates cluster activity near (38.805, -121.686) — consider a temporary burn ban and farmer outreach.
- recommendation: The last 30 days are running above the record mean — heighten early-warning dissemination.

### Anomalous days vs other years - SKIPPED

- Need >1 year of data

### Forecast (LSTM or seasonal fallback) - TRAINED

- method: Seasonal climatology (install torch for LSTM), horizon 30 days
- first 2026-09-23: 565.7, last 2026-10-22: 532.1, mean 439.5 fires/day

### Sensor Transition Illusion diagnostic - PARTIAL

- 2025: MODIS 807, VIIRS 15498, raw 16305, harmonized 27872.8
- 2026: MODIS 2836, VIIRS 44297, raw 47133, harmonized 87785.2
- observed/adjusted post-2012 growth unavailable: the record has no pre-2012 MODIS era and no 2012-2015 sensor overlap, which is what this diagnostic calibrates against (use the 2002-2024 demo dataset for it)

## 3. What this record can and cannot support

- **Clustering, the calendar and the forecast** work from a single continuous year;
- **anomalies and z-score streaks** compare each day against the same +/-7-day window in
  *other* years, so they need more than one year of overlapping dates;
- **the Sensor Transition Illusion** is calibrated against the pre-2012 MODIS era and the
  2012-2015 MODIS/VIIRS overlap, so it needs the multi-decadal record.

## 4. Appendix - the same diagnostic on the 2002-2024 dataset

- observed growth 102.4% -> adjusted 17.0% (85.4 pp of the jump was the sensor change)
- VIIRS scaling factor 1.73, pre-2012 days 7351, overlap-era days 13121
- 2012-2015 calibration: R2 0.857, RMSE 3.18 MW

## 5. Incident Commander briefing (exported from this data)

```markdown
# Wildfire Intelligence Briefing

**Threat level:** Low (score 1)  
**Record window:** 358 days · mean 323.1 fires/day  
**Last 30 days:** mean 671.0/day · peak 2007.4

## Critical burning periods (z ≥ 2.0σ, ≥ 2d)
- None detected at this threshold.

## Dominant fuel biomes (K-means stratification)
- **Forest** — 15889 fires, mean FRP 18.7 MW, total 296440.8 MW, spread ~143.3 km
- **Agricultural Crop Residue** — 18526 fires, mean FRP 11.7 MW, total 216767.7 MW, spread ~116.2 km
- **Savanna** — 20117 fires, mean FRP 6.5 MW, total 130968.4 MW, spread ~126.7 km
- **Mediterranean Shrubland** — 8906 fires, mean FRP 13.1 MW, total 116379.7 MW, spread ~149.1 km

## Recommendations
- No sustained anomaly streaks at the chosen z-threshold; routine monitoring is sufficient.
- Forest fuel cluster near (36.62, -120.499) carries the highest total FRP (296440.8 MW) — prioritize patrols and firebreak checks.
- Agricultural residue burning dominates cluster activity near (38.805, -121.686) — consider a temporary burn ban and farmer outreach.
- The last 30 days are running above the record mean — heighten early-warning dissemination.
```
