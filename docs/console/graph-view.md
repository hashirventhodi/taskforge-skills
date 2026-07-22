# Human Console — Graph View design

*Designed against the real sourcegrid store (5 tasks, 10 edges) and the
`dependency-cycle` fixture. The findings that shaped this view came from real
data, not invention.*

The graph is TaskForge's substrate, not its headline: most tasks are isolated
nodes, and edge density maps exactly to where human judgment entered the
system (decomposition, dependencies, generated work — all human-approved).
The Graph View exists for the moments the structure *is* the question:
"what is blocking what", "where did this work come from", "what does this
decision bind".

## The one load-bearing rule: edge hierarchy

The sourcegrid store has 10 edges; only 2 (`blocked_by`) determine what
happens next. Rendering all edges equally makes the graph dense and mute.

| Edge | Rendering | Why |
|---|---|---|
| `blocked_by` | solid, directional, foreground | the only edge readiness reads — the execution skeleton |
| `parent` | quiet containment (indent/grouping or thin line) | membership, not flow |
| `generated_from` | faint, dashed, off by default | provenance — discoverable, not ambient |
| `decision_ref` | dotted, labeled `v N`, toggleable | binding input; the label makes a stale pin *visible* before the cascade fires |
| annotations (`relates_to`, …) | off by default | metadata |

Nodes: title (truncated), readiness as color, parked badge. Node size and
position carry no meaning — no invented metrics.

## Cycles

A `blocked_by` cycle renders as an error state: the loop's edges highlighted,
both members marked, one click to the merged Home card. The unparked member
(`readiness: "human"`, the fixture's finding) is drawn as urgently as the
parked one — the graph must not understate half the problem.

## Interaction

Click → Task Detail. Hover → full title + readiness reason. Filter by
readiness (the same vocabulary everywhere). No drag-to-connect: edges are
topology, topology is human-approved *through results*, and inventing a
gesture that writes edges would recreate the drag-a-card problem — if edge
creation ever gets UI it is a composer that emits a result via
`human-update --result`, engine-refusable like everything else.

Layout: simple layered placement — roots (unblocked) left, dependents
rightward along `blocked_by`; disconnected nodes in a quiet grid below.
Deterministic for the same snapshot (no physics simulation, no jitter):
the same store must always draw the same picture.
