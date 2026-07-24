# TaskForge Architecture

The canonical map of where code — and especially *logic* — belongs. Three
layers, each with one job. When you're unsure where something goes, this
document is the answer.

```
                    ┌─────────────────────────────────────┐
                    │  ENGINE                              │  state + rules
                    │  the single source of truth          │  (the only writer)
                    │  model · store · readiness · apply · │
                    │  delivery · audit · validation       │
                    └──────────────────┬──────────────────┘
                                       │  read-only
                    ┌──────────────────▼──────────────────┐
                    │  PROJECTION API                      │  presentation truth
                    │  pure composition of engine facts    │  (no business logic)
                    │  task · feature · review · health ·  │
                    │  digest · board                      │
                    └──────────────────┬──────────────────┘
                                       │  typed, serializable data
        ┌──────────────┬───────────────┼───────────────┬──────────────┐
        ▼              ▼               ▼               ▼              ▼
     Web UI          CLI            MCP             IDE          desktop / …
   (adapter)      (adapter)      (adapter)       (adapter)      (adapter)
                    render only — no business or presentation logic of their own
```

## The three layers

### 1. Engine — state and rules

The single source of truth. It owns **stored state** and **every business
rule**: readiness routing, delivery resolution, the landing rule, review
budgets, capability enforcement, integrity. It is the **only writer**. Its
stable surface is the CLI (`docs/PUBLIC_API.md`); its design record is
`DESIGN.md`.

*Logic that belongs here:* anything that decides, enforces, derives, or mutates
domain state. If two clients could disagree about the answer, the answer lives
here — computed once, exposed as a fact.

### 2. Projection API — presentation truth

A pure, deterministic, **read-only** layer (`taskforge/scripts/projections.py`,
contract in `docs/PROJECTION_API.md`) that composes engine reads into typed,
JSON-serializable projections built around **domain concepts, one meaning per
field** (Structural Integrity, Review Result, Audit Status, Delivery Status).

It is the source of truth for **how humans consume** engine state, as the
engine is for the state itself. It **never** contains business logic: it
filters, groups, joins, and formats, but never re-derives a rule the engine
owns. It knows nothing about any client — no HTML, colors, terminal codes, or
HTTP.

*Logic that belongs here:* composing existing facts into the shape a decision
needs — grouping the board by readiness, rolling up audit status over a
feature, joining a criterion to its result. Never a new rule.

### 3. Presentation adapters — render only

Each client renders the projections in its medium and does nothing else. The
Web UI draws screens; the CLI prints text; an MCP server exposes tools; an IDE
plugin shows panels. They **share terminology and semantics** because they read
the same contracts. An adapter maps projection *state* to its own visual
vocabulary (a pill, a colour, a table row) — that mapping is the only thing an
adapter is allowed to decide.

*Logic that belongs here:* presentation only — how `readiness: "run"` looks as
a button vs. a coloured word vs. a tool name. Nothing that another adapter would
need to reproduce.

## Where does my change go?

- **A new rule, state field, or enforcement** → engine (then expose it as a
  fact; see how `landing_status` is owned by the engine and merely surfaced by
  projections).
- **A new answer a human needs that's derivable from existing facts** → an
  **additive** projection field or a new projection. Never a client.
- **A new way to *show* an existing projection** → the relevant adapter only.
- **You're about to re-derive an engine rule in a projection or client** →
  stop. Move the rule (or its exposure) into the engine.
- **You're about to add client-specific logic to make the API fit** → stop.
  The Projection API needs an additive improvement instead.

## Invariants

- **One writer.** Only the engine mutates state.
- **One derivation.** A rule is computed once, in the engine; clients never
  reproduce it (two derivations drift).
- **Frozen, additive contract.** The Projection API is a public contract
  (`docs/PROJECTION_API.md`, v1). It evolves additively; breaking changes are a
  major event, and client-specific forks are never allowed.
- **Adapters are interchangeable.** Any client — Web, CLI, or one that doesn't
  exist yet — consumes the same projections unchanged. That interchangeability
  is the test that the layering is intact.

## Reference documents

- `DESIGN.md` — engine design record (numbered decisions, §10.x).
- `docs/PUBLIC_API.md` — the engine's stable CLI contract.
- `docs/PROJECTION_API.md` — the Projection API contract (the presentation truth).
- `docs/console/design-principles.md` — the Web UI host server's client rules.
