#!/usr/bin/env python3
"""Fail when a relative link in the docs does not resolve.

A markdown link that points at a file this repository does not contain is an error
(`docs/AGENTS.md` asks review to check exactly that), and this makes it a build
failure rather than something a reviewer has to notice by hand.

Four kinds of error, each its own line in the report:

1. **Broken file** — `docs/PRD.md` links to `decisions/0001-layout.md`, which was
   renamed. The checkout resolves the link on a case-insensitive filesystem and in
   a fuzzy editor, so nothing else complains; GitHub renders a 404.

2. **Case mismatch** — the target exists, but not with that spelling. Same problem,
   same silence: NTFS and macOS resolve `README.md` for `readme.md`, the remote
   does not.

3. **Dead anchor** — a `#fragment` that names no heading. GitHub builds heading
   anchors by lowercasing the heading, dropping punctuation (backticks included,
   but not the code between them) and joining the words with hyphens, so a
   shortened table-of-contents entry
   (`#5-how-the-papers-fit-together` for a heading reading
   `## 5. How the Papers Fit Together (Workflow View)`) jumps nowhere. Repeated
   headings get a `-1`, `-2`, … suffix; those are honoured.

4. **Untracked file** — the target is on this machine but not in git, so a fresh
   clone will not have it: a generated report, an archive someone dropped in
   `.data/`, a file that was never `git add`ed. It renders here and 404s for
   everyone else. Membership in git's index is the test, because in CI the index
   *is* the committed tree, and locally a newly written file passes as soon as it
   is staged. A tracked file that also matches a `.gitignore` line is fine — that
   combination is normal, and the ignore rule does not apply to it.

What it does *not* check: external URLs (a typo there is invisible to us and the
network is not a place to spend CI); anchors on non-markdown files, where the
fragment is a line number or a class name rather than a slug; and directory
targets, which have no index entry of their own.

Zero dependencies beyond the standard library and ``git`` itself: ``python
scripts/check-doc-links.py`` runs anywhere python3 does. Without git (a source
tarball, a zip download) the first three checks still run and the fourth isskipped with a note, rather than the guard failing for the wrong reason. Run next to
``scripts/check-doc-figures.py`` in the CI ``docs`` job and in
``scripts/check.sh`` / ``scripts/check.bat``.

``scripts/test_check_doc-links.py`` is this guard's own test suite: the slug rules,
the case check, the link parser and all four error classes, pinned with
assertions so a change to any of them has to be a deliberate one. It is stdlib
``unittest`` like the guard itself, and runs in the same CI ``docs`` job.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]

# Directories that never hold project markdown: caches, build output, virtualenvs,
# and the datasets/checkpoints that are gitignored anyway. Same list as the
# doc-figure guard reads, so the two agree on what "the docs" means — including
# `.pytest_cache`, whose README would otherwise make the file count depend on
# whether anyone had run the tests.
SKIP = {".git", "node_modules", ".venv", "dist", "__pycache__", ".pytest_cache",
        ".data", "model"}

# A fenced code block can hold markdown that is *illustrative* rather than linked
# (a README showing `[label](target)`), so its lines are blanked before scanning —
# but the blanking keeps one newline per line, so reported line numbers stay true.
FENCE = re.compile(r"```.*?```", re.S)

# `[text](target)`, `![alt](target)`, and the `<...>` form that lets a target carry
# spaces. The optional quoted title is dropped, which is what keeps
# `[x](y "t")` from reading the title as part of the path.
INLINE = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)>\s]+)>?(?:\s+\"[^\"]*\")?\)")
# Reference definitions: `[label]: target`.
REFDEF = re.compile(r"^\[[^\]]+\]:\s*<?([^>\s]+)>?", re.M)
# Raw HTML, for the rare `<a href="...">`.
HREF = re.compile(r"<a\b[^>]*?href=[\"']([^\"']+)[\"']")
# Anything with a scheme (`https:`, `mailto:`) or protocol-relative (`//host`).
SCHEME = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.\-]*:|//)")

ERRORS: list[str] = []


def markdown_files() -> list[Path]:
    return [p for p in sorted(ROOT.rglob("*.md")) if not any(part in SKIP for part in p.parts)]


def git_top() -> Path | None:
    """The work tree root, or None when this is not a git checkout."""
    out = _git(["rev-parse", "--show-toplevel"])
    return Path(out) if out else None


def tracked_files(top: Path) -> set[str]:
    """Every path in git's index, relative to ``top`` and slash-separated."""
    out = _git(["ls-files", "-z", "--full-name"], top=top)
    return {p for p in (out or "").split("\0") if p}


