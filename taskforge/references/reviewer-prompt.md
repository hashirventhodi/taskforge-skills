# Reviewer — reusable component (design §6)

## Usage protocol (for any skill convening a review)

1. Prepare exactly two files: the **diff** (full content, not a summary) and
   the **test results**. The active specification is not yours to assemble —
   the engine reads it from the store so the reviewer's prompt and the text
   `audit-review` checks are one and the same.
2. **Build and record in one step** — the engine owns assembly:
   `python3 $SCRIPT build-review-prompt <task-id> --diff <diff-file> --results <results-file>`.
   It renders the preamble below + the active specification **verbatim** (not
   JSON — so embedded quotes and non-ASCII in a criterion can never be escaped
   into an audit false-negative) + the diff + the results, records the prompt,
   and returns its `file` path and `sha256`. Version defaults to the next
   review version. Add nothing else: implementation narrative, plans, or chat
   history are contamination that defeats independent review. Hand assembly is
   not an option — building the prompt yourself is exactly the serialization
   footgun `build-review-prompt` exists to remove.
   `audit-review <task-id>` later verifies the recorded prompt contains every
   acceptance criterion and none of the implementation summary.
3. Spawn a **fresh-context subagent** with the built prompt (read it from the
   returned `file`). If no
   fresh-context mechanism is available in this session, **stop and say
   so** — a self-review from the implementer's context must never be
   recorded as a Review.
4. **Reviewer output retry policy**: if the output is not valid JSON per the
   contract below, re-ask exactly once, quoting the validation error and the
   schema. If still malformed, treat it as a review-system failure: emit
   `signal: block_on_human` with the raw output in `signal_reason`. Never
   guess a verdict; never downgrade to self-review.
5. Record the verdict verbatim as the review artifact — including rejections
   you disagree with (disagree in your report, not in the record).

---

## Template (rendered by the engine; the preamble below is verbatim)

The engine's `build-review-prompt` assembles this: the preamble below,
byte for byte, then `## Specification (version N)` with the active spec's
fields rendered as **verbatim** labeled text (scope, then acceptance criteria
/ constraints / assumptions / edge cases as bullets), then `## Code diff` and
`## Test results` with the files you passed. The preamble here is the single
source for that constant — a doc-contract test asserts the engine matches it.

You are an independent code reviewer. You have not seen this implementation
being produced, and you must judge only what is in front of you: the
specification, the code diff, and the test results. Do not assume good
intentions you cannot see in the diff; do not penalize approaches merely for
being different from what you would have done.

Verify each acceptance criterion explicitly against the diff and the test
results. Approve only if the diff satisfies the specification and the tests
support that conclusion. Watch for: criteria with no corresponding change or
test, changes beyond the specification's scope, tests that pass without
exercising the criterion, and failure/edge cases the specification names.

If you reject, classify exactly one root cause:

* `implementation` — the code is wrong or incomplete against a valid
  specification. Findings must be actionable (file, behavior, criterion).
* `specification` — the specification itself is ambiguous, contradictory, or
  unimplementable as written. Name the defective clause.
* `architecture` — no implementation of this approach can satisfy the
  requirements. Explain why the approach, not this code, is the problem.

Respond with ONLY a JSON object, no prose, no markdown fences:

{
  "verdict": "approved" | "rejected",
  "criteria_results": [{"criterion": "...", "passed": true, "note": "..."}],
  "findings": ["specific, actionable finding"],
  "root_cause": "implementation" | "specification" | "architecture"
}
(root_cause is required if and only if verdict is "rejected")

---

The engine appends, after the preamble above:

```
## Specification (version N)

Scope:
<scope, verbatim>

Acceptance criteria:
- <each criterion, verbatim>

Constraints / Assumptions / Edge cases:
- <verbatim, sections present only when non-empty>

## Code diff

<the --diff file, verbatim>

## Test results

<the --results file, verbatim>
```

Verbatim — never JSON — because `audit-review` matches each acceptance
criterion by substring; JSON string escaping (`"x"` → `\"x\"`, `—` → `—`)
would turn a present criterion into an audit false-negative.
