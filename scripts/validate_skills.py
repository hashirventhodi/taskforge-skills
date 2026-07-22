#!/usr/bin/env python3
"""Validate every SKILL.md against the Agent Skills spec before it ships.

This exists because of a real failure: an unquoted colon in a description
(`Four modes: adopt ...`) turned the YAML scalar into a nested mapping, so
the `skills` CLI skipped taskforge-refine entirely — printing one warning
line in the middle of otherwise successful output and installing 4 of 5
skills. Nothing in the repo caught it. This does.

Checks, per skill directory:
  * frontmatter delimiters present and well formed
  * YAML parses (PyYAML when available; otherwise a targeted lint for the
    plain-scalar footguns that actually break the CLI)
  * `name` and `description` exist and are strings
  * `name` is lowercase/digits/hyphens and matches its directory
  * `description` is within the 1024-character budget
  * `license` is declared and is MIT (skills ship detached from LICENSE)
  * names are unique across the repo
  * the main `taskforge` skill ships alongside the skills that resolve through it

Exits non-zero with a report on any error. Stdlib-only by default, matching
the engine's constraint; PyYAML is used only if already installed.
"""
import re
import sys
from pathlib import Path

MAX_DESCRIPTION = 1024
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ROOT = Path(__file__).resolve().parent.parent

try:
    import yaml  # type: ignore
    HAVE_YAML = True
except ImportError:  # pragma: no cover - depends on environment
    HAVE_YAML = False


def split_frontmatter(text, errors):
    """Return the raw frontmatter block, or None if the delimiters are wrong."""
    if not text.startswith("---\n"):
        errors.append("must start with a '---' frontmatter delimiter on line 1")
        return None
    end = text.find("\n---", 3)
    if end == -1:
        errors.append("frontmatter is never closed with '---'")
        return None
    return text[4:end + 1]


def lint_plain_scalars(block, errors):
    """Catch the unquoted-value footguns that break YAML parsers.

    Only applies to unquoted (plain) scalars: a bare ': ' inside one makes
    the parser read a nested mapping, and a leading '"' or '[' changes the
    node type. Quoted values are the fix, so they are exempt.
    """
    for line in block.splitlines():
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        if not NAME_RE.match(key.strip().lower().replace("_", "-")):
            continue
        value = value.strip()
        if not value or value[0] in "\"'":
            continue
        if ": " in value:
            errors.append(
                "%s: unquoted value contains ': ', which YAML reads as a "
                "nested mapping — quote the value or replace the colon "
                "(offending text: %r)" % (key.strip(), value[:60]))
        if value[0] in "[{&*!|>%@`":
            errors.append(
                "%s: unquoted value starts with the reserved character %r — "
                "quote the value" % (key.strip(), value[0]))


def parse_frontmatter(block, errors):
    if HAVE_YAML:
        try:
            data = yaml.safe_load(block)
        except Exception as exc:  # noqa: BLE001 - report any YAML failure
            errors.append("YAML parse error: %s" % str(exc).replace("\n", " "))
            return None
        if not isinstance(data, dict):
            errors.append("frontmatter must be a mapping of fields")
            return None
        return data

    lint_plain_scalars(block, errors)
    data = {}
    for line in block.splitlines():
        if not line or line[0].isspace():
            continue
        key, sep, value = line.partition(":")
        if sep:
            data[key.strip()] = value.strip().strip("\"'")
    return data


def check_skill(skill_md):
    """Validate one SKILL.md. Returns (name_or_None, [errors])."""
    errors = []
    directory = skill_md.parent.name
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        return None, ["cannot read file: %s" % exc]

    block = split_frontmatter(text, errors)
    if block is None:
        return None, errors

    data = parse_frontmatter(block, errors)
    if data is None:
        return None, errors

    name = data.get("name")
    description = data.get("description")

    if name is None:
        errors.append("missing required field 'name'")
    elif not isinstance(name, str):
        errors.append("'name' must be a string, got %s" % type(name).__name__)
    else:
        if not NAME_RE.match(name):
            errors.append(
                "'name' must be lowercase letters, digits and hyphens: %r" % name)
        if name != directory:
            errors.append(
                "'name' (%r) must match its directory (%r) — the CLI installs "
                "into a directory named after the frontmatter, so a mismatch "
                "breaks sibling path resolution" % (name, directory))

    if description is None:
        errors.append("missing required field 'description'")
    elif not isinstance(description, str):
        errors.append(
            "'description' must be a string, got %s" % type(description).__name__)
    elif len(description) > MAX_DESCRIPTION:
        errors.append(
            "'description' is %d characters, over the %d limit"
            % (len(description), MAX_DESCRIPTION))
    elif not description.strip():
        errors.append("'description' is empty")

    # Skills are distributed individually and travel detached from the repo's
    # LICENSE file, so each must declare its own license in frontmatter.
    license_ = data.get("license")
    if license_ is None:
        errors.append("missing 'license' — each skill ships detached from the "
                      "repo LICENSE, so it must declare its own (e.g. MIT)")
    elif license_ != "MIT":
        errors.append("'license' is %r; this project's skills are MIT"
                      % (license_,))

    return (name if isinstance(name, str) else None), errors


def main():
    skill_files = sorted(ROOT.glob("*/SKILL.md"))
    if not skill_files:
        print("error: no */SKILL.md found under %s" % ROOT)
        return 1

    failed = False
    seen = {}

    if not HAVE_YAML:
        print("note: PyYAML not installed — using the built-in lint. "
              "Install pyyaml for full parser fidelity.\n")

    for skill_md in skill_files:
        rel = skill_md.relative_to(ROOT)
        name, errors = check_skill(skill_md)

        if name:
            if name in seen:
                errors.append(
                    "duplicate skill name %r, already used by %s" % (name, seen[name]))
            else:
                seen[name] = rel

        if errors:
            failed = True
            print("FAIL %s" % rel)
            for err in errors:
                print("     - %s" % err)
        else:
            print("ok   %s (%s)" % (rel, name))

    if "taskforge" not in seen:
        failed = True
        print("\nFAIL the main taskforge skill is missing — every other skill "
              "resolves the engine through it as a sibling directory")

    print("\n%d skill(s) checked, %s"
          % (len(skill_files), "FAILED" if failed else "all valid"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
