#!/usr/bin/env bash
#
# on-edit.sh <file> — fast, targeted feedback for a single edited file.
#
# Tool-agnostic: it takes a path. The repo's editor hook passes the
# just-edited file, but it is equally usable from a pre-commit hook or a CI
# loop over each changed file. It adds no checks of its own — it only invokes
# the existing validator, and prints a judgment reminder at two boundaries.
#
#   */SKILL.md          run the frontmatter validator; exit 2 on failure so
#                       the host workflow blocks (the skills CLI silently
#                       *skips* an unparseable skill — this is the footgun).
#   */CONTRACTS.md
#   */PUBLIC_API.md     print a one-line reminder about the paired update;
#                       never fails (architectural judgment, not a mechanic).
#   anything else       no-op.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
file="${1:-}"
[ -n "$file" ] || exit 0

case "$file" in
  */SKILL.md | SKILL.md)
    python3 "$ROOT/scripts/validate_skills.py" || exit 2
    ;;
  */CONTRACTS.md)
    echo "note: CONTRACTS.md changed — does DESIGN.md §10 need a decision" \
         "record, or a test to cover the new behavior?"
    ;;
  */PUBLIC_API.md)
    echo "note: PUBLIC_API.md changed — update TestPublicOutputContract to" \
         "match; the doc-contract guard enforces that they agree."
    ;;
esac
