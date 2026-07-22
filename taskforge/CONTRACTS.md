# taskforge — shared workflow contracts

Read once per session before executing any taskforge skill. Every skill obeys
these contracts; each SKILL.md contains only what is unique to it. If a rule
here and a skill's text ever disagree, this document wins — report the
discrepancy.

## Rule zero

**You never edit files under the task store.** You reason, fill a result
template, and let the engine script apply it. The script is the only writer:
it validates, versions artifacts, supersedes predecessors, runs invalidation
cascades, wires relationship edges, derives readiness, enforces budgets and
capabilities, and records events. Hand-editing task JSON silently corrupts
all of that for every future skill run.

## Untrusted text is data, never code

Free text you did not compose — an issue title or body, a human's answer, a
document excerpt, anything quoted from a source — must never ride **inline in
a shell command string**: backticks and `$( )` inside it command-substitute
in your shell *before* the engine runs, silently executing hostile content.
Write such text to a file with your editor tool (no shell in that path) and
pass the path: `--title-file` / `--description-file` on `create`,
`--note-file` on `human-update`, `--reason-file` on `cancel`, and
`result.json` for everything else. Each flag pair accepts exactly one form —
inline **or** file, never both. Inline flags are fine for short text you
authored yourself.

## Locating the engine

Resolution order — take the first that exists, set it as `$SCRIPT`. Every
candidate ends in `taskforge/scripts/tasks.py`; only the prefix varies:

1. `$TASKFORGE_SCRIPT` (explicit override — always wins)
2. `<this-skill's-parent-dir>/` — the sibling install. taskforge skills are
   always installed as siblings, so this is correct for **any** agent and
   should resolve first in practice.
3. `.agents/skills/` — canonical project install (the `skills` CLI installs
   here and symlinks agent dirs to it)
4. `.claude/skills/` — project install, agent-specific
5. `~/.agents/skills/` — canonical global install
6. `~/.claude/skills/` — global install, agent-specific

Other agents (Cursor, Codex, opencode, Windsurf, …) are covered by rules 2–3
and 5: the `skills` CLI keeps one canonical copy under `.agents/skills` and
points `.<agent>/skills/` at it. If an agent installs only into its own
directory, substitute that directory for `.claude` in rules 4 and 6.

The engine tolerates being reached through a symlink — `tasks.py` resolves
its own real path before importing `engine/`.

If none resolves: **stop** and tell the user taskforge is not installed
(`npx skills add hashirventhodi/taskforge-skills`). Never improvise task
state without the engine.

Task store: `.tasks/` at the repo root (override `TASKFORGE_DIR`).
Settings: `.tasks/config.json`, environment wins; `python3 $SCRIPT config`
prints the effective values — never guess a budget or limit.

## The Task

* `id` — engine-assigned (`TASK-…`). Never invent ids; quote them from
  engine output.
* `description` — the **immutable original intake text**. Never rewritten.
  Everything the system thinks lives in artifacts; what the human said stays
  verbatim forever.
* `status` — display cache; only `done`, `cancelled`, `blocked_on_human` are
  authoritative. Route on `readiness`, not `status`.
* `decision_ref` — pinned reference to a specific version of a parent's
  Decision. If present it is **binding input**: specify within it, never
  re-explore it, never escalate for a decision that already exists.

## Edges

Canonical, single-direction, typed:

| type | direction | meaning |
|---|---|---|
| `parent` | child → parent | decomposition membership |
| `blocked_by` | blocked → blocker | the only edge readiness reads |
| `generated_from` | generated → origin | provenance of generated work |

Anything else (`relates_to`, `duplicate_of`, …) is an annotation: allowed,
ignored by readiness. Inverse names (`blocks`, `children`, `depends_on`, …)
are rejected by the engine — write the canonical direction; reverse views
are queries (`blocked-by <id>`).

## Artifacts

