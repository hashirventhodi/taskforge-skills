# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `reopen <id> --reason …` (`--reason-file` too): restores a closed terminal
  (`done`/`cancelled`) to active work. Nothing is lost — artifacts, reviews,
  decisions and history are preserved, and readiness re-derives the route
  from what the task already holds (spec → run, none → refine, pending
  escalation → explore, open blocker → waiting). Reopening a task others were
  blocked on re-blocks any still-active dependent; terminal dependents are
  untouched. `blocked_on_human` is not reopenable — it resumes via
  `human-update`, which captures the human's answer. (Internal:
  `wake_blocked_by` → `refresh_dependents`, now symmetric — `unblocked` on
  close, `reblocked` on reopen.)

### Security
- Injection-safe input paths for untrusted free text: `create --title-file`,
  `human-update --note-file`, `cancel --reason-file` (mirroring the existing
  `--description-file`). Text quoted from a source — an issue title, a
  human's answer — inlined into a shell command string is a
  command-injection vector (backticks/`$( )` substitute before the engine
  runs); the file path has no shell in it. Intake and human-update docs now
  mandate the file form for source-derived text, and CONTRACTS.md states
  the rule ("Untrusted text is data, never code").
- Each inline/file flag pair now requires exactly one form; passing both is
  an error (previously `--description-file` silently won over
  `--description`).

### Changed — restructuring (breaking)
- **Four skills instead of five.** `taskforge-core` is renamed `taskforge`
  and becomes the primary, command-oriented entry point (`add`, `status`,
  `backlog`, `next`, `show`, `why`, `budget`, `unblock`, `cancel`, `sync`,
  `doctor`, `audit`, `config`). `taskforge-add-task` is removed; its intake
  procedure lives on unchanged as the `add` command
  (`taskforge/references/intake.md`).
- The intake actor is renamed `add-task` → `taskforge` in
  `capabilities.json` and in the `created` event the engine records.
- Engine resolution paths change accordingly:
  `<siblings>/taskforge/scripts/tasks.py`. Set `TASKFORGE_SCRIPT` or
  re-install if you pinned the old `taskforge-core` path.
- Existing task stores keep working — historical events that name
  `add-task` are records, not validated state.

### Added
- Doc-contract test suite (repo-level `tests/`, stdlib-only, in CI): guards
  that every path a skill references resolves, the documented command table
  matches the engine's real subcommands both ways, every template is
  result-shaped JSON, no renamed identifiers or hardcoded test counts survive
  in evergreen docs, engine resolution is single-sourced in CONTRACTS.md, and
  source-derived text keeps the file form. Catches the drift class that hit
  this repo repeatedly (40→41→42 test counts, `-v2` naming, stale paths).
- Open-source project scaffolding: MIT `LICENSE`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue and pull request templates.
- `scripts/validate_skills.py` — validates every `SKILL.md` against the
  Agent Skills spec (frontmatter parses, `name`/`description` present and
  typed, name matches its directory, names unique, description within
  budget).
- CI on every push and pull request: the frontmatter validator, the engine
  suite across Python 3.8–3.13, and an end-to-end job that installs the
  skills with the real `skills` CLI and asserts every skill lands.

### Changed
- Engine resolution now prefers the sibling path and knows the `skills`
  CLI's canonical `.agents/skills` location, making it agent-agnostic
  instead of Claude Code-specific.
- Documentation describes an "Agent Skills framework" rather than a "Claude
  Code Skills framework", noting the one agent-specific dependency (a
  fresh-context subagent for `taskforge-run`'s independent review).
- Naming aligned on `taskforge-skills` throughout; stale `-v2` package
  references removed.
- Corrected the documented test count (README said 40, HANDOFF said 42; the
  suite has 41).

### Fixed
- `taskforge-refine` was silently skipped by the `skills` CLI: an unquoted
  `: ` in its frontmatter description parsed as a nested YAML mapping, so
  installs produced four of five skills with only a warning line. Since
  refine is the workflow's entry point, installs were effectively broken.

## [0.1.0] - 2026-07-22

### Added
- Initial release: five skills (`taskforge-core`, `taskforge-add-task`,
  `taskforge-refine`, `taskforge-explore`, `taskforge-run`) over a
  deterministic, stdlib-only Python engine that is the sole writer of task
  state — versioning, invalidation cascades, derived readiness, capability
  enforcement, review budgets and an event log.
- Recorded, auditable reviewer isolation (`audit-review`).
- 41-test engine suite.

[Unreleased]: https://github.com/hashirventhodi/taskforge-skills/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/hashirventhodi/taskforge-skills/releases/tag/v0.1.0
