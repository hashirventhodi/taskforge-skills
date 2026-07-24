# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-07-24

The **architecture release**: TaskForge gains a clean three-layer separation —
Engine (state + business rules) → Projection API (presentation semantics) →
thin adapters (Web UI, CLI, future clients) — proven by two independent clients
rendering the same projections with zero duplicated logic. It also lands two
engine-correctness fixes and the git-aware delivery model that motivated the
work. See `docs/RETROSPECTIVE-v0.6.0.md` and `docs/ARCHITECTURE.md`.

### Added — the Projection API: the shared presentation layer
- **`taskforge/scripts/projections.py`** — six pure, framework-agnostic domain
  projections (`task`, `feature`, `review`, `health`, `digest`, `board`) that
  compose engine facts into typed, JSON-serializable shapes. The single source
  of truth for *how humans consume* engine state; every renderer (Web UI, CLI,
  MCP, SDK) consumes the same contracts. Documented as a stable surface in
  `docs/PROJECTION_API.md`, evolved additively.
- **Read-only, deterministic, no business logic.** The layer never mutates the
  store and never re-derives an engine-owned rule — enforced by
  `test_projections.py` (read-only, determinism, pure-JSON, and a guard that
  `feature().landing` matches `engine.delivery.landing_status` byte-for-byte).
- **`engine.delivery.landing_status`** — the landing rule (done + every
  descendant closed) extracted into one function, now consumed by *both* the
  `link --landed` gate and the feature projection. The projection surfaces it;
  it never re-implements it. Behavior-preserving refactor of the existing gate.
- Screens are compositions of these projections, not new projections — the
  Dashboard = `board()` + in-flight `feature()` summaries + `health()` summary.
- **Four domain concepts, one meaning per field** — Structural Integrity,
  Review Result, Audit Status, Delivery Status. `doctor` findings gained a
  `kind` so structural integrity never conflates with audit hygiene. Two
  orthogonalities are enforced and tested: a review can be `approved` yet a
  `breach`; a missing reviewer prompt is not a graph defect.

### Added — the projection-driven Web UI
- **Six workflow screens** — Dashboard, Task Focus, Feature, Review, Activity,
  Health — vanilla JS with no build step, each rendering one projection and
  nothing more (untrusted text always escaped). Visible Activity time ranges,
  a deduped next action, keyboard navigation (`d`/`a`/`h`/`?`), relative
  timestamps, consistent loading/error states, and markdown descriptions.
  Validated by a real browser walkthrough against "would I enjoy using this
  daily?".
- **Becomes the human's primary client**, replacing the snapshot-driven Console
  UI. Served by the existing Console server as read-only projection endpoints
  (`/api/p/…`); the whitelisted human-action write surface (`/api/command`) is
  retained.

### Added — `tf`, the terminal client
- **A presentation adapter over the same six projections** (`board`, `task`,
  `feature`, `review`, `activity`, `health`), sharing the Web UI's terminology
  and semantics. Building it required **zero Projection API changes and no
  duplicated logic** — the proof that the contract is truly client-agnostic.

### Changed — audit and integrity are distinct domain concepts
- Split the overloaded `review.audited` boolean and `integrity_ok` flag into
  **Audit Status** (`verified`/`breach`/`unrecorded`/`none`, identical across
  task, feature, review, and health) and **Structural Integrity** (graph
  well-formedness only). Fixed two cross-screen contradictions surfaced by the
  Web UI; both clients inherited the corrected semantics. The projection
  contract also drops presentation leaks caught before the v1 freeze: no
  CLI command string, and the authoritative `readiness` + `terminal` axes
  instead of the raw engine status cache.

### Added — git-aware tasks: `done` is not `merged` (v0.6.0)
- **`link <id> [--branch B] [--pr P] [--landed]`** — records a task's delivery
  provenance: where its work lives (branch, PR) and whether it landed (a merged
  PR). `source` is intake provenance; `delivery: {branch, pr, landed_at}` is
  output provenance.
- **Closes the `done` ≠ `merged` gap found running TaskForge on SourceGrid.**
  The old sync-back rule closed the source issue on task-`done` — but `done`
  means *reviewed and accepted*, not *merged*. On gh-335 the issue was closed
  before the PR even opened, and had to be reopened. Now `references/sync.md`
  keys external-issue closure on the merge fact, and `done` merely comments.
  The engine holds the merge fact; the skill still owns the GitHub mechanism.
