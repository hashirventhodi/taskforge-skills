# AGENTS.md — TaskForge

> **TaskForge is a deterministic workflow engine. Skills are thin interfaces
> over a single engine implementation. When in doubt, preserve engine
> simplicity and explicit contracts over convenience or abstraction.**

This is the constitution — load it before changing anything. The *reasoning*
lives in the linked documents, not here; this file only states the laws.

## Architecture in four lines

- Skills (prompts) perform engineering **judgment**; they never write task state.
- One deterministic engine (`taskforge/scripts/`) is the **sole writer** of
  task state, and **derives** routing ("readiness") rather than assigning it.
- The design is `DESIGN.md`; the rules every skill obeys are
  `taskforge/CONTRACTS.md`; the frozen public surface is `docs/PUBLIC_API.md`.

## The four invariants (never violate; reasoning in DESIGN §10)

- **Durability** — a circuit-breaker park overrides routing, never discards
  declared work.
- **Concurrency** — only one session may attempt stale-lock recovery, and only
  after re-confirming staleness.
- **Compatibility** — the public surface is the CLI, and deliberately small
  (`docs/PUBLIC_API.md`); internal structure is free to change.
- **Evolution** — an engine never interprets, mutates, or routes on data from
  a newer schema version than its own.

## Engineering process (how every change is made here)

1. Identify the underlying architectural principle.
2. State it as an invariant.
3. Implement the smallest solution that enforces it.
4. Prove it with a deterministic test — one that fails without the fix.
5. Record the reasoning: `DESIGN.md` §10 for decisions, `CHANGELOG.md` for changes.
6. Review before moving on.

Design-first: for anything non-trivial, agree the approach before writing code.

## What not to do

- Don't put deterministic rules in prompts. If code can enforce it, code does.
- Don't add a runtime dependency; the engine is stdlib-only, Python 3.8+.
- Don't grow the public surface without a real consumer (`docs/PUBLIC_API.md`).
- Don't land engine behavior without a test, or a decision without a record.
- Permanent non-goals: no daemon, no orchestrator, no vendored issue-tracker
  integration, no auto-execution of generated tasks.

Contributor mechanics are in `CONTRIBUTING.md`. Enforcement is automated —
the validator, the test suites, the doc-contract guards, and the repo hooks
(`scripts/hooks/`). `CLAUDE.md` covers how Claude should work here.
