# Frontend — the Pyro-Harmony console

How the React console is put together, which files own what, and the rules that keep it inside its performance budget. Product context lives in [PRD.md](PRD.md); install and commands in the [README](../README.md).

## The screen

One screen, five zones, all fed by the same single dataset:

| Zone | Contents |
|---|---|
| Command bar (header) | Link signal, logo, hotspot/window/sensor readouts, **Upload CSVs**, the **Local archives…** dataset selector, region picker, **Select area** / **Clear** |
| Left rail | Hero telemetry (HFII, ESFP, hotspots, record span), Dataset (file, sensor, slice), Selection (AOI, cursor day, span, region facts), Clustering (counts, DBSCAN params, live feed state) |
| Centre stage | MapLibre: one camera that morphs a 3D globe into a flat map, with cluster extents, detection points and the readout chip |
| Right rail | Incident Commander briefing (headline version) and the anomalies list |
| Analytics drawer | Five tabs — Burning calendar, Forecast, Climatology, Illusion diagnostic, Briefing detail |

## Module map

| File | Responsibility |
|---|---|
| `main.jsx` | Mounts `<App />`. |
| `App.jsx` | The shell: dataset state (`meta`, `dataKey`), the local-archive list and the picker's `loadArchive()` (one archive or `MERGE_ALL`), cursor day and span, bbox and region presets, drawer tab routing, the calendar heatmap (`Heatmap`, `YearView`), `PanelBoundary`, and the lazy registrations. |
| `MissionMap.jsx` | The MapLibre stage: globe ⇄ mercator morph, basemap switching, GeoJSON sources for fires/clusters/selection, two-corner area picking, camera controls, the view badge and readout chip. |
| `autoRotate.js` | The globe drift's policy: the rate (6°/s, 3°/s on a low-end probe), the clamped per-frame step, `AXIAL_TILT_DEG` (Earth's 23.44° obliquity, the pitch the drift holds the camera at so the globe turns about the real axis), and the rule that the drift yields whenever a gesture or an animated camera move owns the map. Pure numbers, so the prebuild guard can simulate frame cadences. |
| `basemapStyles.js` | The basemap style documents — the Esri raster pair as one style, the mission layers, and `mergeOverlays()` for grafting them onto the fetched vector style. Pure data and pure functions: no React, no DOM, no MapLibre, so the styles can be built and validated from Node. |
| `panels.jsx` | Chart-free pillars: `HeroStats`, `LivePanel` (24 h NIR feeds + real-window pull), `BriefingPanel` (rail headline and the four-report sub-tabs). |
| `charts.jsx` | `ClimatologyPanel` and `DiagnosticPanel` — named exports, deliberately in a lazy module so no charting code is in the first paint. Shares `useEndpoint` (stale-reply guard) and the `C` colour map. |
| `ForecastChart.jsx` | The forecast line chart; default export, lazy. |
| `plot.jsx` | The hand-rolled SVG chart kit — `<Chart>` renders bands, bars, lines, a caption-and-keys legend, the crosshair with its hover card, and the optional drag-to-zoom brush. No charting dependency exists. |
| `chartGeometry.js` | The chart kit's pure arithmetic: gutters, row positions with a bar inset, axis step and top, tick selection, hover snapping, tooltip clamping, and the run-splitting that breaks a line at a gap. No React, no DOM — so the prebuild guard can drive every coordinate from Node. |
| `lib.js` | The API client (`api`, `errMsg`, `invalidateApiCache`), the heat ramp, `fmt`, `doyLabel`. |
| `styles.css` | "Ember dusk" tokens, the soft-UI shadow pair, and the letter-case contract at the top of the file. |

## Data flow

