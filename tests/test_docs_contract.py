"""Doc-contract tests — deterministic guards against documentation drift.

These are dev-only (repo-scoped) and are NOT shipped inside any skill: they
scan repo-root files (README, DESIGN, CHANGELOG) that no install carries, so
they live in the repo's `tests/`, separate from the shipped engine suite in
`taskforge/tests/`.

Each guard exists because a specific drift already happened, or is one CLI/
doc edit away:

  * test-count claims went 40 → 41 → 42 across three files (now forbidden)
  * `-v2` package names and `taskforge-core`/`taskforge-add-task` survived a
    rename in stray docs
  * a SKILL.md can reference a moved file, or name an engine command that
    doesn't exist, with nothing to catch it
  * the P0 injection fix can silently regress if a doc example goes back to
    inline `--title`/`--description` for source-derived text

Stdlib only (`re`, `json`, `pathlib`), hermetic (reads committed files, no
network, no subprocess).

Run: python3 -m unittest discover tests
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUB = ROOT / "taskforge"
CLI = HUB / "scripts" / "engine" / "cli.py"

SKILL_FILES = sorted(ROOT.glob("*/SKILL.md"))
REFERENCE_FILES = sorted((HUB / "references").glob("*.md"))
# Docs that are point-in-time records: they legitimately name old versions,
# renamed skills, and per-release counts. Excluded from "current-state" guards.
HISTORY_DOCS = {"CHANGELOG.md", "DESIGN.md", "HANDOFF.md"}


def read(path):
    return path.read_text(encoding="utf-8")


def cli_subcommands():
    """The engine's real subcommand names, parsed from cli.py — both the
    per-command `add_parser("x")` calls and the batched `for name in (...)`."""
    src = read(CLI)
    names = set(re.findall(r'add_parser\("([a-z][a-z-]*)"\)', src))
    loop = re.search(r'for name in \(([^)]*)\):', src)
    if loop:
        names |= set(re.findall(r'"([a-z][a-z-]*)"', loop.group(1)))
    return names


class TestReferencedPathsExist(unittest.TestCase):
    """Every repo file a skill points at must exist."""

    # Backtick-quoted paths ending in a real extension.
    PATH_RE = re.compile(r'`([A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:md|json|py))`')
    # Runtime / user-created paths that are not repo files.
    SKIP_PREFIXES = (".tasks/",)
    SKIP_EXACT = {"result.json", "tasks.py", "reporting.md"}

    def resolvable(self, ref):
        """Try the sensible bases; a path is OK if it resolves under any.
        References are written relative to the hub (`references/x`,
        `templates/x`, `taskforge/x`) or as repo-root paths."""
        if ref in self.SKIP_EXACT or ref.startswith(self.SKIP_PREFIXES):
            return True
        # Bases a reference may be written relative to: repo root
        # (`taskforge/...`), the hub, or the hub's own subdirs when a doc
        # names a template/reference by bare filename (`run-approved.json`).
        for base in (ROOT, HUB, HUB / "templates", HUB / "references"):
            if (base / ref).exists():
                return True
        return False

    def test_all_referenced_paths_exist(self):
        missing = []
        for doc in SKILL_FILES + REFERENCE_FILES + [HUB / "CONTRACTS.md"]:
            for ref in self.PATH_RE.findall(read(doc)):
                if not self.resolvable(ref):
                    missing.append(f"{doc.relative_to(ROOT)} → {ref}")
        self.assertEqual(missing, [], f"referenced files not found: {missing}")


class TestCommandTableMatchesEngine(unittest.TestCase):
    """The docs and the engine's command surface must agree, both ways."""

    DOC_CMD_RE = re.compile(r'\$SCRIPT ([a-z][a-z-]+)')

    def documented_commands(self):
        cmds = set()
        for doc in SKILL_FILES + REFERENCE_FILES:
            cmds |= set(self.DOC_CMD_RE.findall(read(doc)))
        return cmds

    def test_documented_commands_are_real(self):
        real = cli_subcommands()
        bogus = self.documented_commands() - real
        self.assertEqual(bogus, set(),
                         f"docs invoke non-existent engine commands: {bogus}")

    def test_engine_commands_are_documented(self):
        """A new subcommand must surface *somewhere* in the doc set — the hub
        command table, CONTRACTS' result contract (apply/validate), or a
        workflow skill/reference (record-review-prompt). An engine command no
        doc mentions is an undiscoverable feature."""
        corpus = "\n".join(read(d) for d in (
            SKILL_FILES + REFERENCE_FILES + [HUB / "CONTRACTS.md"]))
        undocumented = {c for c in cli_subcommands() if c not in corpus}
        self.assertEqual(undocumented, set(),
                         f"engine commands absent from all docs: "
                         f"{undocumented}")


