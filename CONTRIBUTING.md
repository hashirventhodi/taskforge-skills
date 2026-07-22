# Contributing to taskforge-skills

Thanks for considering a contribution. This project has an unusually strict
architecture, and most review friction comes from not knowing it up front —
so please read the invariants below before opening a PR.

## The invariants

These are not style preferences. A change that breaks one of them will be
asked to change direction, however well written it is.

1. **The engine is the only writer of task state.** Skills reason, fill a
   `result.json`, and hand it to `tasks.py`. Nothing else may write under
   `.tasks/`. Hand-editing task JSON silently defeats versioning,
   invalidation cascades, readiness, capabilities and the event log.
2. **Deterministic mechanics never live in prompts.** If a rule can be
   enforced by code, a prompt may explain it but must never be its
   enforcement. Anything a probabilistic system could "forget" belongs in
   the engine.
3. **The engine is stdlib-only.** No runtime dependencies, ever — the skills
   must run wherever Python does. Development and CI tooling may use
   dependencies (`scripts/validate_skills.py` uses PyYAML when present).
4. **Python 3.8+.** CI tests every minor version from 3.8 up.
5. **`taskforge-core` travels with every skill.** All skills resolve the
   engine through it as a sibling directory. Never add a resolution path
   that assumes one specific agent.

`taskforge-core/CONTRACTS.md` is the authoritative architecture document and
`DESIGN.md` §10 records which decisions were already argued and overturned —
worth checking before proposing a change to the model.

## Getting set up

No install step. Clone it and run:

```bash
python3 -m unittest discover taskforge-core/tests   # 41 tests, must pass
python3 scripts/validate_skills.py                  # frontmatter validation
pip install pyyaml                                  # optional, sharper validation
```

To test as a user would, install from your working tree:

```bash
cd /tmp && mkdir demo && cd demo && git init -q
npx skills add /path/to/your/taskforge-skills --agent claude-code
```

## Before you open a PR

- [ ] `python3 -m unittest discover taskforge-core/tests` passes
- [ ] `python3 scripts/validate_skills.py` passes
- [ ] New engine behaviour has a test — engine changes are not accepted
      without one, because the engine is the thing prompts are allowed to
      trust
- [ ] Docs updated if you changed behaviour: `CONTRACTS.md` for anything a
      skill relies on, `DESIGN.md` for an architectural decision, `README.md`
      for anything user-facing
- [ ] Commit messages explain *why*, not just what

## Changing a SKILL.md

Frontmatter must satisfy the Agent Skills spec: `name` and `description` as
strings, `name` lowercase-hyphenated and identical to its directory.

**Watch the description field.** It is a plain YAML scalar, so an unquoted
`: ` inside it makes the parser read a nested mapping and the skills CLI
skips the entire skill — with one warning line, still exiting 0. This has
already happened once in this repo. Use a dash instead, or quote the whole
value. `scripts/validate_skills.py` catches it; CI runs the validator plus a
real `npx skills add` and asserts all five skills land.

Descriptions should be trigger-phrase-rich — they are how an agent decides
to invoke the skill — and stay under 1024 characters.

## Adding a new skill

Add `taskforge-<name>/SKILL.md` following the conventions in `CONTRACTS.md`,
plus an entry in `taskforge-core/capabilities.json` granting the actor only
the artifacts, relations and signals it needs (deny-by-default). No existing
skill should need to change.

New **artifact kinds or relation types** are engine changes, not skill
changes: they carry cascade and readiness semantics, so they need engine
tests and a `schema_version` consideration.

## Scope

Permanent non-goals — please don't send PRs for these: a daemon, an
orchestrator, or vendored GitHub/Jira integration code. Intake and sync-back
are deliberately instructions over whatever MCP or CLI a session already has.

## Reporting bugs

Open an issue with the template. For anything involving task state, include
the output of `python3 <path>/tasks.py doctor` — it is designed to make
store corruption legible.

## License

Contributions are licensed under the MIT License, matching the project.
