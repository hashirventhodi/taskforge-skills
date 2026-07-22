#!/usr/bin/env bash
#
# verify-changed.sh — run the repo's checks scoped to what changed in the
# working tree.
#
# Tool-agnostic: no arguments, reads `git status`. Exits 0 if the scoped
# checks pass (or nothing changed) and non-zero if any fail — so a pre-commit
# hook or CI job blocks on it, while the editor's Stop hook invokes it
# advisorily (it appends `|| true`). It adds NO checks of its own; it only
# decides which existing checks are relevant and runs them.
#
#   engine code / tests changed  -> the engine suite
#   any skill / doc / template /
#   reference / contract changed -> the validator + the doc-contract suite
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

changed="$( { git diff --name-only
              git diff --cached --name-only
              git ls-files --others --exclude-standard
            } 2>/dev/null | sort -u )"
[ -n "$changed" ] || exit 0

need_engine=0
need_docs=0
while IFS= read -r f; do
  case "$f" in
    taskforge/scripts/* | taskforge/tests/*) need_engine=1 ;;
  esac
  case "$f" in
    */SKILL.md | \
    taskforge/CONTRACTS.md | taskforge/references/* | taskforge/templates/* | \
    taskforge/capabilities.json | docs/PUBLIC_API.md | \
    README.md | CONTRIBUTING.md | AGENTS.md | CLAUDE.md | \
    scripts/validate_skills.py | tests/*)
      need_docs=1 ;;
  esac
done <<< "$changed"

fail=0
echo "── taskforge verify (scoped to changed files) ──"
if [ "$need_engine" = 1 ]; then
  echo "• engine suite"
  python3 -m unittest discover taskforge/tests -q || fail=1
fi
if [ "$need_docs" = 1 ]; then
  echo "• skill validator"
  python3 scripts/validate_skills.py >/dev/null && echo "  ok" || fail=1
  echo "• doc-contract suite"
  python3 -m unittest discover tests -q || fail=1
fi

if [ "$fail" = 0 ]; then
  echo "✓ scoped checks passed"
else
  echo "✗ scoped checks FAILED — fix before opening a PR"
fi
exit "$fail"
