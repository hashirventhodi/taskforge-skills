---
name: taskforge-explore
description: Produce an engineering Decision for a taskforge task - chosen approach, real alternatives with rejection reasons, trade-offs, risks - and optionally decompose large work into child tasks. Use when a task's readiness is "explore" (an escalation is pending from refine, run, or a child task), or when the user explicitly asks to explore, architect, decide an approach for, or break down a taskforge task. Not for writing specifications (taskforge-refine) or implementing (taskforge-run).
license: MIT
---

# taskforge-explore

Produce a **Decision**: a committed direction that specification and
implementation can rely on. Reached only by explicit escalation or explicit,
confirmed user request — never because a decision merely "doesn't exist yet".

**Prerequisites**: read `taskforge/CONTRACTS.md` this session; resolve
`$SCRIPT`; guard on readiness (`explore` required; on explicit user request
without a pending escalation, confirm intent and note it in `notes`).

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

Fill `taskforge/templates/explore-decision.json`:

* `chosen_approach` — specific enough that refine needs no follow-up
  question.
* `rationale` — in terms of this codebase and these constraints; if
  decomposing, include the integration intent (the parent still gets its own
  refine + run after children complete — decomposition is not a way to
  launder a feature past review).
* `alternatives` — the real contenders, each `rejected_because` a falsifiable
  claim about this codebase. No real alternatives? Say so — the task may not
  have needed explore, and the honest note is worth more than invented
  contenders.
* `trade_offs` — every real decision costs something; empty is a red flag.
* `risks` — what would invalidate this decision, so a future re-exploration
  knows what changed.

**Escape valve**: build-vs-buy, budget, conflicting stakeholders — not your
decision. `signal: block_on_human` with the question, the options, and their
implications spelled out for a one-message answer.

## 3. Decompose only when size demands

Children: each independently implementable and reviewable, sized for one
run, description written like a good issue (it becomes one — refine will
judge it). The engine wires parent + blocking edges and pins each child to
your Decision; don't restate the decision in child descriptions. More than
~6 children → reconsider the split. Research ideas are `follow_up`, never
children.

## 4. Emit, apply, report

Fresh `result_id`; `validate` then `apply` with `--actor explore`; report
per `taskforge/references/reporting.md` (decision in one sentence,
children with ids, new readiness — `refine` undecomposed, `waiting`
decomposed); children are backlog, not a work queue — stop.

## Quality bar

* The escalation reason is explicitly answered.
* Rejection reasons are falsifiable, not platitudes.
* Any child is refinable from its description + the inherited decision alone.
* Re-explorations state what changed and why the old approach is dead.
