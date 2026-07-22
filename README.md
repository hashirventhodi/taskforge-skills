# taskforge-skills

[![CI](https://github.com/hashirventhodi/taskforge-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/hashirventhodi/taskforge-skills/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![Agent Skills](https://img.shields.io/badge/agent-skills-black.svg)](https://skills.sh)

A production-quality Agent Skills framework implementing the durable-Task
AI engineering workflow. Drop it into any repository: skills perform
reasoning; a shared deterministic engine is the only writer of task state.

Developed against Claude Code and installable into any agent the
[skills.sh](https://skills.sh) CLI supports. The one agent-specific
requirement is a fresh-context subagent for `taskforge-run`'s independent
review; where none exists the skill stops rather than recording a
self-review.

```
taskforge/             the primary entry point + shared SDK
  SKILL.md             command-oriented: intake · backlog queries · routing ·
                       lifecycle · maintenance (full command table in the file)
  CONTRACTS.md         the architecture (single source, read once per session)
  capabilities.json    actor → allowed artifacts/relations/signals (deny-by-default)
  scripts/tasks.py     engine entry point + stable API facade (stdlib-only)
  scripts/engine/      the engine: model · store · readiness · validation ·
                       apply · audit · cli — one writer, decomposed by concern
  references/          intake procedure · reviewer component · reporting · sync-back
  templates/           result.json skeletons per skill/mode
  tests/               stdlib unittest suite for the engine
taskforge-refine/      universal entry: adopt | elaborate | clarify | escalate
taskforge-explore/     Decisions; decomposition into children
taskforge-run/         implement + recorded, auditable fresh-context review
DESIGN.md              the design document, incl. critical review (§10)
```

## Install

Via [skills.sh](https://skills.sh) — works with Claude Code, Cursor, Codex,
opencode, Windsurf, Cline and any other agent the `skills` CLI supports:

```bash
npx skills add hashirventhodi/taskforge-skills          # this project
npx skills add hashirventhodi/taskforge-skills --global # all projects
```

Install **all four** skills (the default). Or copy the four directories into
your agent's skills directory by hand — `.claude/skills/` (project),
`~/.claude/skills/` (user), or the CLI's canonical `.agents/skills/`.

**The `taskforge` skill must travel with the others** — every skill resolves
the engine through it, as a sibling directory (resolution order in
`taskforge/CONTRACTS.md`; `TASKFORGE_SCRIPT` overrides). Requires
Python 3.8+; no dependencies, tests included.

## Your first task

The skills are the interface — you drive the workflow in natural language and
the agent invokes them. In an agent session in your repo:

- **Add work:** *"add a task: make the export button also support CSV"* →
  `taskforge` captures it (readiness `refine`).
- **Refine it:** *"what's next for that task?"* → `taskforge-refine` turns it
  into a specification (or asks a blocking question, or escalates a genuine
  architectural fork to `taskforge-explore`).
- **Run it:** *"run it"* → `taskforge-run` implements against the spec and
  submits the diff to an independent, recorded review before it can reach
  `done`.
- **Check in:** *"what's the backlog?" / "why is TASK-x stuck?"* → the
  `taskforge` hub answers from derived state.

[`examples/walkthrough.md`](examples/walkthrough.md) is a full worked run on
a real codebase — intake → refine → run → review → done — if you want to see
every step and command first.

Task state lives in `.tasks/` (one JSON per task). The store is
**self-ignoring by default** (the engine writes `.tasks/.gitignore` on first
use) because task state is workflow state, orthogonal to code branches — a
Run branch must never sweep it into a feature commit. To track workflow
history in git instead, delete `.tasks/.gitignore` and commit the store from
the trunk line only. Settings in `.tasks/config.json`; env vars win.

## Division of labor

**Claude reasons; the engine enforces.** Skills fill result templates and
apply them through `tasks.py`, which owns every deterministic rule:
versioning and supersession, invalidation cascades (a new Decision kills the
spec built on the old one — including specs of child tasks pinned to it),
relationship wiring, derived readiness with cycle detection, per-actor
capability enforcement, the review retry budget, done-requires-approval
coherence, double-apply idempotency (`result_id`), a store lock, and the
event history. If a rule can be enforced by code, a prompt may explain it
but is never its enforcement.

## Verifying the framework

```bash
python3 -m unittest discover taskforge/tests         # engine correctness
python3 -m unittest discover tests                   # doc-contract guards
python3 scripts/validate_skills.py                   # SKILL.md frontmatter
python3 taskforge/scripts/tasks.py doctor            # store integrity
python3 taskforge/scripts/tasks.py audit-review TASK-x        # reviewer isolation
```

Reviewer isolation is *recorded and audited*, not just instructed: run
registers the exact reviewer prompt before use; `audit-review` verifies each
recorded prompt contains the spec's acceptance criteria verbatim and none of
the implementation summary, and flags unrecorded reviews.

## Judgment trial (prompt-level evaluation)

Engine tests cannot test judgment. Before trusting the skills on real work,
run the ten-task trial: mixed-quality tasks, weighted toward *well-written*
ones (the likely failure is refine over-elaborating good issues). Pass
criteria: adoption without inflation (`adopted_from_source` specs stay at
description scale); elaborated specs executable cold; escalation fires on
genuine approach forks only; a clarify case provably blocks and resumes;
every result validates first try; `audit-review` clean on all runs. Iterate
prompt text with the skill-creator methodology (`claude -p` runs) if any
criterion fails.

## Extending

New skill: add `taskforge-<name>/SKILL.md` per CONTRACTS.md + an entry in
`capabilities.json`. No existing skill changes. New artifact kinds or
relations are deliberate engine changes (they carry cascade/readiness
semantics); `schema_version` + `tasks.py migrate` exist so stored tasks
survive evolution.

Non-goals, permanently: no daemon, no orchestrator, no GitHub/Jira
integration code (intake and sync-back are instructions over whatever
MCP/CLI the session has), no auto-execution of generated tasks.

## Contributing

Contributions are welcome — start with [CONTRIBUTING.md](CONTRIBUTING.md),
which documents the architectural invariants a PR has to respect (the engine
is the only writer of task state; deterministic rules never live in prompts;
the engine stays stdlib-only). See also
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) and, for vulnerabilities,
[SECURITY.md](SECURITY.md).

Note that skills execute with your agent's full permissions — read them
before installing, here as anywhere else in the ecosystem.

The reference documents are `DESIGN.md` (the design and decision history),
`taskforge/CONTRACTS.md` (how the engine behaves — the skill-runtime
contract), [`docs/PUBLIC_API.md`](docs/PUBLIC_API.md) (what we promise never
to break — the maintainer/tooling contract), and
[`docs/reviews/`](docs/reviews/) (point-in-time architecture reviews, which
also record which parts are kept deliberately minimal).

## License

[MIT](LICENSE) © Hashir Venthodi
