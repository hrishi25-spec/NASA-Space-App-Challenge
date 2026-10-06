#!/usr/bin/env python3
"""The doc-link guard's own tests — what it must catch, and what it must not.

``scripts/check-doc-links.py`` fails builds on broken links, so its own rules
deserve assertions rather than the manual probe that found the last batch of dead
anchors. Every rule in the guard is pinned here:

* **the slug rules** — lowercase, punctuation dropped, spaces hyphenated,
  duplicates suffixed ``-1``/``-2``, and inline code keeping its contents (GitHub
  strips the backticks, not what is between them);
* **the case check** — the quiet one, since ``README.md`` resolves for
  ``readme.md`` on NTFS and macOS and 404s on GitHub;
* **the link parser** — fences, reference definitions, ``<a href>``, schemes,
  percent-escapes, fragments;
* **the four error classes** and the two deliberate exemptions, driven through
  ``main()`` against throwaway git repositories.

Deliberately a stdlib ``unittest`` module, not a pytest one: the guard promises to
run anywhere python3 does, and its CI job installs nothing. It runs under either
runner:

    python scripts/test_check_doc_links.py       # no dependencies at all
    firecal/backend/.venv/bin/python -m pytest scripts/test_check_doc_links.py

The filename cannot be imported normally (the guard's name has hyphens), so it is
loaded by path below.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUARD = HERE / "check-doc-links.py"

_spec = importlib.util.spec_from_file_location("check_doc_links", GUARD)
assert _spec and _spec.loader, f"cannot load {GUARD}"
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

HAS_GIT = shutil.which("git") is not None
needs_git = unittest.skipUnless(HAS_GIT, "git is required for the tracked-file check")


class SlugRules(unittest.TestCase):
    """GitHub builds a heading anchor by lowercasing it, dropping punctuation,
    and joining the words with hyphens. Pinned against github-slugger's regex,
    which is what GitHub actually implements."""

    def slugs(self, text: str) -> set[str]:
        return guard.slug_headings(text)

    def test_words_are_lowercased_and_hyphenated(self):
        self.assertEqual(self.slugs("## How It Works"), {"how-it-works"})

    def test_punctuation_is_dropped_not_hyphenated(self):
        # The real bug this guard was built for: a table of contents shortened
        # this anchor and the link went nowhere.
        self.assertEqual(
            self.slugs("## 5. How the Papers Fit Together (Workflow View)"),
            {"5-how-the-papers-fit-together-workflow-view"},
        )
        self.assertEqual(self.slugs("## What's new?"), {"whats-new"})

    def test_a_leading_number_keeps_the_anchor(self):
        self.assertEqual(self.slugs("## 14. Roadmap"), {"14-roadmap"})

    def test_underscores_survive_because_they_are_word_characters(self):
        # github-slugger strips `.` but not `_`; a naive slugger eats both and
        # then rejects a link that works.
        self.assertEqual(self.slugs("## check_doc_links"), {"check_doc_links"})
        self.assertEqual(self.slugs("## Use `x.py` Here"), {"use-xpy-here"})

    def test_inline_code_keeps_its_contents(self):
        # The regression this suite exists for: GitHub strips the backticks as
        # punctuation and nothing else, so the code's words are part of the
        # anchor. Deleting them produced a hole where the code was.
        self.assertEqual(self.slugs("## The `x.py` guard"), {"the-xpy-guard"})
        self.assertEqual(self.slugs("## Run `npm run build` first"),
                         {"run-npm-run-build-first"})

    def test_repeated_headings_get_numbered_in_document_order(self):
        text = "## Notes\n\n## Notes\n\n## Notes\n"
        self.assertEqual(self.slugs(text), {"notes", "notes-1", "notes-2"})

    def test_closing_hashes_are_not_part_of_the_heading(self):
        self.assertEqual(self.slugs("## Summary ##"), {"summary"})

    def test_heading_depths_one_to_six_all_count(self):
        text = "\n".join("#" * n + f" Depth{n}" for n in range(1, 7))
        self.assertEqual(self.slugs(text), {f"depth{n}" for n in range(1, 7)})

    def test_a_hash_without_a_space_is_not_a_heading(self):
        # `#tag` in prose must not invent an anchor, or every doc full of
        # issue references would fail.
        self.assertEqual(self.slugs("See #123 for the bug."), set())
        self.assertEqual(self.slugs("####### seven hashes is not a heading"), set())

    def test_headings_inside_a_fenced_block_are_not_headings(self):
        text = "```markdown\n## Example Heading\n```\n\n## Real Heading\n"
        self.assertEqual(self.slugs(text), {"real-heading"})


class CaseCheck(unittest.TestCase):
    """``case_exact`` compares the linked spelling against the real directory
    listing, because on a case-insensitive filesystem nothing else would."""

    def with_root(self, tmp: Path):
        """Point the guard's ROOT at a throwaway tree for the duration."""
        old = guard.ROOT
        guard.ROOT = tmp
        self.addCleanup(lambda: setattr(guard, "ROOT", old))

    def test_the_exact_spelling_passes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "docs").mkdir()
            (root / "docs" / "PRD.md").write_text("# PRD\n", encoding="utf-8")
            self.with_root(root)
            self.assertTrue(guard.case_exact(root / "docs" / "PRD.md"))
            self.assertTrue(guard.case_exact(root / "docs"))

    def test_a_wrong_case_filename_is_caught(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "README.md").write_text("# hi\n", encoding="utf-8")
            self.with_root(root)
            self.assertFalse(guard.case_exact(root / "README.MD"))
            self.assertFalse(guard.case_exact(root / "readme.md"))

    def test_a_wrong_case_directory_component_is_caught(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "docs").mkdir()
            (root / "docs" / "PRD.md").write_text("# PRD\n", encoding="utf-8")
            self.with_root(root)
            self.assertFalse(guard.case_exact(root / "Docs" / "PRD.md"))
            self.assertFalse(guard.case_exact(root / "docs" / "prd.md"))

    def test_a_path_outside_the_repo_is_not_our_business(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "docs").mkdir()
            self.with_root(root)
            self.assertTrue(guard.case_exact(Path(raw).resolve().parent / "elsewhere.md"))

    @unittest.skipUnless((guard.ROOT / "README.md").is_file(), "not running in the repo")
    def test_this_repositorys_own_names_are_exact(self):
        # The guard checks the repo it lives in, so its idea of a correct
        # spelling is verified against the real thing.
        self.assertTrue(guard.case_exact(guard.ROOT / "README.md"))
        self.assertFalse(guard.case_exact(guard.ROOT / "README.MD"))
        self.assertFalse(guard.case_exact(guard.ROOT / "docs" / "AGENTS.MD"))


