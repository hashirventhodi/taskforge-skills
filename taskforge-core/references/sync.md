# Terminal sync-back

Applies when your apply made a task `done`, `cancelled`, or
`blocked_on_human` AND `source.type` is `github` or `jira`.

* Use whatever access this session has (MCP server, `gh` CLI, `jira` CLI,
  REST). The mechanism is yours; only the outcome matters.
* `done` — close the issue/ticket with a short comment: outcome, spec
  version satisfied, diff reference.
* `cancelled` — comment with the cancellation reason; close if the tracker's
  semantics allow.
* `blocked_on_human` — do NOT close. Comment with the concrete question or
  blocker so a human can answer where they work.
* **Honesty rule**: if no tracker access is available, say exactly that in
  your report ("not synced — no GitHub access in this session"). Never
  pretend a sync happened; never fake a URL.
* Progress updates before terminal states are out of scope.

Record nothing yourself — the engine's event history plus your report are
the record.
