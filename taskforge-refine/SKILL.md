---
name: taskforge-refine
description: The universal entry point of the taskforge workflow - assess whether a task is executable and produce its Specification, or route it. Use whenever the user says to refine, spec, scope, groom, or prepare a taskforge task, asks "what's next for TASK-x", or wants to move a new task forward - and whenever a task's readiness is "refine" (including after escalations or invalidation cascades). Four modes - adopt a well-written task nearly verbatim, elaborate an underspecified one, generate blocking clarification prerequisites, or escalate to taskforge-explore for an architectural decision.
---

# taskforge-refine

Answer one question — **is this task executable?** — and let the answer
route. Refine produces Specifications; it never makes architectural
decisions and never implements.

**Prerequisites**: read `taskforge-core/CONTRACTS.md` this session; resolve
`$SCRIPT`; guard on readiness (`refine` required — otherwise report actual
state and the right skill; ask before re-refining a `run`-ready task).

## 1. Gather binding context

`python3 $SCRIPT show <id>`:

* The immutable `description` is the ground truth of what was asked.
* `decision_ref` set → read that pinned version on the parent
  (`show <parent-id>`). It is **binding**: specify within it; do not
  re-open it; do not escalate for a decision that exists. Same for an
  active local decision.
* Escalated back from run? The superseded spec's `superseded_reason` and the
  rejected review's `findings` are your work order — a re-refined spec that
  doesn't visibly address them will bounce again.

## 2. Choose a mode — first match wins

**ADOPT** — could run start from the description as-is, without one
question? Then the spec *is* the description, minimally restructured:
`scope` close to original wording; `acceptance_criteria` extracted (or
minimally inferred), not invented; `adopted_from_source: true`.
**Over-elaborating a good task is a failure mode, not diligence.** If your
spec is much longer than a well-written description, you are doing it wrong:
no added constraints, edge cases, or unrequested "improvements".

**ELABORATE** — direction clear, task underspecified. Full spec: `scope`;
`acceptance_criteria` each independently verifiable by a reviewer holding
only spec + diff + tests (that is literally who verifies them);
`constraints`; `assumptions` (safe ones only — risky ones are CLARIFY
material); `edge_cases`. `adopted_from_source: false`.

**CLARIFY** — unspecifiable without information only a human or external
party can supply (business decision, priorities, credentials, third-party
work). No spec, no guessing: one `prerequisite` generated task per genuinely
blocking question, each description containing the question, the options,
and their implications — answerable inside the task, no archaeology. The
engine blocks this task on them. Nice-to-know questions are assumptions or
follow_ups, not prerequisites.

**ESCALATE** — a spec would have to commit to one of materially different
technical approaches, and no decision exists (no decision_ref, no active
decision). Test: would two competent engineers plausibly build this in
structurally different ways a spec must choose between? `signal:
escalate_explore` with the open decision named in one sentence. Vague is not
architectural — vague gets ELABORATE or CLARIFY.

## 3. Emit and apply

Start from the matching template in `taskforge-core/templates/`
(`refine-adopt|elaborate|clarify|escalate.json`); fresh `result_id`;
follow_ups for anything real you noticed outside this task's scope; then:

```bash
python3 $SCRIPT validate result.json --actor refine --task <id>
python3 $SCRIPT apply <id> result.json --actor refine
```

A validation rejection means your result is out of contract — fix the
result, never the store. Report per
`taskforge-core/references/reporting.md`; name the next skill; stop.

## Quality bar

* ADOPT spec diffed against description: structure changes only.
* Every criterion checkable by someone who wasn't in the room.
* Every CLARIFY prerequisite answerable in one human message.
* Spec v2+ names what changed vs the superseded version and why.
