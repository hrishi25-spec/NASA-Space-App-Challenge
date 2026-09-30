# Pyro-Harmony (firecal) — agent rules

FastAPI + React/Vite fire-intelligence console (NASA Space Apps 2026 challenge app).
Backend `firecal/backend` (uvicorn, pandas/NumPy/SciPy/scikit-learn), frontend
`firecal/frontend` (React 18, Vite 5, MapLibre GL). Docs live in `README.md` (how it
works) and `PRD.md` (requirements, evidence, gaps, roadmap).

## Skills: 1,258 of them are available in this repo. Use them.

`.skills/skills/` holds 417 skill directories (a mirror of `~/skills`, the directory
Freebuff auto-loads). Two of those are bundles: `Anthropic-Cybersecurity-Skills`
(818 skills one level down) and `claude-plugins-official` (31). A skill is an
instruction set, not documentation: read the `SKILL.md`, then do what it says.

**Route before you plan.** For any non-trivial request:

1. Name the domains it touches, then read the mapped `SKILL.md` (the table below).
   One to three skills, not the whole library — they are short files.
2. Domain rules and skill methods beat habit; this file's project rules beat a skill.
3. Still no match? Grep the one-line-per-skill catalog instead of walking the tree:
   `rg -i 'secrets|vault|scan' .skills/CATALOG.md`
4. After adding or changing skills: `python3 .skills/catalog.py` (rewrites `CATALOG.md`).

### Curated map (paths relative to `.skills/skills/`)

| Task | Read |
|---|---|
| Reviewing, refactoring, cutting scope | `ponytail/SKILL.md`, `ponytail-review/SKILL.md`, `ponytail-audit/SKILL.md`, `ponytail-debt/SKILL.md` |
| New feature, plan or spike | `ponytail/SKILL.md`, `agent-analyze-code-quality/SKILL.md`, `writing-rules/SKILL.md` |
| Design, layout, visual polish | `frontend-design/SKILL.md`, `infographics/SKILL.md`, `diagram-design/SKILL.md` |
| Browser verification of this app | `browser-use/SKILL.md`, then the `Read`/screenshot tools already in this session |
| Security review of this repo | `claude-security/SKILL.md`, `security-audit/SKILL.md`, `safety-scan/SKILL.md`, `cybersecurity-skills-router/SKILL.md` (routes into the 818-skill bundle) |
| Web-app security specifics | `Anthropic-Cybersecurity-Skills/skills/performing-web-application-penetration-test/SKILL.md`, `Anthropic-Cybersecurity-Skills/skills/implementing-semgrep-for-custom-sast-rules/SKILL.md`, `Anthropic-Cybersecurity-Skills/skills/analyzing-sbom-for-supply-chain-vulnerabilities/SKILL.md` |
| PII / secrets in data or logs | `pii-detect/SKILL.md`, `harness-mcp-scan/SKILL.md` |
| API surface, OpenAPI, docs | `api-docs/SKILL.md`, `doc-gen/SKILL.md`, `markdown-mermaid-writing/SKILL.md` |
| Geo / time-series / science method | `geopandas/SKILL.md`, `geomaster/SKILL.md`, `aeon/SKILL.md`, `matplotlib/SKILL.md`, `exploratory-data-analysis/SKILL.md`, `analytical-method-validation/SKILL.md` |
| Claims, sources, papers | `deep-research/SKILL.md`, `literature-review/SKILL.md`, `citation-management/SKILL.md` |
| Tests, verification, perf | `test-gaps/SKILL.md` (intent only, see below), `verification-quality/SKILL.md`, `performance-analysis/SKILL.md`, `tdd-workflow/SKILL.md` |
| Dependencies, cost, token budget | `dependency-check/SKILL.md`, `cost-optimize/SKILL.md` (intent only, see below) |
| Git, commits, PRs, handoff | `git-workflow/SKILL.md`, `commit-context/SKILL.md`, `github-code-review/SKILL.md`, `handoff/SKILL.md` |
| Architecture decisions | `adr-create/SKILL.md`, `adr-review/SKILL.md`, `adr-verify/SKILL.md` |
| Adding a skill of your own | `skill-creator/SKILL.md`, `skill-development/SKILL.md` |

### Skills that cannot run here

Most of the library is orchestration for other runtimes. Do **not** burn time trying
to execute them; apply their intent with the local tools instead.

- Everything named `agent-*`, `agentdb-*`, `swarm*`, `hive*`, `v3-*`, `flow-nexus*`,
  `daa-*`, `loop-*`, `reasoningbank-*`, `intelligence-*`, `rvf-*`, `federation*`,
  `harness-*`, `claims`, `monitor-stream`, `hookify`, `hooks-automation`,
  `cron-schedule`, `autopilot-*` — they shell out to `npx @claude-flow/cli`,
  `ruflo <cmd>`, or `mcp__plugin_ruflo-core_ruflo__*` tools that are not installed
  in this session. Several are empty stubs that only say "invoke with $agent-x".
- `cost-*` (24 skills), `test-gaps`, `dependency-check` — thin wrappers over the same
  CLI/MCP surface. Apply their *intent* by hand: measure locally, grep for real gaps,
  inspect the lockfile and bundle sizes.
- `browser-record`, `browser-replay`, `browser-test`, `browser-screenshot-diff` —
  need the ruflo RVF container; use the session's own preview/browser tools.
- `access`, `configure` — Discord bot administration; needs a bot token.
- `music-*`, `trader-*`, `iot-*`, `cardputer-buddy` — need hardware, broker or media
  credentials and have nothing to do with this project.

## Project rules

- **Never commit, push, open a PR or stage broadly unless asked.** This checkout is
  shared; leave other people's changes and hunks alone.
- **Verify before you report.** Backend: `cd firecal/backend && .venv/bin/python -m pytest -q`.
  Frontend: `cd firecal/frontend && npm run build` (it runs a lazy-export guard first).
  A change to a chart or panel also gets a real browser check.
- **Docs are part of the change.** `README.md` and `PRD.md` quote measured numbers
  (test counts, endpoint timings, demo statistics, payload sizes). When a number moves,
  update every place it is stated, or say which ones you left stale.
- **Numbers in the docs must be measured, never estimated.** If a claim cannot be
  measured here, say so instead of inventing a figure.
- Backend servers: bind `127.0.0.1:8000` (uvicorn from `firecal/backend`), frontend
  `127.0.0.1:5173` (vite). Check for an existing listener before starting another one;
  background processes die with the shell, so start them detached.
- Prefer editing existing files; the fewest changes that fix the real cause. This repo
  has no database and no auth by design — that is a stated non-goal, not a bug.
