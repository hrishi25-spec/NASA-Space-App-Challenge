# Frontend — the Pyro-Harmony console

How the React console is put together, which files own what, and the rules that keep it inside its performance budget. Product context lives in [PRD.md](PRD.md); install and commands in the [README](../README.md).

## The screen

One screen, five zones, all fed by the same single dataset:

| Zone | Contents |
|---|---|
| Command bar (header) | Link signal, logo, hotspot/window/sensor readouts, **Upload CSVs**, **Load demo**, **2002–2024**, region picker, **Select area** / **Clear** |
| Left rail | Hero telemetry (HFII, ESFP, hotspots, record span), Selection (AOI, cursor day, span, region facts), Clustering (counts, DBSCAN params, live feed state) |
| Centre stage | MapLibre: one camera that morphs a 3D globe into a flat map, with cluster extents, detection points and the readout chip |
| Right rail | Incident Commander briefing (headline version) and the anomalies list |
| Analytics drawer | Five tabs — Burning calendar, Forecast, Climatology, Illusion diagnostic, Briefing detail |

## Module map

| File | Responsibility |
|---|---|
| `main.jsx` | Mounts `<App />`. |
| `App.jsx` | The shell: dataset state (`meta`, `dataKey`), cursor day and span, bbox and region presets, drawer tab routing, the calendar heatmap (`Heatmap`, `YearView`), `PanelBoundary`, and the lazy registrations. |
| `MissionMap.jsx` | The MapLibre stage: globe ⇄ mercator morph, basemap switching, GeoJSON sources for fires/clusters/selection, two-corner area picking, camera controls, the view badge and readout chip. |
| `basemapStyles.js` | The basemap style documents — the Esri raster pair as one style, the mission layers, and `mergeOverlays()` for grafting them onto the fetched vector style. Pure data and pure functions: no React, no DOM, no MapLibre, so the styles can be built and validated from Node. |
| `panels.jsx` | Chart-free pillars: `HeroStats`, `LivePanel` (24 h NIR feeds + real-window pull), `BriefingPanel` (rail headline and the four-report sub-tabs). |
| `charts.jsx` | `ClimatologyPanel` and `DiagnosticPanel` — named exports, deliberately in a lazy module so no charting code is in the first paint. Shares `useEndpoint` (stale-reply guard) and the `C` colour map. |
| `ForecastChart.jsx` | The forecast line chart; default export, lazy. |
| `plot.jsx` | The hand-rolled SVG chart kit — `<Chart>` renders bands, bars, lines, legend and hover readout. No charting dependency exists. |
| `lib.js` | The API client (`api`, `errMsg`, `invalidateApiCache`), the heat ramp, `fmt`, `doyLabel`. |
| `styles.css` | "Ember dusk" tokens, the soft-UI shadow pair, and the letter-case contract at the top of the file. |

## Data flow

- Every request goes through `api()` in `lib.js` to `/api/...`; the Vite dev proxy forwards it to `127.0.0.1:8000` (see `vite.config.js`). In the image there is no proxy: the API serves this same build and strips the `/api` prefix itself, so the client's paths are identical in both shapes.
- The client keeps a per-URL promise cache (max 200). Identical in-flight requests collapse into one, so flipping between days, spans or AOIs is served from memory; failures are never cached.
- Replacing the dataset (upload, demo, archive pull) goes through `datasetChanged()`: `invalidateApiCache()`, bump `dataKey`/`diagKey`, clear the cursor day. The panels then refetch exactly once.
- Panels that take a bbox guard against out-of-order replies — a slow answer for the previous AOI can never overwrite a newer one (`useEndpoint` in `charts.jsx`, effect cleanup in `App.jsx`).
- A thin selection answers `200` with a `note`; the UI must surface the note (as `hint` text) rather than spin forever.

## Why it is light

Measured in `npm run build`:

| Load | Size |
|---|---|
| First paint (app + React, gzip) | ≈ 55 KB |
| Map engine, on map mount (gzip) | ≈ 280 KB + 510 KB worker |
| Chart code, on first chart tab (gzip) | ≈ 4 KB |

