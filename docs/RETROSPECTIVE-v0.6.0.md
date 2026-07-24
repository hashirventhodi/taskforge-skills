# v0.6.0 — Engineering Retrospective

*Why the system looks the way it does today.* Written for a contributor who
wasn't here, so they can understand the reasoning behind the architecture before
touching it. This covers the arc from "TaskForge works" to "TaskForge has a
clean three-layer architecture with two validated clients."

For the *first* production validation that motivated this work, see
`RETROSPECTIVE-sourcegrid.md`. For the layering itself, `ARCHITECTURE.md`. For
the numbered engine decisions, `DESIGN.md §10.x`.

---

## 1. The problem we started with

TaskForge had just proven itself on real work — delivering a customer-facing
fix (SourceGrid gh-335) end-to-end through the engine's own workflow. That
first production use was a success, but it surfaced three kinds of gap:

1. **A correctness leak in the one place the human worked by hand** — reviewer
   prompts were hand-assembled, and the serialization escaped acceptance
   criteria, causing the isolation audit to false-flag clean reviews. The
   engine trusted a step it didn't own.
2. **A model that overclaimed reality** — a task could be `done` while its code
   sat unmerged on a branch, and the source issue was closed on `done`. `done`
   silently meant "shipped."
3. **No way for a human to *see* state** — the human's real interface was the
   AI's prose reports and raw `.tasks/*.json` in an editor. The engine had a
   read model, but no surface a person could read at a glance and trust.

The through-line: **facts the human tracked by hand should be owned by the
engine, and state a human consumes should have a real presentation surface.**
v0.6.0 is the systematic response.

---

## 2. Architectural evolution

The system moved from *one writer, many ad-hoc readers* to *one writer, one
presentation truth, many thin adapters*. Three ideas drove every decision:

- **The engine owns state and every rule.** If two clients could disagree about
  an answer, that answer is computed once, in the engine, and exposed as a fact.
- **Prefer derived state over stored references.** A stored pointer is a second
  source that drifts; a derivation over existing structure cannot.
- **Presentation is a layer, not a client.** The definition of what a fact
  *means to a human* belongs in one place that every client reads — otherwise
  the CLI, the Web UI, and the AI's prose each re-invent it and diverge.

The end state is the three-layer architecture in `ARCHITECTURE.md`: **Engine →
Projection API → Presentation Adapters.**

---

## 3. Milestones

### Engine correctness — E1: engine-owned review pipeline (§ CHANGELOG v0.6.0)
The engine now assembles and records the canonical reviewer prompt
(`build-review-prompt`), rendering acceptance criteria as **verbatim text**.
Because the audit matches criteria by substring, and the prompt now contains
them verbatim, the audit is **sound by construction** — the check didn't change;
the input stopped being escaped. The hand-assembly command was removed outright
(pre-release, no compat debt).

### Git-aware delivery — E2 + §10.18/§10.19
`done` is no longer `merged`. Tasks gained delivery provenance
(`{branch, pr, landed_at}`); external-issue closure keys on the **landed** fact,
not on `done`. The landing rule (`link --landed`) refuses unless every
descendant is closed. **§10.19 is the decision that matters most here:** rather
than store delivery on every task (or add a `via` pointer between tasks),
delivery is **derived up the parent chain** to the nearest owning ancestor — the
same "derive, don't store" pattern as readiness. A feature owns one branch/PR;
its children inherit it. The landing rule was extracted into
`engine.delivery.landing_status`, owned once and consumed by both the gate and
the projections.

### Presentation layer — Projection API (Phase 1, §10.20)
Six pure, deterministic, read-only projections (`task`, `feature`, `review`,
`health`, `digest`, `board`) that compose engine facts into typed,
JSON-serializable shapes — the source of truth for *how humans consume* state.
Frozen as a public contract at v1 (`PROJECTION_API.md`), evolved additively.
The load-bearing constraint — **no business logic in the projection layer** —
is what forced clean engine boundaries (it's why `landing_status` and
structured `doctor` findings exist).

### Web UI (Phase 2)
A projection-driven client (vanilla JS, no build) rendering all six screens.
Validated by a real browser walkthrough against the single question "would I
enjoy using this daily?" — answered yes only after the workflow, readability,
and polish passes. This is the *reference* client: it exercises the API most
thoroughly, so its findings shape every future client.

### CLI (Phase 3)
`tf` — a terminal adapter over the *same* six projections. It renders the same
information with the same terminology, and it required **zero Projection API
changes and zero duplicated logic**. That is the strongest possible validation
that the layering is real: a genuinely different medium consumed the contract
unchanged.

---

## 4. Decisions we intentionally rejected

Recording these because the *rejections* explain the shape as much as the
choices. Each was a plausible path we deliberately didn't take.

