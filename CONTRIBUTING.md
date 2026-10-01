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

It runs exactly what CI runs: the backend test suite (33 smoke + 22 security tests, in-process via `TestClient`) and the frontend production build, whose prebuild step is the lazy-export guard plus the adaptive-detail policy check.

## Pull requests

- Branch from `main` — `fix/…` or `feat/…` — and keep the change focused.
- Update the docs a change invalidates; [docs/PRD.md](docs/PRD.md) is the acceptance-criteria contract.
- New non-trivial logic leaves one runnable check behind (a test, or an assert-style self-check for a script).
- Don't commit datasets (`*.csv`), `.env` files or build output — `.gitignore` covers all three.
- Layout decisions are recorded as ADRs in [docs/decisions/](docs/decisions/); add one when a change is expensive to reverse.

## Where things live

| Path | What it holds |
|---|---|
| `firecal/backend/` | FastAPI app, synthetic demo generator, region presets, tests |
| `firecal/frontend/` | React + Vite console (hand-rolled SVG charts, MapLibre map) |
| `docs/` | Requirements, background material, ADRs |
| `scripts/` | Automation shared by humans and CI |
