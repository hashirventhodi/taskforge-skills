# Human Console — Task Detail design

*Designed against the `review-budget` fixture (richest chain: spec v1 /
impl v3 / review v3, 16 history events) and the `topology-proposal` fixture.
Excerpts are real fixture output.*

Task Detail is the **primary workspace**: Home is where a human discovers
what needs them; this screen is where they understand one task and act. It is
not `show <id>` in a browser — `show` returns facts flattened; this screen's
job is to restore the *story*.

Data: the task's snapshot row (already loaded) + `show <id>` and
`budget <id>` on open. Nothing else; no polling beyond the snapshot refresh.

## Layout

Header → the story (artifact chain as attempt cycles) → the ask (if parked)
→ actions → related tasks → raw timeline (collapsed).

### Header

Title · id · status · readiness with `readiness_detail` inline ("waiting —
blocked by TASK-x, TASK-y") · source (link out when `source.reference` is a
URL) · the immutable description, always visible. The description is the
ground truth of what was asked; every judgment on this screen is made against
it, so it never hides behind a click.

### The story — the artifact chain as cycles, not a list

The fixture's raw history is 16 events; the human's question is "why is this
parked?" The answer is a *pattern*: three implementations rejected on the
same criterion against one unchanged spec. The client groups stored facts
into cycles — no new derivation, pure presentation of `artifacts` + history:

```
decision      —                      (none)
specification v1  active             "reject over 4096 with a typed error"
  attempt 1   impl v1 → review v1    rejected: implementation — "guard fires at 4097, spec says over 4096"
  attempt 2   impl v2 → review v2    rejected: implementation — "guard fires at 4097…"
  attempt 3   impl v3 → review v3    rejected: implementation — "guard fires at 4097…"
budget        3/2 retries used → engine parked
```

Rendering rules, each cited to an engine fact:

- **Cascade order is the layout order** (decision → spec → impl → review):
  the chain reads top-down as the workflow ran.
- **Superseded versions collapse under their active version**, expandable;
  `superseded_reason` is the one-line label ("review found the boundary off
  by one"). History is never hidden, only folded.
- **An implementation+review pair is one visual unit** (an attempt): they
  arrive in the same result and are meaningless apart.
- **Repetition is highlighted**: when consecutive rejections carry
  similar findings, the screen should make the repetition visible (the
  fixture's three identical boundary findings are the entire diagnosis —
  spec ambiguity vs. bad implementation). Similarity is presentation;
  the findings are verbatim.
- **`budget <id>` renders as used/limit** ("3 of 2 retries — parked"), from
  the command, never computed client-side.
- **A `decision_ref` renders at the top of the chain** with its pinned
  version and a link to the parent's Decision: it is binding input, and a
  human reading this task must see what binds it.

### The ask

If parked: the same card the Home screen shows (same component, same
classification), so acting from either surface is identical.

### Actions — derived from state, never hardcoded

The action list is a function of engine facts; buttons the engine would
refuse are not offered (and if raced, the engine's refusal is shown
verbatim):

| Task state | Actions |
|---|---|
| `blocked_on_human` | the park's actions (approve / answer / redirect composer) |
| active, any | `cancel` (reason required) |
| `done` / `cancelled` | `reopen` (reason required) |
| any | copy id · open source reference |

There is deliberately **no** "edit status", "reassign", "set priority" —
states the engine doesn't have don't get controls.

### Related tasks

From the snapshot's normalized `edges[]`, filtered to this task, grouped by
type with direction phrased in words: "blocked by …", "child of …",
"generated from …", "pinned to decision v1 of …". Each links to its Task
Detail. Blocking edges first (they answer "why is this waiting"), provenance
after — same hierarchy the graph view uses.

### Raw timeline (collapsed by default)

The full `history[]`, verbatim, newest last — the audit trail for when the
story view isn't enough. Collapsed because the story section already *is*
the timeline, organized; but never absent, because the engine's history is
the authority and the human must always be able to see it unabridged.
