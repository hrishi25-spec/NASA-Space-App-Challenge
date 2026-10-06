# Contributing

Thanks for wanting to help. This is a hackathon prototype; the fastest way to contribute is a focused pull request against `main`.

## Setup

Python 3.10+ and Node 18+ are the only requirements. One command creates the backend virtualenv, installs both sides and starts them:

```bash
python run.py
```

Docker works too, and needs neither runtime installed — it builds the console and serves it from the API on one port:

```bash
docker build -t pyro-harmony . && docker run --rm -p 8000:8000 pyro-harmony
```

Product context — what each pillar does, the acceptance criteria and the known gaps — lives in [docs/PRD.md](docs/PRD.md). The docs index is [docs/README.md](docs/README.md).

## The one command that must pass

```bash
scripts/check.sh          # POSIX   (bash)
scripts\check.bat         # Windows
```

It runs exactly what CI runs: the doc-figure check (`scripts/check-doc-figures.py`, which fails when a number the docs quote drifts from the code), the doc-link check (`scripts/check-doc-links.py`, which fails when a relative link does not resolve), that guard's own test suite (`scripts/test_check_doc_links.py`, 34 stdlib `unittest` tests pinning its slug, case and tracked-file rules), the backend test suite (106 tests: 44 smoke + 34 security + 28 local-archive, in-process via `TestClient`), and the frontend production build, whose prebuild step is the lazy-export guard and the adaptive-detail, chart-layout and orbital-drift policy checks.

Neither takes minutes. Training the forecast model does:

```bash
cd firecal/backend && python train.py        # ~15 min over a 10 GB FIRMS archive, once
```

It is not part of the check — the archive is local data that is not in the repository — so the tests build a few dozen synthetic rows and push them through the same scan/save/load path instead. The console's dataset picker is tested the same way: `test_archives.py` writes its own small FIRMS export directory — three files over two instruments, one of them naming its platform (`SNPP`) the way the real S-NPP downloads do — and points the app at it, so `GET /datasets`, `POST /datasets/load` and the all-archives merge are exercised without a 10 GB directory. The console itself needs one only for a look at real data — drop FIRMS exports in `.data/`, pick one from the standby card, or merge them all.

## Pull requests

- Branch from `main` — `fix/…` or `feat/…` — and keep the change focused.
- Update the docs a change invalidates; [docs/PRD.md](docs/PRD.md) is the acceptance-criteria contract.
- New non-trivial logic leaves one runnable check behind (a test, or an assert-style self-check for a script).
- Don't commit datasets (`*.csv`), the FIRMS training directory (`.data/`), `.env` files or build output — `.gitignore` covers all four, and the checkpoint trained from the archive (`firecal/backend/model/`) is derived data that belongs with it.
- Don't reintroduce synthetic data into the console. `demo.py` and `POST /demo` exist as fixtures for the suite and are documented as such; the UI opens the real archives in `.data/`, and a new UI path that fabricates a dataset needs a reason a reviewer can weigh against that.
- Layout decisions are recorded as ADRs in [docs/decisions/](docs/decisions/); add one when a change is expensive to reverse.

## Where things live

| Path | What it holds |
|---|---|
| `firecal/backend/` | FastAPI app, the local-archive inventory + slice reader, the synthetic fixture generator, region presets, the forecast model and its trainer, tests |
| `firecal/frontend/` | React + Vite console (hand-rolled SVG charts, MapLibre map) |
| `docs/` | Requirements, background material, ADRs |
| `scripts/` | Automation shared by humans and CI |