class LinkParsing(unittest.TestCase):
    """``link_targets`` finds the links worth resolving and no others."""

    def targets(self, text: str) -> list[tuple[str, int, str | None]]:
        return guard.link_targets(text)

    def test_inline_reference_and_html_links_are_all_found(self):
        text = (
            "see [a](docs/PRD.md)\n"
            "![img](media/map.png)\n"
            "[ref]: docs/brain.md\n"
            '<a href="docs/AGENTS.md">agents</a>\n'
        )
        found = {t for t, _, _ in self.targets(text)}
        self.assertEqual(found, {"docs/PRD.md", "media/map.png", "docs/brain.md",
                                 "docs/AGENTS.md"})

    def test_a_fenced_code_block_is_not_a_link(self):
        text = "```\n[x](not/real.md)\n```\n[y](docs/PRD.md)\n"
        self.assertEqual([t for t, _, _ in self.targets(text)], ["docs/PRD.md"])

    def test_line_numbers_survive_the_fence_blanking(self):
        text = "one\n```\n[x](ghost.md)\n```\nfour\n[y](real.md)\n"
        self.assertEqual(self.targets(text), [("real.md", 6, None)])

    def test_external_and_absolute_targets_are_left_alone(self):
        text = ("[a](https://example.com/x.md)\n"
                "[b](//example.com/x.md)\n"
                "[c](mailto:someone@example.com)\n"
                "[d](/abs/path.md)\n"
                "[e](docs/PRD.md)\n")
        self.assertEqual([t for t, _, _ in self.targets(text)], ["docs/PRD.md"])

    def test_a_fragment_is_split_off_and_a_query_dropped(self):
        self.assertEqual(self.targets("[x](docs/PRD.md#14-roadmap)\n"),
                         [("docs/PRD.md", 1, "14-roadmap")])
        self.assertEqual(self.targets("[x](docs/PRD.md?v=2#top)\n"),
                         [("docs/PRD.md", 1, "top")])

    def test_a_bare_fragment_belongs_to_the_same_file(self):
        self.assertEqual(self.targets("jump to [top](#next-steps)\n"),
                         [("", 1, "next-steps")])

    def test_percent_escapes_are_decoded(self):
        self.assertEqual([t for t, _, _ in self.targets("[x](docs/my%20doc.md)\n")],
                         ["docs/my doc.md"])

    def test_a_quoted_title_is_not_part_of_the_path(self):
        self.assertEqual([t for t, _, _ in self.targets('[x](docs/PRD.md "The PRD")\n')],
                         ["docs/PRD.md"])


