---
name: taskforge-explore
description: Produce an engineering Decision for a taskforge task - chosen approach, real alternatives with rejection reasons, trade-offs, risks - and propose decomposition or related work for human approval. Use when a task's readiness is "explore" (an escalation is pending from refine, run, or a child task), or when the user explicitly asks to explore, architect, decide an approach for, or break down a taskforge task. Not for writing specifications (taskforge-refine) or implementing (taskforge-run).
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

Then investigate for real: read the relevant code, configs, and docs. A
decision made without looking at the codebase is a guess with formatting.

## 2. Decide

Fill the decision payload (`chosen_approach`, `rationale`, `alternatives`
each with a falsifiable `rejected_because`, `trade_offs`, `risks`). No real
alternatives? Say so — the task may not have needed explore, and the honest
note beats invented contenders.

## 3. Route — content commits, topology is proposed

**Self-contained** — the Decision changes only this task (no decomposition,
no new tasks, no dependency edges). Start from `templates/explore-decision.json`,
`apply --actor explore`, route to refine. Done.

**Entails topology** — the Decision implies splitting the work, related
backlog work, or new dependencies. Do **not** create any of it (the engine
won't let you). Start from `templates/explore-propose.json`: in ONE result,
record the decision **and** `signal: block_on_human`, with `signal_reason`
carrying the structured proposal —

* **Decomposition** (if any): the proposed children, each an issue-quality
  title + description sized for one run, as a numbered list to approve/adjust.
  More than ~6 → reconsider the split.
* **Related findings** (if any): each discovery *outside this task's scope*,
  with a recommendation — **promote to backlog · note only · ignore**. A
  finding is not a task; the human decides.
* Your recommendation and why, so a one-message answer suffices.

The parent parks; `taskforge` renders the proposal and, on approval, commits
the chosen topology **as the human**. You never create the children or edges.

**Not your call at all** — build-vs-buy, budget, conflicting stakeholders:
`block_on_human` with the question and options; record no decision.

## 4. Emit, apply, report

Fresh `result_id`; `validate` then `apply --actor explore`; report per
`taskforge/references/reporting.md`. Self-contained → new readiness `refine`.
Proposed topology → `blocked_on_human`; name the human approval as the next
step and **stop**.

## Quality bar

* The escalation reason is explicitly answered.
* Rejection reasons are falsifiable, not platitudes.
* A proposed child is refinable from its title + description + the inherited
  decision alone.
* Findings are recommendations with a clear promote/note/ignore, never
  silently created work.
* Re-explorations state what changed and why the old approach is dead.
