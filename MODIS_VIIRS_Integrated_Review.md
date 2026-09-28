# Integrated Review: MODIS & VIIRS Remote Sensing Papers (7 papers)

> Compiled from the seven uploaded PDFs. The papers do not share one research question, so this document is organised by **sensor → product → application → method**, with cross-paper comparisons and a critical-notes section.
>
> **Note on filenames:** the uploaded filenames (e.g. `MODIS_2017`, `VIIRS_2020`) do not reliably match the publication years inside the PDFs. Papers below are identified by title and venue, not filename.

**In one paragraph:** seven IGARSS/JSTARS papers spanning MODIS, VIIRS and LJ1-01 show a common arc — *upstream calibration (P6) determines whether downstream trend claims (P1) are real*; *sensor resolution drives accuracy on heterogeneous surfaces (P3, P7)*; and *accuracy comes from fusing ancillary data — DEM, meteorology, AOD, NTL — rather than from any single sensor (P2, P4, P7)*. Reported accuracies range from simulation-only RMSEs (P5) to station-validated CV R² 0.79–0.87 (P7 winter). Critical notes in §4 flag one non-significant headline predictor (P7), three inconsistent input counts/units (P2, P7), and two citation-unsafe references (P4, P6).

## Table of contents

1. [Master overview](#1-master-overview)
2. [Individual paper summaries](#2-individual-paper-summaries)
3. [Cross-paper synthesis](#3-cross-paper-synthesis) — 3.1 sensors · 3.2 methods · 3.3 themes · 3.4 accuracy · 3.5 band reference · 3.6 study periods · 3.7 evidence quality
4. [Critical notes and inconsistencies](#4-critical-notes-and-inconsistencies) — incl. 4.1 cross-paper consistency checks
5. [How the papers fit together](#5-how-the-papers-fit-together)
6. [Collated limitations and future work](#6-collated-limitations-and-future-work)
7. [Glossary](#7-glossary)
8. [Relevance to Pyro-Harmony](#8-relevance-to-pyro-harmony) and [feature backlog](#9-feature-backlog-from-the-review-added)
9. [Reference list](#reference-list)

> **Provenance note (added during review):** sections 1–7 are as compiled from the source PDFs; sections marked *added* in this revision (TOC, §3.5–3.7, §4.1, §6, §8–9, renumbered references) derive only from the content already in this document — no new external sources were consulted. The original author's confidence tags are preserved verbatim.

---

## 1. Master Overview

| # | Paper (short name) | Venue / Year | Sensor(s) | Core topic | Headline result |
|---|---|---|---|---|---|
| P1 | Long-term variation of global LAI & uncertainty (GEOV2 vs MODIS) | IGARSS 2020 | MODIS (MCD15A2H V6), SPOT/VGT + PROBA-V (GEOV2) | LAI trend and product uncertainty, 2003–2018 | LAI rising in both products; GEOV2 uncertainty rises 0.019/decade, MODIS stable |
| P2 | Reconstructing MODIS LST over Tibetan Plateau with Random Forest | IGARSS 2020 | MODIS (MOD11A1, MOD09A1, MOD15A2), ASTER DEM | Gap-filling / improving LST | Test RMSE 2.693 K, r = 0.815; network-scale RMSE 1.618 K |
| P3 | MODIS LAI validation with DHP, Bhitar Kanika mangroves | IGARSS 2019 | MODIS (MOD15A2H, MOD13Q1) | Improved 250 m LAI via modified Choudhury method | Modified model r = 67.4% vs MOD15A2H 44% (15 plots) |
| P4 | Pasture intensification in the Brazilian Amazon | IGARSS 2017 | MODIS EVI time series | Pasture management classification (TWDTW) | Fertilised/renewed/iCL pastures separable at farm scale |
| P5 | Net Surface Shortwave Radiation (NSSR) from VIIRS | IGARSS 2018 | VIIRS (I1–I4, M1–M3) | NSSR retrieval via MODTRAN 5 simulation | Albedo conversion RMSE 0.011; NSSR RMSE 50.2 W/m² (clear sky, simulated) |
| P6 | Reprocessing of Suomi NPP VIIRS SDRs | IGARSS (NOAA STAR) | VIIRS (RSB, TEB, DNB) | Calibration improvements | ~2% F-factor change in M2–M4; WUCD SST artefact (~0.3 K) removed; DNB dark offset/straylight fixed |
| P7 | LJ1-01 vs NPP-VIIRS nighttime lights for PM2.5 | IEEE JSTARS 2020 | LJ1-01, VIIRS DNB, MODIS AOD | Monthly PM2.5 estimation (GWR) | Adding NTL raises seasonal R² (fit) 2.6–5.1%; LJ1-01 beats VIIRS by ~0.8–1.8% |

---

## 2. Individual Paper Summaries

### P1 — Long-term Variation of Global LAI and the Uncertainty: GEOV2 and MODIS
**Authors:** H. Fang, Y. Wang, Y. Zhang, S. Li (CAS, Beijing)

**Problem.** Validation studies measure LAI *uncertainty*, but nobody had examined LAI *stability* over time. GCOS requires ≤15% uncertainty and stability of ≤10% (relative) or 0.25 per decade (absolute).

**Data.**
- **GEOV2:** SPOT/VEGETATION then PROBA-V, ~1 km (1/112°), 10-day, neural network trained on fused MODIS + CYCLOPES LAI. Quantitative uncertainty = RMSE; quality flag = LAIQFLAG.
- **MODIS V6 MCD15A2H:** 500 m, 8-day, LUT-based radiative transfer algorithm with 8 biome types. Uncertainty = LaiStdDev; quality flag = FparLAI_QC (main retrievals only).

**Method.** Mosaic, resample to 0.01° (nearest neighbour), aggregate monthly, exclude cloudy/filled pixels. Relative uncertainty = QQI / LAI.

**Results (2003–2018).**

| Metric | GEOV2 | MODIS |
|---|---|---|
| Global LAI trend | +0.045 /decade | +0.019 /decade |
| LAI uncertainty trend | +0.019 /decade (increasing) | ~0.002 /decade (stable) |
| Relative uncertainty | +0.8 %/decade | −0.027 %/decade |

- Spring (MAM) and summer (JJA) show the strongest increases in GEOV2 uncertainty.
- **Savanna:** LAI +0.074/decade, uncertainty +0.033/decade, relative uncertainty +0.009/decade (GEOV2).
- **Forests:** LAI stable in both; GEOV2 uncertainty rises for all forest biomes, abruptly for EBF after 2014, attributed to the SPOT/VGT → PROBA-V switch.
- **Urban:** LAI < 1.0, slight decline since 2013; uncertainty stable.

**Takeaway.** A "trend" in a satellite product can be partly a sensor artefact. Uncertainty layers should be analysed temporally, not just spatially.

---

### P2 — Reconstructing MODIS LST over the Tibetan Plateau Using Random Forest
**Authors:** Y. Cheng, Y. Li, H. Wu, F. Li, Y. Li, L. He

**Problem.** MODIS LST has limited overpass times (~4/day), terrain/climate-dependent accuracy, and cloud contamination.

**Study area / ground truth.** Maqu network (NE Tibetan Plateau, 33.5–34.25°N, 101.63–102.75°E), 20 stations, ~40 × 80 km; LST at 10:00 AM, May 2008–Oct 2015 (May–Oct only, to avoid snow/frozen soil).

**Inputs to RF.** NIR reflectance and NDVI (MOD09A1), day & night LST (MOD11A1), LAI (MOD15A2), elevation (ASTER GDEM 30 m). All resampled to 1000 m, WGS84.

**Model.** Random Forest (bootstrap row sampling + random feature selection; prediction = mean of T trees). 16,615 points (2008–2014): 80% train / 20% validate; 1,796 points from 2015 as an independent temporal test.

**Results.**

| Dataset | RMSE (K) | MAE (K) | R |
|---|---|---|---|
| Training | 1.768 | 1.223 | 0.939 |
| Validation | 2.257 | 1.483 | 0.925 |
| Testing (2015) | 2.693 | 1.901 | 0.815 |
| Network-averaged 2015 time series | 1.618 | 1.336 | 0.913 |

**Takeaway.** RF can correct MODIS LST toward in-situ values and fill gaps, but accuracy degrades on unseen years (train→test RMSE +0.9 K). Only one of three TP-SMTMN networks (Maqu) was used.

---

### P3 — Evaluation of MODIS LAI with Digital Hemispherical Photography, Bhitar Kanika Mangroves
**Authors:** S. Paramanik, M. D. Behera, B. K. Bhattacharya, S. Tripathi (IIT Kharagpur, ISRO, Odisha Forest Dept.)

**Problem.** MOD15A2H (500 m) over- or under-estimates LAI, and produces implausible values (25–50, or zero where NDVI = 0.6).

**Study area.** Bhitar Kanika mangrove sanctuary, Odisha (672 km², 86°48′–87°03′E, 20°33′–20°47′N).

**Method — ModcModLAIE (modified Choudhury).**
- Fractional cover: `f = 1 − ln{(NDVImax − NDVI)/(NDVImax − NDVImin)}^(1/ε)`
- LAI: `LAI = 1 − ln{(1 − f)/(−β)}`
- ε (canopy leaf-angle distribution; ~0.8 planophile to ~1.4 erectophile) and β (extinction; 0.42–0.91) are *derived per pixel* from NDVI, view angle and solar zenith from **MOD13Q1 (250 m)** rather than fixed.
- Ground truth: DHP (Nikon D5300 + fisheye), 20 × 20 m plots, 13 photos per plot, processed in CAN-EYE (Beer–Lambert gap fraction; Miller's formula for PAI). Data: Oct–Dec 2018.

**Results.**
- MOD15A2H LAI mostly 4–5; ModcModLAIE mostly 2–4.
- Correlation with DHP LAI (15 plots): **ModcModLAIE 67.4% vs MOD15A2H 44%**.
- The modified model avoided the spurious zero/25–50 values.

**Takeaway.** Deriving canopy parameters per pixel improves LAI and yields 250 m resolution from MODIS inputs, but validation is thin (15 plots, one site, one season).

---

### P4 — Monitoring Pasture Intensification in the Brazilian Amazon with MODIS Time Series
**Authors:** V. D. Manabe, M. R. S. Melo, J. V. Rocha (UNICAMP)

**Problem.** Statistics show expansion of agriculture and sugarcane over pasture, but management intensity (renewal, fertilisation, integrated crop-livestock, iCL) is poorly mapped.

**Method.** Two-year MODIS EVI time series (2015–2016) over sites in Mato Grosso and Pará; field data on stocking rate, forage type and management. Classification via **Time-Weighted Dynamic Time Warping (TWDTW)**, which aligns time series and returns a dissimilarity measure.

**Results.**
- **Mato Grosso:** recently renewed pasture reaches its EVI peak earlier and faster; iCL (soy + pasture) has a distinct annual cycle. A shortened June–September window separates iCL from double-crop (maize/millet), since iCL keeps higher EVI from pasture.
- **Pará:** fertilised and unfertilised pastures reach similar maximum EVI, but fertilised pasture grows faster after the onset of rains (Jan–Feb).

**Takeaway.** Management classes are separable at farm scale using TWDTW distance; regional-scale mapping is the stated next step. This is a short abstract-style paper with qualitative evidence and no accuracy metrics.

---

### P5 — Net Surface Shortwave Radiation Retrieval Using VIIRS Data
**Authors:** W. Ying, H. Wu, Z.-L. Li (CAS)

**Problem.** Few NSSR studies use VIIRS narrowband data.

**Method.**
1. NSSR = α′·(E₀cosθₛ / D²) − β′·F_u, with F_u = r · E₀cosθₛ / D² (r = TOA broadband albedo).
2. α′ and β′ are functions of cosine solar zenith, precipitable water, and constants a₁–a₇, x, y, z (Table 1 of the paper).
3. Narrowband→broadband albedo: `r = b₀ + Σ bᵢρᵢ` over 7 VIIRS bands (I1–I4, M1–M3), with bᵢ depending on view zenith and constants cᵢ.
4. Coefficients fitted by least squares on **MODTRAN 5** simulations: 9 surface spectra, 6 atmospheres, 4 aerosol models, 4 visibilities, 6 view angles, 8 solar angles, 3 relative azimuths = **124,416 clear-sky cases**.

**Results.**
- Narrowband→broadband albedo: **RMSE 0.011, R² = 0.995**.
- NSSR (clear sky): **RMSE 50.2 W/m²**.
- TOA upward flux vs NSSR is linear at fixed SZA and independent of surface type.

**Takeaway.** Clear-sky, simulation-only, no in-situ validation. Authors list cloud conditions, ground validation and machine learning as future work.

---

### P6 — Reprocessing of Suomi NPP VIIRS Sensor Data Records (SDRs)
**Authors:** F. Weng, T. Choi, C. Cao, B. Zhang (NOAA STAR)

**Context.** S-NPP launched 28 Oct 2011; VIIRS has 14 reflective solar bands (RSB), 7 thermal emissive bands (TEB), and a Day/Night Band (DNB); 375 m (I-bands) / 750 m (M-bands); 112.56° scan.

**Issues and fixes.**

| Component | Issue in operational (IDPS) product | Reprocessing fix |
|---|---|---|
| **RSB** | F-factor updated suddenly on 23 May and 11 Jul 2014 (solar diffuser degradation curvature); annual oscillations; ocean-colour bias in M1–M4 | Smoother F-factor LUTs (RSBAutoCal); long-term lunar corrections adopted; F-factor changes ~2% in M2–M4 over five years |
| **TEB** | Blackbody Warm-Up-Cool-Down (WUCD) causes F-factor anomalies in M15/M16 → periodic ~0.3 K "global warming" in SST | Empirical Ltrace correction; validated with CrIS; September 19–21, 2016 WUCD anomaly greatly reduced |
| **DNB** | Time-varying spectral response (RTA mirror Tungsten contamination); poor pre-20 Mar 2012 calibration (no dark offset/gain ratio); negative night radiances; stray light before Aug 2014 | Time-dependent RSR in LGS gain; deep-space pitch-manoeuvre dark offset (DN0); new gain-ratio tables; stray-light LUT; terrain correction |

**Takeaway.** Mission-long reprocessing is needed for climate-quality time series (SST, ocean colour, nightlights). Any multi-year VIIRS analysis on operational IDPS data inherits these artefacts.

---

### P7 — Evaluation of LJ1-01 Nighttime Light for Monthly PM2.5: Comparison with NPP-VIIRS
**Authors:** G. Zhang, Y. Shi, M. Xu (Wuhan University) — *IEEE JSTARS, vol. 13, 2020*

**Study area / data.** Beijing–Tianjin–Hebei (BTH), 99 PM2.5 stations, June 2018–May 2019.
- **NTL:** LJ1-01 (130 m, 0.46–0.98 µm, 250 km swath, launched 2 June 2018; 8 moonless cloudless scenes Aug 20–Oct 13, 2018) vs NPP-VIIRS DNB monthly composite (750 m, Aug–Oct 2018 average).
- **AOD:** Terra + Aqua MODIS L2 10 km; gaps filled by regression (τ_AQUA = 0.8406 τ_TERRA + 0.0517; τ_TERRA = 0.9137 τ_AQUA + 0.0621).
- **Covariates:** ERA-Interim meteorology (TEM, WIN, RHU, PBLH), SRTM DEM, MODIS MOD13A3 EVI/NDVI.

**Model.** Geographically weighted regression (GWR) with 5 variants: NP (VIIRS NTL), LJ (LJ1-01 NTL), AOD, NP-AOD, LJ-AOD; 10-fold cross-validation.

**Results.**
- **EVI beats NDVI:** fit R² 0.78 vs 0.72 (LJ1-01); 0.75 vs 0.69 (VIIRS). Cross-validation R² 0.71 vs 0.65 (LJ) with RMSE 7.45 vs 8.42 µg/m³.
- **Adding NTL to AOD model:** seasonal fit R² +5.07%, +4.50%, +2.95%, +2.56%; CV +1.20%, +1.75%, +2.20%, +4.41%.
- **LJ1-01 vs VIIRS (in AOD model):** fit +1.16%, +1.79%, +0.76%, +1.15%; CV +1.04%, +0.85%, +0.78%, +1.37%.
- Best seasonal fit R² (GWR-LJ-AOD): 0.77 spring, 0.79 summer, 0.83 autumn, 0.87 winter.
- Winter is most polluted (predicted mean ~71.3 µg/m³); summer cleanest (~36.5); annual ~48.8 µg/m³ (above China's 35 µg/m³ standard).
- Models overestimate low PM2.5 (<50) and underestimate high (>60).

**Limitations acknowledged.** Small LJ1-01 swath/15-day revisit, moonlight contamination, AOD gaps (Chengde, Zhangjiakou), single overpass time, resolution mismatches.

---

## 3. Cross-Paper Synthesis

### 3.1 Sensors and products used

| Sensor / product | Resolution | Used in | Role |
|---|---|---|---|
| MODIS MCD15A2H / MOD15A2 (LAI/FPAR) | 500 m, 8-day | P1, P2, P3 | Vegetation structure; target of evaluation (P1, P3) or predictor (P2) |
| MODIS MOD13Q1 / MOD13A3 (NDVI/EVI) | 250 m / 1 km | P3, P7 | Input to LAI model (P3); vegetation covariate (P7) |
| MODIS EVI time series | 250 m | P4 | Phenology-based classification |
| MODIS MOD11A1 (LST) & MOD09A1 (reflectance) | 1 km / 500 m | P2 | RF inputs |
| MODIS L2 AOD (Terra + Aqua) | 10 km | P7 | Primary PM2.5 predictor |
| GEOV2 (SPOT/VGT, PROBA-V) | ~1 km | P1 | Comparator LAI product |
| VIIRS I/M bands | 375 / 750 m | P5, P6 | Radiation retrieval; calibration |
| VIIRS DNB | 750 m | P6, P7 | Nighttime light; calibration issues (P6) affect P7-type analyses |
| LJ1-01 NTL | 130 m | P7 | High-resolution NTL |
| ASTER GDEM / SRTM DEM | 30 / 90 m | P2, P7 | Terrain covariate |

### 3.2 Methods by paper

| Approach | Papers | Notes |
|---|---|---|
| Physical / radiative transfer modelling | P1 (MODIS LUT), P5 (MODTRAN 5), P3 (Choudhury canopy model) | P5 is entirely simulation-based |
| Machine learning | P2 (Random Forest), P1 (GEOV2 neural network) | P5 suggests ML as future work |
| Statistical regression | P7 (GWR), P5 (least squares) | |
| Time-series analysis | P1 (trends), P4 (TWDTW) | |
| Ground validation | P2 (Maqu stations), P3 (DHP), P7 (PM2.5 stations), P4 (field campaigns) | P1 and P5 lack direct ground validation |
| Calibration / data-quality engineering | P6 | Upstream of everything else |

### 3.3 Themes that connect the papers

1. **Product quality is not static.** P1 shows GEOV2 uncertainty drifting (and jumping in 2014 with the sensor change); P6 shows VIIRS F-factors jumping in May/July 2014 as well. **Both flag 2014 as a discontinuity year.** [Likely] this coincidence is not causal between the two (different instruments), but it illustrates that trend studies spanning 2014 need artefact checks.
2. **Coarse products mislead at fine scale.** P3 finds MOD15A2H unreliable in mangroves at 500 m and builds a 250 m alternative; P7 finds 130 m LJ1-01 outperforms 750 m VIIRS DNB. Resolution matters for heterogeneous surfaces.
3. **LAI is a hub variable.** It is a product to evaluate (P1, P3), an input to LST reconstruction (P2), and closely tied to vegetation indices used in P4 and P7.
4. **Vegetation indices are not interchangeable.** P7 shows EVI outperforming NDVI; P3 relies on NDVI in Choudhury's method; P4 uses EVI for phenology.
5. **Ancillary data drive gains.** In P2 (elevation, LAI, NDVI), P7 (meteorology, AOD, NTL) and P4 (field management data), accuracy came from combining sources rather than a single sensor.
6. **Uncertainty reporting.** P1 (RMSE/StdDev layers), P5 (RMSE 50.2 W/m²) and P2 (RMSE by dataset) each quantify error differently, so numbers are not directly comparable across papers.

### 3.4 Quantitative comparison of reported accuracy

| Paper | Target variable | Metric | Value | Validated against |
|---|---|---|---|---|
| P1 | LAI stability | Trend | GEOV2 +0.045, MODIS +0.019 /decade | No reference (inter-product) |
| P2 | LST (K) | RMSE (test) | 2.693 K | In-situ Maqu stations |
| P3 | LAI | Correlation | 67.4% (new) vs 44% (MOD15A2H) | DHP, 15 plots |
| P4 | Pasture class | — | Qualitative | Field samples |
| P5 | Broadband albedo | RMSE / R² | 0.011 / 0.995 | MODTRAN simulation |
| P5 | NSSR | RMSE | 50.2 W/m² | MODTRAN simulation |
| P7 | PM2.5 (µg/m³) | CV R² (LJ-AOD) | 0.72 / 0.73 / 0.79 / 0.85 (spr/sum/aut/win) | 99 stations |

### 3.5 Band / product quick reference *added*

Consolidated from the papers' instrument descriptions (P5, P6, P7 are the sources for VIIRS specifics).

| Instrument | Bands relevant here | Resolution | Notes |
|---|---|---|---|
| MODIS (Terra 1999 / Aqua 2002) | 36 bands, 0.4–14 µm; red/NIR for VI/EVI; thermal for LST (MOD11) | 250 m (bands 1–2), 500 m, 1 km | Collections used: C6.1 active-fire, MCD15A2H V6 LAI, MOD13Q1/A3 VI, MOD11A1 LST, MOD09A1 reflectance |
| VIIRS (S-NPP 2011; NOAA-20 2017; NOAA-21 2018) | 14 RSB + 7 TEB + DNB; I1–I4 (0.64–3.7 µm) & M1–M3 (0.41–0.49 µm) used in P5 | 375 m (I), 750 m (M), 112.56° scan | Active fire: I-bands/M-bands with `bright_ti4`; confidence as l/n/h, not numeric |
| VIIRS DNB | 0.5–0.9 µm panchromatic, night | 750 m | Suomet reprocessing artefacts (P6: RTA contamination, stray light pre-Aug 2014) directly affect P7-style NTL analyses |
| LJ1-01 (2018) | 0.46–0.98 µm, night | 130 m, 250 km swath | 8 usable moonless scenes for BTH; 15-day revisit claimed (but cf. §4, P7) |
| SPOT/VGT → PROBA-V | — | ~1 km (1/112°) | GEOV2 LAI lineage; the 2014 switch is P1's suspected EBF discontinuity |
| ASTER GDEM / SRTM | — | 30 m / 90 m | Terrain covariates in P2, P7 |

**MODIS vs VIIRS for active fire (the Pyro-Harmony use case):** VIIRS 375 m detects ~2–4× more hotspots than MODIS 1 km over the same scene (the headline reason for harmonization in this repo's app); MODIS provides the 2000–2012 historical baseline that VIIRS cannot.

### 3.6 Study periods and data availability *added*

| Paper | Study period | Temporal resolution | Spatial extent |
|---|---|---|---|
| P1 | 2003–2018 | monthly | global |
| P2 | May 2008–Oct 2015 (May–Oct only) | daily @ 10:00 | Maqu network, ~40 × 80 km |
| P3 | Oct–Dec 2018 (field); product dates unstated | 8-day/16-day composites | 672 km² sanctuary |
| P4 | 2015–2016 (2 EVI years) | 16-day composites | sites in Mato Grosso, Pará |
| P5 | unstated (simulation) | — | — |
| P6 | mission-long (2011–2016+) | — | global SDRs |
| P7 | Jun 2018–May 2019 | monthly | BTH region |

Observation: only P1 spans more than a decade; **no paper covers both the MODIS-era and VIIRS-era of the same variable** — which is exactly the gap the Sensor Transition Illusion analysis (this project) targets. P4 and P6 lack stated periods entirely, part of the citation-unsafety flagged in §4.

### 3.7 Evidence-quality assessment *added*

Ranked by strength of validation evidence, following the papers' own confidence tags from §4:

| Tier | Papers | Why |
|---|---|---|
| Station-validated, independent test | P2 (2015 hold-out year), P7 (99 stations, 10-fold CV) | strongest; both still carry the autocorrelation/leakage caveats below |
| Ground-truthed but small n | P3 (15 plots, 1 season), P4 (field campaigns, no metrics) | directionally useful, not generalizable |
| Simulation-only | P5 (fit and tested on MODTRAN cases) | no independent or in-situ validation at all |
| Inter-product (no reference) | P1 | trend comparison between two products, neither ground-validated here |
| Calibration engineering | P6 | validated against CrIS/lunar/dark-space references — a different, specialist sense of "validated" |

Cross-cutting: P2's random 80/20 split [Likely] leaks spatial/temporal autocorrelation (its own 2015 test shows the honest number); P5 validates on the same distribution used for fitting; P1 has no statistical significance test on its headline trends. **Rule of thumb this review supports: treat random-split ML accuracy as an upper bound; trust the temporal hold-out.**

---

## 4. Critical Notes and Inconsistencies

Items I noticed while reading. Confidence tags in brackets.

**P1 (LAI stability)**
- [Certain] MODIS relative uncertainty is reported as slightly decreasing "0.027%/decade" while MODIS LAI increases 0.019/decade; the text calls the MODIS uncertainty "stable (~0.002/decade)". Fine, but the sign and unit conventions are not defined.
- [Certain] Both trends (0.045 and 0.019 per decade) are well below the GCOS stability limit of 0.25/decade, yet the paper frames uncertainty growth as "significant". Significance is not tested statistically in the text.
- [Likely] The EBF jump being caused by the SPOT/VGT → PROBA-V switch is presented as "possibly"; no controlled test is shown.

**P2 (LST RF)**
- [Certain] Spectral range typo: "0.4 to 0.14 µm" (should be ~14 µm).
- [Certain] Text says "5 LST related indices" but lists four (NDVI, LAI, NIR reflectance, elevation) plus day/night LST elsewhere; input count is inconsistent.
- [Likely] Random 80/20 split of 16,615 points likely has spatial/temporal autocorrelation, so validation R (0.925) is optimistic; the 2015 test (0.815) is the honest figure.
- [Certain] Only clear-sky MOD09A1 scenes were used, so the "reconstruction" claim for cloudy periods is not actually tested.

**P3 (Mangrove LAI)**
- [Certain] "Correlation" is reported as a percentage (67.4% vs 44%) without specifying r or R²; n = 15 plots.
- [Likely] Comparing 250 m MOD13Q1-derived LAI to 20 × 20 m DHP plots involves a large scale mismatch; both products' LAI range (4–5 vs 2–4) differ systematically and it is not shown which matches DHP magnitude.
- [Certain] Minor formula typesetting issues (e.g., LAI equation as extracted is ambiguous); reference section is numbered "11".

**P4 (Pasture)**
- [Certain] Title spelling ("intesification") and the time-series period appears garbled in extraction ("202015 – 2016"); read as 2015–2016.
- [Certain] No accuracy assessment, sample sizes or confusion matrices; conclusions are qualitative.

**P5 (NSSR VIIRS)**
- [Certain] RMSE 50.2 W/m² on simulated data is large; the validation is against the same simulation used for fitting, not independent data.
- [Certain] Text refers to "Eq. (8)" for reflectance but it is Eq. (7); also the abstract names NPOESS while VIIRS flew on Suomi NPP.
- [Likely] Clear-sky-only limits operational usefulness.

**P6 (VIIRS reprocessing)**
- [Certain] Section numbering skips to "11. References"; text references "Fig. 7" for straylight etc. consistent, but Figure 3 discussion says OC water-leaving radiance "shows a stable trend" for the reprocessed data while the text claims issues are "expected" to be resolved, i.e. not yet demonstrated.
- [Certain] This is a summary paper with figures as the primary evidence; few numeric error metrics are given.

**P7 (LJ1-01 PM2.5)**
- [Certain] **Correlations of LJ1-01 (r = 0.197, p = 0.168) and DNB (r = 0.165, p = 0.241) with PM2.5 are not significant** (Table VI), yet the paper concludes NTL is useful. The gain comes from interaction within GWR, not direct correlation.
- [Certain] Table V lists NDVI mean/SD (0.44 ± 0.15) but the text states NDVI 0.49 ± 0.27, identical to AOD; and the text says "June 2008 to May 2019" for predictions while data are June 2018–May 2019. Text and table are inconsistent.
- [Certain] NTL is treated as constant through the year (Aug–Oct 2018 snapshot), so it cannot explain *temporal* variation, only spatial.
- [Likely] Improvements of LJ1-01 over VIIRS (~1% R²) are small relative to what fold-to-fold variation could produce; no significance test is reported. LJ1-01 also has a spatial resolution advantage and only 8 scenes cover BTH.
- [Certain] The text claims LJ1-01 revisit of 15 days in the limitations section while Table II lists 12 h; inconsistent.

---

### 4.1 Cross-paper consistency checks *added*

Inconsistencies *between* the papers' numbers (the notes above are within-paper):

1. **VIIRS band count.** P6 says 14 RSB + 7 TEB + DNB (22 total); P5 uses "7 VIIRS bands (I1–I4, M1–M3)" for broadband albedo. Both are correct in context (P5 uses a subset), but any summary that says "VIIRS has 7 bands" would be wrong.
2. **"Correlation" units differ.** P3 reports r as a percentage (67.4%), P2 reports R (0.815), P7 reports R². The three are not comparable; the accuracy table in §3.4 keeps the papers' original units for this reason.
3. **RMSE magnitudes across variables are incomparable.** 2.693 K (P2), 50.2 W/m² (P5), 7.45 µg/m³ (P7) look similar as "RMSE + number" but live on different scales with different validation bases (see §3.7 tiers).
4. **Two different "2014 discontinuity" stories.** P1 (SPOT/VGT→PROBA-V switch) and P6 (RSB F-factor jumps, May/Jul 2014) are independent instruments; the coincidence is noted in §3.3 item 1 but should not be read as one event.
5. **VIIRS launch dates.** P6: S-NPP 28 Oct 2011. P7 implies operational DNB composites by Aug 2018, consistent. LJ1-01 (2 Jun 2018) overlaps only ~3 months of the P7 study window — worth remembering when reading its headline gains.
6. **MODIS Collection mismatch risk.** P1 uses MCD15A2H **V6**, P3 MOD15A2H (collection unstated). C6→C6.1 changed active-fire counts noticeably; LAI collection differences between P1 and P3 are unquantified.

## 5. How the Papers Fit Together (Workflow View)

```
Sensor calibration (P6: VIIRS SDR reprocessing)
        │
        ▼
Level-2/3 products ── LAI (P1, P3) ── Vegetation indices (P4, P7)
        │                  │
        │                  ▼
        │            LST correction (P2 uses LAI/NDVI/DEM)
        ▼
Radiation & environmental retrievals
   ├─ NSSR from VIIRS (P5)
   └─ PM2.5 from AOD + nightlights (P7; NTL quality depends on P6-type calibration)
        │
        ▼
Applications: land management (P4), climate stability (P1), air quality (P7)
```

---

## 6. Collated Limitations and Future Work *added*

Every limitation stated by the papers themselves, plus this review's additions, in one scannable list (source paper in brackets).

| # | Limitation / future work | Source |
|---|---|---|
| 1 | Uncertainty trends lack statistical significance testing; EBF jump attribution untested | P1 + this review |
| 2 | Only 1 of 3 TP-SMTMN networks; clear-sky inputs only, so cloudy-period reconstruction untested; random split inflates accuracy | P2 + this review |
| 3 | 15 plots, one site, one season; scale mismatch between 250 m product and 20 m plots; LAI magnitude bias unquantified | P3 + this review |
| 4 | No accuracy metrics or confusion matrices; regional mapping is future work | P4 |
| 5 | Clear-sky, simulation-only; cloudy-sky, in-situ validation and ML listed as future work by the authors | P5 |
| 6 | OC improvements "expected", not demonstrated; few numeric metrics | P6 + this review |
| 7 | NTL–PM2.5 direct correlations not significant (gain is GWR interaction); NTL is a spatial snapshot, cannot explain temporal variation; ~1% LJ-vs-VIIRS gains untested for significance; single overpass; AOD gaps; resolution mismatches; 15-day vs 12 h revisit inconsistency | P7 + this review |
| 8 | **Cross-cutting:** multi-year trend studies spanning 2012–2015 need artefact checks for both the VIIRS deployment and the 2014 calibration events | this review |

## 7. Glossary

| Term | Meaning |
|---|---|
| AOD | Aerosol optical depth |
| DHP | Digital hemispherical photography |
| DNB | Day/Night Band (VIIRS) |
| EVI / NDVI | Enhanced / Normalized Difference Vegetation Index |
| GCOS | Global Climate Observing System |
| GEOV2 | Copernicus/Geoland2 LAI product from SPOT/VGT and PROBA-V |
| GWR | Geographically weighted regression |
| iCL | Integrated crop-livestock system |
| LAI | Leaf area index |
| LST | Land surface temperature |
| LUT | Look-up table |
| NSSR | Net surface shortwave radiation |
| NTL | Nighttime light |
| QQF / QQI | Qualitative quality flag / quantitative quality indicator |
| RF | Random Forest |
| RSB / TEB | Reflective solar bands / thermal emissive bands |
| SDR | Sensor Data Record |
| TOA | Top of atmosphere |
| TWDTW | Time-Weighted Dynamic Time Warping |
| WUCD | Warm-Up-Cool-Down (VIIRS blackbody cycle) |
| FRP | Fire radiative power |
| ESFP | Equivalent standard fire pixels (nadir-normalized fire-pixel count; see repo README) |
| HFII | Harmonized fire intensity index, Σ FRP·ESFP (this project) |

## 8. Relevance to Pyro-Harmony *added*

This repo harmonizes MODIS + VIIRS active fire into one burning-activity calendar. The seven papers bear on it directly:

| Paper | What it warns or enables for this project |
|---|---|
| P1 | The project's core pitch — that the post-2012 hotspot surge is a *sensor artefact*, not a fire boom — is P1's thesis (sensor-change artefacts masquerading as trends) applied to active fire instead of LAI. P1's method (compare trend + uncertainty across products over the same period) is a template for validating our harmonized series. |
| P2 | Random-Forest gap-filling of a geophysical product with ancillary covariates (NDVI, LAI, DEM) is exactly what a future "fill cloudy-day / missing-day" feature for the calendar would look like. Its temporal-holdout discipline (test on unseen 2015) is the right evaluation pattern. |
| P3 | Shows biome-specific canopy parameters beat fixed ones (mangroves). Analogue: our per-sensor rescaling is global; a per-biome or per-land-cover scaling factor is the natural upgrade, and coarse-pixel-vs-fine-truth mismatch (500 m vs 20 m plots) mirrors our 1 km vs 375 m harmonization assumptions. |
| P4 | TWDTW on EVI time series for management classes suggests a future clustering axis: classifying *fire regimes* (crop residue vs forest vs savanna — currently a K-means heuristic in the briefing) with time-series shape matching rather than location+FRP alone. |
| P5 | VIIRS narrowband→broadband work is adjacent to our ESFP footprint normalization: both convert sensor-specific radiometry to a comparable physical quantity. Cautionary tale too: simulation-only validation is weak. |
| P6 | **Directly load-bearing.** Multi-year VIIRS analyses on operational IDPS data inherit F-factor jumps (May/Jul 2014), WUCD SST artefacts, and DNB stray-light fixes. Our 2002–2024 transition demo crosses those dates; any claim about VIIRS-era trends should cite P6-style reprocessing as a confounder alongside the 2012 sensor deployment. |
| P7 | Precedent for the exact harmonization move this project makes: combining a high-resolution newer sensor (LJ1-01) with an established coarser one (VIIRS DNB) and quantifying the added value in R². Its honest reporting of non-significant direct correlations (Table VI) is a model for how our illusion diagnostic should report significance, not just percentage gains. |

**Net takeaway for the project:** (1) the illusion diagnostic should add a significance test / confidence interval on observed-vs-adjusted growth; (2) 2014-era VIIRS calibration events (P6) belong in our confounder list beside the 2012 deployment; (3) per-biome scaling (P3) and time-series-shaped regime clustering (P4) are the two most credible next modelling upgrades.

## 9. Feature Backlog (from the review) *added*

Concrete, prioritized ideas this literature review motivates for the Pyro-Harmony app:

| Prio | Feature | Anchor paper | Effort |
|---|---|---|---|
| 1 | Significance testing on the illusion diagnostic (bootstrap CI on pre/post-2012 growth) | P1, P7 | S |
| 2 | Confounder note in the UI when the record crosses May/Jul 2014 (P6 F-factor events) | P6 | S |
| 3 | Per-biome (land-cover-stratified) sensor scaling factors instead of one global ratio | P3 | M |
| 4 | Gap-filled daily calendar via RF on NDVI/LAI/DEM covariates for cloud-blocked days | P2 | L |
| 5 | Fire-regime clustering using TWDTW shape distance on multi-day FRP series | P4 | M |
| 6 | Uncertainty layer: propagate per-detection confidence into daily totals, not just drop conf < 30 | P1 | M |
| 7 | Exportable validation mode: paired 375 m/1 km collocated detections with R²/RMSE, à la P5's calibration stats | P5, P7 | M |

## Reference List (Papers Covered)

1. H. Fang, Y. Wang, Y. Zhang, S. Li, "Long-term variation of global LAI and the uncertainty: Analysis of the GEOV2 and MODIS LAI products," *IGARSS 2020*, pp. 2890–2893.
2. Y. Cheng, Y. Li, H. Wu, F. Li, Y. Li, L. He, "Reconstructing MODIS LST products over Tibetan Plateau based on Random Forest," *IGARSS 2020*, pp. 6226–6229.
3. S. Paramanik, M. D. Behera, B. K. Bhattacharya, S. Tripathi, "Evaluation and validation of the MODIS LAI algorithm with digital hemispherical photography at Bhitar Kanika mangrove forest, India," *IGARSS 2019*, pp. 6558–6561.
4. V. D. Manabe, M. R. S. Melo, J. V. Rocha, "Monitoring pasture intensification in Brazilian Amazon biome with MODIS time series," *IGARSS 2017*.
5. W. Ying, H. Wu, Z.-L. Li, "Net surface shortwave radiation retrieval using VIIRS data," *IGARSS 2018*, pp. 2623–2626.
6. F. Weng, T. Choi, C. Cao, B. Zhang, "Reprocessing of Suomi NPP VIIRS sensor data records and impacts on environmental applications," *IGARSS*, pp. 294–296 (NOAA STAR).
7. G. Zhang, Y. Shi, M. Xu, "Evaluation of LJ1-01 nighttime light imagery for estimating monthly PM2.5 concentration: A comparison with NPP-VIIRS nighttime light data," *IEEE J-STARS*, vol. 13, pp. 3618–3632, 2020.

*Publication details for P4 and P6 are partly inferred from page headers; verify before citing. See also §4.1 for cross-paper consistency checks.*
