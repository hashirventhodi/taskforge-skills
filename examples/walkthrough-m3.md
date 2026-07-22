# M3 walkthrough: the framework against a real task

A record of the first end-to-end validation on a real codebase (`wordstats`,
a small stdlib CLI with a unittest suite), exercising the workflow exactly
as the skills instruct — readiness guards, templates, validate-then-apply,
recorded reviewer prompts, reports. Ids and outputs below are from the
actual run; the companion demo repo is packaged separately.

## What was exercised

**Intake** — two tasks created with verbatim descriptions:
a well-written one ("Add a --top N flag…", with behavior and acceptance
stated) and a vague-but-directional one ("Improve tokenizer handling of
punctuation…").

**Refine, both modes.** The well-written task took **ADOPT**: scope and
criteria extracted from the description, one edge case minimally inferred
(`N > distinct words`), `adopted_from_source: true` — the spec is
description-scale, not inflated. The vague task took **ELABORATE**: four
verifiable criteria including one the original text never stated but any
implementation must decide (internal apostrophes preserved: `don't` stays
`don't`), explicit constraints and out-of-scope assumptions.

**Run, full loop on the adopted task.** Isolated branch
`taskforge/TASK-381e9c2814c2`; implementation confined to the spec (flag +
validation + four tests); 7/7 tests green. Reviewer prompt built from the
template's three slots only, **recorded before review**
(`record-review-prompt`, version from `budget`'s `next_review_version`);
verdict approved with every criterion in `criteria_results`; result
validated, applied, task `done`. `audit-review`: clean. `doctor`: clean.
Second task left at `ready_to_run` — generated/refined work is backlog,
nothing auto-executes.

**Declared deviation:** this environment has no fresh-context subagent, so
the reviewer role was played by the same session judging strictly from the
recorded prompt. The audit proves the prompt contained only spec + diff +
tests; it cannot prove the judge forgot everything else. True context
isolation is exactly what the M4 judgment trial must verify in real Claude
Code — do not treat this walkthrough as evidence for it.

## Findings (both fed back design-first)

1. **Store/branch collision (architectural — DESIGN.md §1, §10.10).**
   `git add -A` on the Run branch swept `.tasks/` into a feature commit,
   and the engine's post-apply write then blocked `git checkout main`. Task
   state is workflow state, orthogonal to code branches. Fix: the store is
   now **self-ignoring by default** — the engine writes `.tasks/.gitignore`
   (`*`) on first use; tracking workflow history in git is the documented
   opt-in (delete that file, commit from trunk only).

2. **Reviewer version discovery (friction — DESIGN.md §10.11).** Computing
   the version for `record-review-prompt` required parsing full `show`
   output. `budget` now reports `total_reviews` and `next_review_version`;
   the reviewer protocol references it.

Both fixes are engine-enforced (not instructions), covered by new unit
tests, and backwards compatible.

## Reproducing

```bash
export TASKFORGE_DIR=.tasks
S=taskforge-core/scripts/tasks.py
python3 $S create --title "..." --description-file d.txt   # intake
python3 $S readiness TASK-x                                # guard
# fill taskforge-core/templates/<mode>.json -> result.json
python3 $S validate result.json --actor refine --task TASK-x
python3 $S apply TASK-x result.json --actor refine
python3 $S budget TASK-x            # next_review_version before reviewing
python3 $S record-review-prompt TASK-x --version N prompt.md
python3 $S apply TASK-x run-result.json --actor run
python3 $S audit-review TASK-x && python3 $S doctor
```
