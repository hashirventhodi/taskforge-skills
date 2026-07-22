# Reviewer — reusable component (design §6)

## Usage protocol (for any skill convening a review)

1. Prepare exactly three inputs: the **active specification** (verbatim
   payload JSON, with its version number), the **diff** (full content, not a
   summary), the **test results**.
2. Fill the template below. Add nothing — the three slots are the complete
   review input; implementation narrative, plans, reasoning, or chat history
   are contamination that defeats independent review.
3. **Record before use** (verifiable isolation): save the filled prompt to a
   temp file and register it —
   `python3 $SCRIPT record-review-prompt <task-id> --version <N> <file>`
   where N is `next_review_version` from `python3 $SCRIPT budget <task-id>`.
   `audit-review <task-id>` later verifies the recorded prompt contains every
   acceptance criterion and none of the implementation summary.
4. Spawn a **fresh-context subagent** with the filled prompt. If no
   fresh-context mechanism is available in this session, **stop and say
   so** — a self-review from the implementer's context must never be
   recorded as a Review.
5. **Reviewer output retry policy**: if the output is not valid JSON per the
   contract below, re-ask exactly once, quoting the validation error and the
   schema. If still malformed, treat it as a review-system failure: emit
   `signal: block_on_human` with the raw output in `signal_reason`. Never
   guess a verdict; never downgrade to self-review.
6. Record the verdict verbatim as the review artifact — including rejections
   you disagree with (disagree in your report, not in the record).

---

## Template (fill the three slots; change nothing else)

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

## Specification (version {SPEC_VERSION})

{SPECIFICATION_JSON}

## Code diff

{DIFF}

## Test results

{TEST_RESULTS}