- Every request goes through `api()` in `lib.js` to `/api/...`; the Vite dev proxy forwards it to `127.0.0.1:8000` (see `vite.config.js`). In the image there is no proxy: the API serves this same build and strips the `/api` prefix itself, so the client's paths are identical in both shapes.
- The client keeps a per-URL promise cache (max 200). Identical in-flight requests collapse into one, so flipping between days, spans or AOIs is served from memory; failures are never cached.
- Replacing the dataset (opening a local archive, upload, live archive pull) goes through `datasetChanged()`: `invalidateApiCache()`, bump `dataKey`/`diagKey`, clear the cursor day. The panels then refetch exactly once.
- **The dataset is chosen, not handed.** `App.jsx` fetches `GET /datasets` once at mount and keeps the list in state; `null` means *still looking*, `[]` means *nothing on this machine* (a fresh clone, CI, the image) and each entry is a button on the standby card plus one option in the header selector. `loadArchive(id)` posts to `/datasets/load` with a `busy` flag on every trigger, and the response's `load` block becomes the **Dataset** panel — file, sensor, `kept of ~estimated rows · spread`. A bounded slice is a sample of the file, and a calendar that does not say so reads as a full record.
- **One entry merges the lot.** `MERGE_ALL` is not an id: it posts `all=true`, and the same `loadArchive` covers both modes so the busy state, the error path and `datasetChanged()` are written once. It appears only when the directory holds more than one archive, and it is worded with what it actually does (*Merge all 15 archives — every sensor, every year*) because a button that says "load all" invites the reading that the whole directory has been read. The merged panel swaps the file row for an archive count, lists the sensors, and puts each export's contribution behind a `<details>` — the total alone hides how uneven a size-weighted split is.
- The standby card is the console's only empty state, and it is a *choice*: the archives it found, or the upload path, or the sentence saying `.data/` is empty. The AOI-empty state below it says *Clear area* rather than offering to fabricate data into the selection.
- Panels that take a bbox guard against out-of-order replies — a slow answer for the previous AOI can never overwrite a newer one (`useEndpoint` in `charts.jsx`, effect cleanup in `App.jsx`).
- A thin selection answers `200` with a `note`; the UI must surface the note (as `hint` text) rather than spin forever.

## Why it is light

Measured in `npm run build`:

| Load | Size |
|---|---|
| First paint (app + React, gzip) | ≈ 55 KB |
| Map engine, on map mount (gzip) | ≈ 280 KB + 510 KB worker |
| Chart code, on first chart tab (gzip) | ≈ 4 KB |

