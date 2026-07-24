# Terminal sync-back

Applies when `source.type` is `github` or `jira` and either your apply made a
task `done`, `cancelled`, or `blocked_on_human`, **or** you just recorded a
`landed` fact (`link --landed`).

* Use whatever access this session has (MCP server, `gh` CLI, `jira` CLI,
  REST). The mechanism is yours; only the outcome matters.
* `done` — **comment, do NOT close.** `done` means the work was reviewed and
  accepted; it does **not** mean the code merged. Comment the outcome: spec
  version satisfied, the PR reference (from `resolved_delivery.pr`), review
  verdict. The issue closes only when the code lands (next bullet).
* `landed` — the task's **resolved** delivery merged: `resolved_delivery.
  landed_at` is set (because the task, or the feature it delivers through,
  had `link --landed` recorded). **Now** close the issue/ticket with a short
  comment: outcome, spec version, merged-PR reference. This is the single
  point at which an external issue closes — keyed on the merge fact the engine
  holds, never on task-`done`. A child with its own source issue closes when
  its owning feature lands (delivery is resolved up the parent chain, DESIGN
  §10.19); most children are internal and have no issue to close.
* `cancelled` — comment with the cancellation reason; close if the tracker's
  semantics allow.
* `blocked_on_human` — do NOT close. Comment with the concrete question or
  blocker so a human can answer where they work.
* **Honesty rule**: if no tracker access is available, say exactly that in
  your report ("not synced — no GitHub access in this session"). Never
  pretend a sync happened; never fake a URL.
* Progress updates between these points are out of scope.

Record nothing about the sync itself — the engine's event history (the
`landed` event included) plus your report are the record.