- **Delivery is owned or inherited (DESIGN §10.19, supersedes §10.18).** A task
  *owns* a delivery iff it was `link`ed (any field set); a task that owns
  nothing **inherits** its nearest owning ancestor's, resolved up the `parent`
  chain at read time — never stored, no `via` pointer, no decomposition-time
  write. So a decomposed feature owns one branch/PR/landing and its children
  ride it (`link` a child only to break out). `resolve_delivery` is derived,
  exactly as `readiness` is — the projections add `delivery_owner` and
  `resolved_delivery` (informational) beside the stored own `delivery`.
- **Landing asserts completeness and is a separate axis, not a status.**
  `--landed` requires the task be `done` **and every descendant closed**
  (`done`/`cancelled`; it lists any that aren't), and is idempotent. A landed
  task is still `done`/`terminal` — readiness, capabilities, and the state
  machine are untouched.
- **Reopen clears `landed_at`.** Landing is operational completion (like
  `status`), not an artifact; a reopened feature is no longer delivered, so
  reopen lifts it — provenance stays append-only in the event log
  (`landed → reopened → landed`); branch/PR are kept.
- **Schema v1 → v2.** `migrate` back-fills `delivery` on existing tasks (the
  first real migration; the placeholder v1 path was a no-op). An engine still
  reads and migrates older stores and never mutates newer ones (unchanged
  directional-compatibility invariant).

### Added — engine-owned reviewer-prompt assembly (v0.6.0)
- **`build-review-prompt <id> --diff <file> --results <file> [--version N]`** —
  the engine now assembles and records the reviewer prompt from the active
  specification, the diff, and the test results, in one deterministic step.
  Clients no longer hand-serialize the spec into the prompt template.
- **Fixes a real audit false-negative found while running TaskForge on
  SourceGrid.** Hand assembly used `json.dumps`, which escaped embedded quotes
  (`delivery.status == "failed"` → `\"failed\"`) and non-ASCII (`—` →
  `—`). `audit-review` matches each acceptance criterion by verbatim
  substring, so an escaped-but-present criterion looked *absent* — flagging
  genuinely-isolated reviews as isolation failures (twice, on clean work). The
  engine now renders spec fields as **verbatim** labeled text (never JSON), so
  `audit-review`'s existing check holds by construction. The audit logic is
  unchanged; the bug was only ever in client-side serialization.
- **Deterministic:** the same `(spec, diff, results)` renders byte-identical
  output and digest. A code comment records *why not canonical JSON* (RFC 8785
  fixes serialization stability, not escape-freedom — the audit needs the
  latter) so the fix is not reverted backward.
### Removed — `record-review-prompt` (pre-release, no compat promise)
- The hand-assembly command is **gone**, not deprecated. It was the sole way
  to introduce the serialization mismatch above, and `build-review-prompt`
  replaces it entirely — one correct way to produce a review prompt, no
  footgun kept for "compatibility" in a pre-release engine. The low-level
  write/event recorder survives only as an internal helper (`_record_prompt`),
  used by `build-review-prompt` and by the audit suite to inject adversarial
  prompts. `audit-review` is unchanged. `REVIEWER_PREAMBLE` is single-sourced
  in the engine and guarded against doc drift by a new doc-contract test.

### Added — markdown rendering in the Console
- **Prose fields render as markdown** (the description, the ask, artifact
  summaries, review findings) — the first reality-driven UI change, motivated
  by running the Console on a real store where GitHub-issue prose rendered as
  a flat wall and backtick-dense spec text was unscannable. New
  `console/static/md.js`: a self-contained GFM-subset renderer (headers,
  bold/italic, inline + fenced code, lists, tables, blockquotes, safe links).
  Structural text (titles, ids, chips, actors) stays literal. The description
  gains a **raw** toggle to the exact source bytes (principle 7).
- **Safe by construction, no dependency.** The renderer never emits
  input-derived HTML — it emits only its own tags, escapes all input at the
  leaves, and allowlists link protocols (`http`/`https`/`mailto`; drops
  `javascript:`/`data:`). No parser or sanitizer is vendored because there is
  no raw-HTML surface to sanitize (design principle 11, DESIGN §10.17).
  Security + correctness coverage in `console/static/md-test.html` (27
  browser assertions incl. XSS-inert cases); `tests/test_console.py` guards
  the wiring.
- Real content immediately caught two correctness bugs synthetic samples had
  not — underscores inside identifiers (`message_queue_consumer`) causing
  spurious italics, and loose ordered lists splitting/renumbering — both
  fixed and pinned by regression cases.

### Removed — the legacy snapshot Console
- The snapshot-driven Web UI (`console/static/app.js`, `style.css`) and the raw
  read endpoints only it used (`/api/snapshot`, `/api/task/<id>`) are gone —
  reads now go exclusively through the Projection API. Its four screen design
  docs (`docs/console/{home-screen,board-view,task-detail,graph-view}.md`) were
  removed; `design-principles.md` is kept and updated. The dependency-graph view
  was not carried into the projection UI; if wanted it returns as a product
  capability over the `edges` already in the projections, not as legacy code.

### Docs
- **`docs/ARCHITECTURE.md`** — the canonical three-layer map, with explicit
  "where does my change go?" guidance so contributors know which layer owns
  logic. **`docs/PROJECTION_API.md`** — the Projection API contract, frozen v1,
  additive-only. **`docs/RETROSPECTIVE-v0.6.0.md`** — the engineering
  retrospective for this release.

## [0.5.0] - 2026-07-22

The **Human Console** release: TaskForge gains its second client. The
engine's read API (`snapshot`) and a local web UI complete the symmetry the
architecture had been converging on — commands are the write API, snapshot
is the read API, the engine is the sole writer and sole source of derived
state, and the AI (CLI + skills) and the human (Console) are peer clients
over those contracts. No breaking changes; no new engine concepts — the one
engine addition (`snapshot`) is a projection with a stated provenance rule,
and everything else is client and method (DESIGN §10.15–§10.16).

### Added — the Human Console (`console/`)
- **A local web UI as the human actor's native seat** — the CLI + skills are
  the AI's interface; the Console is the human's, a thin peer client of the
  same engine (`python3 console/server.py`, loopback-only, stdlib-only, no
  build step). Every operation is a real engine CLI invocation in-process
  (same lock, same refusals — surfaced verbatim); writes are whitelisted to
  the human surface (`human-update`, `cancel`, `reopen`, `create`); browser
  text reaches the engine by file-input flags (DESIGN §10.16).
- **Home** — the queue of everything needing a human, by the two-clause rule
  (`blocked_on_human` OR readiness `human`), sectioned approve / answer /
  redirect from engine-fact discriminators; cycle members merge into one
  card; the empty queue is the success state. Composers: topology approval
  (proposal pre-parsed into an editable result), research disposition
  (close / spawn+close / continue), answers, redirects.
- **Task Detail** — the workspace: the artifact chain rendered as attempt
  cycles with repeated-rejection diagnosis, budget, the immutable
  description always visible, actions derived from state, related tasks,
  and the raw timeline (folded, never hidden).
- **Graph** — blocking skeleton foregrounded, provenance toggleable,
  `decision_ref` labeled with its pinned version; deterministic layout.
  **Board** — read-only readiness projection; no dragging.
- Console design records in `docs/console/` (home-screen, task-detail,
  graph-view, board-view, design-principles); screen elements justified by
  fixture states, not wireframes. Server contract enforced by
  `tests/test_console.py` (real server, real store, whitelist, injection
  safety, engine-refusal passthrough).

### Added — park-cause fixture stores
- `scripts/make_fixtures.py` stages seven self-verifying stores — one per
  way the engine can need a human, plus `quiet` — through real engine
  commands only; each asserts the state it claims, doubling as a living
  spec and as Console test data.

### Fixed — park attribution
- A skill-requested `block_on_human` recorded the `human_blocked` event with
  actor `tasks.py`, permanently misattributing who parked the task.
  `apply_signal` now passes the requesting actor through; engine enforcement
  parks (budget, breaker, cycle) remain `tasks.py` with
  `enforced_by: "engine"`. Found by the fixture-first design method before
  any UI existed.

### Added — the read model: `snapshot`
- **`tasks.py snapshot`** — one atomic, deterministic projection of the whole
  store, for clients and tooling (the read API a web UI will build on; the
  CLI and any future UI stay peer clients of the same engine). Taken under
  the existing store lock so it is never torn mid-cascade; sorted and
  byte-deterministic except `generated_at`. Every field traces to stored
  state, derived state via existing engine logic, or snapshot metadata —
  the provenance rule that governs all future additions (DESIGN §10.15).
- `edges[]` normalizes **`decision_ref` as a first-class edge** alongside the
  stored edge types, so no client needs special knowledge that one semantic
  edge is stored differently. Parked tasks carry their latest `human_blocked`
  event **verbatim** (no engine-side classification — rendering categories
  belong to clients). `skipped[]` surfaces tasks this engine cannot read
  (future-schema, unreadable) instead of silently omitting them.
- Task rows pair the frozen `readiness` routing string with a separate
  informational `readiness_detail` (same data the `readiness <id>` command
  returns, same `evaluate()` call — no new derivation).
- The snapshot shape is **public API**: frozen keys declared in
  `docs/PUBLIC_API.md`, machine-checked against the contract test, versioned
  by `snapshot_version`. Zero new engine state or derivation — a projection,
  not a concept.

## [0.4.0] - 2026-07-22

First-class **Explore**: two changes that together make Explore a stage, not
just an escalation from Refine — the human owns the *work graph* and the
decision to *stop*. The engine's conceptual surface is unchanged (no new
readiness value, stage, terminal, primitive, or stored field — only an
existing field, now initializable at intake). The line held throughout: the
engine enforces deterministic mechanics; AI reasons; humans own topology and
completion judgments. **Contains a breaking change — see Migration.** Design
rationale: DESIGN §10.13–§10.14.

