## What and why

<!-- What changes, and what problem it solves. Link any issue. -->

## Invariants

<!-- See CONTRIBUTING.md. Tick what applies; explain anything you cannot. -->

- [ ] The engine remains the only writer of task state
- [ ] No runtime dependency added (the engine stays stdlib-only)
- [ ] No deterministic rule moved into a prompt
- [ ] No agent-specific path assumption added

## Verification

- [ ] `python3 -m unittest discover taskforge-core/tests` passes
- [ ] `python3 scripts/validate_skills.py` passes
- [ ] Engine behaviour changes are covered by a new test
- [ ] Docs updated (`CONTRACTS.md` / `DESIGN.md` / `README.md`) if behaviour changed

<!-- If you changed a SKILL.md description, note that an unquoted ': '
     inside it makes the skills CLI skip the skill entirely. -->
