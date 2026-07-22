# Intake (`/taskforge add`)

Turn work from any source — user text, GitHub issues, Jira tickets, markdown
files, documentation — into normalized, durable Tasks. Intake only: never
refine, plan, or execute here; a new task's next stop is `taskforge-refine`.

## 1. Obtain source content

Mechanism is yours (MCP, `gh`/`jira` CLI, REST, file read); provenance is
the task's:

* **Manual** — the user's words are the content.
* **GitHub/Jira** — fetch title + full body; append materially-relevant
  comments under a `--- from comments ---` divider.
* **Markdown/docs** — one task per completable-and-reviewable work item, not
  per heading; ask before splitting a file into more than ~10 tasks.

Cannot access a referenced source? Stop and name the missing access. Never
invent content.

## 2. Normalize without editorializing

* `title` — one line, imperative, specific. The one field you compose.
* `description` — source text **verbatim** (immutable forever; downstream
  skills treat it as ground truth of what was asked). Trim only contentless
  boilerplate. No summarizing, restructuring, or interpretation — that is
  refine's job, and doing it here destroys the evidence refine needs for its
  adopt-vs-elaborate judgment.
* `source` — `--source-type` + `--source-ref`.

## 3. Create

```bash
python3 $SCRIPT create --title "..." --description-file /tmp/desc.txt \
  --source-type github --source-ref "https://github.com/org/repo/issues/42"
```

Use `--description-file` for anything beyond one line. Batch = one create
per item; collect ids from output.

## 4. Stated relationships only

If the source *explicitly* states a relationship ("blocked by #41",
"duplicate of PROJ-7") and the referenced task exists in the store, start
from `templates/intake-edges.json`, emit the canonical edge (`blocked_by`,
or annotations like `duplicate_of`), then validate and apply with
`--actor taskforge`. Do not infer unstated relationships; do not create
tasks for out-of-store references.

## 5. Report

Per `references/reporting.md`. A new task's readiness is `refine` unless it
arrived with blockers; name `taskforge-refine` as next and stop.

## Quality bar

* Description diffed against the source shows no meaning added or removed.
* Ids only from engine output.
* No refinement leakage: no acceptance criteria, no scoping, no opinions.
