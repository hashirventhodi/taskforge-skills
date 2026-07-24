# Public API — the stability contract

> **TaskForge defines the smallest stable public surface necessary for
> interoperability. Anything not explicitly listed in this document is
> considered internal and may change between releases without notice.**

`CONTRACTS.md` answers *"how does the engine behave?"* (the skill-runtime
contract). This document answers a different question for a different
audience — maintainers and external tooling: *"what are we promising never
to break?"*

Every stable element below exists because something depends on it. A field
that no consumer reads is not part of the contract, however long it has
existed. The contract is deliberately small; a smaller contract is a stronger
one. The enforcement is `taskforge/tests/test_engine.py::TestPublicOutputContract`,
and a doc-contract guard keeps this document and that test from diverging.

## Semantic versioning policy

The **CLI** is the versioned surface. Under SemVer (while in 0.x, a breaking
change is a minor bump; from 1.0 on, a major bump):

- **Backward-compatible (minor/patch):** adding a new subcommand, adding a new
  key to an output object, adding a new optional flag, adding a new value to a
  vocabulary *only where consumers tolerate unknowns*, improving an
  informational message.
- **Breaking (major):** removing or renaming a stable subcommand, flag, output
  key, or `--actor`; changing the type or meaning of a stable output key;
  changing exit-code semantics; removing a value from the readiness routing
  vocabulary.

## Stable surface

### Subcommands

The subcommand **names** are stable: `create`, `show`, `list`, `readiness`,
`blocked-by`, `budget`, `validate`, `apply`, `human-update`, `cancel`,
`reopen`, `build-review-prompt`, `audit-review`, `config`, `doctor`,
`migrate`, `snapshot`. (Guarded both ways against the engine by the
doc-contract suite.)

### Exit-code semantics

- `0` — success; the machine-readable result is JSON on **stdout**.
- non-zero — failure; nothing is written to stdout. An engine/contract error
  exits `1` with `{"error": "<message>"}` on **stderr**; a CLI usage error
  (unknown command, missing argument) also exits non-zero.

### Stable output keys

Only these keys are frozen. Each command may emit **additional** keys that are
*not* part of the contract (see Non-goals); consumers must ignore unknown keys.

| Command | Frozen key(s) | Meaning |
|---|---|---|
| `readiness <id>` | `readiness` | the routing value (string, see vocabulary) |
| `list` | each row: `id`, `readiness` | the backlog — one row per task the engine can operate on (future-schema tasks are excluded and surfaced by `doctor`; see directional compatibility, DESIGN §10.12) |
| `budget <id>` | `next_review_version` | integer ≥ 1; the version the next reviewer prompt is recorded under |
| `apply` (result) | `status`, `readiness`, `generated_tasks` | new status, routing value (string), and the ids of tasks created by the result |
| `blocked-by <id>` | *(array)* | JSON array of task-id strings blocked by `<id>` |
| `doctor` | `clean` | boolean; store integrity |
| `validate` | `warnings` | array of non-fatal observations (validity is the exit code) |
| `snapshot` | `snapshot_version`, `tasks`, `edges`, `skipped`; task rows: `id`, `status`, `readiness`, and `human_blocked` (parked tasks only — the latest stored `human_blocked` event, verbatim); edge rows: `type`, `from`, `to` | the read model: one atomic, deterministic projection of the store, taken under the store lock. `edges` flattens every stored edge **plus `decision_ref` normalized as an edge** (`type: "decision_ref"`, with `version`); `skipped` lists tasks this engine cannot read (`future_schema` / `unreadable`) so the snapshot never silently omits part of the world. Every field is stored state, derived state via existing engine logic, or snapshot metadata — nothing else (DESIGN §10.15) |

**`readiness` is always the routing string** — its one meaning across the
entire CLI. Diagnostic detail (why a task routes where it does) is available
only from the dedicated `readiness <id>` command, which additionally returns
informational fields (see Non-goals).

The frozen output-key set is machine-checked against the contract test — this
list and `TestPublicOutputContract.PUBLIC_OUTPUT_KEYS` must match exactly, or
the doc-contract suite fails:

<!-- machine-checked: must equal PUBLIC_OUTPUT_KEYS in TestPublicOutputContract -->
```
id
readiness
next_review_version
status
generated_tasks
clean
warnings
snapshot_version
tasks
edges
skipped
human_blocked
type
from
to
```

### Readiness routing vocabulary

The `readiness` value is one of: `refine`, `explore`, `run`, `waiting`,
`terminal`, `human`. This is the routing contract every skill guards on. These
values are also the accepted arguments to `list --readiness <value>`.

### Actor vocabulary

The `--actor` names are stable and defined in `taskforge/capabilities.json`
(the authoritative registry): `taskforge`, `refine`, `explore`, `run`,
`human`.

## Non-goals — explicitly internal, free to evolve

These exist today but are **not** part of the contract. Contributors may
change them between releases without a breaking-change bump. They are listed
so that freedom is explicit.

- **The Python facade.** `tasks.py`'s re-exported functions and every
  `engine/` module, class, and helper are an internal import surface for
  in-repo tests and tooling — never a supported import. Depend on the CLI.
- **Storage layout.** The `.tasks/` directory, per-task JSON shape, the
  `.lock`/`.lock.break` files, and `audit/` are internal. The stored task
  shape evolves under `schema_version` + `migrate`, not under this contract.
- **Diagnostic / informational output.** `readiness`'s `reason`,
  `blocking_ids`, and `cycle`; `budget`'s `max_review_retries`,
  `total_reviews`, `review_rejections_in_current_cycle`; the `config` key set;
  and the convenience projection in create/show/cancel/reopen output
  (`title`, `active_artifacts`, `pending_escalation`, `edges`, `source`).
  These serve human-facing narration and may change in wording, shape, or
  presence. For authoritative task data, read `show <id>`.
- **Result-application internals.** `apply`'s `applied`, `duplicate_of`,
  `note`, and `warnings` keys communicate idempotency/validation detail, not
  a frozen contract.
- **Snapshot informational fields.** `generated_at`, `store`, and each task
  row's `readiness_detail` (the same diagnostic detail `readiness <id>`
  returns — `readiness` itself stays the bare routing string everywhere) plus
  the convenience projection fields (`title`, `active_artifacts`,
  `pending_escalation`, `decision_ref`, `source`, timestamps). Additions to
  the snapshot must satisfy the provenance rule (stored / derived-by-existing-
  logic / snapshot metadata — DESIGN §10.15); a field that fails it is
  presentation logic and belongs in a client.
- **Error message wording.** Exit codes and the presence of `{"error": …}` on
  stderr are stable; the message text is not.
