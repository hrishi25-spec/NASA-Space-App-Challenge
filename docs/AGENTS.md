# AGENTS.md — house rules for coding agents

Working rules for AI (and human) contributors to **Pyro-Harmony**, the burning-activity
calendar console in this repository. Product context lives in [PRD.md](PRD.md);
orientation and constants in [brain.md](brain.md); console internals in
[frontend.md](frontend.md); human contributor workflow in
[CONTRIBUTING.md](../CONTRIBUTING.md).

## The one command that must pass

```bash
scripts/check.sh          # POSIX — scripts\check.bat on Windows
```

It runs exactly what CI runs (`.github/workflows/ci.yml`):

1. **Doc figures** (`python scripts/check-doc-figures.py`): counts the suite by parsing
   `test_*.py` — test functions with `@pytest.mark.parametrize` expanded, no pytest run
   and no imports — and fails when a count the docs quote drifts from the code, when a
   tracked claim disappears from the docs, or when a prebuild-guard name in a document no
   longer matches a file on disk or the npm wiring.
2. **Backend suite — 98 tests** (`cd firecal/backend && .venv/bin/pytest -q`):
   40 smoke + 34 security + 24 local-archive, in-process via `TestClient`. No network,
   no `.data/` archive, no trained model required — fixtures are built inside the tests.
3. **Frontend production build** (`cd firecal/frontend && npm run build`): the
   `prebuild` step runs four zero-dependency guards — `check-lazy-exports.mjs`,
   `check-quality-policy.mjs`, `check-chart-fill.mjs`, `check-spin-policy.mjs` — then
   Vite bundles. Run one guard alone with `npm run check:charts` (or `check:lazy`,
   `check:quality`, `check:spin`).

A change that fails any of the three is not finished. Run the check before presenting work.

## Setup

```bash
python run.py                       # set up + start backend (:8000) and console (:5173)
cd firecal/backend && python train.py   # optional: train the forecast prior over .data/ (~15 min)
```

Python 3.10+ and Node 18+ are the only requirements; `.venv` lives in
`firecal/backend/`. `torch` is optional — without it `/forecast` falls back to scaled
seasonal climatology and the UI names the fallback.

## Where things live

| Path | What it holds |
|---|---|
| `firecal/backend/main.py` | Every endpoint plus the cores: `harmonize`, `harmonized_daily`, `_zstats`, `_streaks`, `_threat`, `_biomes`, `_cluster_payload`, `_esfp`, `cached` |
| `firecal/backend/archives.py` | Local-archive inventory under `.data/`, the bounded spread slice reader, `allocate()` (merge budget by file size), `read_merge()` |
| `firecal/backend/regions.py` | The five curated AOI presets behind `GET /regions` |
| `firecal/backend/demo.py` | Synthetic FIRMS generator — the test fixture; nothing in the UI calls it |
| `firecal/backend/train.py`, `forecast_model.py` | Train the checkpoint; carry it to `/forecast` |
| `firecal/backend/test_*.py` | Smoke, security and archive suites, colocated with the app |
| `firecal/frontend/src/` | Console: `App.jsx`, `MissionMap.jsx`, `panels.jsx`, `charts.jsx`, `plot.jsx`, `chartGeometry.js`, `autoRotate.js`, `adaptiveQuality.js`, `basemapStyles.js`, `lib.js`, `styles.css` |
| `firecal/frontend/scripts/` | The four prebuild guards |
| `docs/` | PRD, this file, orientation, frontend guide, ADRs |
| `scripts/check.sh` / `.bat` | The same checks CI runs |

## Never do these

- **Never put synthetic data in the console.** `demo.py` and `POST /demo` exist as
  test fixtures and are documented as such. The UI opens the real archives in `.data/`;
  a new UI path that fabricates a dataset needs a reason a reviewer can weigh against it.
- **A filename is data, not a command.** The 2002–2024 poster dataset loads via
  `POST /upload?demo_transition=true`, never by naming a file.
- **An archive id is a name, not a path.** `/datasets/load` resolves its `id` against
  the inventory `GET /datasets` produced and re-checks containment; no request string
  is ever joined onto a path, and no absolute path is ever published in a response.
- **Client input never selects a URL.** `region` is allowlisted before any outbound
  fetch, `bbox` and numerics are range-validated/clamped, writes (`POST`/`PUT`/`PATCH`/
  `DELETE`) are `Origin`-gated, uploads are capped *before* buffering, and
  `FIRMS_MAP_KEY` is read from the environment only — never from a request, never
  echoed into an error body.