class GuardEndToEnd(unittest.TestCase):
    """``main()`` against a throwaway repository: the four error classes, and
    the two things the guard deliberately does not complain about."""

    def repo(self, files: dict[str, str], *, commit: tuple[str, ...] = ()) -> Path:
        raw = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, raw, ignore_errors=True)
        root = Path(raw)
        if HAS_GIT:
            self.git(root, "init", "-q", "-b", "main")
            self.git(root, "config", "user.email", "guard@example.com")
            self.git(root, "config", "user.name", "Guard Test")
        for name, body in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        if HAS_GIT and commit:
            self.git(root, "add", *commit)
            self.git(root, "commit", "-q", "-m", "seed")
        return root

    @staticmethod
    def git(root: Path, *args: str) -> None:
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True, timeout=60)

    def run_guard(self, root: Path) -> tuple[int, str]:
        old_root, old_errors = guard.ROOT, guard.ERRORS
        guard.ROOT, guard.ERRORS = root, []
        err, out = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                code = guard.main()
        finally:
            guard.ROOT, guard.ERRORS = old_root, old_errors
        return code, err.getvalue() + out.getvalue()

    @needs_git
    def test_a_healthy_repository_passes(self):
        root = self.repo({
            "README.md": "# Firecal\n\n[the PRD](docs/PRD.md)\n",
            "docs/PRD.md": "# PRD\n\n## Roadmap\n\n[back](../README.md#firecal)\n",
        }, commit=("README.md", "docs/PRD.md"))
        code, report = self.run_guard(root)
        self.assertEqual(code, 0, report)

    @needs_git
    def test_a_missing_file_is_an_error(self):
        root = self.repo({"README.md": "[gone](docs/GONE.md)\n"}, commit=("README.md",))
        code, report = self.run_guard(root)
        self.assertEqual(code, 1)
        self.assertIn("does not exist", report)

    @needs_git
    def test_a_wrong_case_file_is_an_error(self):
        root = self.repo({
            "README.md": "[prd](docs/prd.md)\n",
            "docs/PRD.md": "# PRD\n",
        }, commit=("README.md", "docs/PRD.md"))
        code, report = self.run_guard(root)
        self.assertEqual(code, 1)
        # On a case-sensitive filesystem the wrong spelling is simply absent; on
        # NTFS/macOS it exists and the case check is what has to catch it.
        self.assertRegex(report, r"different case|does not exist")

    @needs_git
    def test_a_dead_anchor_in_another_file_is_an_error(self):
        root = self.repo({
            "README.md": "[prd](docs/PRD.md#nope)\n",
            "docs/PRD.md": "# PRD\n\n## Roadmap\n",
        }, commit=("README.md", "docs/PRD.md"))
        code, report = self.run_guard(root)
        self.assertEqual(code, 1)
        self.assertIn("names no heading in that file", report)

    @needs_git
    def test_a_dead_same_page_anchor_is_an_error(self):
        root = self.repo({"README.md": "# Firecal\n\n[jump](#nope)\n"}, commit=("README.md",))
        code, report = self.run_guard(root)
        self.assertEqual(code, 1)
        self.assertIn("names no heading in this file", report)

    @needs_git
    def test_an_untracked_file_is_an_error(self):
        root = self.repo({
            "README.md": "[report](REPORT.md)\n",
            "REPORT.md": "# generated\n",          # never added
        }, commit=("README.md",))
        code, report = self.run_guard(root)
        self.assertEqual(code, 1)
        self.assertIn("is not in git", report)

    @needs_git
    def test_a_gitignored_but_tracked_file_is_fine(self):
        # Tracked-but-ignored is an ordinary state, and rejecting it would make
        # the guard impossible to satisfy for some files.
        root = self.repo({
            ".gitignore": "REPORT.md\n",
            "README.md": "[report](REPORT.md)\n",
            "REPORT.md": "# generated\n",
        })
        self.git(root, "add", "-f", "REPORT.md")      # tracked, despite the rule
        self.git(root, "add", ".gitignore", "README.md")
        self.git(root, "commit", "-q", "-m", "seed")
        code, report = self.run_guard(root)
        self.assertEqual(code, 0, report)

    @needs_git
    def test_a_directory_target_is_fine(self):
        # `docs/decisions/` has no index entry of its own; it is a legitimate
        # place to send a reader.
        root = self.repo({
            "README.md": "[decisions](docs/decisions/)\n",
            "docs/decisions/0001-layout.md": "# One\n",
        }, commit=("README.md", "docs/decisions/0001-layout.md"))
        code, report = self.run_guard(root)
        self.assertEqual(code, 0, report)

    @needs_git
    def test_a_link_pointing_outside_the_repository_escapes_the_tracked_check(self):
        # Such a file cannot be in this repository's index, but it is also not
        # ours to judge — so existence applies and tracking does not.
        root = self.repo({"README.md": "[out](../outside.md)\n"}, commit=("README.md",))
        (root.parent / "outside.md").write_text("# out\n", encoding="utf-8")
        self.addCleanup((root.parent / "outside.md").unlink)
        code, report = self.run_guard(root)
        self.assertEqual(code, 0, report)

    @needs_git
    def test_a_link_outside_the_repository_must_still_exist(self):
        root = self.repo({"README.md": "[out](../nowhere.md)\n"}, commit=("README.md",))
        code, report = self.run_guard(root)
        self.assertEqual(code, 1)
        self.assertIn("does not exist", report)


class GuardIsHonestAboutItsOwnRepo(unittest.TestCase):
    """The guard runs on this repository in CI, so a mistake in its plumbing
    shows up here rather than only in a throwaway tree."""

    def test_this_repository_has_no_dead_links(self):
        # Mirror main()'s own git handling rather than reaching past it: with no
        # git there is no index, `tracked_files` answers an empty set rather than
        # None, and passing that on would report every file in the repo as
        # untracked. The guard degrades; this must degrade with it.
        old_errors = guard.ERRORS
        guard.ERRORS = []
        try:
            top = guard.git_top()
            tracked = guard.tracked_files(top) if top else None
            for md in guard.markdown_files():
                guard.check_file(md, md.read_text(encoding="utf-8", errors="replace"),
                                 tracked, top or guard.ROOT)
            self.assertEqual(guard.ERRORS, [])
        finally:
            guard.ERRORS = old_errors


if __name__ == "__main__":
    unittest.main(verbosity=2)