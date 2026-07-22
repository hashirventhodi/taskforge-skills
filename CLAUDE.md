# CLAUDE.md — working in this repository

The project's laws and philosophy are in **`AGENTS.md`** — read it first.
This file is only *how to work here*; it deliberately holds no architecture.

## Design-first

For any non-trivial change, propose the design and its tradeoffs and agree the
direction before implementing — bug fixes included. Fix the principle, not the
symptom (see the engineering process in `AGENTS.md`).

## Which document for which change

| Changing… | Update | And |
|---|---|---|
| engine behavior | `taskforge/CONTRACTS.md` (if a skill relies on it) | a `taskforge/tests/` test + a `DESIGN.md` §10 record |
| a public output shape or command | `docs/PUBLIC_API.md` | `TestPublicOutputContract` |
| a skill's prompt | that `SKILL.md` | (the validator runs on save) |
| a workflow rule, template, or reference | the file (+ `taskforge/CONTRACTS.md` if shared) | keep the doc-contract suite green |
| a decision or its rationale | `DESIGN.md` §10 | `CHANGELOG.md` |

## Before a change is done

Enforcement is automated, so this list is short:

- The scoped checks run on stop (advisory) and in CI (blocking): the engine
  suite, `scripts/validate_skills.py`, and the doc-contract suite. A full
  local run is
  `python3 -m unittest discover taskforge/tests && python3 -m unittest discover tests && python3 scripts/validate_skills.py`.
- Engine behavior has a test that fails without the fix; the decision is recorded.

Enforcement lives in code and hooks, not in this file. Keep it that way.
