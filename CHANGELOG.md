# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Open-source project scaffolding: MIT `LICENSE`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue and pull request templates.
- `scripts/validate_skills.py` — validates every `SKILL.md` against the
  Agent Skills spec (frontmatter parses, `name`/`description` present and
  typed, name matches its directory, names unique, description within
  budget).
- CI on every push and pull request: the frontmatter validator, the engine
  suite across Python 3.8–3.13, and an end-to-end job that installs the
  skills with the real `skills` CLI and asserts all five land.

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