| Rejected | Why |
|---|---|
| A `merged` lifecycle **status** | Landing is orthogonal metadata on a terminal task, not a new state. A status would ripple through readiness, capabilities, reopen, and the state machine for a fact that doesn't affect routing. |
| A `via` **stored pointer** for delivery grouping | It stores what the `parent` edge already knows. Derivation up the existing hierarchy has no synchronization burden and no decomposition-time write. |
| **Canonical JSON (RFC 8785)** for the reviewer prompt | Canonicalization fixes serialization *stability*, not *escape-freedom* — `"failed"` is still `\"failed\"` under JCS. Verbatim rendering fixes the actual bug. |
| Keeping `record-review-prompt` for **backward compatibility** | Pre-release, no external consumers. The footgun that caused the bug was deleted, not deprecated. |
| A dedicated engine **`history` read** for the Digest | The raw store already carries per-task history; only the `snapshot` *command* strips it. The projection composes it — no engine change. |
| A **`command` string** in the Projection API | It binds the contract to the CLI transport. `readiness` is the domain fact; each client renders its own affordance (a button, a colour, a tool). |
| Exposing the raw engine **`status`** | Its intermediate values are a non-authoritative display cache. The contract exposes the two authoritative axes: `readiness` (routing) + `terminal` (how it finished). |
| **String-parsing** `doctor` findings to separate structural from audit | Couples the contract to non-stable message wording. `doctor` gained a structured `kind` instead. |
| **Renaming fields** to fix the audit/integrity inconsistencies | Renaming moves ambiguity around. We derived the domain model instead (see §5). |
| Forcing **⌘K / global search** into this work | A legitimate product capability, but it needs an additive search projection — not a reason to expand the current scope. |

---

## 5. Lessons learned during implementation

- **Real usage refined the model more than more design would have.** The single
  most important architectural change — separating *audit* and *integrity* into
  distinct domain concepts — did not come from design review. It came from
  clicking through the Web UI and seeing two screens contradict each other
  ("unaudited" on one, "0 unaudited" on another). The bug was conceptual
  overloading, not a UI defect: `audited` meant "isolation verified" in one
  projection and "prompt recorded" in another, and `integrity` conflated a
  malformed graph with a missing reviewer prompt. We resisted renaming and
  instead derived four concepts with one meaning each — **Structural Integrity,
  Review Result, Audit Status, Delivery Status** — enforcing two orthogonalities
  (a review can be *approved* yet a *breach*; a missing prompt is not a graph
  defect). Both clients inherited the corrected semantics for free.
- **Build the reference client before the thin one.** The Web UI exercises the
  API far more than the CLI. Every semantic problem surfaced there, and because
  the fix lived in the projection layer, the CLI never had to discover it.
- **A hard constraint is a design tool.** "No business logic in presentation"
  sounds like a restriction; in practice it *forced* the right engine
  boundaries. Every time a projection wanted to compute a rule, that was the
  signal to move the rule (or its structured exposure) into the engine.
- **Tests caught what review didn't.** A generator consumed twice (empty
  children), a wrong assumption that `blocked_on_human` implies `readiness:
  human` (it's `terminal`), and a seed whose diff text collided with an
  implementation summary — all caught by tests, not reasoning.
- **Freeze late, but freeze.** We nearly froze the Projection API before the UX
  validation. The three leaks it then exposed (a CLI command string, raw status,
  a single-viewer field name) would have been permanent. Validating with a real
  client before freezing was worth the extra pass.

---

## 6. Final architecture

```
                    ┌─────────────────────────────────────┐
                    │  ENGINE                              │  state + rules
                    │  the single source of truth          │  (the only writer)
                    └──────────────────┬──────────────────┘
                                       │  read-only
                    ┌──────────────────▼──────────────────┐
                    │  PROJECTION API  (frozen v1)         │  presentation truth
                    │  task · feature · review · health ·  │  (no business logic)
                    │  digest · board                      │
                    └──────────────────┬──────────────────┘
                                       │  typed, serializable data
        ┌──────────────┬───────────────┼───────────────┬──────────────┐
        ▼              ▼               ▼               ▼              ▼
     Web UI          CLI            MCP             IDE          desktop / …
   (adapter)      (adapter)      (future)        (future)       (future)
                    render only — no business or presentation logic of their own
```

One writer (engine). One derivation of each rule. One presentation contract.
Interchangeable adapters. The CLI proved the interchangeability is real.

---

## 7. Backlog — product, not infrastructure

The foundation is complete. Everything remaining is a **user-facing
capability**, prioritizable independently, and none of it requires expanding the
architecture:

- **Global search / ⌘K** — jump to any task by id or title. Add an *additive*
  search projection (the engine already has the data); every client benefits.
- **Web write-actions** — wire buttons to the retained, whitelisted
  `/api/command` surface (cancel, reopen, unblock, create) so the Web UI can
  *act*, not only read.
- **Responsive QA** — a dedicated cross-device pass on the Web UI before any
  production release (the media queries exist but haven't been walked end-to-end
  on small viewports).
- *(Dropped, not lost)* — the old dependency-**graph view** was not carried into
  the projection UI. If wanted, it returns as a product capability over the
  `edges` already in the projections, not as legacy code.

**Infrastructure is considered done.** From v0.7.0 the work shifts to building
product on this foundation; the architecture expands only when a product
requirement forces it.