### Added — first-class Explore: research entry + human disposition
- **Explore is now a first-class stage, not only an escalation from Refine.**
  A user can start with research whose deliverable is a *Decision* (which may
  or may not lead to implementation): `taskforge explore <topic>` intakes an
  ordinary task with the existing pending-explore flag set at creation
  (`create --explore`), so derived readiness routes it to `taskforge-explore`.
  No new readiness value, no new terminal, no new engine primitive, and no
  schema change beyond initializing a field — the "explicit user request"
  branch the readiness guard always named, now a real engine state
  (DESIGN §10.14).
- **The Explore protocol routes on provenance, in one explicit rule:** the
  only autonomous route is an *escalation fork whose Decision spawns no work*
  (→ refine); every other outcome parks `blocked_on_human` for the human. A
  research topic's Decision never drops into Refine on its own.
- **The human disposes a parked research Decision** with a `human-update`
  (actor `human`): **close** (`signal: done` — a decided-not-to-build task is
  a first-class `done` with a recorded Decision, via the human's review-gate
  exemption), **spawn independent work then close**, or **continue** to refine
  with the Decision binding. New `templates/explore-dispose.json`; the Hub
  renders the disposition menu. Completion meaning is the human's judgment at
  the checkpoint, never a stored task attribute.

### Changed — Explore: topology requires human approval (breaking, pre-1.0)
- **A skill may autonomously change a task's *contents*, but not the
  *topology* of the work graph** (child tasks, backlog tasks, dependency
  edges) — the new engine invariant (DESIGN §10.13), found by real use where
  Explore autonomously split an issue into children and created tangential
  backlog tasks. Reasoning and recommendation stay fully autonomous; only the
  graph-changing commit gates, and the gate is a deterministic engine
  property, never a judgment about "consequentiality."
