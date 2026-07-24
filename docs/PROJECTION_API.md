# Projection API — the presentation contract

> The engine (`PUBLIC_API.md`) answers *"what is the state, and what are the
> rules?"* This document answers *"what does that state mean to a human, and in
> what shape?"* — the stable surface every renderer (Web UI, CLI, MCP, SDK, and
> clients that don't exist yet) consumes, unchanged.

The Projection API is **the product**. HTTP, the terminal, and an SDK are
*transports* over it, not the design. Implemented in `taskforge/scripts/
projections.py`.

## Domain concepts — one field, one meaning

The contract is built on four domain concepts derived from the engine's facts.
They are kept strictly separate, because real usage showed that overloading
them ("audited", "integrity") produced contradictory fields across screens.

| Concept | Question | Source | Values |
|---|---|---|---|
| **Structural Integrity** *(store)* | is the task graph well-formed? | `doctor`'s structural findings | sound / issues (dangling edge, cycle, unresolved ref, unreadable/future) |
| **Review Result** *(task)* | did the *work* meet its spec? | review artifacts | verdict `approved`/`rejected`, attempts, per-criterion pass/fail |
| **Audit Status** *(review)* | can the *review* be trusted as isolated? | `audit_review` + recorded prompt | `verified` / `breach` / `unrecorded` / `none` |
| **Delivery Status** *(task/feature)* | where is the work in shipping? | delivery + `landing_status` | unlinked / in-flight / landed |

Two orthogonalities the contract enforces:

