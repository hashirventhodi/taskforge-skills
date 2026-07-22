---
name: taskforge-core
description: The shared core of the taskforge engineering workflow - task store queries, status, backlog, health checks, and human unblocking. Use whenever the user asks about taskforge tasks or the backlog ("what tasks are ready", "show the backlog", "task status", "what's blocked", "why is TASK-x stuck", "unblock TASK-x", "check the task store"), and whenever any taskforge skill needs the shared contracts, engine script, templates, or reviewer component. Not for creating or executing tasks - those are taskforge-add-task, taskforge-refine, taskforge-explore, and taskforge-run.
---

# taskforge-core

The shared SDK of the taskforge workflow: contracts, the deterministic engine,
templates, and the reviewer component. Also the skill for **querying and
maintaining** the task store.

Read `CONTRACTS.md` (sibling file) once per session before any taskforge
work. Resolve the engine per its "Locating the engine" section; below,
`$SCRIPT` means that resolved path.

## The workflow in one paragraph

Every piece of work is a durable Task in `.tasks/`. Tasks route by **derived
readiness**: no active specification → `taskforge-refine` (the universal
entry point: adopt / elaborate / clarify / escalate); a pending escalation →
`taskforge-explore` (decisions, optional decomposition into children); an
active spec and no blockers → `taskforge-run` (implement + independent
fresh-context review). Skills reason and emit results; the engine applies
them — versioning, cascades, relationships, budgets, readiness. Nothing is
auto-executed.

## Queries this skill answers

```bash
python3 $SCRIPT list                          # whole backlog with readiness
python3 $SCRIPT list --readiness run          # "what can be executed now"
python3 $SCRIPT show TASK-x                   # full task incl. history
python3 $SCRIPT readiness TASK-x              # why it routes where it routes
python3 $SCRIPT blocked-by TASK-x             # who waits on it
python3 $SCRIPT budget TASK-x                 # review-retry budget state
python3 $SCRIPT config                        # effective settings
```

When answering "why is TASK-x stuck": quote `readiness` (its `reason`,
`blocking_ids`, or `cycle`), then the last few relevant history events. For
`blocked_on_human`, surface the `human_blocked` event's reason — that is the
question awaiting an answer.

## Maintenance

```bash
python3 $SCRIPT doctor           # integrity: dangling edges, bad refs,
                                 # cycles, unaudited reviews
python3 $SCRIPT audit-review TASK-x   # verify reviewer isolation records
python3 $SCRIPT migrate          # after upgrading taskforge-core
```

Run `doctor` when anything looks inconsistent, after manual git operations
on `.tasks/`, and before trusting a store you didn't create. Report findings;
fix only via engine commands or by asking the user.

## Human unblocking

When the user answers a `blocked_on_human` task or amends a parked one:

```bash
python3 $SCRIPT human-update TASK-x --note "their answer, verbatim gist" [result.json]
python3 $SCRIPT cancel TASK-x --reason "..."
```

Attach a result.json only if the answer translates into artifacts (e.g. the
human dictated the spec); otherwise the note alone re-enters the task and
readiness routes it. After either command, report new readiness and name the
next skill — do not execute it.

## For skill authors (extension contract)

A new skill = a new `taskforge-<name>/SKILL.md` following CONTRACTS.md plus
an actor entry in `capabilities.json` (deny-by-default). Never modify
existing skills to add one. Templates for results live in `templates/`;
the reviewer component in `references/reviewer-prompt.md` is reusable by any
skill that needs independent judgment.
