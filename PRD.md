# Pyro-Harmony — Product Requirements Document

**Product:** Pyro-Harmony (a.k.a. *Burning Activity Calendar*)
**Event:** NASA Space Apps Challenge 2026 — Earth Science / Software
**Status:** feature-complete prototype, hardened and verified — see [§12 Status](#12-status-summary)
**Owners:** the project team
**Related docs:** [README.md](./README.md) (install, API contract, troubleshooting) · [`Nasa Space app challenge.md`](./Nasa%20Space%20app%20challenge.md) (challenge brief + 4 reference papers)

---

## 1. Summary

Pyro-Harmony harmonizes NASA FIRMS **MODIS** (1 km, from 2000) and **VIIRS** (375 m, from 2012) active-fire detections into **one comparable daily timescale**, then presents that record as a four-pillar fire-intelligence console: a multi-decadal burning-activity calendar and climatology, the *Sensor Transition Illusion* diagnostic that quantifies and removes the artificial post-2012 surge, live FIRMS ingestion with DBSCAN clustering, and an Incident Commander briefing.

The one-sentence pitch: **the fire record looks like it exploded in 2012, and most of that is the satellite changing, not the planet — this app shows both the surge and the truth underneath it.**

## 2. Problem statement

Satellites have tracked active fires for 20+ years, but the record is fragmented by sensor:

| | MODIS C6.1 | VIIRS (S-NPP, NOAA-20/21) |
|---|---|---|
| Nadir resolution | 1 km | 375 m |
| Era | 2000 → present | 2012 → present |
| Confidence scale | 0–100 | categorical `l` / `n` / `h` |
| Footprint growth | ≈9.7× at scan edge | ≈9.7× (the *cell* differs, 1 km vs 375 m) |

Four consequences, and the requirements that answer them:

1. **Raw counts are not comparable across sensors.** VIIRS sees many more, smaller fires, so a naive daily count jumps at the 2012 hand-over. → *Pillar 2, harmonization.*
2. **Detections are points, not incidents.** A responder needs incidents with an extent, not 50,000 dots. → *Pillar 3, clustering.*
3. **Climatology is invisible in a point cloud.** "Is this season normal?" needs a day-of-year distribution, not a list. → *Pillar 1, calendar + climatology.*
4. **Analysts and commanders need a decision, not a chart.** → *Pillar 4, briefing.*

## 3. Goals & non-goals

**Goals**

- G1 — Make MODIS and VIIRS detections directly comparable on a single daily series.
- G2 — Quantify the sensor-transition artifact explicitly, and show the corrected series beside the raw one.
- G3 — Let a user ask "what is normal here, and is now different?" for any area and any day.
- G4 — Turn detections into incidents (clusters) and into an actionable briefing.
- G5 — Run the whole thing on a low-end laptop, offline-first after load, with no API keys.
- G6 — Be honest about uncertainty: every derived number exposes its inputs and its caveats.

**Non-goals**

- Not an operational dispatch system: no accounts, no persistence, no alerting, no SMS/email.
- Not a burned-area or emissions product — active-fire detections only, no fire perimeters or smoke modelling.
- Not a forecast service for public safety. The 30-day forecast is a demonstration of feasibility.
- Not multi-tenant. The dataset is a single process-global in-memory store by design.

## 4. Users & jobs to be done

| User | Job | What they use |
|---|---|---|
| **Earth-science analyst / researcher** | "Show me the long-term burning season here, and how much of the trend is instrumentation." | Calendar, Seasonal climatology, Illusion diagnostic, bbox selection |
| **Land manager / responder** | "Where is it burning right now, what kind of fuel, and what should we do first?" | Live FIRMS feed, map clusters, IC briefing (Situation + Actions) |
| **Hackathon judge / reviewer** | "Prove the science is real and the engineering works." | Demo buttons, Method section, test suite, measured performance |
| **Operator** | "Get this running on my machine in one command." | `run.py` / `start.sh` / `start.bat` |

## 5. Product scope

Two demo datasets ship with the app so every pillar is demonstrable with no downloads:

- **2020–2024 standard demo** — a plausible 5-year bilateral record (used for the default console state).
- **2002–2024 transition demo** — MODIS-only era into the VIIRS ramp-up; the dataset that makes the illusion visible. Measured on load: **57,867 hotspots** (MODIS 18,310 / VIIRS 39,557), 2002-01-19 → 2024-12-21, HFII 1,771,574.5, ESFP 136,409.8.

The console is a single screen: left rail (telemetry, selection, clustering), centre stage (the globe⇄map), right rail (briefing, anomalies), and a full-width analytics drawer with five tabs.

## 6. Functional requirements

Status key: **✅ implemented** · **⚠️ partial** · **❌ not started**. "Verified" is what actually proved it.

### FR-1 — Ingestion & harmonization

| ID | Requirement | Status | Acceptance criteria / notes |
|---|---|---|---|
| FR-1.1 | Accept FIRMS archive CSVs by multi-file upload | ✅ | Verified: UTF-8, cp1252 (Excel/Windows) and UTF-16-BOM (Excel/macOS) all parse; each has a test |
| FR-1.2 | Detect and normalize the confidence scale | ✅ | MODIS 0–100 kept; VIIRS `l/n/h` → 20/60/90; detections below 30 dropped for both sensors |
| FR-1.3 | Build UTC timestamps from `acq_date` + `acq_time` | ✅ | `acq_time` is a zero-padded HHMM integer, not a clock time |
| FR-1.4 | De-duplicate detections | ✅ | Key `(lat, lon, time, sensor)` |
| FR-1.5 | Rescale per-sensor daily counts over the overlap period | ✅ | Corrects the VIIRS-sees-more-fires bias before summing |
| FR-1.6 | Reject unreadable/oversized/too-many files with a precise reason | ✅ | HTTP 400 with the sanitised filename + what is missing; HTTP 413 for an oversized request |
| FR-1.7 | Never let a filename select server behaviour | ✅ | Verified: junk named `demo_transition.csv` used to return 200 with the full demo and ignore the bytes; now 400, and the demo loads via `?demo_transition=true` |
| FR-1.8 | Generate synthetic data for demo/testing | ✅ | `demo.py` writes real CSVs and feeds the identical pipeline |

### FR-2 — Burning activity calendar

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-2.1 | One row per year, one cell per day, colour = harmonized daily detections | ✅ | ~8,000 SVG cells for "All years" |
| FR-2.2 | Click a day to select it as the cursor day | ✅ | Selection propagates to map, readouts and briefing |
| FR-2.3 | Single-year calendar view with month/weekday axes | ✅ | Year selector; month labels at first occurrence |
| FR-2.4 | Per-year summary for the selected year | ✅ | Total detections, peak day, active days, ramp legend |
| FR-2.5 | Filter by drawn bounding box | ✅ | All panels refilter |

### FR-3 — Map stage (3D globe ⇄ flat map)

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-3.1 | One camera that continuously morphs a 3D globe into a flat map | ✅ | Projection is interpolated between `vertical-perspective` (≤ zoom 3.7) and `mercator` (≥ 5.2); badge tracks `3D globe → Transition → 2D map`; verified by simulating zoom and reading the badge plus the canvas |
| FR-3.2 | Return to the globe in one click | ✅ | "Globe view" eases back to `START_ZOOM` |
| FR-3.3 | Render detections for the selected day and span | ✅ | 1/3/7/14-day spans |
| FR-3.4 | Render DBSCAN clusters as extents, not points | ✅ | Convex-hull polygons, line fallback for degenerate hulls |
| FR-3.5 | Two basemaps: satellite imagery and colour terrain | ✅ | Esri World_Imagery and World_Topo_Map; toggle grouped with the other view controls |
| FR-3.6 | Draw a bounding box by clicking two corners | ✅ | Crosshair cursor, double-click-zoom disabled while picking, corner marker between clicks |
| FR-3.7 | Overlay live-feed points and clusters | ✅ | Pale-gold points, live polygons |
| FR-3.8 | Chronological readout never covers required attribution | ✅ | Measured 0 px overlap at 820 px and 1440 px viewports after moving the basemap toggle out of the readout chip |
| FR-3.9 | Map engine must load under Vite (worker + dep pre-bundling) | ✅ | Worker URL handed to MapLibre explicitly, otherwise every source stays unparsed |
| FR-3.10 | Camera controls beyond zooming out | ✅ | **Fly to AOI** fits the drawn box (disabled without one), **Reset orbit** restores the default global attitude (centre 0,0, bearing 0, pitch 0), **Auto-rotate** drifts the bearing at 0.22°/70 ms (0.12°/140 ms on a low-end probe). Verified live: bearing −15.72°→−17.40° while on, frozen at −38.40° and `aria-pressed=false` after a `pointerdown` on the canvas |

### FR-4 — Multi-decadal climatology (pillar 1)

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-4.1 | Day-of-year percentile envelope | ✅ | p10 / p50 / p90 / p95 over a rolling 15-day window (window 3–45, step 1–30) |
| FR-4.2 | Report peak day, onset and cessation | ✅ | Onset/cessation = first/last DOY where p95 exceeds 50 % of its max. Demo reads peak **19 Mar**, season **22 Feb → 7 Apr** |
| FR-4.3 | Expose the extreme-fire band | ✅ | Shaded ≥ 90th percentile envelope |
| FR-4.4 | Degrade honestly when there is too little data | ✅ | Thin AOI answers 200 with `summary: null` + `note`; the panel must show the note — it previously span "Analyzing…" forever (fixed) |

### FR-5 — Sensor Transition Illusion diagnostic (pillar 2, the differentiator)

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-5.1 | Per-sensor raw daily/yearly counts beside the comparable series | ✅ | Named MODIS raw / VIIRS raw / Harmonized, in the shared sensor colours |
| FR-5.2 | Quantify the post-2012 surge before and after harmonization | ✅ | Demo: **+304.0 % raw → +11.7 % harmonized**, artifact **292.3 pp** |
| FR-5.3 | Derive the VIIRS scaling factor from the overlap era | ✅ | Detection ratio measured on days both sensors flew (2012–2015), applied so a fire both sensors saw is counted once; demo factor **3.618** |
| FR-5.4 | Report cross-sensor calibration quality | ✅ | 9,767 matchups, daily-count R² **0.867**, RMSE **2.91 MW**, FRP ratio 0.997, ESFP ratio 0.948 |
| FR-5.5 | State plainly when the illusion is unmeasurable | ✅ | If the dataset starts after 2012 the panel says so and points at the transition demo |
| FR-5.6 | Never render `NaN` for a sensor-year with no detections | ✅ | Missing per-year keys default to 0 (was `NaN` bars — fixed) |

### FR-6 — Clustering (pillar 3a)

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-6.1 | Cluster in projected metres with a time window | ✅ | DBSCAN, eps 550 m, minPts 3, 12 h |
| FR-6.2 | Return an extent and metadata per cluster | ✅ | Convex `hull`, count, FRP, sensors, duration |
| FR-6.3 | Bound the response | ✅ | Top 300 clusters by size; parameters clamped (eps 10–5000 m, minPts 1–100, hours 0.5–720) |
| FR-6.4 | Expose cluster counts in the UI | ✅ | Demo day 2013-02-27: 246 hotspots → **29 clusters**, 3.4k MW |

### FR-7 — Live FIRMS feed (pillar 3b)

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-7.1 | Pull 24 h NRT CSVs for MODIS + 3 VIIRS feeds | ✅ | 4 feeds fetched in parallel; no API key required |
| FR-7.2 | Harmonize and cluster on the fly | ✅ | Same pipeline as uploads |
| FR-7.3 | Region selector | ✅ | 8 allowlisted regions |
| FR-7.4 | `region` must not control the outbound URL | ✅ | Verified: an unvalidated region was interpolated into the FIRMS URL (traversal attempt produced 4 outbound 404s); now 400 *before* any fetch |
| FR-7.5 | Bound one outbound download | ✅ | 64 MB streaming cap (was unbounded `r.content`) |
| FR-7.6 | Survive one feed being down | ✅ | Partial success returns the feeds that worked plus per-feed errors; total failure → 502 listing them |
| FR-7.7 | Refuse to stack concurrent ingests | ✅ | 2-slot semaphore → 429; each call is 4 downloads + DBSCAN/K-means |

### FR-8 — Incident Commander briefing (pillar 4)

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-8.1 | Threat level + score | ✅ | `max_z + 0.5·streak_days + min(2, recent_mean/25)` → Low / Watch (≥3.5) / Elevated / Critical (≥6) |
| FR-8.2 | Critical streaks (z ≥ 2σ) with click-through | ✅ | Consecutive days above threshold, 2-day gap tolerance; clicking a streak moves the map |
| FR-8.3 | Fuel-biome stratification | ✅ | K-means k=4 on projected position + FRP. Demo: Forest 19,271 fires (mean FRP 12.9 MW, spread ≈76.5 km), Agricultural Crop Residue 16,240, Savanna 12,475, Mediterranean Shrubland 11,036 |
| FR-8.4 | Rule-based recommendations | ✅ | 3 in the demo state; Markdown export via **Copy MD** |
| FR-8.5 | **The report must be presented as tabs** | ✅ | Four sub-tabs — Situation, Critical streaks, Fuel types, Actions — each with a count badge; only the active section renders |
| FR-8.6 | Headline summary in the rail | ✅ | Compact card: threat, record mean, last 30 days, top streaks, first two actions |
| FR-8.7 | Honest state for a thin window | ✅ | Verified: a <60-day AOI returns `{note, threat, streaks, biomes, recommendations}` with no `record`/`recent`; the panel previously threw on `b.record.mean_daily`, and now shows the note and keeps the console alive |

### FR-9 — Anomalies

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-9.1 | z-score each day against the same ±7-day window in other years | ✅ | Vectorized; needs >400 days |
| FR-9.2 | Flag critical months (mean + 1σ) | ✅ | Demo: **Mar** — month *names*, not raw indices (was printing "3" — fixed) |
| FR-9.3 | Click an anomalous day to select it | ✅ | |
| FR-9.4 | Chart the monthly series returned by the API | ❌ | `/anomalies` returns `monthly[]` but nothing plots it — see [§13 gaps](#13-known-gaps--risks) |

### FR-10 — Forecast

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-10.1 | 30-day forecast appended to the trailing year | ✅ | Demo fits on 365 observed days |
| FR-10.2 | Label the series | ✅ | Observed / Forecast legend + the fitted method named |
| FR-10.3 | LSTM model when PyTorch is present | ⚠️ | Sin/cos day-of-year features; without `torch` it falls back to scaled seasonal climatology and names the fallback in the UI |
| FR-10.4 | Empty state instead of a blank chart | ✅ | Explicit hint when there is no calendar data or no forecast window |
| FR-10.5 | Needs ≥ 120 days of data | ✅ | Otherwise the panel says what is missing |

### FR-11 — Console shell & navigation

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-11.1 | Five analytics tabs in a drawer | ✅ | Burning calendar, Forecast, Climatology, Illusion diagnostic, Briefing detail |
| FR-11.2 | One-click demo loading | ✅ | Demo cached server-side, so repeat loads are ~26 ms |
| FR-11.3 | Area selection and clearing | ✅ | |
| FR-11.4 | Live status indicators | ✅ | Link pulse, hotspot count, record window, per-sensor totals |
| FR-11.5 | Prefetch chart chunks on hover/focus | ✅ | The chart bundle (≈4 KB gzipped, hand-rolled SVG) is warm before the click |

### FR-12 — Design system

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-12.1 | Single, coherent theme | ✅ | "Ember dusk": warm charcoal-teal base, desaturated accents, documented tokens in `styles.css` |
| FR-12.2 | Soothing but instantly legible | ✅ | Amber primary clears ≈7:1 on the base; no neon or pure-saturation accents |
| FR-12.3 | Colour carries consistent meaning | ✅ | MODIS coral / VIIRS amber / live pale gold / clusters sand / modelled teal — identical in map legend, diagnostic bars and forecast |
| FR-12.4 | Consistent letter case throughout | ✅ | Labels uppercased by CSS, prose sentence case, acronyms uppercase, statistic symbol lowercase **z** — one documented contract at the top of `styles.css` |
| FR-12.5 | Motion is optional | ✅ | `prefers-reduced-motion` honoured |

### FR-13 — Robustness & error states

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-13.1 | A failing panel must never blank the console | ✅ | `PanelBoundary` per drawer tab, auto-resetting on tab change; verified that a deliberately failing lazy import used to unmount the whole tree |
| FR-13.2 | Lazy imports are validated at build time | ✅ | `check-lazy-exports.mjs` runs as `prebuild` and fails the build on an unresolvable `React.lazy` target |
| FR-13.3 | Stale responses must not overwrite newer ones | ✅ | Shared `useEndpoint` hook with a live-request flag; an out-of-order reply for an older AOI is discarded |
| FR-13.4 | Empty/loading/failed states are distinguishable | ✅ | "Analyzing…" only while loading; API `note` text is surfaced instead of spinning |
| FR-13.5 | Reloading a dataset with the same row count still reloads it | ✅ | Dataset version counter; previously the cursor day stayed null and the calendar went empty |

### FR-14 — Cross-platform launcher

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-14.1 | One command starts both servers on any OS | ✅ | `run.py` (stdlib only); `start.sh` / `start.bat` are thin wrappers |
| FR-14.2 | Creates the venv and installs what is missing | ✅ | Verified in a throwaway venv |
| FR-14.3 | Handles package managers and shims correctly | ✅ | Real executables rather than `.cmd` shims; `taskkill /T` on Windows, `killpg` on POSIX |
| FR-14.4 | Port conflicts and Ctrl+C are handled | ✅ | Falls back 5173 → 5174 and reports it; Ctrl+C/SIGTERM release both ports |
| FR-14.5 | Bind IPv4 loopback explicitly | ✅ | `localhost` can resolve to `::1` on Node 17+, which the proxy would miss |

### FR-15 — Curated region presets (AOI navigation)

The useful idea taken from the sibling Pyro-Harmony repo: a demo should walk an audience through
named fire regimes, not one anonymous bounding box. Here the presets are a **view** — they never
substitute for real data by themselves.

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-15.1 | Serve a curated AOI catalog | ✅ | `GET /regions`, five presets (California, Amazon & Pantanal, Southeastern Australia, Punjab & Haryana, Mediterranean basin) with bbox, centre, zoom, biome, peak months and notable fire years |
| FR-15.2 | Selecting a preset sets the AOI filter and flies the camera | ✅ | Picker in the command bar; every panel recomputes for that bbox; verified live (badge `SATELLITE · 2D MAP` on arrival, region facts in the Selection panel) |
| FR-15.3 | Preset facts follow the AOI, not the click | ✅ | A hand-drawn box that matches a preset shows that region's facts too (bbox match, not just picker state) |
| FR-15.4 | The demo works for any preset | ✅ | `POST /demo?region=…` scopes the synthetic record to the preset bbox and gives it its own seed, so regions differ statistically; a per-region demo is cached after its first build (~2 s) |
| FR-15.5 | An empty AOI says so and offers a way forward | ✅ | "No detections in this AOI yet" + *Load demo for {region}*; verified live on Southeastern Australia before loading |
| FR-15.6 | A preset's live region stays on the allowlist | ✅ | Every `firms_region` is asserted to be a member of `LIVE_REGIONS` in the test suite, so "pull live" can follow a preset without tripping the 400 |

### FR-16 — Real FIRMS windows via the area API (optional key)

The open 24 h feeds are global, so every AOI looks like a single day. The area API returns real
1–5 day windows per AOI and source, which is the only path to real data without a manual download.

| ID | Requirement | Status | Acceptance criteria |
|---|---|---|---|
| FR-16.1 | Load a real window into the record | ✅ | `POST /archive` harmonizes the response, appends it (dedup on `lat, lon, time, sensor`), invalidates the analytics cache and returns `meta` + `{source, region, days}` |
| FR-16.2 | Never invent credentials, never leak them | ✅ | Key read from the environment (or git-ignored `.env`), matched against `[A-Za-z0-9]{6,64}` before use, never accepted as a request parameter and never echoed; `.env` was added to `.gitignore` as part of this work |
| FR-16.3 | Validate the request before touching the network | ✅ | Unknown source/region → 400, no AOI → 400, malformed date → 400, `days` clamped to 1–5; tested without a key present |
| FR-16.4 | Fail with an actionable message when unconfigured | ✅ | Missing key → 400 pointing at the MAP_KEY page and the three `.env` locations; verified end-to-end in the browser ("Real-window pull failed: FIRMS_MAP_KEY is not set…") |
| FR-16.5 | Trust the API's AOI filter, then verify it | ✅ | Rows outside the requested box are dropped; a stub-feed test proves the out-of-AOI row never reaches the store |

## 7. Non-functional requirements

### NFR-1 — Performance budget (low-end first)

Target: a responsive console on a 4-core, 8 GB machine with integrated graphics.

| Metric | Before | After | Budget |
|---|---|---|---|
| First-paint JS | 2,078 KB | **≈170 KB raw / 55 KB gzipped** | ≤ 250 KB |
| DOMContentLoaded (cold) | 1,768 ms | **283 ms** | ≤ 500 ms |
| Cold-load requests | 44 | **14** | ≤ 20 |
| `/calendar` on the wire | 86,882 B | **9,161 B** | — |
| `/points` on the wire | 50,484 B | **8,869 B** | — |
| `/climatology` on the wire | 21,587 B | **5,065 B** | — |
| Chart code on first chart tab | 411 KB raw / 110.6 KB gzipped | **9.1 KB raw / 4.2 KB gzipped** | — |
| `/briefing` warm | 2.02 s | **0.011 s** | ≤ 100 ms |
| `/clusters` warm | 0.71 s | **0.020 s** | ≤ 100 ms |
| `/calendar` warm | 0.47 s | **0.058 s** | ≤ 100 ms |
| `POST /demo` warm | 2.56 s | **0.026 s** | ≤ 100 ms |

Mechanisms: lazy `React.lazy` splits gated by a path-based `manualChunks` function (the object form only matched entry files and pulled the charting vendor chunk back into first paint), charts drawn as hand-rolled SVG in `plot.jsx` so no charting dependency exists at all, gzip with a 1 KiB floor, server-side memoization of every derived endpoint plus explicit invalidation on dataset change, a client-side in-memory response cache with in-flight request collapsing, a cached demo generator, raster tiles capped at zoom 16 with fade animation disabled, no per-frame React render on zoom, and `LOW_END` degraded effects (no MSAA, instant camera moves) on ≤4-core or ≤4 GB devices.

### NFR-2 — Security

Anonymous, no accounts, no keys. The dataset is public NASA data and a user may replace it — that is the product, not a breach. What is enforced (each with a regression test):

- Client input never selects a URL (`region` allowlisted; `bbox` range-validated; numerics clamped).
- Uploads are bounded before buffering: `Content-Length` gate → 413; 200 MB/file and 400 MB/request; ≤20 files; 1 MiB slice reads that abort at the cap.
- A filename is data, not a command.
- Reflected filenames are sanitised (basename, printable only, 80 chars) so they cannot forge log lines.
- CORS defaults to the local origins, never `*`, and is never paired with credentials.
- Writes need an `Origin` of this host or an explicit `ALLOW_ORIGINS` entry (403 otherwise). CORS only governs *reading* a response, and a form POST is never preflighted, so without this guard any page the operator had open could drive `/upload`, `/demo`, `/archive` and `/live`. A no-`Origin` caller (curl, pytest, launcher) still writes; reads are never gated.
- Outbound transport errors are sanitised (`request failed: <ExceptionType>`) before they can reach a client body, so the `FIRMS_MAP_KEY` that the area-API URL carries cannot be reflected in the 502 detail.
- Outbound downloads capped at 64 MB; concurrent live ingests capped at 2.
- Dependency floors cover the multipart advisories reachable through `/upload` (CVE-2024-47874, CVE-2024-53981).

Accepted gaps: no authentication or rate limiting; process-global mutable state; dev-server-only Vite/esbuild advisories.

### NFR-3 — Accessibility

Partial. Honoured: `prefers-reduced-motion`, `aria-label` on the map and basemap group, `role="tab"` + `aria-selected` on drawer and briefing tabs, `role="listbox"`-style selects, real `<button>`/`<select>` elements, and visible focus via the browser default. Not done: a formal audit, keyboard path for the map's two-corner selection, and text-alternatives for the SVG heatmap beyond per-cell `<title>`. See [§13](#13-known-gaps--risks).

### NFR-4 — Reliability & correctness

53 automated tests (31 smoke + 22 security) run in CI on every push and PR, plus the frontend production build with the lazy-export guard as a prebuild step. Derived values are asserted against invariants (percentile ordering, cluster hull sizes, threat ladder membership, growth relationships) rather than hard-coded snapshots where possible.

### NFR-5 — Portability

Windows, macOS and Linux from one launcher; CSV encodings from all three as they are actually produced by Excel; no shell dependency beyond that launcher. Windows-only paths are simulated rather than executed in this environment — see [§13](#13-known-gaps--risks).

## 8. Architecture

```
                    ┌──────────────────────── browser (React 18 + Vite 5) ────────────────────────┐
                    │  App.jsx ......... console shell, drawer tabs, calendar heatmap, selection  │
                    │  MissionMap.jsx .. MapLibre GL 6 — one camera, globe ⇄ mercator morph       │
                    │  charts.jsx ...... SVG panels (lazy: climatology, illusion diagnostic)      │
                    │  plot.jsx ........ hand-rolled SVG chart kit (line / band / bar, no dep)   │
                    │  ForecastChart.jsx (lazy) · panels.jsx (rail cards) · lib.js (API client)   │
                    │  styles.css ...... "ember dusk" tokens + letter-case contract               │
                    └───────────────┬─────────────────────────────────────────────────────────────┘
                                    │  /api/*  →  Vite dev proxy → 127.0.0.1:8000
                    ┌───────────────▼──────────── FastAPI (uvicorn, single process) ──────────────┐
                    │  upload / demo / data ....... ingest, replace, clear                        │
                    │  calendar / points / clusters  daily series, map data, DBSCAN extents       │
                    │  climatology ................. DOY percentile envelope + onset/cessation    │
                    │  diagnostic .................. raw vs harmonized + calibration              │
                    │  anomalies / forecast ........ z-score days, 30-day forecast                │
                    │  briefing .................... threat, streaks, biomes, recommendations     │
                    │  live ........................ 4 NASA FIRMS NRT feeds → harmonize → cluster │
                    │  cores: harmonize() · daily() · _zstats() · _streaks() · _threat() ·        │
                    │         _biomes() · _cluster_payload() · _esfp() · cached()                 │
                    └──────────────────────────────┬──────────────────────────────────────────────┘
                                                   │
                    pandas/NumPy/SciPy/scikit-learn  ·  64 MB-capped outbound HTTP  ·  process-global DF + memo cache
```

Data flow: **upload or live fetch → harmonize (confidence, UTC, de-dup, per-sensor rescale, ESFP/HFII) → single `DF` → derived endpoints (memoized, invalidated on change) → gzip → client cache → panels.**

The one structural decision worth defending: the dataset is a **process-global in-memory `DataFrame`** with a memo cache keyed by endpoint arguments. That is why warm analytics are ~10–100 ms and why there is no database to run. The cost is that two workers would not share state, and one caller can replace the dataset for everyone.

## 9. Data model & API contract

Canonical detection record after harmonization: `lat, lon, time (UTC), sensor, conf (0–100), frp (MW), bt (K), scan, track, esfp, pixel_km2, daynight, date`.

| Method & path | Key parameters | Returns |
|---|---|---|
| `POST /upload` | multipart `files[]`, `demo_transition` | `meta` |
| `POST /demo` | `mode=standard\|transition`, `region` (preset key) | `meta` |
| `POST /archive` | `region` \| `bbox`, `source`, `days` 1–5, `date`, `append` | `meta` + `{source, region, days}` (needs `FIRMS_MAP_KEY`) |
| `GET /regions` | — | `[{key, name, subtitle, bbox, center, zoom, biome, peak_months, events[], firms_region}]` |
| `DELETE /data` | — | `{n: 0}` |
| `GET /meta` | — | `{n, start, end, sensors, bounds, hfi, esfp, pixels}` |
| `GET /calendar` | `bbox`, `start`, `end` | `[{date, count, raw, frp}]` |
| `GET /points` | `bbox`, `start`, `end`, `limit ≤ 20000` | `[{lat, lon, frp, sensor, conf, time}]` |
| `GET /clusters` | `bbox`, `start`, `end`, `eps`, `min_pts`, `hours` | top 300 clusters with `hull` |
| `GET /climatology` | `bbox`, `window`, `step` | per-year DOY series, percentile envelope, summary (peak/onset/cessation) |
| `GET /diagnostic` | `bbox` | per-year per-sensor series, growth %, artifact pp, scaling factor, calibration |
| `GET /anomalies` | `bbox`, `z` | `{anomalies[], critical[], monthly[]}` (needs >400 days) |
| `GET /forecast` | `bbox`, `horizon`, `epochs` | `{model, forecast[]}` (needs ≥120 days) |
| `GET /briefing` | `bbox`, `z`, `min_days`, `format=json\|markdown` | threat, streaks, biomes, recent/record, recommendations |
| `GET /live` | `region`, `bbox`, `crop`, `eps`, `min_pts`, `hours` | feeds, sensors, HFII, capped rows, top 150 clusters |

`bbox` is `minlat,minlon,maxlat,maxlon`. Thin selections answer **200 with a `note`** rather than failing, and every panel is required to surface that note (FR-4.4, FR-8.7).

## 10. Algorithms & constants

| Concern | Value |
|---|---|
| Confidence floor | ≥30 (MODIS 0–100; VIIRS l/n/h → 20/60/90) |
| Nadir cell | MODIS 1.0 km² (1 km), VIIRS **0.140625 km²** (0.375 km — the I-band 375 m product FIRMS distributes, not the 750 m M-band cell) |
| Footprint clip | `scan`, `track` clamped to 0.1–20 km; ESFP floored at 1.0 standard pixel |
| Footprint growth | both sensors reach ≈9.7× the nadir area at the edge of scan (MODIS 4.83 × 2.01 km, VIIRS ≈1.17 km square) |
| Climatology window | 15-day rolling percentiles (window 3–45, step 1–30) |
| Onset / cessation | first / last DOY where p95 > 50 % of its max |
| Illusion era split | pre-2012 vs 2012–2015 overlap |
| Anomaly window | same ±7-day DOY window in other years |
| Streak rule | z ≥ 2σ (1–5), ≥2 days (1–14), 2-day gap tolerance |
| Threat score | `max_z + 0.5·days + min(2, recent_mean/25)` |
| Clustering | DBSCAN eps 550 m, minPts 3, 12 h window |
| Biomes | K-means k=4, n_init=10, seed 0, on projected position + FRP |
| Data thresholds | climatology/briefing ≥60 days · anomalies >400 days · forecast ≥120 days |
| Region presets | 5 AOIs; `firms_region` must be a `LIVE_REGIONS` member; per-region demo seed = base + `crc32(key) % 997` (default keeps 7 / 11, so the documented demo numbers stay valid) |
| Area API | 1–5 days per pull; area passed as `west,south,east,north` (the API's order, not the internal `bbox` order); sources `MODIS_C6_1`, `VIIRS_SNPP_C2`, `VIIRS_NOAA20_C2`, `VIIRS_NOAA21_C2` |
| Camera flights | preset fly-to uses the preset `zoom` (4.6–6.6); `Fly to AOI` uses `fitBounds` with 56 px padding; all durations are 0 ms on the low-end probe |
| Map zooms | globe ≤3.7 · flat ≥5.2 · start 1.65 · max tiles 16 (map 0.5–19, pitch ≤60°) |
| Low-end probe | `hardwareConcurrency ≤ 4` or `deviceMemory ≤ 4` → no MSAA, 0 ms camera moves |

## 11. Verification & evidence

Nothing in this document is aspirational scaffolding: each pillar was exercised through the running app.

| Area | How it was verified |
|---|---|
| Harmonization & encodings | Tests for UTF-8 / cp1252 / UTF-16-BOM uploads; merge and clear paths |
| Illusion diagnostic | Live render on the 2002–2024 demo: +304.0 % → +11.7 %, 292.3 pp artifact, R² 0.867, RMSE 2.91 MW, era factor 3.618, ESFP ratio 0.948 (was 1.739 while VIIRS was divided by the 750 m cell) |
| ESFP nadir cells | Unit-tested against the FIRMS attribute table: 1.0 at MODIS 1 km and at VIIRS 0.375 km, ≈9.67 at the VIIRS scan edge, never below 1.0 |
| Demo footprints | Synthetic `scan`/`track` asserted inside the product ranges (MODIS 1–4.83 km, VIIRS 0.375–1.17 km) in `test_demo_footprints_are_product_shaped` |
| Climatology | Live render: peak 19 Mar, season 22 Feb → 7 Apr; envelope ordering asserted in tests |
| Calendar | 22-year heatmap plus single-year view; day selection drives the map readout |
| Map stage | Zoom simulated in-browser; badge walked `3D globe → Transition → 2D map` and back with a continuous morph; terrain tiles confirmed loading |
| Clustering | 246 hotspots → 29 clusters on a demo day; hull invariants asserted |
| Briefing | All four sub-tabs exercised; thin-AOI payload reproduced from the API and confirmed to render the note instead of crashing |
| Live feed | Region allowlist, 429 guard and outbound cap covered by tests; real feeds are network-dependent and skipped offline |
| Performance | Cold-load and warm-endpoint timings measured before/after (NFR-1); `/clusters` cold 32,893 → 2,841 ms after ranking clusters before hulling |
| Charts | Hand-rolled SVG kit rendered live on all three panels (band envelope, grouped bars, forecast lines); payload 411 → 9.1 KB raw (110.6 → 4.2 KB gzipped) after removing four charting dependencies |
| Layout integrity | Overlap between the map readout, the legend chip, the tool cluster and the Esri attribution measured at 820 px and 1440 px: 0 px |
| Security | Before/after reproductions against the running server (NFR-2), plus 22 regression tests |
| Key handling & cross-site writes | `/archive` with a live `FIRMS_MAP_KEY` and a refused transport: the 502 body never contains the key. Foreign-origin writes refused 403 while same-host, allowlisted-origin and no-Origin writes pass — both covered in `test_security.py`, and the foreign-origin 403 re-checked against the running server |
| Full suite | `pytest` 49 passed · `npm run build` (incl. lazy-export guard) passed · browser console clean across all tabs |

## 12. Status summary

| Pillar / area | Status |
|---|---|
| Pillar 1 — Calendar + climatology | ✅ Complete |
| Pillar 2 — Sensor Transition Illusion | ✅ Complete |
| Pillar 3a — DBSCAN clustering | ✅ Complete |
| Pillar 3b — Live FIRMS ingestion | ✅ Complete |
| Pillar 4 — IC briefing (now tabbed) | ✅ Complete |
| Anomalies | ⚠️ List + critical months complete; monthly chart missing |
| Forecast | ⚠️ Seasonal fallback complete; LSTM path needs optional `torch` |
| Console UX / design system | ✅ Complete, single documented contract |
| Performance budget | ✅ Met on every measured axis |
| Security posture | ✅ Hardened, tested; auth/rate limiting intentionally out of scope |
| Cross-platform launcher | ✅ Complete (Windows branches simulated, not executed here) |
| Region presets & AOI navigation | ✅ Complete (five presets, per-region demo, camera flights) |
| Real FIRMS window pull (`MAP_KEY`) | ✅ Complete; needs the operator's own free key, reported plainly when absent |
| Chart rendering | ✅ Hand-rolled SVG kit; `recharts`, `cobe`, `leaflet`, `react-leaflet` removed |
| Test suite | ✅ 53 tests green (31 smoke + 22 hardening); CI runs pytest + build |

## 13. Known gaps & risks

| # | Gap / risk | Severity | Mitigation or plan |
|---|---|---|---|
| 1 | No authentication or rate limiting; one caller can replace the dataset for everyone | Medium (prototype-accepted) | Cross-origin writes are already refused and the live-ingest semaphore bounds the worst case; add an API key plus per-IP limits before any public deployment |
| 2 | Dataset is process-global mutable state; multiple workers would not share it | Medium | Stated explicitly; move to a file/DB-backed store if scaled |
| 3 | `/anomalies` returns a `monthly[]` series that nothing plots | Low | Pending feature (FR-9.4) |
| 4 | Forecast is a seasonal fallback unless `torch` is installed | Low | Labelled in the UI; both paths documented |
| 5 | Windows launcher branches are simulated, not executed in this environment | Low | Logic is stdlib-only and mirrors the POSIX path; verify on a Windows machine |
| 6 | No formal accessibility audit; map two-corner selection is pointer-only | Medium | Add keyboard selection, raise contrast checks, audit with a screen reader |
| 7 | `npm audit` flags Vite/esbuild dev-server advisories | Low (dev-only) | Not in the production bundle; dev server bound to loopback; fix = major Vite upgrade |
| 8 | `/upload` silently ignores a file whose rows all fail harmonization when a dataset already exists (returns 200, unchanged data) | Low | Make the response report per-file accepted/rejected counts |
| 9 | Synthetic demo data is plausible but not real; scientific claims rest on the method, not the demo numbers | Low | Ship the Method section and cite the reference papers; the pipeline is identical for real FIRMS files |
| 10 | Region-preset demos are seeded per region, so the headline demo figures quoted in the docs (57,867 hotspots; +304.0 % → +11.7 %) apply only to the default dataset | Low | Stated in the README next to the quoted numbers; the acceptance criterion is "a per-region demo lands in its bbox", not "reproduces the default numbers" |
| 11 | `POST /archive` depends on the operator supplying `FIRMS_MAP_KEY`, and 5 days per request means a multi-decadal record still comes from downloaded archive CSVs | Low (by design) | The key-gated path is for real windows; the download+upload path remains the documented route for 20-year records. Could be automated with a loop over date windows later |

## 14. Roadmap

**Near term (highest value per unit effort)**
1. Report per-file upload outcomes honestly (gap 8) and chart the monthly anomaly series (gap 3).
2. Add a date-window loop so `POST /archive` can assemble a multi-year record (gap 11) from repeated 5-day pulls.
3. Keyboard-accessible area selection plus an accessibility pass (gap 6).

**Mid term**
4. Persistence: a real store behind the same API so datasets survive restarts and multiple workers agree.
5. Compare two AOIs or two eras side by side for the illusion diagnostic — the most requested analyst workflow.
6. Put the calendar/anomaly/forecast series on the same non-double-counting basis the diagnostic uses (§10), so the whole app reports one harmonized record instead of two.
7. Export: GeoTIFF/GeoJSON cluster extents and a one-click briefing PDF.

**Longer term**
8. Burned-area and emissions estimation layered on the same harmonized record.
9. Multi-decadal trend attribution beyond the sensor artifact (climate vs land-use signals).
10. Optional deployment profile with auth, quotas and a managed dataset.

**Done this cycle:** dropped the three unused frontend dependencies plus `recharts` in favour of the SVG kit (gap 8, now closed); corrected the VIIRS nadir cell to the 375 m I-band value and replaced the illusion correction's footprint-ratio factor with the measured collocated detection ratio (§10, §11).

## 15. Glossary

| Term | Meaning |
|---|---|
| **HFII** | Harmonized Fire Intensity Index — Σ (FRP × ESFP), a footprint-standardized energy proxy |
| **ESFP** | Equivalent Standard Fire Pixels — footprint normalized to the sensor's nadir cell |
| **FRP** | Fire Radiative Power (MW) |
| **DOY** | Day of year (1–366) |
| **z** | Standard score against a reference distribution; kept lowercase everywhere |
| **Sensor Transition Illusion** | The apparent post-2012 activity surge caused by the VIIRS hand-over, not by fire |
| **Harmonized** | The per-sensor rescaled series intended to be comparable across sensors |
| **Streak** | Consecutive days at z ≥ 2σ (2-day gap tolerance) |

## 16. References

- NASA FIRMS — <https://firms.modaps.eosdis.nasa.gov/> (archive and 24 h NRT feeds)
- Zhang et al. (2020) — fuel-biome stratification approach behind the K-means briefing
- GISTDA / GIS-IDEAS (2024) — DBSCAN parameters for hotspot clustering
- Further papers and the challenge brief: [`Nasa Space app challenge.md`](./Nasa%20Space%20app%20challenge.md)
- Implementation detail, API examples and troubleshooting: [README.md](./README.md)