- `capabilities.json`: `explore` loses `relations` and `edges` (it keeps
  `decision` — content). Explore now *proposes* topology — it records its
  Decision and parks the task `blocked_on_human` with the proposed
  decomposition and findings (promote / note only / ignore); the human
  commits the approved children via `human-update` (actor `human`). Existing
  primitives throughout — no new engine subsystem, no new readiness value.
- New `edges` capability dimension gates topology edge types
  (`parent`/`blocked_by`/`generated_from`), closing a pre-existing hole where
  `result.edges` were ungated for every actor. Annotation edges
  (`relates_to`) stay ungated (metadata, not topology).
- `run`'s `follow_up` behavior is deliberately **unchanged** (usage-first).

### Migration (from 0.3.0)
- **Re-install** so the engine and all four skills move together:
  `npx skills add hashirventhodi/taskforge-skills`. The breaking change is
  Explore's capabilities (it can no longer create tasks or dependency edges);
  it is enforced engine-side and skills + engine install as a set, so there is
  no partial-upgrade window.
- **Existing `.tasks/` stores are untouched.** §10.13 is a capability change
  (what an actor may commit going forward), not a storage change, and §10.14
  only *initializes* an existing field at intake — a store written by 0.3.0 is
  schema-1 and is read, routed, and continued with no migration step
  (verified). `tasks.py migrate` remains a no-op at this schema version.

## [0.3.0] - 2026-07-22

The architectural-hardening release: the four Tier 1–2 findings from the
v0.2.0 architecture review, each closed as a stated engine invariant —
durability, concurrency, compatibility, and evolution — plus a declared
public API that is deliberately *smaller* than before. See
[`docs/reviews/v0.2.0-architecture-review.md`](docs/reviews/v0.2.0-architecture-review.md).

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

[Unreleased]: https://github.com/hashirventhodi/taskforge-skills/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/hashirventhodi/taskforge-skills/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/hashirventhodi/taskforge-skills/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/hashirventhodi/taskforge-skills/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/hashirventhodi/taskforge-skills/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/hashirventhodi/taskforge-skills/releases/tag/v0.1.0
