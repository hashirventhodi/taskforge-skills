# taskforge-skills — Engineering Handoff

**To:** the next owner (a fresh Claude Code session or human engineer)
**Scope:** everything needed to continue this project without access to prior discussions.
**Package:** `taskforge-skills/` (this document lives at its root). Companion validation repo: `demo-wordstats/`.

---

## 1. Executive Summary

**taskforge is an Agent Skills framework that implements an AI engineering workflow.** It is not an application, daemon, or orchestrator. It is a set of five skills plus a deterministic engine that can be dropped into any repository, under which every piece of engineering work becomes a durable **Task** that moves through the workflow by **derived readiness** rather than by a controller.

**The problem it solves.** LLM-driven engineering fails in characteristic ways: work evaporates when a session ends; scope silently expands mid-implementation; specifications get invented, inflated, or ignored; the same model that wrote the code grades the code; and state transitions (versioning, invalidation, blocking) get "remembered" inconsistently by a probabilistic system. taskforge makes work durable, scope-disciplined, independently reviewed, and mechanically consistent.

**The philosophy, which governs every component:**

> Claude performs engineering reasoning. Deterministic mechanics never live in prompts. If a rule can be enforced by code, a prompt may explain it but must not be its enforcement.

**Why the architecture looks the way it does.** Skills (prompts) hold judgment: is this task executable? what approach? does this diff satisfy the spec? The engine (a stdlib-only Python package behind a stable `tasks.py` facade) is the **only writer of task state**: skills emit a `result.json`, and the engine validates and applies it — versioning artifacts, superseding predecessors, running invalidation cascades, wiring typed relationships, deriving readiness, enforcing capabilities and budgets, recording events. There is no orchestrator: readiness is computed from each task's own state, every skill guards on it before acting and stops after reporting, so the workflow composes without a controller and a future orchestration layer could drive it without changing any skill.

The four workflow skills: **add-task** (normalize any source into a Task with a verbatim, immutable description), **refine** (the universal entry point — adopt / elaborate / clarify / escalate), **explore** (engineering Decisions, optional decomposition into children; reachable only by explicit escalation), **run** (implement against the active specification, then an independent fresh-context review whose prompt is recorded and mechanically auditable). A fifth skill, **taskforge-core**, is the shared SDK made visible to the install mechanism, and answers backlog/status/health queries.

---

## 2. Current State

### Implemented and verified (not merely designed)

| Area | State | Evidence |
|---|---|---|
| Design document | Complete, includes critique history | `DESIGN.md` (§10 records three review rounds, incl. overturned decisions) |
| Engine | Complete | `taskforge-core/scripts/engine/` — 7 modules, ~1,050 lines, stdlib-only; `tasks.py` facade |
| Engine test suite | **42/42 passing** | `taskforge-core/tests/test_engine.py`, stdlib unittest, no dependencies |
| Skills (5 × SKILL.md) | Complete prompts + frontmatter | `taskforge-{core,add-task,refine,explore,run}/SKILL.md` |
| Shared SDK | Complete | `CONTRACTS.md`, `capabilities.json`, `references/` (reviewer, reporting, sync), `templates/` (7 result skeletons) |
| Documentation | Complete | `README.md`, `DESIGN.md`, this handoff, `examples/walkthrough-m3.md` |
| Real-task validation (M3) | Complete, findings fed back design-first | walkthrough + `demo-wordstats` repo: full adopt→run→review→done cycle on a real codebase, audit-review and doctor clean |

### Milestones

- **M1 — Deterministic engine + tests: DONE.**
- **M2 — Skills + shared SDK: DONE.**
- **M3 — Real-task validation: DONE** (produced two design changes, §10.10–11).
- **M4 — Judgment benchmark: NOT STARTED.** Requires real Claude Code sessions (skill triggering, Task-tool reviewer). This is the next milestone — see §9.
- **M5 — Extension proof: NOT STARTED.** Add a fifth workflow skill purely via documented extension points.

### Designed but NOT implemented/validated

