# Human Console — design principles

The Console is the human actor's native seat, as the CLI + skills are the
AI's: two peer clients of one deterministic engine. These rules govern every
screen; each exists because a specific failure mode was identified before a
pixel was drawn. Screen designs cite them; changes to them belong here, once.

1. **Reads come from `snapshot` (+ `show <id>` on demand).** Never from raw
   store files. The snapshot's provenance rule (DESIGN §10.15) is the bar for
   wanting more data: if the field you're missing isn't stored state, derived
   state, or snapshot metadata, you're about to put logic in the client.

2. **Every write is an existing engine command.** A button is a command with
   a nicer surface; the engine may refuse, and the refusal is shown verbatim.
   If a desired interaction can't be expressed as an existing command, that
   is a design smell to investigate — never a missing endpoint to invent.

3. **Readiness is data, never logic.** The client neither re-derives routing
   nor extends it. Two derivations drift; there is one, and it is the
   engine's.

4. **The engine reports facts; the client interprets; the human judges.**
   Sectioning, grouping, similarity, emphasis — interpretation — is client
   work over verbatim facts (the park queue's sections, the attempt-cycle
   story). The client never *decides*: no auto-approve, no default
   disposition, no urgency scoring.

5. **States the engine doesn't have don't get controls.** No drag-to-column,
   no edit-status, no priority field. The UI's vocabulary is exactly the
   engine's.

6. **Human attention is the scarce resource.** The Home screen is the queue
   of what needs a human — membership by the two-clause rule
   (`blocked_on_human` OR `readiness: "human"`) — and the empty queue is the
   product's success state, not a blank page.

7. **History is never hidden, only folded.** Superseded versions collapse,
   the raw timeline collapses; nothing is omitted. The engine's history is
   the authority and must always be reachable unabridged.

8. **Untrusted text is data here too.** Anything a human types in the
   Console (notes, reasons) reaches the engine by file-input flags
   (`--note-file`, `--reason-file`), exactly as CONTRACTS mandates for
   source-derived text in skills.

9. **Local, single-user, loopback-bound.** No accounts, no remote access, no
   database, no websockets — until real usage demonstrates the need, and
   each would then face the same two-condition scrutiny as an engine concept.

10. **Designed against fixtures, not wireframes.** Every screen element is
    justified by a state the engine actually produces
    (`scripts/make_fixtures.py`); the fixtures are the design's test data and
    its living spec. A proposed element with no producing state is invented
    behavior.
