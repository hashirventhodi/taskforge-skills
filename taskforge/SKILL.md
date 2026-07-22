---
name: taskforge
description: The primary entry point for the taskforge engineering workflow - create and import tasks, query and manage the backlog, route work, and unblock humans. Use whenever the user wants to add or import work ("add a task", "import issue #42", "track this bug", "turn these notes into tasks") or asks about tasks and the backlog ("what tasks are ready", "show the backlog", "task status", "what's next", "why is TASK-x stuck", "unblock TASK-x", "check the task store"). Routes to taskforge-refine (specification), taskforge-explore (decisions), and taskforge-run (implementation) but never executes them itself. Also home of the shared contracts, engine, and templates every taskforge skill uses.
---

# taskforge

The primary entry point of the taskforge workflow, and its shared SDK:
contracts, the deterministic engine, templates, and the reviewer component.
This skill **creates, queries, routes, and maintains** tasks; it never
refines, decides, or implements — those are `taskforge-refine`,
`taskforge-explore`, and `taskforge-run`.

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

## Commands

Dispatch on the user's intent (or the argument after `/taskforge`). Every
command reports per `references/reporting.md` and **stops** — routing names
the next skill; it never runs it.

| command | intent | how |
|---|---|---|
| *(none)* / `status` | overview | `list`; summarize counts per readiness, surface `blocked_on_human` tasks with their questions |
| `add <source…>` | create/import tasks | follow `references/intake.md` |
| `backlog` | full list | `python3 $SCRIPT list` (filter: `--readiness refine\|explore\|run\|waiting\|terminal\|human`) |
| `next` | what should happen now | `list --readiness run`, else `refine`/`explore`; name the task(s) and the skill each needs |
| `show <id>` | full detail + history | `python3 $SCRIPT show TASK-x` |
| `why <id>` | explain routing / stuckness | `readiness TASK-x` + `blocked-by TASK-x`; see below |
| `budget <id>` | review-retry budget | `python3 $SCRIPT budget TASK-x` |
| `unblock <id>` | human answered | see Human unblocking |
| `cancel <id>` | close without doing | `python3 $SCRIPT cancel TASK-x --reason "…"`, then sync per `references/sync.md` |
| `sync <id>` | tracker sync-back | `references/sync.md` |
| `doctor` | store integrity | see Maintenance |
| `audit <id>` | reviewer isolation | `python3 $SCRIPT audit-review TASK-x` |
| `config` | effective settings | `python3 $SCRIPT config` |

When answering `why`: quote `readiness` (its `reason`, `blocking_ids`, or
`cycle`), then the last few relevant history events. For `blocked_on_human`,
surface the `human_blocked` event's reason — that is the question awaiting
an answer.

## Human unblocking

When the user answers a `blocked_on_human` task or amends a parked one:

```bash
python3 $SCRIPT human-update TASK-x --note "their answer, verbatim gist" [result.json]
```

Attach a result.json only if the answer translates into artifacts (e.g. the
human dictated the spec); otherwise the note alone re-enters the task and
readiness routes it. After either command, report new readiness and name the
next skill — do not execute it.

## Maintenance

```bash
python3 $SCRIPT doctor           # integrity: dangling edges, bad refs,
                                 # cycles, unaudited reviews
python3 $SCRIPT migrate          # after upgrading taskforge
```

Run `doctor` when anything looks inconsistent, after manual git operations
on `.tasks/`, and before trusting a store you didn't create. Report findings;
fix only via engine commands or by asking the user.

## For skill authors (extension contract)

A new skill = a new `taskforge-<name>/SKILL.md` following CONTRACTS.md plus
an actor entry in `capabilities.json` (deny-by-default). Never modify
existing skills to add one. Templates for results live in `templates/`;
the reviewer component in `references/reviewer-prompt.md` is reusable by any
skill that needs independent judgment.
