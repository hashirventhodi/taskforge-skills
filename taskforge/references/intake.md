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

Title and description are source-derived text — **always pass both by file**
(CONTRACTS.md → "Untrusted text is data"). Write the files with your editor
tool, never via `echo`/heredoc interpolation:

```bash
python3 $SCRIPT create --title-file /tmp/title.txt \
  --description-file /tmp/desc.txt \
  --source-type github --source-ref "https://github.com/org/repo/issues/42"
```

Batch = one create per item; collect ids from output.

Add `--explore` for a **research topic** (the hub's `explore <topic>`): the
task initializes the existing pending-explore flag and routes to
`taskforge-explore` for a Decision instead of to refine. A short topic you
composed yourself may use the inline `--title`/`--description` forms; the file
forms stay mandatory for any source-derived text.

## 4. Stated relationships only

If the source *explicitly* states a relationship ("blocked by #41",
"duplicate of PROJ-7") and the referenced task exists in the store, start
from `templates/intake-edges.json`, emit the canonical edge (`blocked_by`,
or annotations like `duplicate_of`), then validate and apply with
`--actor taskforge`. Do not infer unstated relationships; do not create
tasks for out-of-store references.

## 5. Report

Per `references/reporting.md`. A new task's readiness is `refine` unless it
arrived with blockers (`waiting`) or was created `--explore` (`explore`); name
the skill that readiness points to — `taskforge-refine`, or `taskforge-explore`
for a research topic — and stop.

## Quality bar

* Description diffed against the source shows no meaning added or removed.
* Ids only from engine output.
* No refinement leakage: no acceptance criteria, no scoping, no opinions.
