---
name: taskforge-run
description: Implement a taskforge task against its active Specification and verify it with an independent fresh-context review subagent. Use when a task's readiness is "run", or when the user asks to run, implement, execute, build, or ship a taskforge task that has a specification. Covers the implement-review-retry loop, recorded-and-auditable reviewer isolation, root-cause escalation back to taskforge-refine or taskforge-explore, and scope discipline (out-of-scope discoveries become follow-up tasks). Tasks without an active specification route to taskforge-refine instead.
license: MIT
---

# taskforge-run

Implement the active Specification, then submit the work to an independent
reviewer in a fresh context. Run finishes a task or escalates it — it never
quietly lowers the bar and never expands scope.

**Prerequisites**: read `taskforge/CONTRACTS.md` this session; resolve
`$SCRIPT`; guard on readiness (`run` required).

## 1. The spec is the whole contract

`python3 $SCRIPT show <id>`. The active specification — not the description,
not your memory of the conversation — is what you implement and what the
reviewer judges. Spec vs description conflict? The spec wins; note the
conflict in your report. Record the spec's version; you cite it in
artifacts. Check `python3 $SCRIPT budget <id>` if resuming a task with prior
rejections.

## 2. Implement

Plan briefly, then work on the right line (git repo):

* **A standalone task** owns its delivery — branch `taskforge/<task-id>`,
  recorded so provenance isn't prose: `$SCRIPT link <id> --branch
  taskforge/<task-id>`.
* **A child of a decomposed feature** runs on the **feature branch** and does
  **not** link its own — delivery is inherited from the nearest owning
  ancestor (DESIGN §10.19), so the whole feature ships as one branch/PR. Only
  `link <id> --branch …` a child when it genuinely ships on its own line
  (break-out). If the feature isn't linked yet, `link` the parent's branch
  once.

Run the tests.

**Scope discipline is binding.** Adjacent problems you notice — flaky tests,
dead code, missing validation elsewhere — become `follow_up` entries in your
result, described to stand alone. Never extra diff: the reviewer should see
nothing the spec didn't ask for.

**Upstream discoveries end the attempt immediately** — don't push through a
broken contract:

* spec ambiguous/contradictory/unimplementable → `signal: escalate_refine`,
  the defect named precisely;
* the approach itself cannot work → `signal: escalate_explore`;
* blocked on something only a human can resolve → `signal: block_on_human`.

Include artifacts already produced and all follow_ups in the escalation
result — partial evidence is still evidence.

## 3. Independent review — recorded, isolated, non-negotiable

Follow `taskforge/references/reviewer-prompt.md` **exactly**: write the diff
and the test results to two files, then let the engine assemble and record the
prompt — `build-review-prompt <id> --diff <diff-file> --results <results-file>`
(it renders the active spec verbatim, so you never hand-serialize it and
escaping can never desync the prompt from what `audit-review` checks). Spawn a
fresh-context subagent (Task tool) with the built prompt from the returned
`file`; one re-ask on malformed output, then `block_on_human` — never guess a
verdict, never self-review. `audit-review` will later verify your recorded
prompts deterministically; a review without a recorded prompt is flagged as
an isolation failure. Record the verdict verbatim as the review artifact,
including rejections you disagree with (disagree in the report, not the
record).

## 4. Route on the verdict

* **approved** → template `run-approved.json`, `signal: done`.
* **rejected / `implementation`** → fix and retry: feed back the reviewer's
  `findings` list only; re-test; **new** fresh-context reviewer (new recorded
  prompt, next version number). Budget: `max_review_retries` from
  `$SCRIPT config` (default 2 retries, 3 attempts). All attempts'
  implementation + review artifacts go in the final result, in order. The
  engine enforces the budget — a rejection beyond it parks the task
  automatically; your `signal: block_on_human` on exhaustion states the
  unresolved findings.
* **rejected / `specification`** → `signal: escalate_refine` (template
  `run-rejected-escalate.json`), reason from findings.
* **rejected / `architecture`** → `signal: escalate_explore`; the engine
  also escalates the parent of a child task.

## 5. Emit, apply, sync, report

Fresh `result_id`; `validate` then `apply` with `--actor run`. If you opened
a PR, record it on the delivery **owner** (the feature for a child, else this
task): `$SCRIPT link <owner-id> --pr <ref>`. Terminal + external source → sync
per `taskforge/references/sync.md` (with its honesty rule) — note that `done`
**comments**, it does not close the issue. Report per `reporting.md`:
attempts, verdicts, root causes, follow_ups, final readiness. No
merging/deploying beyond the spec's own criteria; no starting generated
tasks. **`done` is not merged**: the issue closes only when the code lands
(`link <owner> --landed`, which the engine refuses until every descendant is
closed), after the PR merges — often a later session, not here.

## Quality bar

* Recorded reviewer prompts pass `audit-review` (criteria present verbatim;
  implementation summary absent).
* Every acceptance criterion appears in `criteria_results` with explicit
  pass/fail.
* Retries change the code, not the reviewer's standards; never retry
  `specification` or `architecture` rejections.
* The diff contains nothing the spec didn't ask for.
