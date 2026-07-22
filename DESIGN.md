# taskforge-skills — Design Document

A production-quality Agent Skills framework implementing the durable-Task
engineering workflow. This document is the contract for the implementation;
§10 records the critical review of the initial design and the revisions it
forced, and the rest of the document is written **post-revision** (the final
design, with revision markers ◆ where the critique changed something).

Governing principle, restated as the design test applied throughout:

> **Claude performs engineering reasoning. Deterministic mechanics never live
> in prompts.** If a rule can be enforced by code, a prompt may explain it but
> must not be its enforcement.

---

## 1. Package layout

```
taskforge-skills/
├── README.md                          install, philosophy, operations
├── DESIGN.md                          this document
├── taskforge/                         ◆ the primary entry point + shared SDK
│   ├── SKILL.md                       command-oriented: intake, queries, routing,
│   │                                  unblocking, maintenance
│   ├── CONTRACTS.md                   the architecture every skill obeys
│   ├── capabilities.json              ◆ actor → allowed artifacts/relations/signals
│   ├── scripts/
│   │   └── tasks.py                   the deterministic engine (stdlib-only)
│   ├── references/
│   │   ├── intake.md                  the `add` command's procedure
│   │   ├── reviewer-prompt.md         ◆ reusable reviewer component (moved here)
│   │   ├── reporting.md               shared end-of-skill report format
│   │   └── sync.md                    terminal sync-back instructions
│   ├── templates/                     ◆ result.json skeletons per skill/mode
│   │   ├── refine-adopt.json … run-approved.json …
│   └── tests/
│       └── test_engine.py             stdlib unittest suite for tasks.py
├── taskforge-refine/SKILL.md          ◆ prefixed names throughout
├── taskforge-explore/SKILL.md
└── taskforge-run/SKILL.md
```

Decisions:

* ◆ **All skills carry the `taskforge-` prefix.** Bare names (`run`,
  `explore`) will collide with other packages in a shared `.claude/skills/`
  directory; prefixing is free insurance for a years-long package.