- **Never import chart code in the shell.** `MissionMap`, `charts.jsx` and
  `ForecastChart.jsx` are lazy for a reason; a new `React.lazy` target must resolve to
  a default export or `check-lazy-exports.mjs` fails the build.
- **Keep `scipy`/`scikit-learn` imports lazy** inside clustering/briefing. Moving them
  to module scope costs ~2.5 s of startup.
- **Never commit `.data/`, `firecal/backend/model/`, `.env`, `*.csv` or build output.**
  All are gitignored; the checkpoint is derived data rebuilt by `train.py`, and a
  missing or malformed checkpoint is not an error.
- **Never diverge the two harmonizers.** `train.py` reads through the server's own
  `harmonize(geometry=False)` and `harmonized_daily()`; a second implementation of the
  sensor rescale would train the model on a different quantity than the endpoint
  predicts.

## How to change the backend

- Endpoints live in `main.py`. Every numeric query parameter is clamped
  (`limit` ≤ 20000, `eps` ≤ 5000, `epochs` ≤ 200, `horizon` ≤ 90, …); every string
  that reaches an outbound URL is allowlisted or regex-validated first.
- Derived analytics go through the `cached` memo and are invalidated when the dataset
  changes — do not recompute on every request, and do not break invalidation.
- Responses gzip (the app installs `GZipMiddleware`); keep payloads JSON-serializable
  and honest: a thin selection answers `200` with a `note`, and panels must show it
  instead of spinning.
- Security behaviour is pinned by `test_security.py`. If you touch upload handling,
  CORS/CSP, the origin gate or outbound fetching, expect that suite to be the reviewer —
  and extend it when you add a new trust boundary.
- New non-trivial logic leaves one runnable check behind: a `test_*.py` case in the
  suite that fits, colocated with the others.

## How to change the frontend

- **Chart arithmetic goes in `chartGeometry.js`, never inline in `plot.jsx`** — the
  prebuild guard can only assert what is a pure function of width, height and rows.
- **Drift/frame policy goes in `autoRotate.js` / `adaptiveQuality.js`** as pure
  functions for the same reason.
- Every request goes through `api()` in `lib.js` (memoized) — do not add a second
  fetch path, and keep replies stale-guarded (`useEndpoint`, effect cleanup) so a slow
  answer for the previous AOI cannot overwrite a newer one.
- **Labels are uppercased by CSS** (`styles.css`, letter-case contract at the top of
  the file): write labels in sentence case in source; acronyms (HFII, ESFP, FRP, …)
  stay all-caps; the statistic symbol stays lowercase `z`.
- Colour carries meaning: MODIS coral, VIIRS amber, live feed pale gold, clusters
  sand, anything modelled or harmonized teal. Follow it in map, legend and charts.
- Respect the performance budget: first paint stays ~55 KB gzipped, the map engine and
  chart code stay behind `React.lazy`, no charting library, no icon/font packs. New
  numeric layout logic gets an assertion in `check-chart-fill.mjs`.
- Degradation is part of the feature: `prefers-reduced-motion`, `LOW_END` machines,
  missing WebGL2 and a failed basemap fetch all have defined behaviour — extend them
  rather than adding a path that only works on good hardware.

## How to update docs

- **A change that invalidates a doc updates the doc.** [PRD.md](PRD.md) is the
  acceptance-criteria contract; [brain.md](brain.md) holds the orientation numbers;
  [frontend.md](frontend.md) the console internals; the root
  [README.md](../README.md) the user-facing contract (API table, limits, security).
- **Keep counts honest.** Test totals, guard counts and endpoint lists are asserted
  against reality in prose — when you add a test, a guard or a route, update every
  place that names the number (`README.md`, `CONTRIBUTING.md`, `docs/brain.md`,
  `docs/PRD.md`). `scripts/check-doc-figures.py` fails CI when you don't, and fails if a
  tracked claim is deleted instead of updated.
- **CHANGELOG.md is user-facing and newest-first** — describe what a reader of the
  console would notice, not the diff.
- Layout decisions that are expensive to reverse get an ADR in
  [docs/decisions/](decisions/); everything else is prose.
- Links are checked in review: a relative link that points at a file this repository
  does not contain is an error (this file replaced one that had several).

## Pull requests

- Branch from `main` — `fix/…` or `feat/…` — and keep the change focused.
- Run `scripts/check.sh` and keep it green.
- Do not reintroduce synthetic data, absolute paths in API responses, or unbounded
  uploads/queries; those regressions each have a test that will fail loudly.
