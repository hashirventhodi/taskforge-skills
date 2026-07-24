# TaskForge — Findings from First Production Use

**Context:** first end-to-end use of TaskForge to deliver real work on a real
codebase (SourceGrid — a WhatsApp commerce platform). Every observation below
is grounded in that session: an actual task lifecycle, not a design discussion.

**What was delivered through TaskForge on SourceGrid:**

- **gh-335** (WhatsApp cart body exceeds the 1024-char interactive limit → Meta
  rejects → customer receives nothing). Full arc: `add` → `refine` (escalated)
  → `explore` (decision v1, decomposed) → run children → a mid-flight
  re-architecture (deliver oversized carts as an xlsx attachment) that
  superseded decision v1 → decision v2, new children → run → a parent
  **verification** task driven live against the running stack and a real
  browser → PR #343, merged.
- **A second epic started** — real WhatsApp delivery-status tracking via Meta
  status webhooks — through `add` → `refine` (escalate) → `explore` (decision,
  3 children) → refine child 1 → run child 1 (the wamid-capture foundation),
  approved on the first review.

**Verdict:** TaskForge crossed the line from an interesting architecture into a
genuinely useful engineering tool. The proof is not elegance — it is that the
review loop caught two customer-facing correctness bugs the author's own tests
missed, and the escalate→explore step produced a demonstrably better design
than the author would have chosen solo. Those are outcomes, not aesthetics.

---

## 1. What worked

### The review loop caught real bugs the author's tests missed
The single strongest evidence of value. During the Tier-3 (xlsx) run:

- **Attempt 1 — currency bug.** The attachment summary summed *every priced
  row*; the in-chat renderer sums only *available* items. A cart with priced
  out-of-stock parts quoted ₹1,100 on the sheet vs ₹100 in chat. The author's
  own test was tautological — it recomputed the implementation's formula on an
  all-available fixture, so it *could not* catch the divergence. The
  fresh-context reviewer did.
- **Attempt 2 — missing send-failure degradation.** `whatsapp_client` converts
  a rejected send into `{"success": False}` rather than raising, so the
  author's `except` was unreachable dead code. A cart Meta rejected would have
  left the customer with nothing — the exact bug the whole issue existed to
  fix.

Neither was a style nit. The fresh-context isolation is *why* they were caught:
the reviewer did not share the author's rationalizations.

### Escalate → explore produced materially better designs
When refine hit an architectural fork (where does per-message delivery status
live?), escalating instead of guessing led explore to discover that
`conversation_messages` **already existed** with a unique `message_id` and a
`wa_status` column — both dead only because they were never wired. That turned
"build a new table" into "finish the intended design." A spec-driven guess
would have built a redundant table. The escalation *forced* the investigation
that found the better answer.

### Derived readiness eliminated state-management burden entirely
Across ~10 tasks and two epics, the author never once reasoned about "what
state is this task in?" — asking `readiness` returned the state *and named the
next skill*, and never misled. The quiet MVP of the architecture.

### Immutable description + escalation-reason-as-work-order
Every skill resumed exactly where the last left off. When a run bounced back to
refine, the `superseded_reason` was literally the work order. Provenance being
verbatim gave refine's adopt-vs-elaborate judgment real evidence.

### Engine-as-sole-writer was ceremony that paid off
Never once corrupted state, even across a cancel, a decision supersession, and
two epics interleaved on one working tree.

---

## 2. What surprised us (only real usage revealed this)

### Regression evidence was the dominant time sink, and it collided with a red suite
The run skill's "no new failures vs baseline" criterion is sound in principle.
In practice SourceGrid's backend suite is ~143-failing and **order-dependent**
(a test module stubs `sys.modules` at import time and never restores it). A
stash-based before/after therefore reported *dozens* of "new failures" in
modules the change never touched — because stashing shifted collection order.
Three full-suite runs were burned proving, by isolation spot-checks, that those
were pre-existing. TaskForge demanded rigorous evidence; the environment made
rigorous evidence expensive and misleading. No design discussion surfaces this.