- `React.lazy` for `MissionMap`, `charts.jsx` and `ForecastChart`; `manualChunks` in `vite.config.js` splits `vendor-react` and `vendor-maplibre` by module path.
- Hovering or focusing a drawer tab prefetches its chunk, so the click lands on a warm module.
- No web fonts (the console uses the monospace system stack), no icon library, no charting dependency — `plot.jsx` draws everything.
- `scripts/check-lazy-exports.mjs` runs as `prebuild` and fails the build when a `React.lazy` target has no default export — a mistake neither the bundler nor a type checker catches, which used to blank the page at runtime.
- `scripts/check-quality-policy.mjs` runs as `prebuild` too, and replays simulated frame times through the adaptive-detail policy: a drag that keeps up is never touched, a sustained slow one degrades exactly once, a three-frame stutter is not a frame rate, a 1.2 s stall is not a frame rate, and the detail comes back only when the gesture ends. Pure timestamps in, decisions out, so it needs no browser and cannot be timing-flaky.
- Map-side: raster tiles stop at zoom 16, tile fade is disabled, the zoom listener only re-renders when the label changes, and `LOW_END` (≤ 4 cores or ≤ 4 GB) forces a 1× render ratio and instant camera moves.
- Basemaps: the three options live in `basemapStyles.js`. Satellite and Terrain are the same style with two raster sources, so switching between them is a layer-visibility flip and both tile caches stay warm. Vector tiles cannot work that way — the provider ships a whole style document — so entering or leaving it is a `setStyle` of `mergeOverlays(fetched)`, and `hydrateLayers()` re-attaches our data on every `style.load`. The fetched document is cached per session, the failure path returns the operator to imagery with the reason on the button, and the projection expression is ours in both cases, so the badge stays honest on every basemap.
- **Adaptive detail while the camera moves.** A slow map is nearly always slow at one thing — shading the canvas mid-gesture — so the map measures its own frame times while the camera is being moved and, when a gesture holds a sustained low frame rate, drops the canvas to a 1× ratio and takes the detection points out of the draw until the motion stops. The policy lives in `adaptiveQuality.js` (pure arithmetic over timestamps, unit-tested by the prebuild guard); `MissionMap` only feeds it gesture events and rendered frames, and a gesture that keeps up is never touched. The ratio is the lever that matters — it is the whole per-frame fragment bill — and the point layer is what is left when the ratio is already 1×, as on a low-end machine. A DOM flag (`data-quality`) marks the mode for devtools, deliberately not React state: a render is the last thing a janky drag needs.
- Map rendering cost during a drag is held down by four explicit choices in the `Map` options, all of which apply to the satellite and the terrain basemap alike: MSAA is off (MapLibre's own default — it costs a full-resolution resolve every frame and only smooths the round detection dots), the canvas render ratio is capped at 1.5× (1× on a low-end probe) since a HiDPI canvas shades roughly four times the fragments of a 1× one, tile fade is 0, and expired tiles are never re-validated mid-session (failed tiles still retry). Repeated world copies are off: at the opening zoom the same Earth could otherwise be drawn up to seven times per frame.

## The map stage

- **One camera, one morph.** The style's projection interpolates `vertical-perspective` (≤ zoom 3.7) to `mercator` (≥ 5.2); the badge reports `3D globe → Transition → 2D map` from the same thresholds, so it can never disagree with the render. Start zoom is 1.65.
- **Worker handoff.** MapLibre's bundled worker URL is passed to `setWorkerUrl()` explicitly — under Vite's dep pre-bundling the default URL points at a worker that does not exist, leaving every source unparsed.
- **Layers**, in order: satellite imagery and colour terrain rasters, cluster fill/outline (convex hulls, with a line fallback for degenerate hulls), detection circles (MODIS coral, VIIRS amber, live pale gold), then the selection fill/outline/corner.
- **Controls** (bottom-left column, under the readout): Satellite/Terrain/Vector, Globe view, Fly to AOI, Reset orbit, Auto-rotate. Auto-rotate stops on any `pointerdown` or wheel gesture.
- **Basemap choice.** Vector is a real alternative, not a fallback: it carries geometry and labels, so overzooming keeps coastlines and place names sharp while a continent costs a fraction of the bytes of imagery. It trades those bytes for a little CPU (tile parsing, and a style with far more layers), which is why `SLOW_LINK` in `lib.js` weighs the *link* — `saveData`, `effectiveType`, `downlink` — and not the machine. A slow link opens the console on Vector, with a `Slow link` hint beside the controls saying why rather than leaving the operator wondering about the changed palette.
- **The bottom-left column.** The day/hotspot readout and every view control are one bottom-anchored flex column, so a wrapped row of buttons grows upward instead of colliding with the numbers. The column's bottom offset is not a magic number: `MissionMap` measures the Esri attribution notice and writes the measured height into the `--attribBand` custom property (with a `ResizeObserver`, so it holds when the notice wraps to two or three lines on a narrow window), and CSS lifts the column by that much plus a gap. The notice also paints above the console chrome, so an opened notice is never buried under a button.
- **Area selection**: `Select area` then two clicks; double-click zoom is disabled while picking, and a corner marker shows between clicks. Known gap: pointer-only, no keyboard path yet ([PRD §13](PRD.md#13-known-gaps--risks)).

## Design system

- **Material.** Every control is extruded from the surface colour by a light shadow (top-left) and a dark one (bottom-right); anything "pressed" inverts to an inset shadow of the same pair. Tokens live at the top of `styles.css`.
- **Colour meaning is fixed** — MODIS coral, VIIRS amber, live pale gold, clusters pale sand, anything modelled or harmonized teal — and the same values are used in the map legend, the diagnostic bars and the forecast lines.
- **The heat ramp** (`lib.js`) climbs from the surface colour through warm browns to a pale sand; level 0 is the panel itself, so an idle day recedes instead of reading as a low value.
- **Letter-case contract** (top of `styles.css`): labels, headings, tabs, buttons and legend items are uppercased *by CSS*; prose and values stay sentence case; acronyms (AOI, HFII, ESFP, FRP, MODIS, VIIRS, DBSCAN, FIRMS, MW) are always written in full caps; the statistic symbol stays lowercase **z**. Never hard-code a capitalised label string.
- **Motion** respects `prefers-reduced-motion`.

## Conventions for changes

- A new chart panel goes in `charts.jsx` (named export) or its own lazy module; remember the named-to-default mapping in the `React.lazy` call.
- Format numbers with `fmt()`, day numbers with `doyLabel()`; never hand-roll a thousands separator.
- Wrap each drawer tab in `PanelBoundary` so one failing panel cannot blank the console.
- Keep the letter-case contract and the colour meanings; reuse `.panel`, `.stat`, `.kv`, `.hint`, `.row`, `.btn`, `.tab` before inventing classes.
- Run `scripts/check.sh` before a review — the build includes the lazy-export guard.
