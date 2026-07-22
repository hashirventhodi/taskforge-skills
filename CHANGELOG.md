# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`docs/PUBLIC_API.md` — the public stability contract** (review finding
  T2-3, [#3](https://github.com/hashirventhodi/taskforge-skills/issues/3)).
  Declares the smallest stable surface (CLI subcommand names, a short set of
  frozen output keys with identified consumers, exit-code semantics, the
  readiness routing vocabulary, and `--actor` names), the semver policy, and
  an explicit non-goals list (the Python facade, storage layout, and
  diagnostic/convenience output are internal and may change). Enforced by
  `TestPublicOutputContract` (presence-and-type, tolerant of additions) with a
  both-ways doc-contract guard so the declaration and the test cannot diverge.

### Changed — public output (breaking, pre-1.0)
- **Removed the `valid` key from `validate` output.** It was structurally
  always `true`; validity is the exit code (0 valid / 1 invalid, `{error}` on
  stderr) and `warnings[]` carries non-fatal observations.
- **`readiness` is now always the routing string** in every command's output.
  It was previously the full `evaluate()` object in `create`/`show`-summary/
  `cancel`/`reopen`/`apply` output but a bare string in `list`/`readiness`.
  The diagnostic detail (`reason`/`blocking_ids`/`cycle`) remains available
  from the dedicated `readiness <id>` command.

### Migration (from 0.2.0)
- **Re-install** so the engine and all four skills move together:
  `npx skills add hashirventhodi/taskforge-skills`. The output changes above
  are safe because skills and engine install as a set — no partial upgrade.
- **Existing `.tasks/` stores are untouched.** These are *output-shape*
  changes, not storage changes; a store written by 0.2.0 is schema-1 and is
  read, routed, and continued by the new engine with no migration step
  (verified). `tasks.py migrate` remains a no-op at this schema version.

### Fixed
- **Directional schema compatibility** (review finding T2-4,
  [#4](https://github.com/hashirventhodi/taskforge-skills/issues/4)). The
  `schema_version` guard covered single-task `load()` but not the whole-store
  scan, so an older engine could misroute on — or, via a cross-task cascade,
  silently rewrite — a *newer*-schema task (real corruption in a shared
  store). The rule is now uniform: an engine reads/migrates older data but
  never interprets, mutates, or routes on newer data. `all_tasks()` skips
  future-schema tasks (so listing, routing, cascades, and migration all
  inherit the rule from one place), single-task access fails closed with an
  upgrade error, and `doctor` reports future-schema tasks as a finding without
  mutating them. `list` shows only what the engine can operate on; `doctor`
  surfaces the skew.
- **Stale-lock recovery is race-free** (review finding T1-2,
  [#2](https://github.com/hashirventhodi/taskforge-skills/issues/2)). Breaking
  a stale store lock left by a crashed session read the timestamp then
  `unlink`-ed the path unconditionally — a TOCTOU gap in which two sessions
  could both break the same stale lock and end up both holding a fresh one,
  defeating mutual exclusion. Stale-breaking is now serialized through a
  second `O_EXCL` gate (`.lock.break`) and re-verifies staleness under it, so
  a fresh lock is never removed. Same primitives as before (`O_EXCL` +
  `unlink`) — no new portability assumption. The gate is serialization-only,
  never a second lock, and deliberately not itself stale-broken; an
  essentially-impossible crash while holding it degrades to the existing
  "delete the lock if stale" manual path, never a silent double-hold.
- **Circuit-breaker park no longer discards declared work** (review finding
  T1-1, [#1](https://github.com/hashirventhodi/taskforge-skills/issues/1)).
  When an artifact tripped the version breaker or review budget mid-apply, the
  result's `generated_tasks` and `edges` were silently dropped along with the
  routing signal, yet `result_id` was recorded — so an out-of-scope follow-up
  recorded in the same result as a budget-exhausting review vanished
  unrecoverably. A breaker's authority is over **routing only**: the signal is
  now the only thing suppressed on a park; generated tasks and edges always
  apply. The override is recorded as a `signal_overridden` event and
  `apply_result` returns the authoritative signal (`none`) rather than the
  intent. Stated as a first-class invariant in CONTRACTS ("Circuit-breaker
  authority").

## [0.2.0] - 2026-07-22

Establishes the four-skill architecture and hardens the engine and tooling
into a stable foundation. **Contains breaking changes — see Migration.**

### Breaking
- **Four skills instead of five.** `taskforge-core` → **`taskforge`**, now
  the primary, command-oriented entry point (`add`, `status`, `backlog`,
  `next`, `show`, `why`, `budget`, `unblock`, `cancel`, `reopen`, `sync`,
  `doctor`, `audit`, `config`). `taskforge-add-task` is **removed** — its
  intake procedure lives on unchanged as the `taskforge add` command
  (`taskforge/references/intake.md`).
- Engine path is now `<siblings>/taskforge/scripts/tasks.py`; the intake
  actor `add-task` → `taskforge` in `capabilities.json` and the `created`
  event.
- Each inline/file text flag pair now requires exactly one form; passing
  both is an error (previously `--description-file` silently won).

### Migration (0.1.0 → 0.2.0)
- Re-install to pick up the renamed/removed skills:
  `npx skills add hashirventhodi/taskforge-skills`. If you pinned the old
  `taskforge-core/scripts/tasks.py` path, update it or set `TASKFORGE_SCRIPT`.
- **Existing `.tasks/` stores keep working untouched** — historical events
  that name the `add-task` actor are records, not validated state; no
  migration command is needed.

### Added
- **`reopen <id> --reason …`** (`--reason-file` too): restores a closed
  terminal (`done`/`cancelled`) to active work. Nothing is lost — artifacts,
  reviews, decisions and history are preserved, and readiness re-derives the
  route from what the task already holds (spec → run, none → refine, pending
  escalation → explore, open blocker → waiting). Reopening a task others were
  blocked on re-blocks any still-active dependent; terminal dependents are
  untouched. `blocked_on_human` is not reopenable — it resumes via
  `human-update`, which captures the human's answer.
- **Injection-safe file input paths** for untrusted free text:
  `create --title-file`, `human-update --note-file`, `cancel --reason-file`
  (joining the existing `--description-file`). See Security.
- **Doc-contract test suite** (repo-level `tests/`, stdlib-only, in CI):
  guards that every path a skill references resolves, the documented command
  table matches the engine's real subcommands both ways, every template is
  result-shaped JSON, no renamed identifiers or hardcoded test counts survive
  in evergreen docs, engine resolution is single-sourced in CONTRACTS.md, and
  source-derived text keeps the file form.
- **`license: MIT` frontmatter** on every skill (skills ship detached from
  the repo LICENSE), enforced by both the validator and the contract suite.
- Open-source scaffolding: MIT `LICENSE`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue/PR templates.
- `scripts/validate_skills.py` — validates every `SKILL.md` against the
  Agent Skills spec with a real YAML parser (frontmatter parses, required
  fields present and typed, `name` matches its directory, unique, within the
  description budget, MIT-licensed).
- CI on every push and PR: validator + doc-contract guards, the engine suite
  across Python 3.8–3.13, and an end-to-end real-`skills`-CLI install check.

### Changed
- Engine resolution prefers the sibling path and knows the `skills` CLI's
  canonical `.agents/skills` location — agent-agnostic, not Claude
  Code-specific.
- Docs describe an "Agent Skills framework" (one agent-specific dependency: a
  fresh-context subagent for `taskforge-run`'s review); naming aligned on
  `taskforge-skills`.
- Internal: `wake_blocked_by` → `refresh_dependents`, now symmetric —
  `unblocked` on close, `reblocked` on reopen.

### Security
- Untrusted free text (an issue title, a human's answer, a cancellation
  reason) inlined into a shell command string is a command-injection vector:
  backticks/`$( )` substitute before the engine runs. The file-input paths
  above carry it as data instead; intake and human-update docs mandate the
  file form for source-derived text, and CONTRACTS.md states the standing
  rule ("Untrusted text is data, never code").

### Fixed
- `taskforge-refine` was silently skipped by the `skills` CLI: an unquoted
  `: ` in its frontmatter description parsed as a nested YAML mapping, so
  installs produced four of five skills with only a warning line. Now caught
  by the frontmatter validator in CI.

## [0.1.0] - 2026-07-22

### Added
- Initial release: five skills (`taskforge-core`, `taskforge-add-task`,
  `taskforge-refine`, `taskforge-explore`, `taskforge-run`) over a
  deterministic, stdlib-only Python engine that is the sole writer of task
  state — versioning, invalidation cascades, derived readiness, capability
  enforcement, review budgets and an event log.
- Recorded, auditable reviewer isolation (`audit-review`).
- 41-test engine suite.

[Unreleased]: https://github.com/hashirventhodi/taskforge-skills/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/hashirventhodi/taskforge-skills/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/hashirventhodi/taskforge-skills/releases/tag/v0.1.0
