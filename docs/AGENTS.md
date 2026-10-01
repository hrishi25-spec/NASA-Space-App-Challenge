# Combined AGENTS.md

This file combines five separate agent instruction files, kept verbatim, each under its own part heading. Headings inside each part are unchanged from the original, so they are not nested under the part heading.

## Contents

1. [Part 1: Security Skills Library](#part-1-security-skills-library)
2. [Part 2: Ponytail (lazy senior dev mode)](#part-2-ponytail-lazy-senior-dev-mode)
3. [Part 3: agentmemory](#part-3-agentmemory)
4. [Part 4: Scientific Skills Repository](#part-4-scientific-skills-repository)
5. [Part 5: Claude Flow V3 / Ruflo](#part-5-claude-flow-v3--ruflo)

---

# Part 1: Security Skills Library

*Source: AGENTS_security_skills.md*

# AGENTS.md

Instructions for AI agents working in this repository.

## What this repository is

A library of 817 cybersecurity skills. Each skill is a directory under `skills/` containing a `SKILL.md` — YAML frontmatter plus a Markdown procedure — following the [agentskills.io](https://agentskills.io) standard.

The layout is flat: `skills/<skill-name>/SKILL.md`. Do not nest skills by domain; agents discover them by scanning `skills/*/SKILL.md`.

## Reading a skill

Only `name` and `description` load at discovery time. The body loads once the description matches the request; `references/`, `scripts/` and `assets/` load only when referenced.

Read the description first. If it carries a negative trigger — "Do not use for X — use `other-skill`" — honour it. Those exist because two skills would otherwise compete for the same request.

## Changing a skill

Frontmatter is parsed by `tools/skill_frontmatter.py`, which uses PyYAML. Do not write a regex frontmatter parser; CI fails the build if it detects one. Three hand-rolled parsers previously truncated 604 of 817 descriptions to their first line.

After changing any `SKILL.md`:

```bash
pip install pyyaml
python tools/validate-skill.py --all
python tools/validate-agentskills.py --strict
python tools/generate-index.py          # regenerate index.json
python tools/lint-descriptions.py --all
python tools/detect-collisions.py
```

All five run in CI. `index.json` is generated — never edit it by hand.

## Writing a description

The description is the only signal another agent sees when deciding whether to load the skill. It needs four things:

1. What it does, concretely.
2. `Use when …` — the phrasings a user would actually type.
3. `Keywords:` — tool names, event IDs, CVEs, API calls.
4. `Do not use for X — use other-skill.` — the negative trigger.

Keep it under 1024 characters. Keep the body under 500 lines; depth belongs in `references/`.

## Constraints

- `name` must equal the directory name, lowercase-kebab, ≤64 characters.
- `domain` is always `cybersecurity`. `subdomain` must be one the validator accepts — see CONTRIBUTING.md.
- Scripts must run. No placeholders, no invented API endpoints, no fabricated CVE numbers.
- Framework IDs must be real and current. A wrong mapping sends an investigation the wrong way; omit rather than guess.

## Scope

See [SCOPE.md](SCOPE.md). This repository holds skills. Runtimes, engines and applications belong elsewhere.

---

# Part 2: Ponytail (lazy senior dev mode)

*Source: AGENTS_ponytail.md*

# Ponytail, lazy senior dev mode

You are a lazy senior developer. Lazy means efficient, not careless. The best code is the code never written.

Before writing any code, stop at the first rung that holds:

1. Does this need to be built at all? (YAGNI)
2. Does it already exist in this codebase? Reuse the helper, util, or pattern that's already here, don't re-write it.
3. Does the standard library already do this? Use it.
4. Does a native platform feature cover it? Use it.
5. Does an already-installed dependency solve it? Use it.
6. Can this be one line? Make it one line.
7. Only then: write the minimum code that works.

The ladder runs after you understand the problem, not instead of it: read the task and the code it touches, trace the real flow end to end, then climb.

Bug fix = root cause, not symptom: a report names a symptom. Grep every caller of the function you touch and fix the shared function once — one guard there is a smaller diff than one per caller, and patching only the path the ticket names leaves a sibling caller still broken.

Rules:

- No abstractions that weren't explicitly requested.
- No new dependency if it can be avoided.
- No boilerplate nobody asked for.
- Deletion over addition. Boring over clever. Fewest files possible.
- Shortest working diff wins, but only once you understand the problem. The smallest change in the wrong place isn't lazy, it's a second bug.
- Question complex requests: "Do you actually need X, or does Y cover it?"
- Pick the edge-case-correct option when two stdlib approaches are the same size, lazy means less code, not the flimsier algorithm.
- Mark deliberate simplifications that cut a real corner with a known ceiling (global lock, O(n²) scan, naive heuristic) with a `ponytail:` comment naming the ceiling and upgrade path.

Not lazy about: understanding the problem (read it fully and trace the real flow before picking a rung, a small diff you don't understand is just laziness dressed up as efficiency), input validation at trust boundaries, error handling that prevents data loss, security, accessibility, the calibration real hardware needs (the platform is never the spec ideal, a clock drifts, a sensor reads off), anything explicitly requested. Lazy code without its check is unfinished: non-trivial logic leaves ONE runnable check behind, the smallest thing that fails if the logic breaks (an assert-based demo/self-check or one small test file; no frameworks, no fixtures). Trivial one-liners need no test.

(Yes, this file also applies to agents working on the ponytail repo itself. Especially to them.)

---

# Part 3: agentmemory

*Source: AGENTS_memory.md*

# agentmemory — Agent Instructions

## Architecture

agentmemory is a persistent memory system for AI coding agents, built on iii-engine's three primitives (Worker/Function/Trigger). Everything goes through `registerFunction`/`registerTrigger`/`sdk.trigger()` — never bypass iii-engine with standalone SQLite or in-process alternatives.

- **Engine**: iii-sdk 0.22.1 with @iii-dev/helpers 0.22.1 (WebSocket to iii-engine 0.22.1 on port 49134; the client type is `IIIClient`, HTTP requests are `HttpRequest` from `@iii-dev/helpers/http`)
- **State**: File-based SQLite via iii-engine's StateModule (`./data/state_store.db`)
- **Build**: TypeScript → ESM via tsdown, output to `dist/`
- **Test**: vitest (`npm test` excludes integration tests)

## Consistency Rules

**When adding or removing MCP tools, you MUST update ALL of the following:**
1. `src/mcp/tools-registry.ts` — tool definition + `getAllTools()` array
2. `src/mcp/server.ts` — handler case in the `mcp::tools::call` switch
3. `src/triggers/api.ts` — REST endpoint registration
4. `src/index.ts` — function registration + endpoint count in the log line
5. `test/mcp-standalone.test.ts` — tool count assertion
6. `README.md` — tool counts (search for "MCP tools")
7. `plugin/.claude-plugin/plugin.json` — tool count in description
8. `plugin/plugin.json` and `plugin/.mcp.copilot.json` (when present) — tool count or MCP exposure

**When adding REST endpoints, you MUST update:**
1. `src/triggers/api.ts` — endpoint registration
2. `src/index.ts` — endpoint count in the log line
3. `README.md` — endpoint count (search for "REST endpoints" and "endpoints on port")

**When bumping version, you MUST update ALL of the following:**
1. `package.json` — version field
2. `src/version.ts` — VERSION constant and type union
3. `src/types.ts` — ExportData version union
4. `src/functions/export-import.ts` — supportedVersions set
5. `test/export-import.test.ts` — version assertion
6. `plugin/.claude-plugin/plugin.json` — version field
7. `plugin/plugin.json` (when present) — version field

**When adding new KV scopes:**
1. `src/state/schema.ts` — add to the KV object
2. `src/types.ts` — add the corresponding interface

**When adding new audit operations:**
1. `src/types.ts` — add to AuditEntry.operation union type

## Code Patterns

### Function Registration
```typescript
sdk.registerFunction(
  "mem::your-function",
  async (data: { ... }) => {
    // validate inputs
    // do work via kv.get/kv.set/kv.list
    // record audit via recordAudit()
    return { success: true, ... };
  },
);
```

### REST Endpoint Registration
```typescript
import type { HttpRequest } from "@iii-dev/helpers/http";

sdk.registerFunction("api::your-endpoint", async (req: HttpRequest) => {
  const denied = checkAuth(req, secret);
  if (denied) return denied;
  const body = req.body as Record<string, unknown>;
  // validate + whitelist fields (never pass raw body to sdk.trigger)
  const result = await sdk.trigger({
    function_id: "mem::your-function",
    payload: { ... },
  });
  return { status_code: 200, body: result };
});
sdk.registerTrigger({
  type: "http",
  function_id: "api::your-endpoint",
  config: { api_path: "/agentmemory/your-path", http_method: "POST" },
});
```

### MCP Tool Handler
```typescript
case "memory_your_tool": {
  // validate args with typeof checks
  // parse CSV args: args.field.split(",").map(t => t.trim()).filter(Boolean)
  const result = await sdk.trigger({
    function_id: "mem::your-function",
    payload: { ... },
  });
  return { status_code: 200, body: { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] } };
}
```

### Hook Scripts
Hook scripts in `src/hooks/` are standalone Node.js scripts (no iii-sdk import). They read JSON from stdin, make HTTP calls to the REST API, and exit. There are two patterns depending on whether Claude Code consumes the script's stdout:

- **Context-injecting hooks** (`pre-tool-use`, `pre-compact`, `session-start`) write recalled context to stdout for Claude Code to inject. These MUST use `try/catch` with `await fetch(..., { signal: AbortSignal.timeout(N) })` — the script has to wait for the response before exiting, and the timeout is the only bound on hang time.
- **Telemetry-only hooks** (`notification`, `post-tool-failure`, `post-tool-use`, `prompt-submit`, `stop`, `session-end`, `subagent-start`, `subagent-stop`, `task-completed`) write nothing to stdout. These MUST use fire-and-forget `fetch(..., { signal: AbortSignal.timeout(N) }).catch(() => {})` paired with `setTimeout(() => process.exit(0), 500).unref()`. The unawaited fetch dispatches the request; the unref'd `setTimeout` force-exits the process after the request has been flushed to the local daemon's socket buffer (~500ms is enough for single-request hooks; use 1500ms for multi-request hooks like `stop` and `session-end` so all fetches have time to start, especially when `AGENTMEMORY_URL` points to a remote daemon). Without the `setTimeout` Node keeps the event loop alive waiting for any in-flight fetch to settle, which means the hook still blocks Claude Code's next-prompt boundary for up to the AbortSignal duration — exactly the bug fire-and-forget is meant to fix.

## Coding Standards

- TypeScript, ESM only (`"type": "module"`)
- No code comments explaining WHAT — use clear naming instead
- Use `fingerprintId()` for content-addressable dedup, `generateId()` for unique IDs
- Parallel operations where possible (`Promise.all` for independent kv writes/reads)
- Input validation at system boundaries (MCP handlers, REST endpoints)
- REST endpoints must whitelist fields — never pass raw request body to `sdk.trigger()`
- Use `recordAudit()` for state-changing operations
- Timestamps: capture once with `new Date().toISOString()` and reuse

## Testing

- All tests must pass before PR: `npm test` (1,596+ tests)
- Mock pattern: `vi.mock("iii-sdk")` with mock `sdk.trigger`, `kv.get/set/list`
- Test files go in `test/` with `.test.ts` extension
- Follow existing patterns in `test/crystallize.test.ts` for function tests

## Current Stats (v0.9.29)

- 54 MCP tools (8 visible by default, `AGENTMEMORY_TOOLS=all` for all)
- 134 REST endpoints
- 6 MCP resources, 3 MCP prompts
- 12 hooks, 17 skills
- 260+ iii functions
- 1,596+ tests

---

# Part 4: Scientific Skills Repository

*Source: AGENTS_scientic_skills.md*

# Repository Guidance

This repository is a collection of Agent Skills for science and research. Every skill lives in its
own directory under `skills/` and must conform to the open
[Agent Skills specification](https://agentskills.io/specification).

Read this file before creating or changing a skill. `CONTRIBUTING.md` covers the same ground at
more length, plus the pull-request process.

## What belongs here

**In scope:** a narrow skill for one scientific package, database, platform, or research workflow —
`scanpy`, `depmap`, `benchling-integration`, `experimental-design`.

**Out of scope**, and routinely declined:

- General software-engineering or coding-judgment skills — they compete for selection on every task.
- General infrastructure with a scientific example bolted on (a vector database, a cloud SDK) —
  accepting one implies carrying every competitor.
- Broad "orchestrator" skills that route to other skills — they overlap every specialist by design.
- A second provider for a service an existing skill already reaches.

The general-purpose skills that do exist are narrow output-format helpers (`docx`, `pdf`, `pptx`,
`generate-image`, `markdown-mermaid-writing`). They are not precedent for broadening scope.

## Layout

The repository root is an [Agent Plugins](https://agent-plugins.org/) 1.0.0 package: `plugin.json`
plus the portable `skills/` tree. Keep `plugin.json` valid against the Agent Plugins manifest
schema, and keep its `version` identical to `pyproject.toml` `[project].version`. Do not add
non-portable top-level fields to `plugin.json` (no inline MCP, hooks, or client-only keys — use
`mcp.json` or a reverse-domain `extensions` namespace if those are ever needed).

```text
plugin.json                 # Agent Plugins manifest (repo root)
skills/<skill-name>/
├── SKILL.md        # required
├── references/     # optional: long documentation, loaded only when needed
├── scripts/        # optional: executable helpers
└── assets/         # optional: templates and static resources
```

Only `SKILL.md` is required inside each skill. Reference other files with relative paths from the
skill root, kept one level deep.

**Tests never live under `skills/`.** A skill directory ships only what an agent loads. Checks for a
skill's scripts and structure go in the repository-level suite instead:

```text
tests/<skill-name>/          # same name as the skill directory
├── test_scripts.py
└── fixtures/                # optional test data
```

**Diagrams never live under `skills/` either.** A skill may have a generated workflow diagram at
`docs/images/<skill-name>.png`, produced by `scripts/generate_skill_image.py`. Diagrams are optional
— see [Skill diagrams](#skill-diagrams).

Tests reach their skill through an explicit anchor, never a relative walk:

```python
SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills" / "<skill-name>"
```

## Creating a skill

1. Create `skills/<name>/` — **the directory name is the skill name** and must equal frontmatter
   `name`.
2. Write `SKILL.md` from the template below. Start at `metadata.version: "1.0"`.
3. Add `references/`, `scripts/`, or `assets/` only when they earn their place.
4. Run the commands and code you document. Scope claims to the release you actually tested
   ("targets stable GeoPandas 1.1.4"), and mark anything untested as illustrative.
5. If the skill ships `scripts/`, put their tests in **`tests/<name>/`** — never in the skill
   directory. Fixtures go in `tests/<name>/fixtures/`.
6. Validate and scan (below).

```markdown
---
name: skill-name
description: What the skill does and when an agent should use it, including the terms that should trigger it.
license: MIT
compatibility: Requires Python 3.12+ with <package> installed. Needs network access.
metadata:
  version: "1.0"
  skill-author: Your Name
---

# Skill Title

## When to use

Use this skill when...

## Workflow

1. ...

## Examples

...
```

## Updating a skill

1. Read the current `SKILL.md` and its supporting files first.
2. Check upstream docs — APIs move, and the skill may be pinned to an older release.
3. Make the smallest useful change.
4. **Bump `metadata.version` in the same change**: minor for normal improvements (`"1.2"` →
   `"1.3"`), major only for a breaking change or substantial redesign (`"1.9"` → `"2.0"`).
5. Re-run any example, command, or script you touched, plus `tests/<name>/` if that suite exists.
   Suites check that `metadata.version` is present and quoted, not what it equals, so a version bump
   never needs a matching test edit.
## Frontmatter

`SKILL.md` starts with YAML frontmatter. **Only these six fields are allowed** — the spec defines a
closed set, and any other top-level key is a validation error:

| Field | Required | Constraints |
| --- | --- | --- |
| `name` | Yes | 1–64 chars, lowercase letters/digits/hyphens only, no leading, trailing, or consecutive hyphens, and **must equal the directory name**. |
| `description` | Yes | 1–1024 chars. Say what the skill does *and* when to use it, with the keywords that should trigger it. Write it in third person. |
| `license` | No | License name, or a reference to a bundled license file. |
| `compatibility` | No | Max 500 chars. Environment requirements only — omit it if the skill has none. |
| `allowed-tools` | No | A **space-separated string**, e.g. `Read Write Edit Bash`. Not a YAML list, not comma-separated. |
| `metadata` | No | Mapping of string keys to **string** values, except the host manifest blocks below. Required here: `metadata.version`. |

Put anything else — authorship, upstream versions, review dates, client-specific config — inside
`metadata`, never at the top level. In particular, Hermes' top-level
`required_environment_variables` cannot be used here: it fails the validator and, because
`strictyaml` rejects the whole document, takes `name` and `description` down with it. Declare
credentials in `compatibility` and `metadata.openclaw.envVars` instead.

### Write block-style YAML, not JSON flow style

The reference validator parses frontmatter with `strictyaml`, which **rejects JSON-style flow
mappings and sequences**. A flow mapping does not merely fail one check: the whole frontmatter
fails to parse, so `name` and `description` become unreadable and the skill will not register.

```yaml
# Wrong -- breaks the validator
metadata: {"version": "1.1", "skill-author": "K-Dense Inc."}

# Right
metadata:
  version: "1.1"
  skill-author: K-Dense Inc.
```

### Quote `metadata` scalars

Quote values that would otherwise be parsed as a number, boolean, or date — `version: "1.0"`,
`last-reviewed: "2026-07-23"` — so they stay strings as the spec requires.

### Host manifest blocks stay nested mappings

`metadata.openclaw` and `metadata.hermes` are the documented exception: keep them as **nested
mappings**, not JSON strings. OpenClaw's `resolveOpenClawManifestBlock()` requires
`typeof candidate === "object"`, so a JSON string silently disables its dependency gating and
credential injection. Nested mappings still pass `skills-ref validate`.

```yaml
metadata:
  version: "1.1"
  skill-author: Exa
  openclaw:
    primaryEnv: EXA_API_KEY
    envVars:
      - name: EXA_API_KEY
        required: true
        description: Exa search API key.
  hermes:
    category: research
```

Only skills with external requirements need these blocks; most omit them. A failed `requires` /
`requires_toolsets` gate *hides* the skill from the agent, so gate only on something the skill
genuinely cannot run without.

## Body and layout

- Keep `SKILL.md` under 500 lines. CI warns above that. Move long reference material into
  `references/` so agents load it only when needed.
- A skill directory ships only what an agent loads. Tests, fixtures, scratch data, and generated
  artifacts stay out of it; tests go in `tests/<name>/`.
- Give concrete workflows, commands, and worked examples rather than background explanation.
- Name the required packages, system dependencies, credentials, and network access.
- Include the scientific caveats and validation checks that matter.
- Use ASCII console status markers (`[OK]`, `[FAIL]`, `->`) so diagnostics work on
  legacy Windows consoles. Unicode in documentation and generated figures is fine.
- Put fragile or repetitive logic in `scripts/` instead of asking the agent to recreate it.
- Never include secrets, API keys, private URLs, or unpublished data.

## Validate and scan

```bash
uv sync

# spec conformance for one skill
uv run skills-ref validate skills/<name>

# every skill, the way CI does
for d in skills/*/; do uv run skills-ref validate "$d"; done
```

`.github/workflows/skill-spec-validation.yml` runs that on every PR touching `skills/`, plus the
repo rules `skills-ref` does not check: `metadata.version` present, `allowed-tools` a
space-separated string, `metadata` scalars quoted, and a warning past 500 lines.

Security-scan new or substantially changed skills. Scanning uses
[Cisco AI Defense Skill Scanner](https://github.com/cisco-ai-defense/skill-scanner) — the
`cisco-ai-skill-scanner` package pinned in `pyproject.toml`, which detects prompt injection, data
exfiltration, and malicious code patterns in Agent Skills. Its README documents the rule IDs and
CLI flags; consult it when a finding's rule is unfamiliar.

`.github/workflows/pr-skill-scan.yml` runs the repo wrapper for changed skills on every PR and
posts a sticky comment, failing on HIGH or above:

```bash
# needs SKILL_SCANNER_LLM_API_KEY (see .env)
uv run python scan_pr_skills.py skills/<name>

# or the upstream CLI directly, without the repo wrapper
uv run skill-scanner scan skills/<name> --use-behavioral
```

**Verify a finding against the code before "fixing" it.** Known systematic false positives:
`BEHAVIOR_*_EXFILTRATION` and `BEHAVIOR_ENV_VAR_HARVESTING` on any skill that reads its own API key
and calls its own service; `MDBLOCK_PYTHON_SUBPROCESS` on any `subprocess` snippet, including the
safe argument-list form; and `*_EVAL_EXEC` on substrings inside ordinary identifiers (`retrieval`,
`executor`) or on `model.eval()`. Findings sometimes cite files a skill does not contain — check
against `find skills/<name> -type f` before acting.

If the skill has tests in `tests/<name>/`, run them:

```bash
uv run --with pytest python -m pytest tests/<name> -q

# every skill's suite, one process each, after the repo-wide guard
uv run --with pytest python tests/run_all.py
```

**One skill per pytest process.** Skills' `scripts/` directories own plain top-level module names —
32 of them ship a `scripts/_common.py` — so collecting two skills into one interpreter resolves
`_common` to whichever skill imported first and silently tests the wrong files. `tests/conftest.py`
refuses such a session; `tests/run_all.py` forks per skill.

### The repo-wide guard

```bash
uv run --with pytest python -m pytest tests/_meta -q
```

`tests/_meta` is the fastest useful signal in the repo: no scientific packages, a couple of
seconds. It uses `jsonschema` from the dev dependencies to validate `plugin.json` against the
bundled official Agent Plugins schema, without network access. It also checks package-path
containment and version synchronization. It runs the shared structural contract against **every**
skill and fails if a skill ships `scripts/` without a suite under `tests/<name>/` or an entry in
`tests/skill-requirements.toml`. `.github/workflows/skill-tests.yml` runs it on every pull request,
so a skill with untested scripts cannot land. A full run of `tests/run_all.py` starts with it.

It is not one of the per-skill processes because it deliberately spans all of them at once — safe
because it never imports skill code, only parses it.

### The shared contract

`tests/_contract/` holds the assertions every skill shares, so a per-skill suite contains only what
is actually specific to that skill. `tests/conftest.py` registers it as the importable module
`skill_contract`:

```python
import skill_contract

# every argparse script answers --help; skips when its packages are absent,
# runs for real under --isolated
CliHelpTests = skill_contract.cli.help_test_case(SKILL_ROOT)

# for library-style scripts with an `if __name__ == "__main__"` worked example
DemoBlockTests = skill_contract.cli.demo_test_case(SKILL_ROOT, ("doe_designs.py",))
```

- `structure` — frontmatter conformance, the 500-line limit, no tests or bytecode under `skills/`,
  local links resolve, scripts parse, no `eval`/`exec`/`os.system`, no standard-library shadowing,
  no hardcoded local paths, shell scripts valid. Run repo-wide by `tests/_meta`; do not duplicate
  these in a per-skill suite.
- `cli` — the `--help` and demo-block cases above.
- `office` / `schematic` — behaviour for files several skills ship byte-identical copies of (the
  OOXML tree under docx/pptx/xlsx; the AI schematic generator under five skills). `tests/_meta`
  separately fails if those copies drift apart, so fix them together.

### One environment per skill

The project environment deliberately does not carry the skills' scientific packages. Their upstream
pins are mutually exclusive — `opentrons` needs `numpy<2`, `esm` caps `transformers` below the
version the `transformers` skill targets, `geniml` and `spikeinterface` pin `zarr<3` against the
`zarr-python` skill's 3.x, `bioservices` caps `lxml<6` against `matchms`, and `pytdc`, `molfeat`,
`deepchem`, `histolab`, `vaex`, and `ete3` each need an interpreter older than 3.13. Installing them
together forces every one of those skills to the losing side of a version fight.

So `--isolated` builds a throwaway `uv` environment per skill instead, from
[`tests/skill-requirements.toml`](tests/skill-requirements.toml):

```bash
python tests/run_all.py --isolated                 # every suite, one env each
python tests/run_all.py --isolated scanpy qiskit   # just these
```

Each entry lists the packages that skill documents, plus an optional `python` when the skill cannot
run on the default interpreter; uv downloads that interpreter on demand. Packages that cannot be
installed at all — a GitHub-only SDK, a conda-forge-only library, a CUDA build — are recorded under
`[unavailable]` with the reason, and the runner prints them so the gap shows up in test output.

Adding a skill with `scripts/` means adding its `[skills.<name>]` entry — `tests/_meta` fails
without one. Use `packages = []` for skills whose bundled tooling is standard-library only; they
still get a clean environment, and CI runs exactly that set on every pull request. uv caches wheels
globally, so repeat runs create each environment in milliseconds.

The full `--isolated` sweep is not run in CI: it builds one environment per skill, several of which
need a CUDA toolchain, a JDK, or a local MATLAB install. Run it before a release, or whenever you
touch the shared contract.

## Skill diagrams

A skill may carry a generated workflow diagram at `docs/images/<skill-name>.png`. Diagrams are
optional: neither a new skill nor a change to an existing one is blocked on having or refreshing an
image, and no CI check enforces them. If you do ship one, note that it is derived from the
documentation, so regenerate it when the skill's workflow changes rather than leaving a picture that
misrepresents the skill.

`scripts/generate_skill_image.py` is local repository tooling, standard library only, and runs in
two stages on one `OPENROUTER_API_KEY` (environment variable, repository `.env`, or `--api-key`):
a text model reads `SKILL.md` plus everything under `references/` and a manifest of `scripts/` and
`assets/`, distils it into a description of one diagram, then an image model draws it. Because it
reads the whole skill, run it **after** the documentation is final, not before.

```bash
# one skill -> docs/images/<name>.png, replacing any existing image
uv run python scripts/generate_skill_image.py --skill <name>

# see which files feed the reader, and where the image lands — no API calls, nothing billed
uv run python scripts/generate_skill_image.py --skill <name> --dry-run

# read the skill and print the diagram prompt without drawing it
uv run python scripts/generate_skill_image.py --skill <name> --prompt-only

# several skills in one batch
uv run python scripts/generate_skill_image.py --skill <name-a> <name-b>

# backfill everything missing an image, six at a time
uv run python scripts/generate_skill_image.py --all --skip-existing -j 6
```

Look at the result before committing it. Image models misspell labels and occasionally point an
arrow at the wrong card; regenerate rather than ship a diagram whose text is wrong. `--quality low`
makes iteration cheap while checking composition, but commit a `high` render. Both the art direction
and the reader's instructions live at the top of the script — change them there rather than
hand-tuning one skill's prompt, so the set stays visually consistent.

## Before opening a PR

- Directory name and frontmatter `name` match exactly.
- No `tests/` directory and no `test_*.py` anywhere under `skills/<name>/` — tests belong in
  `tests/<name>/`.
- Only the six spec-defined top-level fields; everything else under `metadata`.
- `metadata.version` exists, is quoted, and is bumped if you changed an existing skill.
- `metadata` is a block mapping; `openclaw` / `hermes` blocks are nested mappings.
- `uv run skills-ref validate skills/<name>` passes.
- If the collection version changes, `plugin.json` `version` matches `pyproject.toml`.
- `uv run --with pytest python -m pytest tests/_meta -q` passes — this is what CI blocks on, and it
  catches a missing suite, a missing `skill-requirements.toml` entry, a broken local link, a
  leaked local path, and a drifted Agent Plugins manifest.
- If the skill ships `scripts/`: a suite exists at `tests/<name>/`, a `[skills.<name>]` entry exists
  in `tests/skill-requirements.toml`, and `python tests/run_all.py --isolated <name>` passes.
- If the skill ships `docs/images/<name>.png`, its labels are spelled correctly and its arrows point
  where they should. The image itself is optional.
- Examples and scripts are tested, or clearly marked illustrative.
- No secrets or private data; scan results clean or explained in the PR.

---

# Part 5: Claude Flow V3 / Ruflo

*Source: AGENTS_ruflo.md*

# Claude Flow V3 - Agent Guide

> **For OpenAI Codex CLI** - Agentic AI Foundation standard
> Skills: `$skill-name` | Config: `.agents/config.toml`

---

## 📢 TL;DR - READ THIS FIRST

```
╔═══════════════════════════════════════════════════════════════════════════╗
║  1. claude-flow = LEDGER (tracks state, stores memory, coordinates)       ║
║  2. Codex = EXECUTOR (writes code, runs commands, creates files)          ║
║  3. NEVER stop after calling claude-flow - IMMEDIATELY continue working   ║
║  4. If you need something BUILT/EXECUTED, YOU do it, not claude-flow      ║
║  5. ALWAYS search memory BEFORE starting: memory search --query "task"    ║
║  6. ALWAYS store patterns AFTER success: memory store --namespace patterns║
╚═══════════════════════════════════════════════════════════════════════════╝
```

**Workflow (Use MCP Tools):**
1. `memory_search(query="task keywords")` → LEARN from past patterns (score > 0.7 = use it)
2. `swarm_init(topology="hierarchical")` → coordination record (instant)
3. **YOU write the code / run the commands** ← THIS IS WHERE WORK HAPPENS
4. `memory_store(key="pattern-x", value="what worked", namespace="patterns")` → REMEMBER for next time

---

## Ruflo Policy-Governed Concurrent Codex Workflow

Ruflo is the coordination ledger and policy decision point. Codex agents are
the executors. Coordination records do not write code or run tests.

Use `guidance_brain({ mode: "recommend", task: "..." })` to select Ruflo
capabilities from the live MCP registry. A registered tool is not necessarily
configured, reachable, healthy, or authorized. If it is unavailable, continue
with compatible guidance tools, CLI discovery, and repository instructions.

1. Recall relevant AgentDB memory and ADRs.
2. Inspect source, runtime, dependencies, policy, and health.
3. Route to the smallest capable topology, agents, skills, and tools.
4. Plan acceptance criteria, safety envelope, ownership, and validation.
5. Execute with Codex workers in isolated scopes; Ruflo records coordination.
6. Test focused, regression, and failure paths.
7. Validate types, security, policy, compatibility, and artifact integrity.
8. Benchmark a source-bound candidate against a source-bound baseline.
9. Optimize only measured bottlenecks without weakening safety.
10. Bind claims and evidence into exact source/build receipts.
11. Reconcile handoffs and disclose unresolved limitations.
12. Publish only through a separately authorized release gate.

Hard invariants:

- Never run two writers in one worktree.
- Delegation may only reduce tools, servers, namespaces, network, spend,
  concurrency, expiry, and depth.
- Policy denial cancels dependent work before side effects.
- MetaHarness may evaluate candidates concurrently, but only ADR-322A may
  promote them and MetaHarness may never expand its own SafetyEnvelope.
- Do not commit, push, merge, release, or remove worktrees unless authorized.
- Existing installations migrate in `legacy` policy mode; use `observe` before
  switching to `enforce`.

Repository harness integration:

- If tracked repository instructions define a collaboration harness, start its
  session only after assigning an isolated worktree.
- Inspect existing claims, acquire exact paths/resources/ports, renew leases,
  check acknowledged inbox messages at integration boundaries, and release ownership on
  handoff or exit.
- A repository lease coordinates ownership; it does not grant authorization.
  Protected work still requires the ADR-324/325 action capability and current
  fencing epoch.
- In-memory reference adapters demonstrate semantics; they are not distributed,
  restart-durable release authorities.
- Heartbeats and lease expiry establish liveness; a PID is diagnostic only.
- `HEAD` alone is not an exact source-state identity in a dirty worktree.
  Release evidence must bind a clean commit or an immutable snapshot of tracked
  and untracked changes.

Useful checks:

```bash
npx ruflo policy status
npx ruflo policy verify
npx ruflo metaharness flywheel status
```

Repository release contract:

- The stable public train is exactly `@claude-flow/cli`, `claude-flow`, and
  `ruflo`; internal `@claude-flow/*` components are bundled and are not part of
  a normal standalone publish.
- Publish from a clean, reviewed source state in that order.
- Only the CLI publish receives the helper-signing configuration from
  `ruv-dev`; use the existing authenticated npm session for publication.
- Run `node scripts/audit-umbrella-version-lockstep.mjs`, verify all three
  registry versions, and align `latest`, `alpha`, and `v3alpha`.

---

## 🚨 CRITICAL: CODEX DOES THE WORK, CLAUDE-FLOW ORCHESTRATES

```
┌─────────────────────────────────────────────────────────────┐
│  CLAUDE-FLOW = ORCHESTRATOR (tracks state, coordinates)     │
│  CODEX = WORKER (writes code, runs commands, implements)    │
└─────────────────────────────────────────────────────────────┘
```

### ❌ WRONG: Expecting claude-flow to execute tasks
```bash
npx claude-flow swarm start --objective "Build API"
# WRONG: Waiting for claude-flow to build the API
# Claude-flow does NOT execute code!
```

### ✅ CORRECT: Codex executes, claude-flow tracks
```bash
# 1. Tell claude-flow what you're doing (optional coordination)
npx claude-flow swarm init --topology hierarchical --max-agents 1
npx claude-flow agent spawn --type coder --name codex-worker

# 2. YOU (CODEX) DO THE ACTUAL WORK:
mkdir -p src
cat > src/api.ts << 'EOF'
export function hello() { return "Hello World"; }
EOF

# 3. Report to claude-flow what you did (optional)
npx claude-flow memory store --key "api-created" --value "src/api.ts" --namespace results
```

### The Division of Labor

| Component | Role | Examples |
|-----------|------|----------|
| **CODEX** | EXECUTES | Write files, run tests, create code, shell commands |
| **claude-flow** | ORCHESTRATES | Track agents, store memory, coordinate tasks |

---

## ⛔ DON'T STOP AFTER CALLING CLAUDE-FLOW

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ❌ WRONG: Call claude-flow → STOP → Wait for results                   │
│  ✅ RIGHT: Call claude-flow → IMMEDIATELY continue → YOU do the work    │
└─────────────────────────────────────────────────────────────────────────┘
```

### ❌ WRONG Pattern (Stopping)
```bash
npx claude-flow swarm init --topology hierarchical
npx claude-flow agent spawn --type coder --name worker-1
npx claude-flow swarm start --objective "Build hello world"
# WRONG: Codex stops here and waits for something to happen
# Nothing will happen! Claude-flow doesn't execute code!
```

### ✅ CORRECT Pattern (Continue Immediately)
```bash
# Step 1: Coordination (optional)
npx claude-flow swarm init --topology hierarchical
npx claude-flow agent spawn --type coder --name worker-1

# Step 2: IMMEDIATELY DO THE WORK YOURSELF - DON'T WAIT!
echo 'console.log("Hello World!");' > hello.js
node hello.js

# Step 3: Report what you did
npx claude-flow memory store --key "result" --value "Hello World printed" --namespace results
```

### The Rule
**After ANY claude-flow command, IMMEDIATELY continue with your own work.**

Claude-flow commands return instantly. They create coordination RECORDS only.
You must ALWAYS follow up with YOUR OWN execution.

| After This... | IMMEDIATELY Do This... |
|---------------|----------------------|
| `swarm init` | Start writing code |
| `agent spawn` | Continue implementation |
| `task create` | Execute the task yourself |
| `swarm start` | Begin actual work |

---

### When to Use Claude-Flow Commands

| Use Case | Claude-Flow Command | Then Codex Does |
|----------|---------------------|-----------------|
| Track progress | `memory store --key "step1" --value "done"` | Continue to next step |
| Multi-step tasks | `task create --description "step 2"` | Execute step 2 |
| Store results | `memory store --key "output" --value "..."` | Move on |
| Coordinate | `swarm init` | Start working |

### Hello World - Correct Pattern

```bash
# STEP 1: Optional - register with orchestrator
npx claude-flow swarm init --topology mesh --max-agents 1

# STEP 2: CODEX DOES THE WORK
echo 'console.log("Hello World!");' > hello.js
node hello.js

# STEP 3: Optional - report completion
npx claude-flow memory store --key "hello-result" --value "printed Hello World" --namespace results
```

**REMEMBER: If you need something DONE, YOU do it. Claude-flow just tracks.**

---

## ⚡ QUICK COMMANDS (NO DISCOVERY NEEDED)

### Spawn N-Agent Swarm (Copy-Paste Ready)

```bash
# 5-AGENT SWARM - Run these commands in sequence:
npx claude-flow swarm init --topology hierarchical --max-agents 8
npx claude-flow agent spawn --type coordinator --name coord-1
npx claude-flow agent spawn --type coder --name coder-1
npx claude-flow agent spawn --type coder --name coder-2
npx claude-flow agent spawn --type tester --name tester-1
npx claude-flow agent spawn --type reviewer --name reviewer-1
npx claude-flow swarm start --objective "Your task here" --strategy development
```

### Common Swarm Patterns

| Task | Exact Command |
|------|---------------|
| Init hierarchical swarm | `npx claude-flow swarm init --topology hierarchical --max-agents 8` |
| Init mesh swarm | `npx claude-flow swarm init --topology mesh --max-agents 5` |
| Init V3 mode (15 agents) | `npx claude-flow swarm init --v3-mode` |
| Spawn coder | `npx claude-flow agent spawn --type coder --name coder-1` |
| Spawn tester | `npx claude-flow agent spawn --type tester --name tester-1` |
| Spawn coordinator | `npx claude-flow agent spawn --type coordinator --name coord-1` |
| Spawn architect | `npx claude-flow agent spawn --type architect --name arch-1` |
| Spawn reviewer | `npx claude-flow agent spawn --type reviewer --name rev-1` |
| Spawn researcher | `npx claude-flow agent spawn --type researcher --name res-1` |
| Start swarm | `npx claude-flow swarm start --objective "task" --strategy development` |
| Check swarm status | `npx claude-flow swarm status` |
| List agents | `npx claude-flow agent list` |
| Stop swarm | `npx claude-flow swarm stop` |

### Agent Types (Use with `--type`)

| Type | Purpose |
|------|---------|
| `coordinator` | Orchestrates other agents |
| `coder` | Writes code |
| `tester` | Writes tests |
| `reviewer` | Reviews code |
| `architect` | Designs systems |
| `researcher` | Analyzes requirements |
| `security-architect` | Security design |
| `performance-engineer` | Optimization |

### Task Commands

| Action | Command |
|--------|---------|
| Create task | `npx claude-flow task create --type implementation --description "desc"` |
| List tasks | `npx claude-flow task list` |
| Assign task | `npx claude-flow task assign TASK_ID --agent AGENT_NAME` |
| Task status | `npx claude-flow task status TASK_ID` |
| Cancel task | `npx claude-flow task cancel TASK_ID` |

### Memory Commands

| Action | Command |
|--------|---------|
| Store | `npx claude-flow memory store --key "key" --value "value" --namespace patterns` |
| Search | `npx claude-flow memory search --query "search terms"` |
| List | `npx claude-flow memory list --namespace patterns` |
| Retrieve | `npx claude-flow memory retrieve --key "key"` |

---

## 🚀 SWARM RECIPES

### Recipe 1: Hello World Test (COMPLETE EXAMPLE)

**Step 1: Setup coordination** (returns instantly - don't stop!)
```bash
npx claude-flow swarm init --topology mesh --max-agents 5
npx claude-flow agent spawn --type coder --name hello-main
# ⚠️ DON'T STOP HERE - CONTINUE IMMEDIATELY TO STEP 2
```

**Step 2: YOU (Codex) execute the task** (THIS IS THE REAL WORK)
```bash
# ✅ YOU create the file
echo 'console.log("Hello World from Swarm!");' > /tmp/hello-swarm.js

# ✅ YOU execute it
node /tmp/hello-swarm.js
# Output: Hello World from Swarm!
```

**Step 3: Report completion** (optional - store results)
```bash
npx claude-flow memory store --key "hello-world-result" --value "Executed: Hello World from Swarm!" --namespace results
```

### Recipe 1b: 5-Agent Concurrent Hello World (COMPLETE)
```bash
# COORDINATION (instant - creates records only)
npx claude-flow swarm init --topology hierarchical --max-agents 5
for i in 1 2 3 4 5; do
  npx claude-flow agent spawn --type coder --name "worker-$i"
done

# ⚠️ NOW YOU DO THE ACTUAL CONCURRENT WORK:
for i in 1 2 3 4 5; do
  (echo "Worker $i: Hello World!" && sleep 0.$i) &
done
wait
echo "All 5 workers completed!"

# REPORT (optional)
npx claude-flow memory store --key "concurrent-result" --value "5 workers completed" --namespace results
```

### Recipe 1b: Hello World (Single Command Block)
```bash
# All-in-one execution
npx claude-flow swarm init --topology mesh --max-agents 5 && \
npx claude-flow agent spawn --type coder --name hello-main && \
npx claude-flow swarm start --objective "Print hello world" --strategy development && \
echo 'console.log("Hello World from Swarm!");' > /tmp/hello-swarm.js && \
node /tmp/hello-swarm.js && \
npx claude-flow memory store --key "hello-world-result" --value "Success" --namespace results
```

### Recipe 2: Feature Implementation (6 Agents)
```bash
npx claude-flow swarm init --topology hierarchical --max-agents 8
npx claude-flow agent spawn --type coordinator --name lead
npx claude-flow agent spawn --type architect --name arch
npx claude-flow agent spawn --type coder --name impl-1
npx claude-flow agent spawn --type coder --name impl-2
npx claude-flow agent spawn --type tester --name test
npx claude-flow agent spawn --type reviewer --name review
npx claude-flow swarm start --objective "Implement [feature]" --strategy development
```

### Recipe 3: Bug Fix (4 Agents)
```bash
npx claude-flow swarm init --topology hierarchical --max-agents 4
npx claude-flow agent spawn --type coordinator --name lead
npx claude-flow agent spawn --type researcher --name debug
npx claude-flow agent spawn --type coder --name fix
npx claude-flow agent spawn --type tester --name verify
npx claude-flow swarm start --objective "Fix [bug]" --strategy development
```

### Recipe 4: Security Audit (3 Agents)
```bash
npx claude-flow swarm init --topology hierarchical --max-agents 4
npx claude-flow agent spawn --type coordinator --name lead
npx claude-flow agent spawn --type security-architect --name audit
npx claude-flow agent spawn --type reviewer --name review
npx claude-flow swarm start --objective "Security audit" --strategy development
```

### Recipe 5: V3 Full Coordination (15 Agents)
```bash
npx claude-flow swarm init --v3-mode
npx claude-flow swarm coordinate --agents 15
```

---

## 📋 BEHAVIORAL RULES

- **YOU (CODEX) execute tasks** - claude-flow only orchestrates
- Do what is asked; nothing more, nothing less
- NEVER create files unless absolutely necessary
- ALWAYS prefer editing existing files
- NEVER save to root folder
- NEVER commit secrets or .env files
- ALWAYS read a file before editing it
- NEVER wait for claude-flow to "do work" - it doesn't execute, YOU do
- Use claude-flow commands to TRACK progress, not to EXECUTE tasks

## 📁 FILE ORGANIZATION

| Directory | Purpose |
|-----------|---------|
| `/src` | Source code |
| `/tests` | Test files |
| `/docs` | Documentation |
| `/config` | Configuration |
| `/scripts` | Utility scripts |

## 🎯 WHEN TO USE SWARMS

**USE SWARM:**
- Multiple files (3+)
- New feature implementation
- Cross-module refactoring
- API changes with tests
- Security-related changes
- Performance optimization

**SKIP SWARM:**
- Single file edits
- Simple bug fixes (1-2 lines)
- Documentation updates
- Configuration changes

---

## 🔧 CLI REFERENCE

### Swarm Commands
```bash
npx claude-flow swarm init [--topology TYPE] [--max-agents N] [--v3-mode]
npx claude-flow swarm start --objective "task" --strategy [development|research]
npx claude-flow swarm status [SWARM_ID]
npx claude-flow swarm stop [SWARM_ID]
npx claude-flow swarm scale --count N
npx claude-flow swarm coordinate --agents N
```

### Agent Commands
```bash
npx claude-flow agent spawn --type TYPE --name NAME
npx claude-flow agent list [--filter active|idle|busy]
npx claude-flow agent status AGENT_ID
npx claude-flow agent stop AGENT_ID
npx claude-flow agent metrics [AGENT_ID]
npx claude-flow agent health
npx claude-flow agent logs AGENT_ID
```

### Task Commands
```bash
npx claude-flow task create --type TYPE --description "desc"
npx claude-flow task list [--all]
npx claude-flow task status TASK_ID
npx claude-flow task assign TASK_ID --agent AGENT_NAME
npx claude-flow task cancel TASK_ID
npx claude-flow task retry TASK_ID
```

### Memory Commands
```bash
npx claude-flow memory store --key KEY --value VALUE [--namespace NS]
npx claude-flow memory search --query "terms" [--namespace NS]
npx claude-flow memory list [--namespace NS]
npx claude-flow memory retrieve --key KEY [--namespace NS]
npx claude-flow memory init [--force]
```

### Hooks Commands
```bash
npx claude-flow hooks pre-task --description "task"
npx claude-flow hooks post-task --task-id ID --success true
npx claude-flow hooks route --task "task"
npx claude-flow hooks session-start --session-id ID
npx claude-flow hooks session-end --export-metrics true
npx claude-flow hooks worker list
npx claude-flow hooks worker dispatch --trigger audit
```

### System Commands
```bash
npx claude-flow init [--wizard] [--codex] [--full]
npx claude-flow daemon start
npx claude-flow daemon stop
npx claude-flow daemon status
npx claude-flow doctor [--fix]
npx claude-flow status
npx claude-flow mcp start
```

---

## 🔌 TOPOLOGIES

| Topology | Use Case | Command Flag |
|----------|----------|--------------|
| `hierarchical` | Coordinated teams, anti-drift | `--topology hierarchical` |
| `mesh` | Peer-to-peer, equal agents | `--topology mesh` |
| `hierarchical-mesh` | Hybrid (recommended for V3) | `--topology hierarchical-mesh` |
| `ring` | Sequential processing | `--topology ring` |
| `star` | Central coordinator | `--topology star` |
| `adaptive` | Dynamic switching | `--topology adaptive` |

## 🤖 AGENT TYPES

### Core
`coordinator`, `coder`, `tester`, `reviewer`, `architect`, `researcher`

### Specialized
`security-architect`, `security-auditor`, `memory-specialist`, `performance-engineer`

### Swarm Coordination
`hierarchical-coordinator`, `mesh-coordinator`, `adaptive-coordinator`

### Consensus
`byzantine-coordinator`, `raft-manager`, `gossip-coordinator`

---

## ⚙️ CONFIGURATION

### Default Swarm Config
- Topology: `hierarchical`
- Max Agents: 8
- Strategy: `specialized`
- Consensus: `raft`
- Memory: `hybrid`

### Environment Variables
```bash
CLAUDE_FLOW_CONFIG=./claude-flow.config.json
CLAUDE_FLOW_LOG_LEVEL=info
CLAUDE_FLOW_MEMORY_BACKEND=hybrid
```

---

## 🔗 SKILLS

Invoke with `$skill-name`:

| Skill | Purpose |
|-------|---------|
| `$swarm-orchestration` | Multi-agent coordination |
| `$memory-management` | Pattern storage/retrieval |
| `$sparc-methodology` | Structured development |
| `$security-audit` | Security scanning |
| `$performance-analysis` | Profiling |
| `$github-automation` | CI/CD management |
| `$hive-mind` | Byzantine consensus |
| `$neural-training` | Pattern learning |

---

---

## 🔌 MCP INTEGRATION (Learning & Coordination)

Codex doesn't have native hooks like Claude Code, but uses **MCP (Model Context Protocol)** for learning and coordination.

### MCP Auto-Registration

When you run `npx claude-flow init --codex`, the MCP server is **automatically registered** with Codex.

```bash
# Verify MCP is registered:
codex mcp list

# Expected output:
# Name         Command  Args                   Status
# claude-flow  npx      claude-flow mcp start  enabled

# If not present, add manually:
codex mcp add claude-flow -- npx claude-flow mcp start
```

### Test MCP Connection
```bash
# Test MCP server starts correctly:
npx claude-flow mcp start --test
```

### MCP Tools Available
Once added, Codex can use these tools via MCP:

**Coordination:**
| Tool | Purpose |
|------|---------|
| `swarm_init` | Initialize swarm (topology, maxAgents) |
| `swarm_status` | Check swarm state |
| `agent_spawn` | Register agent roles |
| `agent_status` | Check agent state |
| `task_orchestrate` | Coordinate multi-agent tasks |

**Learning & Memory (USE THESE!):**
| Tool | Purpose | When |
|------|---------|------|
| `memory_search` | Semantic vector search | BEFORE every task |
| `memory_store` | Store patterns with embeddings | AFTER success |
| `memory_retrieve` | Get by exact key | When key is known |
| `neural_train` | Train on patterns | Periodic improvement |
| `neural_status` | Check learning state | Debugging |

**Hive Mind (Advanced):**
| Tool | Purpose |
|------|---------|
| `hive-mind_init` | Byzantine consensus swarm |
| `hive-mind_spawn` | Spawn hive workers |
| `hive-mind_broadcast` | Message all workers |

### Self-Learning via MCP Tools (PREFERRED)

Use MCP tools directly - faster than CLI commands:

**BEFORE starting any task - SEARCH for patterns:**
```
Use tool: memory_search
  query: "keywords related to your task"
  namespace: "patterns"
```

**AFTER completing successfully - STORE the pattern:**
```
Use tool: memory_store
  key: "pattern-[descriptive-name]"
  value: "What worked: approach, code patterns, gotchas"
  namespace: "patterns"
```

### MCP Learning Workflow (Use This!)

```
1. LEARN: memory_search(query="task keywords", namespace="patterns")
   → If score > 0.7, USE that pattern

2. COORDINATE: swarm_init(topology="hierarchical")
   → agent_spawn(type="coder", name="worker-1")

3. EXECUTE: YOU write the code, run commands, create files

4. REMEMBER: memory_store(key="pattern-x", value="what worked", namespace="patterns")
```

### MCP Tools for Learning

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `memory_search` | Find similar past patterns | BEFORE starting any task |
| `memory_store` | Save successful patterns | AFTER completing a task |
| `memory_retrieve` | Get specific pattern by key | When you know the exact key |
| `neural_train` | Train on successful patterns | After multiple successes |

### Example: Learning-Enabled Task

```
STEP 1 - LEARN:
Use tool: memory_search
  query: "validation utility function"
  namespace: "patterns"

→ Found: pattern-email-validator (score: 0.82)
→ Use this pattern as reference!

STEP 2 - COORDINATE:
Use tool: swarm_init with topology="hierarchical", maxAgents=3

STEP 3 - EXECUTE:
YOU create the files:
  echo 'export function validate(x) { ... }' > /tmp/validator.js
  node --test /tmp/validator.js

STEP 4 - REMEMBER:
Use tool: memory_store
  key: "pattern-phone-validator"
  value: "Phone validation: regex /^\+?[\d\s-]{10,}$/, normalize first, test edge cases"
  namespace: "patterns"
```

### Vector Search Tips
- Searches are SEMANTIC (meaning-based, not just keywords)
- Score > 0.7 = strong match, use that pattern
- Score 0.5-0.7 = partial match, adapt as needed
- Store DETAILED values for better future retrieval

### CLI Fallback (if MCP unavailable)
```bash
npx claude-flow memory search --query "keywords" --namespace patterns
npx claude-flow memory store --key "pattern-x" --value "what worked" --namespace patterns
```

### Coordination via MCP

When claude-flow is added as MCP server, Codex can call tools directly:
```
Use tool: swarm_init with topology="hierarchical"
Use tool: memory_store with key="result" value="success"
```

### config.toml MCP Setup
```toml
# ~/.codex/config.toml
[mcp_servers.claude-flow]
command = "npx"
args = ["claude-flow", "mcp", "start"]
enabled = true
```

---

## 📚 SUPPORT

- Docs: https://github.com/ruvnet/claude-flow
- Issues: https://github.com/ruvnet/claude-flow/issues

**Remember: Codex executes, claude-flow orchestrates!**