- **Review Result ⊥ Audit Status.** A review can be `approved` yet a `breach`
  (the code passed, but the review wasn't isolated), or `rejected` yet
  `verified`. They are separate fields, never one boolean.
- **Structural Integrity ⊥ Audit hygiene.** A missing reviewer prompt is not a
  graph defect. `doctor` now tags each finding with a `kind`; only *structural*
  kinds count toward integrity, and `unaudited_review` feeds Audit Status.

## Guarantees

- **Framework-agnostic.** Returns plain JSON-serializable data only —
  `str`/`int`/`bool`/`None`/`list`/`dict`. No HTML, terminal formatting,
  colors, icons, or HTTP. A projection carries a *fact or state*; each client
  maps state → its own visual (a pill, a stripe, a row). This is what lets a
  future desktop/mobile/IDE/MCP client consume the same contract with no
  change.
- **Read-only.** Composes engine reads under the store lock; never mutates the
  store. Enforced by `test_projections.TestLayerProperties.test_read_only`.
- **Deterministic.** Same store → byte-identical projection. Enforced by
  `test_deterministic`.
- **No business logic.** The layer only filters, groups, joins, and formats. It
  never re-derives a rule the engine owns — `readiness`, resolved delivery, and
  **landability** all come from the engine (`test_landing_never_re_derives_the_
  engine_rule`). The one rule this forced into the engine is `landing_status`
  (see below).

## Versioning & compatibility policy

**This is a public contract — v1, frozen.** Assume clients outside our control
consume it. `PROJECTION_API_VERSION = 1`.

- **The consumer rule:** clients MUST ignore fields and enum values they don't
  recognize. A client that rejects unknown keys is non-conforming; this rule is
  what makes additive evolution safe.
- **Additive (minor bump), never breaking:** a new field on a projection; a new
  projection; a new value in a *tolerant* enum (a `digest` group, a
  `needs`-style set) where the consumer rule applies. Existing fields keep their
  name, type, and meaning.
- **Breaking (major bump only):** removing or renaming a field; changing a
  field's type or meaning; removing a value from a *closed* vocabulary
  (`readiness`, `terminal`, `Criterion.result`, `review_state`) that clients
  switch on exhaustively. These are inherited from or aligned with the engine's
  `PUBLIC_API` and are the stable switch surface.
- **Deprecation, not silent removal:** to retire a field, add its replacement
  alongside, mark the old one `deprecated` in this doc with the version it will
  be removed in, and keep it working for at least one minor cycle. The engine's
  own facts change under `schema_version` + `migrate`; this layer never exposes
  that churn — it absorbs it, so a projection field can outlive an engine
  refactor.
- **Version discovery:** `PROJECTION_API_VERSION` is a module constant; a
  transport surfaces it out-of-band (an HTTP header, an SDK property) rather
  than bloating every payload. Projections themselves carry no version field.

`health.structural.issues[].message` is diagnostic-display text — do not parse
it; switch on `.kind` instead. The structured facts (`structural.sound`,
`audit.needs_attention`, `delivery.done_unlanded`) are the programmatic surface.

## Architecture

```
ENGINE (state + rules, source of truth)
   snapshot · show · doctor · landing_status
        │  read-only composition
PROJECTION API  —  task · feature · review · health · digest · board
        │  pure serializable data
  in-process (CLI) · HTTP (Web) · bindings (SDK/MCP) · future clients
```

## Shared sub-shapes (the reuse mechanism)

```ts
Ref       = { id, title }
Card      = Ref & {                       // the reusable unit in every collection
  readiness,                              // "refine"|"explore"|"run"|"waiting"|"terminal"|"human" — the routing axis
  terminal: "done" | "cancelled" | "blocked_on_human" | null,  // authoritative terminal status, else null
  feature: Ref | null,                    // the delivery owner it INHERITS from (null if its own unit)
  is_feature: bool,                       // owns a delivery, or has children
  landable: bool | null                   // engine landing_status; null unless is_feature
}
Criterion = { text, result: "pass" | "fail" | "unchecked" }  // result joined from review.criteria_results, never fabricated
Delivery  = { branch, pr, landed_at }     // own (stored)
Resolved  = { owner: Ref, branch, pr, landed_at } | null     // §10.19, engine-derived
```

**Two authoritative state axes, never the raw engine status.** `readiness`
routes active work; `terminal` disambiguates finished work. The engine's
intermediate status values (`needs_refine`, `ready_to_run`, …) are a
non-authoritative display cache (engine `PUBLIC_API`) and are deliberately not
exposed. A client shows `readiness` for active tasks and `terminal` for closed
ones.

## The six domain projections

Screens are **compositions** of these — e.g. the Dashboard = `board()` +
in-flight `feature()` summaries + `health()` summary. The projections
themselves are domain objects, not screens, so each is reused across clients
and screens.

### `task(id)` → Task
Everything needed to work a task in one view.
```ts
Task = {
  ref: Ref, description, readiness, terminal,
  feature: Ref | null,
  spec: { version, scope, criteria: Criterion[], constraints: str[], edge_cases: str[] } | null,
  review: { verdict: "approved"|"rejected"|null, attempts: int } | null,   // Review Result
  audit: { status: "verified"|"breach"|"unrecorded"|"none" },              // Audit Status
  delivery: Resolved,
  blockers: Card[],        // open blocked_by
  blocks: Card[],          // what waits on this
  follow_ups: Card[]       // generated_from, no parent edge
}
```
The next action is **not** in the contract: `readiness` is the domain fact, and
each client maps it to its own affordance (the CLI to `taskforge-run <id>`, the
Web UI to a "Run" button, an MCP client to a tool call). Putting a command
string here would bind the contract to one transport.

### `feature(id)` → Feature
A delivery unit: its subtree, progress, landing readiness, audit health.
```ts
Feature = {
  ref: Ref, readiness, terminal,
  delivery: Delivery,
  children: (Card & { review_state: "none"|"approved"|"rejected", depth: int })[],  // depth-ordered tree
  progress: { closed: int, total: int },                 // closed = done|cancelled
  landing: { landable: bool, blockers: Card[] },         // ← ENGINE landing_status, never re-derived
  audit: { status, verified: int, breach: int, unrecorded: int },  // Audit Status rolled up over the subtree
  follow_ups: Card[]
}
```

### `review(id)` → Review
The review domain for one task.
```ts
Review = {
  ref: Ref,
  criteria: Criterion[],                                 // active spec × latest criteria_results
  attempts: { version: int, verdict, root_cause: str|null, findings: str[] }[],  // Review Result, every version
  audit: { status, findings: str[], reviews_checked: int[] },   // Audit Status enum + audit-review findings
  budget: { retries_used: int, retries_max: int }        // retries_used = count of rejected attempts
}
```

### `health()` → Health
Store soundness across the three separate domain concerns — never conflated.
```ts
Health = {
  structural: { sound: bool, issues: { kind, task: str|null, message: str }[] },  // Structural Integrity only
  audit: { verified: int, breach: int, unrecorded: int, needs_attention: { task: Ref, status }[] },  // Audit Status, store-wide
  delivery: { done_unlanded: Card[] }                    // reviewed but not merged (inherited children excluded)
}
```

### `digest(since)` → Digest
Changes after `since` (ISO timestamp), grouped by impact — not a raw log.
Composed purely from task history (which the raw store carries), so it needs
**no engine change**.
```ts
Digest = {
  since: ts,
  groups: { landed: Item[], done: Item[], awaiting_human: Item[], escalated: Item[], reopened: Item[] },
  total: int
}
Item = { task: Ref, at: ts, note: str }   // note = the event's reason, verbatim
```

### `board()` → Board
The actionable collection — backs the Dashboard and CLI `next`/`status`.
```ts
Board = {
  next: Card | null,                                     // top pick: run > refine > explore, oldest first
  ready: { run: Card[], refine: Card[], explore: Card[] },
  waiting: Card[],
  awaiting_human: { task: Ref, kind: "proposal"|"question", prompt: str }[],  // status=blocked_on_human (or cycle-parked)
  counts: { run, refine, explore, waiting, awaiting_human, terminal: int }    // sizes of the board's buckets
}
```
`awaiting_human` is neutral by design (not "needs_you") — the contract carries
no assumption of a single viewer; a client labels it "Needs you" if it wishes.

## Composition ↔ engine ledger

| Consumed from the engine (never re-derived) | Composed by this layer |
|---|---|
| `readiness`, resolved delivery (§10.19), review verdict / `criteria_results`, `audit-review`, `doctor`, **`landing_status`** | group-by-readiness, counts, task↔spec↔review↔delivery joins, descendant tree, done-unlanded filter, event→impact bucketing, proposal-vs-question heuristic, `command` strings, "next" ordering, criterion↔result join |

## Notes where the contract met reality (during implementation)

- **`landing_status` was extracted into `engine.delivery`** and is now consumed
  by *both* the `link --landed` gate and `feature()`/`Card.landable`. One
  source of the landing rule — the presentation layer surfaces it, never
  re-implements it.
- **Audit Status** (`verified`/`breach`/`unrecorded`/`none`) is computed from
  the engine's audit verdict (`audit_review().clean`) + prompt evidence, and is
  surfaced identically on `task`, `review`, and (rolled up) `feature`/`health`.
  This replaced the old `review.audited` boolean, which meant two different
  things across projections — the inconsistency that motivated this remap.
- **`doctor` findings gained a `kind`** so Structural Integrity can exclude
  `unaudited_review` (audit hygiene, not a graph defect). The `landing_status`
  pattern: the engine owns the check, the projection composes structured facts.
- **`review.budget.retries_used`** counts rejected attempts, not the engine's
  live per-cycle breaker counter (which resets to 0 once a task is approved).
- **`Digest` needs no engine read** — the raw store carries `history`; only the
  `snapshot` *command* strips it. Confirmed the earlier "history read" concern
  does not apply to the projection layer.
- **`board.needs_you`/`counts`** key the human queue on `status ==
  blocked_on_human` (its readiness is `terminal`); the `human` readiness value
  is the dependency-cycle park, also surfaced as needs-you.