### A mid-flight re-architecture was absorbed by the primitives
The xlsx pivot arrived with decision v1 already decomposed and a child in
flight. `cancel` (history-preserving) + re-`explore` (v2 supersedes v1,
re-pins children) handled it with no special machinery. Re-architecture is
where task systems usually break; this one did not.

### The one place correctness *leaked* was reviewer-prompt assembly
The author hand-serialized the spec into the prompt template with
`json.dumps`. That escaping produced the audit false-negative below. The single
most error-prone step in the loop was the one the human did by hand.

---

## 3. Weaknesses & friction

- **Ceremony-to-payload ratio is high for small or non-code tasks.** Every
  skill completion is pick-template → write `result.json` → `validate` →
  `apply`. The parent *verification* task (no code) had to force evidence into
  a `test_results` slot and put a doc diff where a code diff belongs.
- **Reviewer-prompt assembly was hand-done** → the escaping bug (fixed in
  v0.6.0, §"E1 delivered").
- **Regression evidence was re-derived by hand each run**, and the engine had
  no notion of a baseline or a flaky set to warn against.
- **Branch/PR bookkeeping was entirely manual** (which branch, rebasing onto
  `development` after merge, remembering which epic sat where). Two wrong-cwd
  `unknown task` errors trace to this.
- **`done` does not mean *merged*.** The author closed the source issue on
  task-`done` before the PR merged — a wrong, user-visible state. Corrected by
  reopening + opening PR #343. The terminal state *overclaims reality*.
- **Children are "backlog, not a queue" — but real children have hard
  ordering** (capture → reconcile → project). Ordering lived only in prose
  ("land this first"), invisible to `readiness`.

---

## 4. Architecture assessment

**Better than expected**
- **Derived readiness** — the best decision in the system.
- **Deny-by-default capabilities** — refine literally *cannot* emit an
  implementation artifact; kept skills honest about their roles.
- **Cancel/reopen as history-preserving** — exercised for real; losing nothing
  meant cancelling freely instead of hoarding.
- **Review budget / circuit breakers** — never bit (approvals landed at
  attempts 2–3), but the right kind of insurance.

**Did not earn their keep this session**
- **Provenance edges** (`generated_from`, `relates_to`, `duplicate_of`) —
  recorded faithfully, never *traversed*. Possibly valuable at 100+ tasks;
  unproven here.
- **The audit's verbatim matcher** — excellent *intent* (deterministically
  prove the reviewer saw the criteria), brittle *implementation*: it string-
  matched against hand-escaped text and false-flagged two genuinely-clean
  reviews. That undermines the exact trust it exists to create. (Fixed in
  v0.6.0.)
- **`doctor` / `migrate`** — never needed. Fine.

**Would keep exactly the same:** engine-as-sole-writer, immutable description,
readiness derivation, escalate→explore→decision→children, fresh-context
recorded budgeted review.

---

## 5. The Human Console — honest note

A console exists (`console/server.py`) but was **not used this session**. The
human's actual interface was three things: the AI's prose reports, raw
`.tasks/*.json` files opened in the IDE, and slash commands. Findings:

- The **snapshot-as-file** meant the human *could* verify prose against ground
  truth — a real property of an inspectable read model.
- But raw JSON is not a review surface. There was no glance-able view of the
  board, the follow-up backlog (~9 follow-ups tracked entirely through AI
  prose), the blocked-on-human queue, or audit health. The human was auditing
  the AI's *summary of state* rather than seeing state.

The read model (snapshot + derived readiness + event log) is the right
foundation; what is missing is a thin *projection* a human reads at a glance —
not a new data model.

---

## 6. Roadmap for v0.6.0

Three coherent epics remove friction actually experienced; two small riders.