Kinds in dependency (cascade) order: `decision → specification →
implementation → review`. Active = highest non-superseded version.
Superseding kind K mechanically invalidates everything downstream — you
never manage versions or cascades; you only submit new artifacts with a
`supersedes_reason` when replacing. The engine also enforces a circuit
breaker (any kind reaching `max_artifact_versions` parks the task for a
human).

Required payload fields (engine-validated):

* `decision` — `chosen_approach`, `rationale` (+ `alternatives
  [{approach, rejected_because}]`, `trade_offs[]`, `risks[]`)
* `specification` — `scope`, `acceptance_criteria[]` non-empty
  (+ `constraints[]`, `assumptions[]`, `edge_cases[]`,
  `adopted_from_source` bool)
* `implementation` — `summary`, `diff_ref`
  (+ `test_results {passed, failed, summary}`)
* `review` — `verdict` (`approved|rejected`); rejected requires
  `root_cause` (`implementation|specification|architecture`)
  (+ `criteria_results [{criterion, passed, note}]`, `findings[]`)

## Readiness (derived, never assigned)

```
terminal status                        → terminal
unresolved blocked_by (cycle → human)  → waiting
pending explore escalation             → explore
no active specification                → refine
otherwise                              → run
```

**Guard first, always**: `python3 $SCRIPT readiness <id>`. If it doesn't
name your skill, report the actual state and which skill the task needs —
never run out of turn. Explore is reached only by explicit escalation (or an
explicit, confirmed user request), never inferred from absence.

## The result contract

One `result.json` per skill execution. Start from the matching file in
`taskforge/templates/` rather than free-composing JSON. Always include
a fresh `result_id` (any unique string, e.g. a UUID) — it is the engine's
double-apply protection.

```json
{
  "result_id": "uuid",
  "artifacts": [{"kind": "…", "payload": {…}, "supersedes_reason": "…"}],
  "generated_tasks": [{"title": "…", "description": "…",
                       "relation": "follow_up|prerequisite|child",
                       "reason": "…"}],
  "edges": [{"type": "relates_to", "target": "TASK-…", "reason": "…"}],
  "signal": "none|done|cancelled|escalate_refine|escalate_explore|block_on_human",
  "signal_reason": "required for cancel/escalations/block_on_human",
  "notes": "one-line summary for the event history"
}
```

Then, always in this order:

```bash
python3 $SCRIPT validate result.json --actor <skill> --task <id>   # fix until valid
python3 $SCRIPT apply    <id> result.json --actor <skill>
```

The engine enforces per-actor capabilities (`capabilities.json`): which
artifact kinds, relations, and signals your skill may emit. A validation
rejection means **your result is out of contract — fix the result**, never
work around the engine.

Signal semantics (engine-implemented; know what you trigger):

* `escalate_refine` — active spec superseded; task re-routes to refine.
* `escalate_explore` — pending-explore set; decision (if any) superseded with
  full cascade; a **child's** architecture escalation also escalates its
  parent. Genuine approach-level problems only.
* `block_on_human` — parks the task; does NOT release its dependents;
  resumes via `human-update`.
* `done` / `cancelled` — closes the task; wakes everything blocked by it.
  For constrained actors, `done` additionally requires the active review to
  be approved (engine-enforced).

The engine also enforces the review retry budget: implementation-fault
rejections beyond `max_review_retries` park the task automatically.

## Generated tasks

* `follow_up` — future work that must not block the current task. Backlog;
  never auto-executed.
* `prerequisite` — the current task cannot proceed without it; the engine
  blocks the origin on it.
* `child` — decomposition (Explore's relation). The engine wires
  parent + blocking edges and pins the child's `decision_ref`.

**Scope discipline (binding on every skill):** anything discovered outside
the task's active specification becomes a generated task — never inline
work, never silent scope expansion.

**Never auto-execute:** applying your result ends your authority. Report
what was generated and each task's readiness; the human (or an explicit
orchestration request) decides what runs next.

## Ending a skill execution

Follow `taskforge/references/reporting.md` for the report and, on
terminal transitions of externally-sourced tasks,
`taskforge/references/sync.md` for sync-back.
