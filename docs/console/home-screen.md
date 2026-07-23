# Human Console — Home screen design

*Designed against staged fixture snapshots (`scripts/make_fixtures.py`), not
wireframes: every element below is justified by a state the engine actually
produces. Excerpts in this document are real fixture output.*

The Console is the human actor's native seat, as the CLI + skills are the
AI's. Client rules (established in DESIGN §10.15 and the v0.5 architecture):
reads come from `snapshot` (plus `show <id>` on demand), writes are existing
engine commands only, readiness is never re-derived, the engine never
classifies — the client interprets.

## The queue: what belongs on the Home screen

Human attention is the scarce resource; the Home screen is the queue of
everything that needs it — and nothing else. Membership is defined by **two**
engine facts, not one:

1. `status == "blocked_on_human"` — a parked task (carries its
   `human_blocked` event in the snapshot), **or**
2. `readiness == "human"` — an *unparked* task the derivation routes to a
   human.

The second is not theoretical. The dependency-cycle fixture shows the engine
parks only the task it *detected* the cycle on; the other member stays
unparked and surfaces only through readiness:

```
dependency-cycle   UNPARKED  readiness=human  detail={"cycle": [A, B, A]}
dependency-cycle   PARKED    detail={"cycle": [B, A, B]}
```

A console filtering on status alone would show half the problem. The client
should merge cycle members into **one** card (their `cycle` arrays name the
same loop).

## Sections: three kinds of human act

The queue is one list sectioned by what the human is being asked to *do* —
approve, answer, or redirect. Classification is client-side (the engine
reports facts), but every discriminator is an engine fact from the
`human_blocked` event, verified across the fixtures:

| Observed facts (fixture output) | Cause | Section |
|---|---|---|
| `detail.cycle` present | dependency cycle | **Redirect** |
| `detail.enforced_by == "engine"`, `detail.kind` present | version breaker (`"specification reached v4; iteration is not converging"`) | **Redirect** |
| `detail.enforced_by == "engine"`, no `kind` | review budget (`"review retry budget exhausted (2 retries)…"`) | **Redirect** |
| `actor == "explore"` | decision proposal (topology or research disposition) | **Approve** |
| `actor == "refine"` or `"run"` | a question for the human | **Answer** |

The park **actor** is recorded correctly as of the attribution fix
(`apply_signal` passes the requesting actor through; engine enforcement parks
stay `tasks.py` + `enforced_by: "engine"`). Within the Approve section,
topology-proposal vs research-disposition is distinguished only by the
proposal *text* (the `TOPOLOGY PROPOSED…` / `DECISION IS THE DELIVERABLE…`
template headers) — a prompt convention, not an engine contract. The card
renders the reason verbatim either way; only the suggested action buttons
differ, and they degrade gracefully to the generic composer if the text
matches no known template.

Ordering within a section: `human_blocked.at` ascending — oldest ask first.
(An engine fact; no client-side urgency scoring.)

## Card anatomy

Everything on a card comes from the snapshot row; opening the card may fetch
`show <id>` for artifact payloads.

**All cards:** title · task id · time parked (`human_blocked.at`) · the ask
(`human_blocked.reason`, verbatim — it was written to be sufficient for a
one-message answer, so the card's body *is* the skill's own text). The ask
renders as markdown (principle 11) so its numbered decompositions and code
references read as such; the title stays literal.

**Approve — topology proposal** (fixture: SSO login). Context chip
`decision v1` from `active_artifacts`. The reason carries the numbered
decomposition and findings; the client renders the numbered list as
approve/adjust rows and each finding as promote/note/ignore. One decision the
human confirms, not N separate ones.

**Approve — research disposition** (fixture: ClickHouse). Same chip; the
reason carries the close / spawn+close / continue menu and explore's
recommendation. Three buttons.

**Answer — question** (fixture: WhatsApp 1024-char limit). No artifact chips
(`active_artifacts` all null — the fixture confirms a clarify park happens
*before* a spec exists). Reason text + a free-text answer box.

**Redirect — budget** (fixture: oversized-payload guard). Chips are the
story: `spec v1 · impl v3 · review v3` — three failed attempts at one spec.
The card should surface the latest review's findings (via `show`): the human
is deciding *why it keeps failing*, and the finding
(`"guard fires at 4097, spec says over 4096"`) is the evidence.

**Redirect — breaker** (fixture: webhook retries). Chip `spec v4`;
`detail.kind` names which artifact is churning. The human is deciding whether
the task is ill-posed.

**Redirect — cycle** (fixture: auth middleware ⇄ Redis sessions). One merged
card, both tasks named, the loop drawn from `detail.cycle`.

## Actions → commands

Every button is an existing engine command; the engine may refuse and the
console shows the refusal. No action changes state client-side.

| Card | Action | Command |
|---|---|---|
| Topology proposal | approve/adjust children, promote findings | `human-update <id> --note-file … --result …` (children + follow_ups as the human) |
| Topology proposal | reject the decision itself | `human-update` note → route to re-exploration |
| Disposition | close | `human-update … --result {"signal":"done"}` |
| Disposition | spawn + close | `human-update … --result {generated_tasks…, "signal":"done"}` |
| Disposition | continue | `human-update … --note-file …` (note only → refine) |
| Question | answer | `human-update … --note-file …` (+ `--result` if the answer dictates artifacts) |
| Budget / breaker | redirect with guidance | `human-update … --note-file …` (+ optional `--result`, e.g. a superseding spec) |
| Budget / breaker / any | abandon | `cancel <id> --reason-file …` |
| Cycle | resolve | see open question below |

## Empty state

The `quiet` fixture (nothing parked, nothing `readiness=human`) is a real
state and the *desired* one. The empty queue should say so and hand off:
"Nothing needs you — N tasks ready to run, M in refinement" (counts from the
same snapshot). The Console's success condition is showing this screen.

## Findings from the fixture pass

1. **Park attribution was wrong and is now fixed.** Skill-requested parks
   recorded `actor: "tasks.py"`; the history misattributed who parked.
   `apply_signal` now passes the actor through (test:
   `test_park_attribution`). This was found because the Home screen's
   sectioning needed the fact — the fixture-first method working as intended.
2. **Cycle membership needs readiness, not just status** (above). Queue
   membership is a two-clause rule.
3. **Open question — resolving a cycle has no clean command.** Edges can be
   added but never removed; today the human resolves a cycle by cancelling or
   re-scoping one of its tasks. Whether an edge-removal command is justified
   is a §10.14 two-condition question to take up *only if* real usage parks
   real cycles — not before.
4. **Template headers are conventions.** The Approve sub-types ride on
   prompt-template text. If a skill's proposal format evolves, the console's
   affordances degrade to the generic composer — acceptable, and exactly the
   coupling boundary we chose when we kept classification out of the engine.
