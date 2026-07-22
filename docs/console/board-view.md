# Human Console — Board View design

*The deliberately-least-interesting screen, and the one carrying the most
philosophical weight per pixel.*

Columns are the readiness vocabulary — `refine · explore · run · waiting ·
needs a human · terminal` — in workflow order. Every card sits in the column
`snapshot` says it does. "Needs a human" merges the two-clause queue rule
(parked + `readiness: "human"`) and links each card to its Home action;
`terminal` is collapsed by default.

**The board is read-only. Cards cannot be dragged.**

Kanban's core gesture — drag a card to change its state — is illegal here,
because columns are *derived* and statuses are *earned*: `done` requires an
approved review; `run` requires an active spec; `waiting` follows from edges.
A board where dragging "works" would reinstate self-assigned status through
the UI — the exact thing the engine was built to abolish. Instead, a card's
context menu offers only that card's real actions (the same derived action
list as Task Detail), and the engine's response moves the card — or refuses.

The board answers one question at a glance — "where is everything?" — and
hands off: click → Task Detail. Cards show title, id, parked badge,
blocked-by count. Parent/child renders as a stacked indicator on the parent
("3 children open"), not as separate swimlanes — near-duplicate parent/child
titles misread as duplicates in flat lists (the sourcegrid finding), and the
stack keeps decomposition legible without inventing board structure.

No WIP limits, no swimlanes, no aging indicators, no per-column counts
beyond what the snapshot trivially yields. Anything the board wants to add
must first answer: *which engine fact is this presenting?*
