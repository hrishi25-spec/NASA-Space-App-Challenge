#!/usr/bin/env python3
"""Fail when a documented figure drifts from the code that produces it.

Two things are checked:

1. **Test counts.** The backend suite is counted by parsing ``test_*.py`` — test
   functions, with ``@pytest.mark.parametrize`` expanded — so no pytest run, no
   imports and no fixtures are needed. Every place the docs quote those numbers
   (the README's suite sizes and total, CONTRIBUTING's composition, PRD's status
   rows, brain's status snapshot, the agent rules) must match. A claim that
   disappears from the docs fails too: a figure may be updated, not quietly
   dropped.

2. **Prebuild-guard names.** Every ``check-*.mjs`` named in a markdown file must
   exist in ``firecal/frontend/scripts/``, every guard on disk must be named in
   the README and the frontend guide, and every guard must be wired into an npm
   script that ``prebuild`` chains — so a renamed or newly added guard cannot
   leave a stale name behind.

Zero dependencies beyond the standard library: ``python scripts/check-doc-figures.py``
runs anywhere python3 does. Wired into its own CI job (``docs`` in
.github/workflows/ci.yml) and into ``scripts/check.sh`` / ``scripts/check.bat``.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "firecal" / "backend"
FRONTEND = ROOT / "firecal" / "frontend"

# The three suites the docs name individually. A file added or removed under
# firecal/backend/test_*.py that is not here means the docs' composition claims
# are incomplete — reported explicitly rather than only through a total mismatch.
NAMED_SUITES = ("test_smoke.py", "test_security.py", "test_archives.py")

ERRORS: list[str] = []


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _decorator_name(call: ast.Call) -> str:
    fn = call.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return ""


def _cases(decorator: ast.expr, where: str) -> int:
    """How many collected tests one decorator contributes (1 unless parametrize)."""
    if not isinstance(decorator, ast.Call):
        return 1
    if _decorator_name(decorator) != "parametrize":
        return 1
    if len(decorator.args) < 2:
        ERRORS.append(f"{where}: @pytest.mark.parametrize without a values list — teach scripts/check-doc-figures.py")
        return 1
    try:
        values = ast.literal_eval(decorator.args[1])
    except (ValueError, SyntaxError):
        ERRORS.append(f"{where}: @pytest.mark.parametrize list is not a literal — teach scripts/check-doc-figures.py")
        return 1
    if isinstance(values, dict):
        ERRORS.append(f"{where}: parametrize given a dict — teach scripts/check-doc-figures.py")
        return 1
    return len(values)


def _function_cases(fn: ast.FunctionDef | ast.AsyncFunctionDef, where: str) -> int:
    cases = 1
    for decorator in fn.decorator_list:
        cases *= _cases(decorator, f"{where}:{fn.lineno}")
    return cases


def count_collected(path: Path) -> int:
    """Tests pytest would collect from one file: top-level ``test_*`` functions
    and ``test_*`` methods of ``Test*`` classes, parametrize expanded."""
    tree = ast.parse(read(path), filename=str(path))
    total = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            total += _function_cases(node, path.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test_"):
                    total += _function_cases(sub, path.name)
    return total


def check_claims(relpath: str, pattern: str, expected: tuple[int, ...], note: str) -> None:
    """Everywhere ``pattern`` matches in the file, its groups must equal ``expected``."""
    path = ROOT / relpath
    if not path.exists():
        ERRORS.append(f"{relpath}: the file the guard reads is gone — update scripts/check-doc-figures.py")
        return
    text = read(path)
    hits = list(re.finditer(pattern, text))
    if not hits:
        ERRORS.append(
            f"{relpath}: no longer states {note} — the docs dropped a figure this guard tracks; "
            "reword the docs or update the guard deliberately."
        )
        return
    for match in hits:
        got = tuple(int(group) for group in match.groups())
        if got != expected:
            line = text.count("\n", 0, match.start()) + 1
            ERRORS.append(
                f"{relpath}:{line}: says {got}, the code says {expected} — {note} "
                "(first number is the group order of the pattern)"
            )


def markdown_files():
    skip = {".git", "node_modules", ".venv", "dist", "__pycache__", ".data", "model"}
    for path in sorted(ROOT.rglob("*.md")):
        if not any(part in skip for part in path.parts):
            yield path


def check_guard_names(disk: set[str]) -> None:
    guard_pattern = r"check-[a-z-]+\.mjs"

    # A stale name in any document points at a guard that no longer exists.
    for path in markdown_files():
        for name in sorted(set(re.findall(guard_pattern, read(path)))):
            if name not in disk:
                rel = path.relative_to(ROOT)
                ERRORS.append(f"{rel}: names {name}, which does not exist in firecal/frontend/scripts/")

    # A guard on disk must be named where the docs enumerate them.
    for relpath in ("README.md", "docs/frontend.md"):
        mentioned = set(re.findall(guard_pattern, read(ROOT / relpath)))
        for missing in sorted(disk - mentioned):
            ERRORS.append(f"{relpath}: never names the guard {missing} — a new guard needs documenting")

    # npm wiring: every guard has a script, no script points at a missing file,
    # and prebuild chains every check: script.
    pkg = json.loads(read(FRONTEND / "package.json"))
    scripts = pkg.get("scripts", {})
    referenced: set[str] = set()
    for value in scripts.values():
        referenced.update(re.findall(r"scripts/(check-[a-z-]+\.mjs)", value))
    for missing in sorted(disk - referenced):
        ERRORS.append(f"firecal/frontend/package.json: guard {missing} is not wired into any npm script")
    for stale in sorted(referenced - disk):
        ERRORS.append(f"firecal/frontend/package.json: references scripts/{stale}, which does not exist")
    prebuild = scripts.get("prebuild", "")
    for key in sorted(key for key in scripts if key.startswith("check:")):
        if f"npm run {key}" not in prebuild:
            ERRORS.append(f"firecal/frontend/package.json: prebuild does not run {key} — a guard must join the chain")


def main() -> int:
    counts = {path.name: count_collected(path) for path in sorted(BACKEND.glob("test_*.py"))}
    smoke = counts.get("test_smoke.py", 0)
    security = counts.get("test_security.py", 0)
    archives = counts.get("test_archives.py", 0)
    total = sum(counts.values())

    for name in sorted(set(counts) - set(NAMED_SUITES)):
        ERRORS.append(
            f"firecal/backend/{name}: a new suite — quote it in the docs' compositions "
            "and add it to NAMED_SUITES in scripts/check-doc-figures.py"
        )
    for name in sorted(set(NAMED_SUITES) - set(counts)):
        ERRORS.append(f"firecal/backend/{name}: the docs describe this suite but the file is gone")

    # --- figures the docs quote -------------------------------------------------
    check_claims("README.md", r"(\d+)-test API smoke suite", (smoke,), "the smoke-suite size in the project tree")
    check_claims("README.md", r"(\d+)-test hardening suite", (security,), "the security-suite size in the project tree")
    check_claims("README.md", r"(\d+)-test suite for the local-archive", (archives,), "the archive-suite size in the project tree")
    check_claims("README.md", r"`test_smoke\.py` \((\d+)\)", (smoke,), "the test_smoke.py count in Testing & CI")
    check_claims("README.md", r"`test_security\.py` \((\d+)\)", (security,), "the test_security.py count in Testing & CI")
    check_claims("README.md", r"`test_archives\.py` \((\d+)\)", (archives,), "the test_archives.py count in Testing & CI")
    check_claims("README.md", r"# (\d+) tests, ~", (total,), "the total test count in the Testing & CI commands")
    check_claims(
        "CONTRIBUTING.md",
        r"test suite \((\d+) tests: (\d+) smoke \+ (\d+) security \+ (\d+) local-archive",
        (total, smoke, security, archives),
        "the suite composition in 'The one command that must pass'",
    )
    check_claims(
        "docs/brain.md",
        r"(\d+) passing — (\d+) API smoke \+ (\d+) security \+ (\d+) local-archive",
        (total, smoke, security, archives),
        "the status-snapshot test counts",
    )
    check_claims(
        "docs/PRD.md",
        r"(\d+) automated tests \((\d+) smoke \+ (\d+) security \+ (\d+) archive\)",
        (total, smoke, security, archives),
        "the CI test count in the quality section",
    )
    check_claims(
        "docs/PRD.md",
        r"(\d+) tests green \((\d+) smoke \+ (\d+) hardening \+ (\d+) archive\)",
        (total, smoke, security, archives),
        "the status-summary test count",
    )
    check_claims("docs/PRD.md", r"`pytest` (\d+) passed", (total,), "the full-suite line in the verification table")
    check_claims("docs/PRD.md", r"plus (\d+) regression tests", (security,), "the security regression-test count")
    check_claims("docs/PRD.md", r"(\d+) tests cover the picker", (archives,), "the archive-suite count")
    check_claims("docs/AGENTS.md", r"Backend suite — (\d+) tests", (total,), "the backend-suite total in the agent rules")
    check_claims(
        "docs/AGENTS.md",
        r"(\d+) smoke \+ (\d+) security \+ (\d+) local-archive",
        (smoke, security, archives),
        "the suite composition in the agent rules",
    )

    # --- guard names -------------------------------------------------------------
    guard_dir = FRONTEND / "scripts"
    disk_guards = {path.name for path in guard_dir.glob("check-*.mjs")}
    if not disk_guards:
        ERRORS.append("firecal/frontend/scripts/: no check-*.mjs guards found — did they move?")
    check_guard_names(disk_guards)

    if ERRORS:
        print("doc figures FAILED — the docs drifted from the code:\n", file=sys.stderr)
        for error in ERRORS:
            print(f"  - {error}", file=sys.stderr)
        print(
            f"\nWhat the code says: {total} tests "
            f"({smoke} smoke + {security} security + {archives} archive), "
            f"{len(disk_guards)} prebuild guards.",
            file=sys.stderr,
        )
        return 1

    print(
        f"doc figures ok — {total} tests ({smoke} smoke + {security} security + {archives} archive), "
        f"{len(disk_guards)} prebuild guards, all quoted consistently"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
