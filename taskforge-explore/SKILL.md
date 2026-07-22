---
name: taskforge-explore
description: Produce an engineering Decision for a taskforge task - chosen approach, real alternatives with rejection reasons, trade-offs, risks - and propose decomposition or related work for human approval. Use when a task's readiness is "explore" (an escalation is pending from refine, run, or a child task, or a research topic was started via the explore command), or when the user explicitly asks to explore, architect, decide an approach for, or break down a taskforge task. Not for writing specifications (taskforge-refine) or implementing (taskforge-run).
license: MIT
---

# taskforge-explore

Produce a **Decision**: a committed direction that specification and
implementation can rely on. Reached only by explicit escalation or explicit,
confirmed user request — never because a decision merely "doesn't exist yet".

**Prerequisites**: read `taskforge/CONTRACTS.md` this session; resolve
`$SCRIPT`; guard on readiness (`explore` required; on explicit user request
without a pending escalation, confirm intent and note it in `notes`).

**What you may and may not commit** (CONTRACTS → "Topology"). A Decision is
**content** — you record it. Child tasks, backlog tasks, and dependency edges
are **topology** — they change the shape of the work graph, and only a human
may commit them. The engine enforces this: your actor cannot create tasks or
dependency edges. You *reason and recommend* freely; you **propose** topology
and the human approves it.

## 1. Read the question you were summoned to answer

`python3 $SCRIPT show <id>`. In order: the immutable description; the
`escalated` events — **their `reason` fields are the specific question; a
Decision that answers something else has failed**; superseded decision
versions (re-exploration: their `superseded_reason` + any child escalation
events say what broke); existing children (their state bounds how disruptive
a new decision may be — the engine will invalidate the specs of children
pinned to the version you supersede).

This read is also your **provenance**, and §3 turns on it: an `escalated`
event means you were summoned to resolve a fork in *existing work*; **no**
`escalated` event — `pending_escalation` was set at `created` — means this is
a **research topic** whose deliverable is the Decision itself, and the
description is the question.

Then investigate for real: read the relevant code, configs, and docs. A
decision made without looking at the codebase is a guess with formatting.

## 2. Decide

Fill the decision payload (`chosen_approach`, `rationale`, `alternatives`
each with a falsifiable `rejected_because`, `trade_offs`, `risks`). No real
alternatives? Say so — the task may not have needed explore, and the honest
note beats invented contenders.

## 3. Route — one autonomous path; everything else the human disposes

Two facts you already have decide the route: **provenance** (§1 — an
escalation, or a research topic) and whether the Decision implies **new work**
(tasks or dependency edges).

**The one autonomous path — an escalation fork, self-contained.** Provenance
is an escalation *and* the Decision creates no new work: the fork is resolved
and this same task simply proceeds to its specification. Start from
`templates/explore-decision.json`, `apply --actor explore`; readiness routes
to refine. No human needed. This is the *only* route you complete on your own.

**Everything else parks `block_on_human`** — you record the Decision (content)
and the human disposes (topology and completion are the human's, per
CONTRACTS → "Topology"). Two shapes, one mechanic — decision **and**
`signal: block_on_human` in ONE result:

* **The Decision spawns work** — `templates/explore-propose.json`. The
  `signal_reason` carries the proposal: **decomposition** (proposed children,
  each an issue-quality title + description sized for one run — more than ~6,
  reconsider the split) and/or **related findings** outside this task's scope
  (each with **promote to backlog · note only · ignore**; a finding is not a
  task). Either provenance can spawn work.
* **The Decision is the deliverable** — a research topic with nothing to
  build. `templates/explore-dispose.json`. Recommend the disposition:
  **close** (the answer is the deliverable), **spawn independent work then
  close**, or **continue** (specify this task). A research topic never drops
  into refine on its own — the human calls it.

End each with your recommendation, so a one-message answer suffices.
`taskforge` renders the disposition and commits the human's call; you never
create tasks, edges, or a terminal state.

**Not your call at all** — build-vs-buy, budget, conflicting stakeholders:
`block_on_human` with the question and options; record no decision.

## 4. Emit, apply, report

Fresh `result_id`; `validate` then `apply --actor explore`; report per
`taskforge/references/reporting.md`. The autonomous fork → new readiness
`refine`. Any park (proposed work or a research deliverable) →
`blocked_on_human`; name the human disposition as the next step and **stop**.

## Quality bar

* The escalation reason is explicitly answered.
* Rejection reasons are falsifiable, not platitudes.
* A proposed child is refinable from its title + description + the inherited
  decision alone.
* Findings are recommendations with a clear promote/note/ignore, never
  silently created work.
* A research deliverable states one recommended disposition (close / spawn /
  continue); it never silently drops into refine.
* Re-explorations state what changed and why the old approach is dead.
