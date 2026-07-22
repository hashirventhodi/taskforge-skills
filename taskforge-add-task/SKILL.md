---
name: taskforge-add-task
description: Create normalized taskforge Tasks from any source - user text, GitHub issues, Jira tickets, markdown files, or documentation. Use whenever the user wants to add, create, import, capture, or track engineering work in the taskforge workflow ("add a task", "import issue #42", "track this bug", "turn these notes into tasks", "pull in the open issues"), including batch imports. Intake only - it never refines, plans, or executes; existing tasks are queried via taskforge-core.
---

# taskforge-add-task

Turn work from any source into normalized, durable Tasks. Intake only.

**Prerequisites**: read `taskforge-core/CONTRACTS.md` this session; resolve
`$SCRIPT` per its "Locating the engine" section (stop if unresolved).

## Procedure

### 1. Obtain source content

Mechanism is yours (MCP, `gh`/`jira` CLI, REST, file read); provenance is
the task's:

* **Manual** — the user's words are the content.
* **GitHub/Jira** — fetch title + full body; append materially-relevant
  comments under a `--- from comments ---` divider.
* **Markdown/docs** — one task per completable-and-reviewable work item, not
  per heading; ask before splitting a file into more than ~10 tasks.

Cannot access a referenced source? Stop and name the missing access. Never
invent content.

### 2. Normalize without editorializing

* `title` — one line, imperative, specific. The one field you compose.
* `description` — source text **verbatim** (immutable forever; downstream
  skills treat it as ground truth of what was asked). Trim only contentless
  boilerplate. No summarizing, restructuring, or interpretation — that is
  refine's job, and doing it here destroys the evidence refine needs for its
  adopt-vs-elaborate judgment.
* `source` — `--source-type` + `--source-ref`.

### 3. Create

```bash
python3 $SCRIPT create --title "..." --description-file /tmp/desc.txt \
  --source-type github --source-ref "https://github.com/org/repo/issues/42"
```

Use `--description-file` for anything beyond one line. Batch = one create
per item; collect ids from output.

### 4. Stated relationships only

If the source *explicitly* states a relationship ("blocked by #41",
"duplicate of PROJ-7") and the referenced task exists in the store, emit a
result with the canonical edge (`blocked_by`, or annotations like
`duplicate_of`), validate, apply with `--actor add-task`. Do not infer
unstated relationships; do not create tasks for out-of-store references.

### 5. Report

Per `taskforge-core/references/reporting.md`. A new task's readiness is
`refine` unless it arrived with blockers; name `taskforge-refine` as next
and stop.

## Quality bar

* Description diffed against the source shows no meaning added or removed.
* Ids only from engine output.
* No refinement leakage: no acceptance criteria, no scoping, no opinions.