def _git(args: list[str], top: Path | None = None) -> str | None:
    """Run one git command, returning stdout, or None if git cannot answer."""
    try:
        done = subprocess.run(["git", "-C", str(top or ROOT), *args],
                              capture_output=True, check=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.decode("utf-8", errors="replace").strip()


def slug_headings(text: str) -> set[str]:
    """Every heading in one document, in the form GitHub would anchor it.

    Lowercased, punctuation removed (so ``## 5. How (Workflow)`` becomes
    ``5-how-workflow``), spaces joined with hyphens, and a repeated heading
    suffixed ``-1``, ``-2`, … in document order.

    Inline code keeps its *contents*: GitHub strips the backticks as punctuation
    and nothing else, so ``## The `x.py` guard`` anchors to ``the-xpy-guard``,
    not to a hole where the code was. Deleting the contents would make this guard
    invent a dead anchor for a heading that works and wave through a link written
    for one. ``scripts/test_check_doc_links.py`` pins that, and every other rule
    above, with assertions.

    Not modelled, and a known gap rather than a decision: setext headings, the
    ``Title`` underlined with ``===`` form.
    """
    # A heading inside a fenced block is an example of a heading, as far as
    # GitHub is concerned: it gets no anchor, so offering one would let a link
    # to a phantom section pass.
    text = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    out: set[str] = set()
    seen: dict[str, int] = {}
    for line in text.splitlines():
        m = re.match(r"^#{1,6}\s+(.*)$", line)
        if not m:
            continue
        h = m.group(1).strip().lower()
        h = re.sub(r"[^\w\- ]", "", h).strip().replace(" ", "-")
        n = seen.get(h, 0)
        seen[h] = n + 1
        out.add(h if n == 0 else f"{h}-{n}")
    return out


def case_exact(path: Path) -> bool:
    """True when every component of ``path`` exists with exactly that spelling.

    ``path`` must be the *linked* path, not a resolved one: ``Path.resolve()`` on
    Windows and macOS hands back the true on-disk spelling for a file that exists,
    which would normalise `AGENTS.MD` to `AGENTS.md` before this ever sees it — and
    the whole point is to catch that the document said it wrong.

    ``Path.exists()`` is likewise true for ``readme.md`` on NTFS and APFS, so it
    cannot answer the question on its own: walk the components and match each
    against the real directory listing, which is where the spelling the remote
    will see is stored.
    """
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return True                       # outside the repo: nothing to compare
    cur = ROOT
    for part in rel.parts:
        if part in (".", ".."):
            cur = cur / part
            continue
        if not cur.is_dir():
            return False
        if part not in {child.name for child in cur.iterdir()}:
            return False
        cur = cur / part
    return True


def link_targets(text: str) -> list[tuple[str, int, str | None]]:
    """``(target, line, fragment)`` for every link worth resolving.

    An empty target means a bare ``#anchor``, which belongs to the current file.
    Absolute paths and anything with a scheme are dropped — not ours to resolve.
    Percent-escapes are decoded (``docs/my%20doc.md`` is ``docs/my doc.md``) and a
    query string dropped — after the fragment, so the fragment survives.
    """
    text = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    hits = [(m.group(1), text[:m.start()].count("\n") + 1)
            for m in INLINE.finditer(text)]
    hits += [(m.group(1), text[:m.start()].count("\n") + 1) for m in REFDEF.finditer(text)]
    hits += [(m.group(1), text[:m.start()].count("\n") + 1) for m in HREF.finditer(text)]

    out: list[tuple[str, int, str | None]] = []
    for target, line in hits:
        if target.startswith("#"):
            out.append(("", line, target[1:]))
            continue
        if target.startswith("/") or SCHEME.match(target):
            continue
        target = unquote(target)
        # Fragment first, query second: `PRD.md?v=2#roadmap` still anchors at
        # `#roadmap`, and dropping the query before the split would throw the
        # fragment away and check nothing.
        path, _, frag = target.partition("#")
        path = path.split("?", 1)[0]
        if path:
            out.append((path, line, frag or None))
    return out


def check_file(md: Path, text: str, tracked: set[str] | None, top: Path) -> int:
    """Report every unresolvable link in one document; return how many were checked."""
    rel = md.relative_to(ROOT).as_posix()
    checked = 0
    own_slugs = slug_headings(text) if "#" in text else set()

    for target, line, frag in link_targets(text):
        checked += 1
        if not target:                                   # bare #anchor in this file
            if frag not in own_slugs:
                ERRORS.append(f"{rel}:{line}: #{frag} names no heading in this file")
            continue

        # Deliberately not .resolve(): the linked spelling is the evidence here.
        dest = md.parent / target
        if not dest.exists():
            ERRORS.append(f"{rel}:{line}: links to {target}, which does not exist")
            continue
        if not case_exact(dest):
            ERRORS.append(f"{rel}:{line}: {target} exists with different case")
            continue
        # Directories have no index entry, and `docs/decisions/` is a legitimate
        # target; only a file can be missing from a fresh clone.
        if tracked is not None and dest.is_file():
            try:
                key = dest.resolve().relative_to(top).as_posix()
            except ValueError:
                key = None                              # outside the work tree
            if key is not None and key not in tracked:
                ERRORS.append(
                    f"{rel}:{line}: {target} is not in git — a fresh clone will not have it "
                    "(generated output, a local dataset, or an uncommitted file)")
                continue
        if frag and dest.is_file() and dest.suffix == ".md":
            if frag not in slug_headings(dest.read_text(encoding="utf-8", errors="replace")):
                ERRORS.append(f"{rel}:{line}: {target}#{frag} names no heading in that file")
    return checked


def main() -> int:
    files = markdown_files()
    if not files:
        print("doc links FAILED — no markdown found; did the path change?", file=sys.stderr)
        return 1

    top = git_top()
    tracked = tracked_files(top) if top else None
    if tracked is None:
        print("note: git is unavailable here, so links are checked for existence, case and "
              "anchors but not for being tracked.\n", file=sys.stderr)

    checked = sum(check_file(md, md.read_text(encoding="utf-8", errors="replace"),
                             tracked, top or ROOT)
                  for md in files)

    if ERRORS:
        print(f"doc links FAILED — {len(ERRORS)} dead link(s):\n", file=sys.stderr)
        for error in ERRORS:
            print(f"  - {error}", file=sys.stderr)
        print(
            f"\n{checked} relative link(s) across {len(files)} markdown file(s) were checked; "
            "a link is fixed by correcting the target, by committing the file it points at, "
            "or by teaching this guard to ignore it.",
            file=sys.stderr,
        )
        return 1

    tail = "every target and anchor resolves" + (
        ", and every target is tracked" if tracked is not None else " (tracked-target check skipped)")
    print(f"doc links ok — {checked} relative link(s) across {len(files)} markdown file(s), {tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())