class TestTemplatesValid(unittest.TestCase):
    """Every result template must be parseable and shaped like a result."""

    RESULT_KEYS = {"result_id", "artifacts", "generated_tasks", "edges",
                   "signal", "signal_reason", "notes"}

    def test_templates_parse_and_are_result_shaped(self):
        templates = sorted((HUB / "templates").glob("*.json"))
        self.assertTrue(templates, "no templates found")
        for tpl in templates:
            with self.subTest(template=tpl.name):
                data = json.loads(read(tpl))  # raises on malformed JSON
                self.assertIsInstance(data, dict)
                self.assertIn("result_id", data,
                              f"{tpl.name} missing result_id")
                extra = set(data) - self.RESULT_KEYS
                self.assertEqual(extra, set(),
                                 f"{tpl.name} has non-result keys: {extra}")


class TestNoStaleIdentifiers(unittest.TestCase):
    """Renamed package/skill names must not survive in current-state docs."""

    STALE = ("taskforge-core", "taskforge-add-task", "taskforge-skills-v2",
             "skills-v2")

    def current_state_docs(self):
        docs = list(SKILL_FILES) + list(REFERENCE_FILES)
        docs += [HUB / "CONTRACTS.md"]
        for name in ("README.md", "CONTRIBUTING.md", "SECURITY.md"):
            docs.append(ROOT / name)
        return docs

    def test_no_stale_identifiers(self):
        hits = []
        for doc in self.current_state_docs():
            text = read(doc)
            for token in self.STALE:
                if token in text:
                    hits.append(f"{doc.relative_to(ROOT)} → {token}")
        self.assertEqual(hits, [],
                         f"stale identifiers in current-state docs: {hits}")


class TestResolutionOrderSingleSourced(unittest.TestCase):
    """The engine-resolution order is authored once, in CONTRACTS.md."""

    def test_env_override_named_only_in_contracts(self):
        for skill in SKILL_FILES:
            self.assertNotIn(
                "TASKFORGE_SCRIPT", read(skill),
                f"{skill.relative_to(ROOT)} restates engine resolution — it "
                f"should reference CONTRACTS.md, which owns it")

    def test_contracts_actually_documents_it(self):
        self.assertIn("TASKFORGE_SCRIPT", read(HUB / "CONTRACTS.md"),
                      "CONTRACTS.md must document the resolution order")


class TestNoHardcodedTestCount(unittest.TestCase):
    """A suite-size integer in evergreen prose is drift bait (it went
    40→41→42). Counts belong only in per-release CHANGELOG entries."""

    COUNT_RE = re.compile(r'\b\d+[- ]tests?\b', re.IGNORECASE)

    def test_no_evergreen_count_claims(self):
        hits = []
        docs = list(SKILL_FILES) + list(REFERENCE_FILES)
        docs += [HUB / "CONTRACTS.md", ROOT / "README.md",
                 ROOT / "CONTRIBUTING.md"]
        for doc in docs:
            for m in self.COUNT_RE.findall(read(doc)):
                hits.append(f"{doc.relative_to(ROOT)} → {m!r}")
        self.assertEqual(hits, [],
                         f"hardcoded test counts (drift bait) — say 'the "
                         f"engine suite' instead: {hits}")


class TestSkillLicenses(unittest.TestCase):
    """Every distributed skill declares `license: MIT` in frontmatter — it
    ships detached from the repo LICENSE. (The frontmatter validator also
    enforces this; the guard here keeps it a stated repo invariant.)"""

    LICENSE_RE = re.compile(r'^license:\s*(.+?)\s*$', re.MULTILINE)

    def test_every_skill_declares_mit(self):
        for skill in SKILL_FILES:
            head = read(skill).split("---", 2)
            self.assertGreaterEqual(len(head), 3,
                                    f"{skill.relative_to(ROOT)}: no frontmatter")
            m = self.LICENSE_RE.search(head[1])
            self.assertIsNotNone(
                m, f"{skill.relative_to(ROOT)}: missing 'license' in frontmatter")
            self.assertEqual(m.group(1), "MIT",
                             f"{skill.relative_to(ROOT)}: license is "
                             f"{m.group(1)!r}, expected MIT")


class TestUntrustedTextFileForm(unittest.TestCase):
    """The P0 injection fix: source-derived text uses the file form. Guards
    against a doc example regressing to inline --title/--description."""

    def test_intake_mandates_file_form(self):
        intake = read(HUB / "references" / "intake.md")
        self.assertIn("--title-file", intake)
        self.assertIn("--description-file", intake)
        # No inline create example for the source-derived fields.
        self.assertNotIn('create --title "', intake)
        self.assertNotIn('--description "', intake)

    def test_contracts_states_the_rule(self):
        contracts = read(HUB / "CONTRACTS.md")
        self.assertIn("Untrusted text is data", contracts)


if __name__ == "__main__":
    unittest.main()