- **Skill triggering**: the frontmatter descriptions follow best practice ("pushy", trigger-phrase-rich) but have never been tested against real Claude Code skill selection.
- **Reviewer isolation via the Task tool**: the protocol and audit exist; a real fresh-context subagent has never executed a review (M3's reviewer was the same session, declared as a deviation).
- **Terminal sync-back**: exists as instructions (`references/sync.md`) with an honesty rule; never exercised against a real GitHub/Jira tracker.
- **`migrate`**: scaffold only; schema_version is 1 and no migration has ever been needed.

---

## 3. Architectural Decisions

The most important section. Format per decision: what / why / alternatives / why rejected.

**D1. Skills emit results; a single deterministic engine is the only writer of task state.**
Why: versioning, cascades, and readiness are deterministic; an LLM "remembering" them fails probabilistically and corrupts silently. Alternatives: (a) rules as markdown instructions Claude follows while editing task files — rejected because an instruction is a request, not a guarantee, and corruption is invisible until much later; (b) a running service/daemon — rejected as out of scope by definition (this must drop into any repo with nothing but Python 3.8+).

**D2. No orchestrator; routing is derived readiness.**
`terminal → waiting (cycle→human) → pending-explore → refine (no active spec) → run`, computed from task state; every skill guards on it and stops after reporting. Why: composability without a controller; independently executable skills. Alternatives: a pipeline/state-machine driver — rejected because it recreates the daemon, couples skills, and adds a component that must be running to make progress. Consequence accepted: a human (or explicit request) advances work; nothing auto-executes.

**D3. The task `description` is immutable verbatim intake text.**
Why: it is the evidence Refine's adopt-vs-elaborate judgment runs on, and the ground truth when specs are later disputed. Alternative: normalize/summarize at intake — rejected because it destroys that evidence and injects interpretation before judgment is supposed to happen.

**D4. Canonical single-direction typed edges; inverse names rejected by the engine.**
`parent`, `blocked_by`, `generated_from` are semantic; everything else is annotation ignored by readiness; `blocks`/`children`/`depends_on` are rejected with a pointer to the canonical form; reverse views are queries. Why: bidirectional storage guarantees eventual inconsistency. Alternative: store both directions, sync them — rejected as a permanent consistency liability with zero query benefit at this scale.

**D5. Append-only versioned artifacts with cascade invalidation, in fixed order `decision → specification → implementation → review`.**
Superseding kind K mechanically invalidates all active downstream artifacts (a spec written against a dead decision is dead). Supersession reason lives on the *old* version; first reason wins. Why: correctness of stale-work detection cannot depend on a prompt remembering to clean up. Alternative: mutable artifacts — rejected because history is the audit trail and the recovery record.

**D6. `decision_ref`: children pin a specific version of the parent's Decision.**
A new parent decision version flags every sibling pinned to the old one, superseding their specs (cascade), re-routing them to refine. Why: cross-task staleness is the failure mode of decomposed work; pinning makes it detectable mechanically. Alternative: children reference "the parent's current decision" — rejected because staleness becomes undetectable exactly when it matters.

**D7. Explore is reached only by explicit escalation (or explicit, confirmed user request).**
Why: "no decision exists yet" is true of every trivial task; inferring explore from absence sends everything through architecture review. Alternative: readiness infers explore when no decision artifact exists — rejected for exactly that reason.

**D8. Refine is the universal entry point with four ordered modes (adopt ▸ elaborate ▸ clarify ▸ escalate), and adopt-not-inflate is an explicit quality bar.**
Why: the single most likely LLM failure on well-written tasks is over-elaboration dressed as diligence; the skill states "if your spec is much longer than a well-written description, you are doing it wrong." Alternative: one generic "write a spec" mode — rejected because it optimizes for the vague case and damages the well-specified one.

**D9. Independent review: fresh-context reviewer, three inputs only (spec, diff, tests), recorded prompt, deterministic audit.**
`record-review-prompt` stores the exact prompt (hashed, evented) before the subagent runs; `audit-review` verifies each recorded prompt contains the spec's acceptance criteria verbatim and does not contain the implementation's summary; unrecorded reviews are flagged. Why: prompt-only isolation is unverifiable; recording moves it from "trust" to "audit". Rejection routing by root cause: `implementation` → local retry (budget), `specification` → escalate_refine, `architecture` → escalate_explore (also escalates the parent of a child). Alternatives: self-review — rejected as review theater; process-level isolation guarantees — unavailable in a skills package, so the residual gap (a skill could skip recording) is made *detectable* instead (doctor + audit flag it).

**D10. Capability matrix, deny-by-default, enforced at validate/apply.**
`capabilities.json` maps actor → allowed artifact kinds / relations / signals; unknown actors are denied; `human` is universal. Why: which-skill-may-emit-what is deterministic and was originally only prose; enforcement makes contract violations impossible rather than discouraged, and adding a skill becomes a data edit. Alternative: trust skill prompts — rejected after the prototype showed instructions drift.

**D11. Engine-enforced invariants beyond capabilities:** review retry budget (3rd implementation-fault rejection in a cycle parks the task), verdict/signal coherence (`done` requires an approved active review — constrained actors only; `human` is exempt because review-less closures like answered clarifications are legitimate, and the exemption is auditable via event actor), `result_id` idempotency (checked **before** validation so a retry after a terminalizing apply gets a no-op, not an error), a store lock (O_EXCL, 60s stale-break), and a version circuit breaker (any kind reaching v4 parks the task). Each of these was once an instruction; each is now a guarantee.

**D12. Engine shape: package behind a stable facade.**
`scripts/tasks.py` is the resolved public entry point and re-exports the module API; implementation lives in `scripts/engine/` decomposed along the dependency DAG (model → store → readiness/validation → apply → audit → cli). Why: "single deterministic engine" is a **process property** (one entry point, one writer, one resolution path), not a file-count property; a years-horizon monolith accretes unreviewably. Alternative: one file — was the original decision, **overturned in review** (see §10 / Lessons). Anything importable from `tasks.py` is public API; anything reachable only via `engine.*` is internal.

**D13. The task store is self-ignoring by default.**
The engine writes `.tasks/.gitignore` (`*`) on first use. Why: task state is workflow state, orthogonal to code branches; M3 proved that otherwise a Run branch sweeps the store into feature commits and engine writes block checkouts. Alternative: "commit it if you want history" as blanket guidance — was the original position, overturned by evidence; tracked-from-trunk remains a documented opt-in (delete the `.gitignore`).

**D14. No GitHub/Jira integration code; no auto-execution; stdlib-only.**
Intake fetching and terminal sync-back are skill instructions over whatever MCP/CLI a session has, with an explicit honesty rule ("say so if you can't; never pretend a sync happened"). Generated tasks always enter the backlog. The engine has zero dependencies so it runs in any Claude Code environment untouched. Alternatives (API clients, plugin loaders, pip dependencies) rejected as portability and maintenance liabilities that duplicate what the session already has.

---

## 4. Validated Assumptions

Only what implementation or testing actually proved. Evidence: 42-test engine suite (`python3 -m unittest discover taskforge-core/tests`) plus the M3 walkthrough on a real repository.

- **Deterministic engine correctness**: versioning + supersession-reason placement; cascade order incl. escalation cascades; **cross-task decision_ref staleness** (child spec invalidated when parent re-decides); the full readiness rule table incl. pending-escalation precedence and terminal short-circuit.
- **Result contract**: structural validation, unknown-key rejection, reason-required signals, per-actor **capability enforcement** (deny-by-default, verified at validate and apply), verdict/signal **coherence** incl. the human exemption.
- **Relationships**: canonical-direction enforcement with pointers, relation wiring (follow_up / prerequisite / child incl. blocking edges and decision_ref pinning), edge idempotency, self-edge rejection, dangling-blocker = waiting.
- **Cycles**: direct and transitive detection; diamond dependencies correctly *not* flagged; cycle drains to `blocked_on_human`.
- **Blocking/wake**: done and cancelled wake dependents; `blocked_on_human` does not release them.
- **Budgets**: derivation from event history (reset on approval/human-update/escalation) and **in-engine enforcement** (third implementation-fault rejection parks the task).
- **Idempotency**: duplicate `result_id` is a no-op, including the retry-after-terminal case (regression-tested after being found live).
- **Reviewer audit**: clean pass, leaked-summary detection, missing-criterion detection, unrecorded-review flagging, hash-mismatch detection.
- **Store integrity tooling**: doctor detects dangling edges, unresolvable decision_refs, cycles, unaudited reviews.
- **Config precedence**: defaults ← config.json ← environment.
- **Public API stability through refactor**: the monolith→package decomposition passed the pre-existing suite **unmodified** against the facade, and no SKILL.md/CONTRACTS path changed.
- **End-to-end lifecycles**: adopt→run→done→wake; escalate→decide→decompose→children-complete→parent-refine; clarify→block→answer→resume; park→human-update→resume — as unit-level integration tests *and* (first path) live on a real repo with real code, tests, branch, and merge.
- **Self-ignoring store**: engine writes `.tasks/.gitignore`; verified by test and by the repaired demo repo.

**Partially validated (do not over-claim):** the store lock is exercised by every mutating CLI call but has no contention test; multi-line/exotic intake text is exercised only lightly; `validate` and `apply` share one code path by construction, not by differential testing.

---

## 5. Remaining Unknowns

Brutally honest list. None of these are known to work.

1. **Judgment quality — the largest unknown.** Adopt-without-inflation, elaboration that's executable cold, escalating only on genuine approach forks, clarify questions a human can actually answer: all specified, none benchmarked. The prompts have never been executed by a real Claude Code session following the SKILL.md as a skill.
2. **Reviewer isolation with the real Task tool.** The audit proves prompt *content*; it cannot prove the judge had no other context. M3's reviewer was the implementing session (declared deviation). Until a real fresh-context subagent runs a review and `audit-review` passes, independent review is unproven end-to-end.
3. **Skill triggering.** Descriptions were written to best practice but trigger rates are unmeasured; "refine"/"run" are common words and the `taskforge-` prefix protects install collisions, not selection behavior.
4. **Scale.** Readiness and reverse views scan all task files; fine in design to low thousands of tasks, measured never. Event histories grow unboundedly per task.
5. **Long-running usage.** Schema migration is a scaffold that has migrated nothing; artifact-version circuit breakers have never tripped in earnest; no store has lived longer than one session.
6. **Concurrency and multi-user.** The lock serializes one machine's sessions; two humans (or a human + CI) sharing a store via git is undesigned territory — merge conflicts on task JSON are unhandled.
7. **Sync-back reality.** Never run against a real tracker; the honesty rule has been exercised only in its "no access" branch.
8. **Windows.** POSIX-flavored assumptions (O_EXCL semantics, path handling) are untested there.
9. **Human ergonomics.** `human-update`, parked-task queues, and the report format have never been used by an actual human across days of work.

---

## 6. Outstanding Milestones

**M4 — Judgment benchmark (NEXT).** In real Claude Code: (a) verify Task-tool reviewer isolation end-to-end on one task; (b) run the ten-task trial — mixed-quality inputs **weighted toward well-written tasks**, because over-elaboration of good input is the predicted failure mode; (c) measure skill triggering on natural phrasings; (d) iterate prompt text with the skill-creator methodology (`claude -p`), never touching engine semantics. Pass criteria are in `README.md` ("Judgment trial").

**M5 — Extension proof.** Add one real skill (e.g. `taskforge-estimate` or `taskforge-postmortem`) using only the documented extension points: new `taskforge-<name>/SKILL.md` + one `capabilities.json` entry + optional templates. Acceptance: zero edits to existing skills or engine, capability enforcement observed working for the new actor.

**M6 — Operational hardening (provisional, evidence-dependent).** Whatever M4/M5 surface, plus the known partials: lock contention test, store-scale measurement, multi-user story (likely "one store per checkout, trunk-only tracking"), sync-back against a real tracker.

**Why this order:** M4 attacks the two largest unknowns (judgment, isolation) — everything else is worthless if those fail; M5 is cheap and validates the extensibility promise before third parties rely on it; M6 hardens only against demonstrated rather than imagined problems. Do not reorder M4 behind M5: extension points multiply surface area that M4 findings might reshape.

---

## 7. Development Principles

Preserve these; they are the project's identity.

1. **Deterministic mechanics belong in the engine; engineering judgment belongs in skills.** When you find a rule living in a prompt that code could enforce, move it. This has happened three times (capabilities, budgets, coherence) and each move eliminated a failure class.
2. **Contracts before implementation.** The §5 skill-contract table in DESIGN.md was stabilized before any prompt was written. New skills follow the same order.
3. **Design changes before code changes.** When implementation exposes a weakness, update DESIGN.md first, then the code — and record *overturned* decisions with the reasoning that killed them (DESIGN.md §10 is the precedent: items 9–11).
4. **Benchmark judgment separately from mechanics.** Unit tests must never pretend to cover prompt quality; the trial protocol exists precisely so that pretense is unnecessary.
5. **The facade is the API.** Anything imported through `tasks.py` is public and test-covered; `engine.*` internals are free to move. Preserve the invocation path unless something compelling forces otherwise.
6. **Honesty over simulation.** Skills say "not synced — no access" rather than pretending; a self-review is never recorded as a Review; deviations get declared in the record (see M3 walkthrough).
7. **Backwards compatibility wherever practical**: additive JSON fields, `schema_version` + `migrate` for anything structural, deny-by-default so new capability grants are explicit.
8. **Milestones end with**: working implementation, passing tests, updated docs, and a short design review of deviations.

---

## 8. Repository Map

```
taskforge-skills/
├── HANDOFF.md                  ← this document
├── DESIGN.md                   the design contract; §10 = decision history incl. overturns
├── README.md                   install, operations, judgment-trial protocol
├── examples/walkthrough-m3.md  the real-task validation record (commands, findings, deviation)
├── taskforge-core/             shared SDK — itself a skill (backlog/status/health queries)
│   ├── SKILL.md                triggers on task-status/backlog questions; human unblocking
│   ├── CONTRACTS.md            THE architecture doc every skill reads once per session
│   ├── capabilities.json       actor → allowed artifacts/relations/signals (deny-by-default)
│   ├── scripts/
│   │   ├── tasks.py            PUBLIC ENTRY POINT + stable API facade (48 lines)
│   │   └── engine/             implementation, decomposed along the dependency DAG:
│   │       ├── model.py        pure domain: constants, task/artifact/edge helpers (no IO)
│   │       ├── store.py        filesystem: atomic IO, lock, config, capabilities, self-ignore
│   │       ├── readiness.py    derived readiness + cycle detection (the routing rules)
│   │       ├── validation.py   boundary validation: results, payloads, capabilities, coherence
│   │       ├── apply.py        the pipeline: artifacts→tasks→edges→signal→readiness→wake
│   │       ├── audit.py        reviewer-isolation audit, doctor, migrate
│   │       └── cli.py          parsing + dispatch only
│   ├── references/
│   │   ├── reviewer-prompt.md  reusable reviewer component: protocol + 3-slot template
│   │   ├── reporting.md        shared end-of-skill report format
│   │   └── sync.md             terminal sync-back instructions + honesty rule
│   ├── templates/              result.json skeletons (refine-adopt/elaborate/clarify/escalate,
│   │                           explore-decision, run-approved, run-rejected-escalate)
│   └── tests/test_engine.py    42 tests, stdlib unittest, imports via the facade
├── taskforge-add-task/SKILL.md intake: any source → normalized Task (verbatim description)
├── taskforge-refine/SKILL.md   universal entry: adopt ▸ elaborate ▸ clarify ▸ escalate
├── taskforge-explore/SKILL.md  Decisions + optional decomposition; escalation-only
└── taskforge-run/SKILL.md      implement + recorded, auditable independent review

Runtime artifacts (created per-repo, not in this package):
.tasks/                         task store: TASK-*.json, config.json, audit/, .lock, .gitignore
```

Command surface (all JSON output): `create · show · list [--readiness] · readiness · blocked-by · budget · validate · apply · human-update · cancel · record-review-prompt · audit-review · config · doctor · migrate`.

---

## 9. Next Immediate Task

You are a fresh Claude Code session. Do exactly this, in order:

1. **Install and verify (10 min).** Install the five skills with `npx skills add hashirventhodi/taskforge-skills` (or copy the directories into your agent's skills directory). From the package root run `python3 -m unittest discover taskforge-core/tests`. Expect **41 OK**. Then in a scratch directory: `python3 <resolved>/tasks.py create --title smoke --description smoke` and `... doctor` (expect clean). If anything fails, stop and fix before proceeding — the engine is the foundation of everything else.
2. **M4 step (a): prove reviewer isolation with the real Task tool (the single highest-value experiment).** In a small real repo (reuse `demo-wordstats` or equivalent): create one well-written task, refine (expect ADOPT), implement per `taskforge-run/SKILL.md` — and at the review step, actually spawn a **Task-tool subagent** with the recorded prompt. Then run `audit-review` and confirm clean. Success ends the project's largest declared deviation. Failure modes to watch: the subagent receiving ambient context beyond the prompt; malformed reviewer JSON (exercise the one-re-ask rule).
3. **M4 step (b): the ten-task judgment trial.** Author ten tasks: six well-written (the adopt-inflation trap), two vague-but-directional (elaborate), one requiring external input (clarify), one genuine approach fork (escalate). Run each through natural user phrasing (this simultaneously measures triggering). Grade against the pass criteria in `README.md`. Record results in `examples/` as `judgment-trial-1.md`.
4. **Only then** iterate prompt text on failures (skill-creator methodology), and only after M4 concludes, start M5.

Rules that bind you: read `taskforge-core/CONTRACTS.md` before executing any workflow skill; never hand-edit `.tasks/`; if you change behavior, DESIGN.md first, code second, and deviations get recorded in §10.

---

## 10. Lessons Learned

These cost real iterations; do not relearn them.

1. **"Single X" claims hide two claims — separate the process property from the artifact property.** "Single deterministic engine" was defended as a single *file* for a full review round. The architectural content was one entry point / one writer / one resolution path; the file count was incidental, and defending it blocked an obviously better internal structure. When someone attacks a "single X" decision, first ask which property is actually load-bearing. (Overturned: DESIGN §10.9.)
2. **An instruction is a request; production needs guarantees.** Three rules born as prompt text (capability limits, retry budgets, done-requires-approval) migrated into the engine once treated as invariants. The general test: if violating the rule corrupts state rather than merely lowering quality, it must be code. This is the governing principle applied recursively — the prototype's engine/skill split had to be re-applied one level deeper.
3. **"Git-friendly" was an undischarged assumption — real usage found it in one task.** The store lived in the working tree; Run's isolated branch swept it into a feature commit; the engine's next write blocked checkout. The design had never decided *whose history task state belongs to*. Lesson: any state that outlives a branch must not be subject to branch checkouts, and the fix should be engine-enforced (self-ignoring store), not another instruction. (Overturned: DESIGN §10.10.)
4. **Tests are design instruments, not just verification.** The suite falsified two design rules as written: done-coherence had to exempt the `human` actor (review-less closures are legitimate), and idempotency had to run *before* validation (a retried apply on a now-terminal task must no-op). Both were recorded as design deviations, not silently patched — which is the only reason we can still explain them.
5. **Unverifiable safety properties should be made auditable, not merely asserted.** Reviewer isolation cannot be process-enforced from inside a skills package. Recording the exact prompt and auditing it deterministically (criteria present, implementation summary absent, unrecorded reviews flagged) converts "trust the prompt" into "check the artifact" — and makes even the evasion (skipping the recording) detectable.
6. **Design history is worth more than design state.** DESIGN.md records *overturned* decisions with the argument that killed each one. That is what stops the next contributor from re-litigating the monolith, re-trusting prompt-enforced budgets, or re-committing the task store to feature branches.
7. **The predicted judgment failure is over-elaboration, not under-specification.** Every quality bar in refine is angled against inflating well-written tasks, and the M4 trial deliberately over-weights good inputs. Whoever runs M4: grade adopt cases hardest.
8. **Honesty rules earn their keep immediately.** The declared M3 deviation (same-session reviewer) is exactly what makes the M4 isolation experiment well-posed instead of already-"proven".

— End of handoff. The store is empty, the tests are green, and the next experiment is written down. Take it from here.