- `React.lazy` for `MissionMap`, `charts.jsx` and `ForecastChart`; `manualChunks` in `vite.config.js` splits `vendor-react` and MapLibre's two prebundled modules (`vendor-maplibre` + `vendor-maplibre-shared`) by module path, so the entry and the shared code it imports download in parallel and cache apart. `chunkSizeWarningLimit` is a 600 kB budget set just above the two chunks that legitimately cannot go lower — MapLibre's entry (~554 kB minified) and its worker (~510 kB) ship as single prebundled files — which keeps Vite's oversized-chunk warning armed for everything else instead of muting it.
- Hovering or focusing a drawer tab prefetches its chunk, so the click lands on a warm module.
- No web fonts (the console uses the monospace system stack), no icon library, no charting dependency — `plot.jsx` draws everything.
- `scripts/check-lazy-exports.mjs` runs as `prebuild` and fails the build when a `React.lazy` target has no default export — a mistake neither the bundler nor a type checker catches, which used to blank the page at runtime.
- `scripts/check-spin-policy.mjs` runs as `prebuild` too, and simulates frame cadences through `autoRotate.js`: the drift travels the same degrees per second at 100, 50, 20 and 10 fps, a five-second frame advances one clamped 250 ms slice rather than 30°, the globe never turns backwards across the ±180 seam, the tilt is Earth's 23.44° obliquity rather than 0, and the wiring is checked (animation frames rather than a timer, `map.isMoving()` rather than an API the public `Map` does not have, the sampler flag, and both `easeTo` calls that pitch and level the camera).
- `scripts/check-chart-fill.mjs` runs as `prebuild` too, and drives `chartGeometry.js` directly: the plot fills its container and a band edge can never exceed the axis, ticks are readable round numbers, x labels never crowd each other, bars stay inside the frame, hover snaps to a row and the readout card stays on screen, a gap in a series splits the line, and the card's CSS width matches the clamp in code. It also fails the build if `plot.jsx` ever goes back to a scaled, letterboxing viewBox. Layout is otherwise only visible by looking at it.
- `scripts/check-quality-policy.mjs` runs as `prebuild` too, and replays simulated frame times through the adaptive-detail policy: a drag that keeps up is never touched, a sustained slow one degrades exactly once, a three-frame stutter is not a frame rate, a 1.2 s stall is not a frame rate, and the detail comes back only when the gesture ends. Pure timestamps in, decisions out, so it needs no browser and cannot be timing-flaky.
- Map-side: raster tiles stop at zoom 16, tile fade is disabled, the zoom listener only re-renders when the label changes, and `LOW_END` (≤ 4 cores or ≤ 4 GB) forces a 1× render ratio and instant camera moves.
- Basemaps: the three options live in `basemapStyles.js`. Satellite and Terrain are the same style with two raster sources, so switching between them is a layer-visibility flip and both tile caches stay warm. Vector tiles cannot work that way — the provider ships a whole style document — so entering or leaving it is a `setStyle` of `mergeOverlays(fetched)`, and `hydrateLayers()` re-attaches our data on every `style.load`. The fetched document is cached per session, the failure path returns the operator to imagery with the reason on the button, and the projection expression is ours in both cases, so the badge stays honest on every basemap.
- **Which style is on the map is state, and it has three values.** `styleKindRef` holds `placeholder` (the map was built before the vector document arrived), `raster` or `vector`; it is seeded from the style the `Map` is actually constructed with, so "the raster pair" and "the style we are wearing" can never be confused. Only a loaded raster style can be panned by flipping visibility — anything else has to be replaced with `setStyle`, or the console would report a basemap it never drew. That is what the fallback path does: a declined vector fetch installs the imagery, because an opening on Vector begins on the placeholder, whose raster layers do not exist, and a visibility flip on it leaves a black well under a badge that says *Satellite*.
- **Adaptive detail while the camera moves.** A slow map is nearly always slow at one thing — shading the canvas mid-gesture — so the map measures its own frame times while the camera is being moved and, when a gesture holds a sustained low frame rate, drops the canvas to a 1× ratio and takes the detection points out of the draw until the motion stops. The policy lives in `adaptiveQuality.js` (pure arithmetic over timestamps, unit-tested by the prebuild guard); `MissionMap` only feeds it gesture events and rendered frames, and a gesture that keeps up is never touched. The ratio is the lever that matters — it is the whole per-frame fragment bill — and the point layer is what is left when the ratio is already 1×, as on a low-end machine. A DOM flag (`data-quality`) marks the mode for devtools, deliberately not React state: a render is the last thing a janky drag needs.
- Map rendering cost during a drag is held down by four explicit choices in the `Map` options, all of which apply to the satellite and the terrain basemap alike: MSAA is off (MapLibre's own default — it costs a full-resolution resolve every frame and only smooths the round detection dots), the canvas render ratio is capped at 1.5× (1× on a low-end probe) since a HiDPI canvas shades roughly four times the fragments of a 1× one, tile fade is 0, and expired tiles are never re-validated mid-session (failed tiles still retry). Repeated world copies are off: at the opening zoom the same Earth could otherwise be drawn up to seven times per frame.

## The map stage

- **One camera, one morph.** The style's projection interpolates `vertical-perspective` (≤ zoom 3.7) to `mercator` (≥ 5.2); the badge reports `3D globe → Transition → 2D map` from the same thresholds, so it can never disagree with the render. Start zoom is 1.65.
- **Worker handoff.** MapLibre's bundled worker URL is passed to `setWorkerUrl()` explicitly — under Vite's dep pre-bundling the default URL points at a worker that does not exist, leaving every source unparsed.
- **Layers**, in order: satellite imagery and colour terrain rasters, cluster fill/outline (convex hulls, with a line fallback for degenerate hulls), detection circles (MODIS coral, VIIRS amber, live pale gold), then the selection fill/outline/corner.
- **Controls** (bottom-left column, under the readout): Satellite/Terrain/Vector, Globe view, Fly to AOI, Reset orbit, Auto-rotate. Auto-rotate stops on any `pointerdown` or wheel gesture.
- **Auto-rotate** turns the globe at a real rate (6°/s, or 3°/s on a low-end probe) accumulated from frame times by `autoRotate.js`, so it is the same speed at 60 fps or at 10 fps; a frame longer than 250 ms contributes one clamped slice instead of teleporting the globe. It holds while another move owns the camera — a gesture, or this console's own Fly to AOI / Globe view / Reset orbit — because every bearing set goes through MapLibre's `jumpTo`, which calls `stop()` and would otherwise cancel that animation a frame after it started. Its own rotation is flagged so it never arms the adaptive-detail sampler (which would otherwise hold the measurement window open every frame and pin a slow machine at reduced detail).
- **…about the right axis.** A bearing change with a level camera turns the planet about a vertical line — a top, not a world — so the drift pitches the camera to `AXIAL_TILT_DEG` (23.44°, Earth's obliquity) as it starts and eases it back to level when it stops. The ease back is conditional on the pitch still being the one the drift set: an operator who has tilted the camera themselves since is left alone rather than having their view taken away. Both the constant and the two `easeTo` calls are pinned by the prebuild guard, since the difference between 23° and 0° is only visible by looking at the pole.
- **Basemap choice.** Vector is a real alternative, not a fallback: it carries geometry and labels, so overzooming keeps coastlines and place names sharp while a continent costs a fraction of the bytes of imagery. It trades those bytes for a little CPU (tile parsing, and a style with far more layers), which is why `SLOW_LINK` in `lib.js` weighs the *link* — `saveData`, `effectiveType`, `downlink` — and not the machine. A slow link opens the console on Vector, with a `Slow link` hint beside the controls saying why rather than leaving the operator wondering about the changed palette.
- **The bottom-left column.** The day/hotspot readout and every view control are one bottom-anchored flex column, so a wrapped row of buttons grows upward instead of colliding with the numbers. It sits on the map's own bottom edge, 12 px — the same inset the legend chip uses on the top edge, which is what makes the two read as one frame. The one thing that can genuinely collide with it is the Esri attribution notice, a legal requirement whose size we do not control, so the band under the column is not a constant: `MissionMap` compares their horizontal extents and writes the notice's measured height into `--attribBand` **only while the notice reaches far enough left to overlap the column** (`ResizeObserver` watches the notice, the map container and the column, plus every `styledata`, so attribution movement on resize and control wrapping both trigger a new measurement). A lifted column stays lifted while the notice remains present; if the notice disappears, the band resets to zero. Collapsed — the small corner button — the reserved right margin keeps the band at 0 and the controls on the edge; expanded, the column lifts by the notice's height instead of permanently floating a notice's height above the edge. The notice also paints above the console chrome, so an opened notice is never buried under a button.
- **Any browser, or a legible reason why not.** MapLibre draws with WebGL2 only, and a browser that refuses it throws during construction — which used to leave a black rectangle that reads as a broken map. `MissionMap` asks a throwaway canvas for a `webgl2` context first (and releases it immediately, since browsers cap how many live contexts a page may hold), catches a constructor that throws anyway, and puts the reason in the well while every panel below keeps working. Anything the page itself blocks — a CSP refusal, most often — is surfaced the same way through a `securitypolicyviolation` listener, because a refused tile host is otherwise completely silent in the UI.
- **Area selection**: `Select area` then two clicks; double-click zoom is disabled while picking, and a corner marker shows between clicks. Known gap: pointer-only, no keyboard path yet ([PRD §13](PRD.md#13-known-gaps--risks)).

## The chart tabs

- **Full width, measured.** A chart is laid out in its container's own pixels: `plot.jsx` measures the widget with a `ResizeObserver` and sets the SVG `viewBox` to that many units, so one viewBox unit is one CSS pixel. A wide window therefore gets a wide plot with 9px labels that stay 9px, instead of a fixed 720-unit viewBox being scaled (which letterboxed the plot and shrank its own text). Every coordinate comes from `chartGeometry.js`.
- **Chart on top, facts beneath.** `charts.jsx` renders a `.chartStack`: the plot, then its key numbers as `.stat` cards in a row that reflows with the width, then any explanatory hint. A chart squeezed beside a 220px sidebar is what made these tabs read as a small box in the corner.
- **Legend below the plot** — caption on the left, series keys on the right (centred when there is no caption) — matching where the calendar and the map put their keys.
- **Interaction.** Hovering draws a crosshair and a card beside the pointer listing every series' value, with a per-series `fmt` when the readout should not match the axis units (the diagnostic bars are drawn in thousands and read out as exact counts). The tooltip snaps to the nearest row rather than following the pointer, so moving the mouse inside a column does not re-render the chart. `←`/`→` (and `Home`/`End`-style paging) walk the readout, `Esc` clears it, so the values are not mouse-only.
- **Zoom where it means something.** `Chart` takes an optional `onSelect`: dragging across the plot reports a row range, which `ForecastChart` turns into a zoom with a brush overlay, a **Window** selector and **Reset zoom**. Ranges are stored as absolute indices, so a second, tighter drag composes instead of re-zooming from the full series.
- **Gaps break lines.** `runs()` splits a series at missing values; a path through them used to plunge to the axis floor (the forecast series is null on every observed day).

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
- Run `scripts/check.sh` before a review — the build runs the lazy-export, adaptive-detail, chart-layout and orbital-drift guards.
- Put a new coordinate in `chartGeometry.js`, not inline in `plot.jsx`: the prebuild guard can only assert what is a pure function of the width, the height and the rows.