* ◆ **The shared SDK is itself a skill (`taskforge`).** Its SKILL.md
  triggers on backlog/status queries ("what tasks are ready", "show the
  backlog", "task status") — real functionality, not a stub — and its
  presence makes the SDK visible to the same install/discovery mechanism as
  the skills that depend on it. A shared folder without a SKILL.md is
  invisible infrastructure that partial installs silently drop.
* ◆ **Script resolution order**, defined once in CONTRACTS.md: the
  `$TASKFORGE_SCRIPT` env var → the sibling path relative to the running
  skill → the canonical `.agents/skills/` install (project, then user) →
  agent-specific directories such as `.claude/skills/`. The sibling path is
  deliberately second: skills are always installed as siblings, so one rule
  covers every agent the `skills` CLI targets rather than enumerating
  per-agent directories forever. If none resolves, the skill stops and
  reports the missing dependency — it never improvises task state.
* **Task store**: `.tasks/` at repo root (override `TASKFORGE_DIR`). One JSON
  file per task; `audit/` subfolder for recorded reviewer prompts; `config.json`
  for settings.
  ◆ **Store vs. branches (M3 finding, §10.10):** task state is *workflow*
  state, orthogonal to code branches — Run implements on an isolated branch
  while the engine keeps writing task state, so the store must never be
  swept into feature-branch commits or block checkouts. The engine therefore
  makes the store **self-ignoring by default**: on first use it writes
  `.tasks/.gitignore` containing `*` (the `.git`/`.terraform` pattern).
  Teams that want task history in git delete that file and commit `.tasks/`
  from the trunk line only; the event history inside each task remains the
  authoritative record either way.

## 2. Shared SDK contents

| Component | Location | Consumed by |
|---|---|---|
| Terminology + task/edge/artifact/readiness/cascade rules | `CONTRACTS.md` | all skills (read once per session) |
| Task/Artifact/Result JSON schemas | `CONTRACTS.md` (prose) + `tasks.py validate` (executable) | skills author against prose; script enforces |
| Relationship definitions | `CONTRACTS.md` + script constants | both |
| Capability matrix | `capabilities.json` | script (enforcement), CONTRACTS (documentation) |
| Readiness + cascade rules | script only (single implementation) | skills query, never re-derive |
| Common prompt sections (readiness guard, reporting, sync) | `references/reporting.md`, `references/sync.md` | all skills reference, none duplicate |
| Reviewer template | `references/reviewer-prompt.md` | taskforge-run today; any future reviewing skill |
| Validation helpers | `tasks.py validate` subcommand | all skills, pre-apply |
| Output templates | `templates/*.json` | skills copy-and-fill instead of free-composing JSON |

The duplication rule: **if two SKILL.md files would state the same rule, the
rule moves to CONTRACTS.md or a reference file and both point at it.** Skills
contain only what is unique to them: their mode logic, their quality bar,
their specific failure handling.

## 3. The deterministic engine (`tasks.py` + `engine/`)

Stdlib-only, importable (unit tests import the API directly) and runnable as
a CLI. ◆ The engine is a **package with a stable facade**, not a monolith
(revised in review round 2 — see §10.9): `scripts/tasks.py` is the public
entry point skills resolve and invoke, and it re-exports the module API;
the implementation lives in `scripts/engine/`, decomposed along the
dependency DAG:

```
engine/model.py       pure domain: constants, task/artifact/edge helpers (no IO)
engine/store.py       filesystem: task files, atomic writes, lock, config, capabilities
engine/readiness.py   derived readiness + cycle detection
engine/validation.py  boundary validation: results, payloads, capabilities, coherence
engine/apply.py       the application pipeline: cascades, relations, signals, wake
engine/audit.py       reviewer-isolation audit, doctor, migrate
engine/cli.py         argument parsing and dispatch (no workflow logic)
```

"Single deterministic engine" is a **process property** — one entry point,
one writer of task state — not a file-count property. The facade keeps the
invocation path and API stable; the package keeps a years-long codebase
reviewable, with module boundaries that make dependency direction explicit
(model at the bottom, cli at the top, no cycles).

**Sole responsibilities** (and the only writer of `.tasks/`):
apply results · assign artifact versions · supersede predecessors · run
invalidation cascades (including cross-task decision_ref staleness) · wire
relationship edges per relation type · derive readiness (with cycle
detection) · record events *with* their changes · validate everything at the
boundary · enforce budgets and invariants (§3.2) · terminal wake-ups.

### 3.1 Command surface

```
create / show / list [--readiness R] / readiness / blocked-by
budget ID                                  ◆ retry budget + next_review_version
validate RESULT --actor A [--task ID]     ◆ two-phase: check without writing
apply ID RESULT --actor A                  validate, then apply atomically
human-update ID --note N [RESULT] / cancel ID --reason R
reopen ID --reason R                       ◆ restore a closed terminal (§10)
config                                     ◆ print effective configuration
record-review-prompt ID --version N FILE   ◆ store reviewer prompt for audit
audit-review ID                            ◆ verify recorded prompts (§6)
doctor                                     ◆ store integrity check
migrate                                    ◆ schema_version upgrades (v1: no-op)
```

All output is JSON on stdout; errors are JSON on stderr with exit code 1 —
machine-legible for the skill, greppable for the human.

### 3.2 Invariants enforced in code, not prompts ◆

The critique (§10) found several rules the prototype left as prompt
instructions that are actually deterministic. Moved into the script:

1. **Capability enforcement.** `capabilities.json` maps each actor to allowed
   artifact kinds, relations, and signals. `apply --actor refine` with an
   implementation artifact is rejected. Unknown actors are denied by default;
   enabling a new skill is a data edit, not a code edit (§9).
2. **Retry-budget enforcement.** When a rejected review with root_cause
   `implementation` makes the current-cycle rejection count exceed
   `max_review_retries`, the script itself parks the task
   (`blocked_on_human`, reason: budget exhausted). The Run skill still
   *narrates* the budget; the script *guarantees* it.
3. **Verdict/signal coherence.** `signal: done` is rejected unless the active
   review is `approved`. A model cannot talk a task into done.
   *Implementation note (deviation found by tests):* the rule binds
   capability-constrained actors only; the universal `human` actor is exempt,
   because humans legitimately close review-less tasks (e.g. answering a
   clarification prerequisite). The exemption is auditable — the closing
   event carries `actor: human`.
4. **Idempotent application.** A result may carry a `result_id` (skills are
   instructed to generate one, templates include the field); applied ids are
   recorded on the task and duplicates are acknowledged as no-ops. Protects
   against the double-apply-after-timeout failure mode.
   *Implementation note (bug found by CLI verification):* the duplicate
   check runs **before** validation, because a retry of a result whose first
   application made the task terminal must get the no-op, not the
   terminal-task guard error — retry-after-timeout is precisely the scenario
   this mechanism exists for.
5. **Concurrency lock.** `.tasks/.lock` (O_EXCL, pid+timestamp, stale after
   60s) around every mutating command. Two Claude sessions in one repo can't
   interleave a cascade. Breaking a *stale* lock (crash recovery) is
   serialized through a second O_EXCL gate so only one session may attempt
   recovery and it re-verifies staleness before removing anything — see
   §10.11.
6. Everything the prototype already enforced: canonical edges (inverse names
   rejected with a pointer to the canonical form), payload validation,
   version circuit breaker (kind reaching v4 → blocked_on_human), self-edge
   rejection, cascade order, pinned decision_ref staleness flagging,
   child→parent escalation propagation.

### 3.3 Application order (unchanged from the validated engine)

artifacts → generated tasks → annotation edges → signal → recompute
readiness → persist → wake tasks blocked by a closed task. Events are
written with their changes; the history is the recovery record for any
partial multi-task application (per-task writes are atomic tmp+rename;
cross-task consistency is deliberately the event log's job).

## 4. Configuration

`.tasks/config.json`, created on first `create`, read by every command;
environment variables win over file values:

```json
{ "max_review_retries": 2, "max_artifact_versions": 4, "schema_version": 1 }
```

Two knobs exist because two behaviors demand them; the file exists so a
years-long installation has one obvious place for future knobs. `tasks.py
config` prints the effective merged configuration so skills and humans never
guess.

## 5. Skill contracts

Common to all four (defined once in CONTRACTS.md, referenced by each):
readiness guard first; read binding context (immutable description,
decision_ref, relevant history); reason; fill a template into `result.json`
with a fresh `result_id`; `validate` then `apply`; report per
`references/reporting.md`; sync-back per `references/sync.md` when terminal;
**stop** — never auto-execute generated tasks or chain skills unasked.

| | taskforge (`add`) | taskforge-refine | taskforge-explore | taskforge-run |
|---|---|---|---|---|
| **Purpose** | normalize any source into a Task | universal entry: produce the Specification or route | produce a Decision; decompose when size demands | implement the spec; independent review; finish or escalate |
| **Inputs** | source content (user text, issue via MCP/CLI, file) | task (description, decision_ref/decision, escalation history) | task (description, escalation reasons, superseded decisions, existing children, codebase) | task (active spec = whole contract), codebase |
| **Outputs** | new Task(s), stated-relationship edges | spec artifact, or prerequisite tasks, or escalation | decision artifact, child/follow-up tasks, or block_on_human | implementation + review artifacts, follow-ups, terminal signal |
| **Readiness guard** | n/a (creates tasks) | `refine` | `explore` (or explicit user request, confirmed) | `run` |
| **Allowed artifacts** ◆ | — | specification | decision | implementation, review |
| **Allowed relations** ◆ | follow_up | prerequisite, follow_up | child, follow_up | follow_up |
| **Allowed signals** ◆ | none | none, escalate_explore, block_on_human | none, block_on_human | none, done, escalate_refine, escalate_explore, block_on_human |
| **Internal workflow** | fetch → normalize (verbatim description) → create → stated edges → report | gather context → mode decision (adopt ▸ elaborate ▸ clarify ▸ escalate, first match) → result | read escalation question → investigate codebase → decide (alternatives/trade-offs/risks) → optional decompose → result | plan → implement on isolated branch → test → fresh-context review → route on verdict (retry ≤ budget / escalate) |
| **Failure handling** | source unreachable → stop, name the missing access | can't validate result → fix result, never hand-edit store | no real alternatives → say so; decision not ours → block_on_human | subagent unavailable → stop honestly; malformed review → one re-ask (§6) |
| **Escalation** | never | → explore (approach fork), → human (via clarify prerequisites) | → human only | → refine (spec defect), → explore (approach defect; parents notified by script), → human (budget/permissions) |
| **Quality checks** | description verbatim vs source; no refinement leakage | adopt-not-inflate (spec ≤ description-scale); criteria independently verifiable; re-refines address rejection reasons | escalation question explicitly answered; falsifiable rejection reasons; children stand alone | diff contains nothing the spec didn't ask; criteria all in criteria_results; recorded review verbatim |
| **Required references** | CONTRACTS, reporting, sync | CONTRACTS, reporting, templates | CONTRACTS, reporting, templates | CONTRACTS, reporting, sync, reviewer-prompt, templates |

Prompts are written only after this table is stable; each SKILL.md is the
prose realization of its column plus its unique judgment guidance.

## 6. The reviewer as a reusable component

Lives in `taskforge/references/reviewer-prompt.md` because it is a
workflow asset, not a Run implementation detail.

* **Input contract**: exactly three slots — Specification (active version,
  verbatim JSON), diff (full content), test results. The template forbids
  additions in its own text.
* **Isolation requirements**: fresh-context subagent (Claude Code Task tool);
  no implementer narrative, plan, reasoning, or chat history may enter the
  prompt. If no fresh context is available, the skill stops and says so —
  a self-review is never recorded as a Review.
* **Output contract**: strict JSON — verdict, criteria_results (every
  acceptance criterion, explicit pass/fail), findings, root_cause (required
  iff rejected).
* **Retry policy (of the reviewer itself)** ◆: malformed output → exactly one
  re-ask containing the validation error and the schema; still malformed →
  treat as review-system failure: `block_on_human` with the raw output
  attached in `signal_reason`. Never guess a verdict, never downgrade to
  self-review.
* **Verifiable isolation** ◆ (the critique's biggest find): before spawning
  the reviewer, Run must register the exact prompt via
  `record-review-prompt <id> --version N <file>`; the script stores it under
  `.tasks/audit/` with a hash event. `audit-review <id>` then checks
  deterministically, per review version: the recorded prompt **contains the
  spec's acceptance criteria verbatim** and **does not contain that
  implementation's `summary` text**. Isolation moves from "trust the prompt"
  to "audit the artifact" — the strongest guarantee available without a
  process boundary, and the residual gap (a skill could skip recording) is
  itself detectable: reviews without recorded prompts are flagged by both
  `audit-review` and `doctor`.

## 7. Testing strategy

Three layers, matching the two kinds of failure (mechanics vs judgment):

1. **Unit tests of the engine** (`taskforge/tests/test_engine.py`,
   stdlib `unittest` — the framework stays dependency-free even in tests;
   the module is imported directly, no subprocess). Coverage map:
   versioning + supersession-reason placement · cascade correctness
   (decision→spec→impl→review; escalations; decision_ref staleness across
   tasks) · readiness transitions (full rule table, incl. terminal
   precedence and pending escalation) · relationship integrity (canonical
   enforcement, relation wiring, idempotent edges, self-edge rejection) ·
   cycle detection (direct, transitive, diamond-is-not-a-cycle) · blocking
   and wake (done/cancel wake; blocked_on_human doesn't) · retry budgets
   (derivation from events + in-script enforcement) · capability
   enforcement · verdict/signal coherence · result idempotency · circuit
   breaker · config/env precedence · lock behavior · doctor findings.
2. **End-to-end lifecycle tests** (same suite, integration section): the
   adopt→run→done→wake happy path; escalate→decide→decompose→children→parent
   completion; clarify→block→human-answer→resume; budget
   exhaustion→park→human-update→resume — each asserting the full event trail.
3. **Judgment evaluation** (not unit-testable; designed as a benchmark
   protocol in README): the ten-mixed-quality-task trial with the criteria we
   fixed earlier — adoption without inflation (weighted toward *well-written*
   inputs, the likely failure), elaboration executable cold, escalation on
   genuine forks only, clarify wiring provably resumes, plus reviewer-prompt
   spot-checks now backed by `audit-review`. Run via `claude -p` per the
   skill-creator methodology when iterating on prompt text.

CI story: `python3 -m unittest discover taskforge/tests` — zero
dependencies, runs anywhere the script runs.

## 8. Documentation set

`README.md` (install, resolution order, operations: list/doctor/audit,
judgment-trial protocol) · `CONTRACTS.md` (the architecture, single source)
· `DESIGN.md` (this) · per-skill SKILL.md (unique judgment only) ·
reference files (shared prose). No document states a rule another document
owns; each points instead.

## 9. Extensibility

Adding a skill (e.g. `taskforge-estimate`, `taskforge-postmortem`) without
touching existing components:

1. create `taskforge-<name>/SKILL.md` following the §5 common contract;
2. add its actor entry to `capabilities.json` (data, not code — deny-by-default
   makes the matrix the single gate);
3. optionally add templates under `taskforge/templates/`.

Extension points designed in: annotation edge types are free-form today;
new *relations* or *artifact kinds* are engine changes by design (they carry
cascade/readiness semantics — cheap to add in one file, and `schema_version`
+ `migrate` exist so stored tasks survive the evolution); readiness rules
live in exactly one function; new terminal-sync targets are prose additions
to `references/sync.md`; a future orchestrator drives `list --readiness` +
skill invocations with zero skill changes.

**Schema evolution.** `schema_version` + `migrate` let a newer engine upgrade
older stores; directional compatibility (§10.12) governs the reverse. When the
first real (field-rewriting) migration lands, it **must append a `migrated`
event via `record()`**, not a bare `store.save()`, so a task's own history
shows that its shape changed — the same "every state change is a recorded
event" rule the rest of the engine follows. The mechanism is deferred until
that first migration exists (v1's `migrate` is a no-op bump); the invariant is
stated here so it lands with the migration rather than being retrofitted.

Non-goals, restated so future extension doesn't drift: no daemon, no queue,
no GitHub/Jira code, no auto-execution of generated tasks.

## 10. Critical review of the initial design, and what it changed

Weaknesses found by adversarial pass over the v0 prototype + first draft:

1. **Fragile shared-path coupling.** `../taskforge-shared` breaks under
   partial installs or path differences between project/user scopes.
   → shared SDK became a *skill* (now `taskforge`); explicit resolution
   order; skills stop rather than improvise. (§1)
2. **Skill-name collisions.** `run` is near-guaranteed to collide.
   → `taskforge-` prefix everywhere. (§1)
3. **Prompt-enforced rules that are actually deterministic.** Budget
   counting, "done requires approval", and which-skill-may-emit-what were
   instructions. An instruction is a request; production needed guarantees.
   → capability matrix, in-script budget enforcement, verdict/signal
   coherence. (§3.2) This is the same lesson as the engine/skill split,
   applied one level deeper.
4. **Unverifiable reviewer isolation** — the honest limitation I flagged when
   delivering v0. → recorded prompts + deterministic `audit-review`;
   unrecorded reviews are themselves flagged. Residual risk documented. (§6)
5. **Double-apply and concurrent-session corruption.** LLM retries after a
   timeout would duplicate artifact versions; two sessions could interleave.
   → `result_id` idempotency + store lock. (§3.2)
6. **Malformed result.json discovered only at apply time.** → templates to
   fill instead of JSON to freestyle, plus a `validate` subcommand so skills
   self-check before mutating anything. (§2, §3.1)
7. **No schema evolution story** for a package meant to live years.
   → `schema_version` + `migrate` scaffold, no-op at v1. (§3.1, §9)
8. **No integrity tooling** for a store that humans will also touch.
   → `doctor` (dangling edges, unresolvable decision_refs, cycles, parse
   failures, unaudited reviews). (§3.1)

Reviewed and deliberately **kept** despite critique: JSON-per-task store
(scan-based reverse views are fine to thousands of tasks; an index is a
future store swap, not a schema change); prompt-level judgment untested in
CI (that's what the benchmark protocol is for — pretending unit tests cover
judgment would be false comfort); no plugin loader (capabilities.json *is*
the registry).

9. ◆ **Review round 2 (external): the one-file engine was overturned.**
   The first critique kept `tasks.py` as a single file, arguing two files
   would "complicate resolution." That reasoning conflated the architectural
   requirement (a single deterministic engine: one entry point, one writer,
   one resolution path) with an incidental file-count choice — and the
   resolution argument dissolves once the resolved path is a thin facade.
   At a years-long horizon the monolith's costs are real: twelve
   responsibilities accreting in one ~1000-line file, unreviewable diffs,
   and implicit module boundaries free to drift. Revised per §3: a
   `scripts/engine/` package decomposed along the dependency DAG, with
   `scripts/tasks.py` as the stable facade re-exporting the API. The
   refactor's acceptance test: the invocation path in every SKILL.md and
   CONTRACTS.md unchanged, and the existing engine test suite passing
   **unmodified** against the facade. Both held.

10. ◆ **M3 (real-task validation): the store/branch collision.** Running the
    workflow on a real repo exposed it within one task: Run's isolated
    branch committed `.tasks/` (a natural `git add -A`), and the engine's
    post-apply write then blocked `git checkout main`. Root cause: the
    design said "git-friendly" without deciding whose history the store
    belongs to. Decision (see §1): task state is workflow state, orthogonal
    to code branches; the store is self-ignoring by default via an
    engine-written `.tasks/.gitignore` (`*`), with tracked-from-trunk as the
    documented opt-in. Deterministic, backwards compatible, and enforced by
    the engine rather than instructed to skills.

11. ◆ **M3 friction: reviewer version discovery.** The reviewer protocol
    needs "next review version" before recording a prompt; obtaining it
    required parsing full `show` output — error-prone for a skill. `budget`
    (already the pre-review status command) now also reports
    `total_reviews` and `next_review_version`. Additive, backwards
    compatible.

---

*Implementation follows this document. Any deviation discovered during
implementation gets recorded here, not silently absorbed.*

### v0.2 restructuring (recorded after release)

**Intake merged into a command-oriented `taskforge` skill; `taskforge-core`
renamed; `taskforge-add-task` removed.** Two forces drove it: intake is a
procedure, not a judgment domain — it shares no artifact kinds with the
workflow skills (its actor could emit only `follow_up` edges) and its
"never editorialize" rule is a management concern, the same family as
querying and unblocking; and the package needed one obvious front door.
The main skill is now organized as a command table (`add`, `status`,
`backlog`, `next`, `show`, `why`, `unblock`, `cancel`, `sync`, `doctor`,
`audit`, `config`) with the intake procedure as a reference
(`references/intake.md`) loaded only when `add` runs — the same progressive
disclosure already used for the reviewer and sync-back. The single-writer
engine, capability matrix (actor `add-task` → `taskforge`), and the three
single-responsibility workflow skills are unchanged. Overturned from the
initial design: "add-task is a separate skill" — separateness bought
nothing once the entry point had to exist anyway.

### v0.2 — reopen: closed terminals become reversible

**`done` and `cancelled` gained a `reopen` path; `blocked_on_human` did
not.** The original model had three terminal statuses and no way back from
any closed one — a wrongly-cancelled or to-be-extended task was a dead end,
which contradicts the durability premise (work is supposed to survive). The
fix is unusually small because the architecture already carried it: reopen
touches **no** artifacts. Supersession only sets flags, history is
append-only, and there are no scratch lifecycle fields to clear (the close
reason lives in an immutable event) — so reopen is a status transition plus
a recorded event, and routing is **derived** by `refresh_status` from the
task's existing artifacts, not assigned. This is the derived-readiness
design paying off: the engine doesn't decide where a reopened task goes; its
artifacts do.

Two decisions worth recording:

* **`blocked_on_human` is excluded.** It is a *park* awaiting a human answer,
  not a closed terminal; it already had the right resurrection path
  (`human-update`, which captures that answer). Folding it into reopen would
  bypass the answer capture. `CLOSED = {done, cancelled}` (which release
  blockers) turned out to be exactly the reopenable set — the distinction the
  code already drew for a different reason.
* **Reopening re-blocks still-active dependents, for free.** `blocked_by`
  edges persist through a close and readiness derives blocker-openness live,
  so a reopened blocker flips its still-active waiters back to `waiting` with
  no bespoke logic — the same `refresh_dependents` pass that wakes them on
  close (renamed from `wake_blocked_by`, now symmetric: `unblocked` on close,
  `reblocked` on reopen). Terminal dependents are untouched (terminal wins in
  readiness) — a finished task does not un-finish because an upstream task
  reopened.

### v0.2.x — circuit-breaker authority is over routing, not declared work

**Fixes the silent data-loss bug found in the v0.2.0 architecture review
(T1-1).** When an artifact tripped a circuit breaker (version breaker or
review budget) mid-apply, `apply_result` parked the task and then skipped the
result's `generated_tasks`, `edges`, **and** `signal` in one guard — while
still recording `result_id`. The follow-up tasks and edges were silently
dropped and made unrecoverable by the idempotency no-op. In the realistic
case (Run records an out-of-scope follow-up in the same result as a review
that exhausts the budget), the out-of-scope discovery vanished — directly
violating the scope-discipline rule that such findings must never be lost.

The root cause was a conflation: the guard suppressed three unlike things
together. The breaker's authority is over **routing** — it exists to overrule
a skill's `done`/`escalate` when the engine has decided iteration isn't
converging. It has no authority over the skill's **declared work**: generated
tasks and edges are durable facts discovered during execution, independent of
whether this task may keep iterating, and they stay coherent on a parked task
(a generated prerequisite's `blocked_by` edge is ignored by readiness while
parked and honored on unpark). So the fix suppresses the **signal only**;
tasks and edges always apply. The result is therefore still *fully* applied,
so `result_id` is recorded and a retry no-ops cleanly.

Recorded as a first-class invariant in CONTRACTS ("Circuit-breaker
authority"), not merely an implementation detail: *a breaker may override
where a task goes; it may never make declared work disappear.*

Two honesty refinements landed with it: an engine override of a requested
signal is recorded as a `signal_overridden` event (the history must answer
what the skill requested, what the engine did, and why), and `apply_result`
returns the authoritative signal (`none` when suppressed) rather than the
intent, so the engine's own output never contradicts the task's status.

**Rejected alternative:** withholding `result_id` on a mid-artifact park so a
re-apply could "finish" the dropped work. There is no per-section
idempotency, so re-applying the same result would add a *duplicate* artifact
version, re-trip the breaker, and loop — and it would introduce
partial-application state the engine has deliberately avoided. Option A
(above) keeps every apply atomic, durable, and idempotent.

### v0.2.x — §10.11 stale-lock recovery is serialized, not racy (T1-2)

**Fixes the TOCTOU race found in the v0.2.0 architecture review.** The store
lock's happy path (a single `O_EXCL` create) was always correct; the defect
was in *breaking a stale lock* left by a crashed session. The old code read
the timestamp, judged it stale, and `unlink`-ed the path unconditionally —
a read-decide-remove gap in which a second session could break the same
stale lock and acquire a fresh one, only to have the first session's late
`unlink` delete that fresh lock. Both would then believe they held it,
defeating the mutual-exclusion guarantee the lock exists to provide (§3.2.5).

The fix composes the primitive we already trust rather than adding a new one:
a stale break must first acquire a second `O_EXCL` gate (`.lock.break`), so
only one session may attempt recovery at a time, and under that gate it
**re-verifies staleness** before removing anything. Correctness rests on one
invariant — *while a stale `.lock` exists, `O_EXCL` blocks any fresh holder*
— so a lock still stale when the sole breaker re-checks it has nothing live
beneath it, and a fresh lock reads non-stale and is left untouched. The model
moved from "anyone may decide to break" to "only one session may even attempt
to break, and only after re-confirming."

**Design rule (binding):** the break gate is *not* a second lock. It exists
solely to serialize stale-lock recovery and never participates in normal
acquisition — visible in the code as the private `_break_if_stale` helper,
separate from `__enter__`'s acquire path.

**Rejected alternatives**, each against TaskForge's portability + shared-store
model: `os.rename` steal (rename-replace is last-writer-wins — no mutual
exclusion — and a path-based move has the same TOCTOU as unlink); PID-liveness
via `os.kill(pid, 0)` (POSIX-only, and meaningless for the git-tracked
cross-machine store of §10.10); `fcntl`/`flock` (POSIX-only, broken on NFS);
hardlink arbiters (new filesystem dependency + hairy restore races). The
chosen design keeps the exact portability envelope of the original — only
`O_EXCL` + `unlink`, no new filesystem assumption.

**Accepted tradeoff:** the gate is deliberately *not* itself stale-broken —
recursively stale-breaking the stale-breaker would reintroduce the race. If a
session crashes in the microsecond it holds the gate (far rarer than crashing
mid-cascade with the main lock), auto-recovery stops and acquisition raises
the "delete the lock if stale" error naming both files. Safety (mutual
exclusion) is never sacrificed; only liveness degrades to manual recovery in
that near-impossible case — the right trade for a durability-first engine.

### v0.2.x — the public contract is declared, and made smaller first (T2-3)

**Establishes `docs/PUBLIC_API.md` — the smallest stable surface necessary
for interoperability — before the version number promises anything.** The
review found the public boundary undeclared (the facade docstring even called
itself "the engine's public interface") and the surface skills actually
depend on — JSON output field names — untested. The work was less "write down
what exists" than "decide what deserves to be public at all."

The contract is driven by an audit of *actual* consumers: every frozen
element has an identified reader (skills route on the `readiness` value;
`reviewer-prompt.md` reads `next_review_version`; `reporting.md` reads apply's
`status`/`readiness`/`generated_tasks`; the hub reads `list` rows,
`blocked-by`, `doctor.clean`). Everything with no consumer stays internal:
the Python facade, storage layout, diagnostic/informational fields, and the
`summary()` convenience projection. A field that no consumer reads is not part
of the compatibility burden, however long it has existed.

Two pre-freeze redesigns rather than freezing cruft:

* **Removed `validate.valid`.** It was structurally always `true` (any real
  invalidity raises → exit 1 + `{error}` on stderr), so it carried no
  information and had no consumer. Validity is now the exit code; `warnings[]`
  carries non-fatal observations — consistent with every other command.
* **Unified `readiness` to the routing string.** It was a bare string in
  `list`/`readiness` but the full `evaluate()` dict in `summary()`/apply
  output — the same key with two shapes, ambiguous before it was even
  published. `readiness` now means the routing string everywhere; the
  diagnostic detail (`reason`/`blocking_ids`/`cycle`) lives only on the
  dedicated `readiness` command, where `why` already reads it.

Enforced by `TestPublicOutputContract` (presence-and-type, tolerant of extra
keys — an internal key may be added freely; removing/renaming a frozen key or
changing the routing vocabulary fails loudly), and a lightweight both-ways
doc-contract guard keeps the declaration and the enforcement from diverging —
the same pattern as command-table↔engine and license↔validator. `CONTRACTS.md`
was deliberately left lean: it answers "how does the engine behave"
(skill-runtime); `PUBLIC_API.md` answers "what won't we break" (maintainers +
tooling) — different audiences, different documents.

### v0.2.x — §10.12 directional schema compatibility (T2-4)

**Closes the last v0.2.0-review blocker: how an engine behaves when it meets
data from a newer version of itself.** The `schema_version` guard existed on
the single-task `load()` path but not on the whole-store scan (`all_tasks`),
so `list`/`blocked-by` could misroute on a newer task and — the real hazard —
the cross-task cascades (`refresh_dependents`, `flag_stale_decision_refs`)
could `refresh_status` + `save` a newer-schema *dependent*, silently rewriting
it as if it were old. In the git-tracked cross-machine store the design
supports (§10.10), an older machine could corrupt a newer machine's tasks.

The rule, stated once:

> **Schema compatibility is directional.** An engine may safely read and
> migrate data from older schema versions. It must never interpret, mutate,
> or route on data from newer schema versions. Future-schema tasks are
> therefore invisible to operational scans and visible only to diagnostics
> until an appropriate engine version is used.

Everything follows from that one rule, which is why the design collapses to
three interaction categories, each with one policy point:

* **Single-task access** (`load`) — fail closed with an actionable upgrade
  error. Report-by-refusal; never mutates. `find()` already downgrades the
  refusal to `None`, so a current task blocked by a future one routes to
  `waiting` (can't confirm the blocker resolved → stay blocked).
* **Store-wide scans** (`all_tasks`) — skip future-schema tasks. This is a
  *store-level* guarantee, not a caller convention: `all_tasks()` now yields
  "every task this engine can safely reason about", so listing, routing,
  cross-task cascades, and migration all inherit the rule and no future scan
  author has to remember it. The single predicate is `store.is_future`.
* **Whole-store diagnostics** (`doctor`) — read the raw store, report each
  future-schema task as a finding (never mutate), and skip structural
  validation of data this engine can't interpret. `doctor` is the one place
  their existence surfaces; `list` deliberately stays an operational view of
  what the engine can act on (keeping the frozen `readiness` vocabulary clean
  — see §10 T2-3).

The load-bearing test is not "doctor prints a finding" but *a current engine
never mutates the bytes of a future-schema task*; every other behavior
follows from that invariant holding. The migration-event mechanism (§9) is
deferred until a real migration needs it — machinery built before its first
use is machinery built wrong.

This completes the four architectural-hardening invariants the v0.2.0 review
set out: **#1 durability** (a breaker overrides routing, never discards
declared work), **#2 concurrency** (only one session may attempt stale
recovery, and only after re-confirming), **#3 compatibility** (the public
surface is the CLI; internal structure is free to change), and **#4
evolution** (an engine never mutates or routes on data from a newer version
of itself).

### v0.3.x — §10.13 topology requires human approval (Explore)

**Found by real use (a GitHub issue explored autonomously): Explore chose an
approach, split the issue into children, and created backlog tasks for
unrelated discoveries — all committed with no human in the loop.** Every
piece was correct; the problem was *autonomous commitment of consequential
state*, at the one artifact with no independent gate. An implementation
cannot reach `done` without a review; a Decision — higher leverage, since it
binds children and shapes scope — had none.

The rule, stated so a contributor can reason from it:

> **A skill may autonomously change a task's *contents*. It may not
> autonomously change the *topology* of the work graph** — creating child
> tasks, creating backlog tasks, or adding a dependency edge.

The critical design move was **what to gate on**. The first instinct — "gate
when Explore judges the decision consequential / multi-option" — puts the
producer back in charge of deciding whether its own output needs review, the
self-grading pattern the engine exists to remove, at the one point with no
backstop. So we gate on a **deterministic, engine-verifiable property**
(does the outcome create tasks or dependency edges?), never on judgment.
Reasoning and recommendation stay fully autonomous; only the graph-changing
commit gates.

Enforcement is the capability matrix, not a prompt: `explore` loses
`relations` (no task creation) and `edges` (no dependency edges), keeping
`decision` (content). A pre-existing hole surfaced — `result.edges` were
ungated for *every* actor — so an `edges` capability dimension was added,
gating the topology edge types (`SEMANTIC_EDGES`) while leaving annotation
edges (`relates_to`) free. Explore now *proposes* topology: it records its
Decision (content) and parks the task `blocked_on_human` with the proposal;
the human commits the approved children/findings via `human-update` (actor
`human`). Every mechanic already existed — `block_on_human`, `human-update`,
`materialize`, `decision_ref` — so this is a data edit + a protocol, not a new
subsystem. No new readiness value; the Hub distinguishes "awaiting approval"
from "blocked on an answer" by the block's detail (presentation only).

**Accepted residual risk:** a *self-contained* decision (changes only this
task, no topology) still commits autonomously. Its blast radius is one task
and the normal workflow (refine, review, re-exploration) can correct it —
qualitatively different from a graph change, which creates durable work for
other tasks and people. **Deferred (usage-first):** `run` also auto-creates
`follow_up` tasks; those are discovered while completing an already-approved
task and don't restructure the graph under execution, so the same rule is
*not* extended to `run` yet — we gather evidence before making every rule
symmetric.

**Independent corroboration:** the frozen `squad-skills` package reached the
same boundary from the opposite direction — its explore saves the report
autonomously but gates *task creation* behind an explicit human choice
("save report only, don't create tasks"). Two independently designed systems
drew the same line (AI owns investigation + recommendation; humans own the
work graph), which raised confidence this is an abstraction, not an
invention. Where TaskForge differs — and is stronger for its philosophy — is
mechanism: Squad gates by a synchronous prompt convention (`AskUserQuestion`,
no engine to enforce it); TaskForge gates by a durable, engine-enforced
capability (`block_on_human` + deny-by-default), so the boundary holds
whether or not a human is in the session and whatever a model chooses to do.