| Epic | Absorbs | Root friction |
|---|---|---|
| **E1 — Engine-owned review pipeline** ✅ *delivered* | prompt-assembly-by-hand + audit false-negatives | the one place correctness leaked |
| **E2 — Git-aware tasks** | premature issue-close + branch juggling | `done` ≠ *merged* |
| **E3 — Thin read projection** | reading state via prose; 9 prose-tracked follow-ups | raw JSON became the console by default |
| *Rider A* — verification-kind tasks | bent the code/diff/review contract | folds into E1's review path |
| *Rider B* — evidence-under-red-suite guidance | 3 wasted regression runs | doc/contract, not a feature |

**Ordering & ROI:** `E1 → E2 → E3`. E1 is highest-compounding (every task
passes through review) and fixes the only correctness leak — uncontested first.
E2 is a *model correctness* gap (`done` lying), not mere convenience, so it
ranks second. E3 removes *trust-me* friction, not *dangerous* friction, and is
strictly better after E1+E2 give it audit-health and merge-state to display.

**Deliberately excluded** (no real pain removed): soft child ordering (prose
worked), ceremony reduction (the file-dance also *prevented* state
corruption), provenance-edge tooling (recorded, never traversed).

**Priority change vs. the retrospective:** baseline-aware validation dropped
from "clear missing capability" to Rider B. Most of that pain was SourceGrid's
red flaky suite, not a TaskForge design gap; building "the engine manages test
baselines" would over-engineer for one bad environment. The right version is a
paragraph of run-skill guidance (prescribe the deterministic blast-radius
method), not a feature.

---

## 7. E1 delivered — Engine-Owned Review Pipeline

**Root cause.** The `audit-review` check (`crit in prompt`) was always correct.
The bug was that hand-assembled prompts fed it JSON-escaped text: a criterion
containing `delivery.status == "failed"` became `\"failed\"` under
`json.dumps`, and `—` became `—` under `ensure_ascii`. The canonical
criterion was then not a substring of the escaped prompt → false-negative on
genuinely-isolated reviews (twice, on clean work).

**Fix.** The engine now owns assembly:
`build-review-prompt <id> --diff <file> --results <file> [--version N]` loads
the active spec, renders `preamble + spec (verbatim) + diff + results`
deterministically, and records it. Because spec fields render as **verbatim
text (never JSON)**, `crit in prompt` holds by construction — **the audit logic
did not change**.

**Why not canonical JSON (RFC 8785).** Canonicalization fixes serialization
*stability*, not *escape-freedom* — under JCS, `"failed"` is still `\"failed\"`,
so it would not fix a verbatim substring audit. Recorded as a code comment so
the fix is not reverted backward.

**Clean, not backward-compatible.** In pre-release with no compat promise,
`record-review-prompt` (the hand-assembly command that *caused* the bug) was
**removed**, not deprecated. One correct way to produce a review prompt; the
low-level write/event recorder survives only as an internal helper used by
`build-review-prompt` and by the audit's adversarial tests. `audit-review`
unchanged; `REVIEWER_PREAMBLE` single-sourced in the engine and guarded against
doc drift by a doc-contract test.

**Verified.** The exact SourceGrid regression (a criterion with `"` and `—`) is
now recorded verbatim and audits **clean**; build is deterministic (identical
digest for identical inputs); the removed verb errors with `invalid choice`;
full suite + subtests green; skill validator clean.

---

## 8. Open questions / deferred

- **E2 (git-aware) and E3 (read projection)** — next, in that order.
- **Dogfooding.** E1 was built by direct implementation, not routed through
  TaskForge's own run→review loop. Whether the engine's *own* development
  should run through the skills (which are written to operate on a *target*
  project's `.tasks/` store) is an open decision, not an assumption.
- **The recurring test-isolation leak** (`test_customer_grpc_client_320.py`
  stubbing `sys.modules` at import time) cost real time across three run
  cycles on SourceGrid. It is SourceGrid's bug, not TaskForge's — noted here
  only because it is the environmental reason the regression-evidence friction
  (§2, Rider B) was so acute.
