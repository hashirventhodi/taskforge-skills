"""Review-prompt assembly, isolation auditing, and store maintenance.

The engine owns reviewer-prompt construction (``build_review_prompt``) so the
prompt the reviewer sees, and the canonical text ``audit_review`` checks, are
produced by one deterministic renderer — a client can never introduce a
serialization/escaping mismatch between them.
"""
import hashlib
import json

from engine import store
from engine.model import SCHEMA_VERSION, TERMINAL, active, record
from engine.readiness import evaluate

# The reviewer instruction preamble — the reviewer's *behavior*, held byte
# for byte. It is duplicated, verbatim, in references/reviewer-prompt.md for
# human readers; a doc-contract test asserts the two never diverge. Everything
# after it (the Specification / Code diff / Test results sections) is assembled
# per review by build_review_prompt.
REVIEWER_PREAMBLE = """\
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
(root_cause is required if and only if verdict is "rejected")"""

# Specification fields rendered into the prompt, in this fixed order. List
# fields become verbatim bullets; scalar fields a verbatim line. Order is
# fixed (not dict iteration order) so the render is a pure function of the
# payload — same spec -> same bytes -> same digest.
_SPEC_LIST_FIELDS = ("acceptance_criteria", "constraints",
                     "assumptions", "edge_cases")
_SPEC_LABELS = {
    "acceptance_criteria": "Acceptance criteria",
    "constraints": "Constraints",
    "assumptions": "Assumptions",
    "edge_cases": "Edge cases",
}


def _render_spec(version, payload):
    """Render a specification payload as VERBATIM labeled text.

    Deliberately not JSON. JSON string encoding escapes embedded quotes
    (``"failed"`` -> ``\\"failed\\"``) and, with ensure_ascii, non-ASCII
    (``—`` -> ``\\u2014``). audit_review checks each acceptance criterion by
    verbatim substring, so any escaping makes a genuinely-present criterion
    look absent — the exact false-negative this renderer removes. Canonical
    JSON (RFC 8785) fixes serialization *stability* but NOT escape-freedom, so
    it would not help here. Verbatim text is what makes the audit sound.
    """
    lines = [f"## Specification (version {version})", ""]
    scope = payload.get("scope")
    if scope:
        lines += ["Scope:", scope, ""]
    for field in _SPEC_LIST_FIELDS:
        items = payload.get(field) or []
        if items:
            lines.append(f"{_SPEC_LABELS[field]}:")
            lines += [f"- {item}" for item in items]
            lines.append("")
    if "adopted_from_source" in payload:
        lines += [f"adopted_from_source: "
                  f"{json.dumps(payload['adopted_from_source'])}", ""]
    return "\n".join(lines).rstrip() + "\n"


def build_review_prompt(task_id, diff, results, version=None):
    """Assemble and record the canonical reviewer prompt for a task.

    Renders PREAMBLE + the active specification (verbatim) + the diff + the
    test results, then records it (file + event + digest). The render is
    deterministic: the same
    (spec, diff, results) yields byte-identical output. ``version`` defaults
    to the next review version. Fails loudly if there is no active spec to
    review — a review with nothing to judge against is meaningless.
    """
    task = store.load(task_id)
    spec = active(task, "specification")
    if spec is None:
        from engine.model import TaskforgeError
        raise TaskforgeError(
            f"{task_id} has no active specification to review")
    if version is None:
        version = len(task["artifacts"].get("review", [])) + 1
    prompt = (
        f"{REVIEWER_PREAMBLE}\n\n"
        f"{_render_spec(spec['version'], spec['payload'])}\n"
        f"## Code diff\n\n{diff}\n\n"
        f"## Test results\n\n{results}\n"
    )
    return _record_prompt(task_id, version, prompt)


def _record_prompt(task_id, version, prompt_text):
    """Write a reviewer prompt to the audit dir and event-record its digest.

    Internal: build_review_prompt is the one public way to produce a review
    prompt. This low-level recorder exists for build to call and for the audit
    suite to inject adversarial prompts when testing that audit_review catches
    leaks and missing criteria independently of the renderer."""
    task = store.load(task_id)
    fname = f"{task_id}-review-v{version}.prompt.md"
    (store.audit_dir() / fname).write_text(prompt_text, encoding="utf-8")
    digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    record(task, "review_prompt_recorded", "tasks.py",
           detail={"version": version, "file": f"audit/{fname}",
                   "sha256": digest})
    store.save(task)
    return {"task": task_id, "version": version,
            "file": f"audit/{fname}", "sha256": digest}


def audit_review(task_id):
    """Deterministic isolation audit. For each review version:
    - a prompt must have been recorded before use (unrecorded => finding);
    - the recorded prompt must contain every acceptance criterion of the
      spec that review judged (verbatim);
    - it must NOT contain the paired implementation's summary text."""
    task = store.load(task_id)
    findings, checked = [], []
    for review in task["artifacts"].get("review", []):
        v = review["version"]
        fname = store.audit_dir() / f"{task_id}-review-v{v}.prompt.md"
        if not fname.exists():
            findings.append(f"review v{v}: no recorded prompt "
                            f"(isolation unverifiable)")
            continue
        prompt = fname.read_text(encoding="utf-8")
        events = [e for e in task["history"]
                  if e["type"] == "review_prompt_recorded"
                  and e["detail"].get("version") == v]
        if not events or events[-1]["detail"]["sha256"] != \
                hashlib.sha256(prompt.encode("utf-8")).hexdigest():
            findings.append(f"review v{v}: recorded prompt hash mismatch "
                            f"(file edited after recording)")

        spec = _artifact_at_or_before(task, "specification",
                                      review["created_at"])
        impl = _artifact_at_or_before(task, "implementation",
                                      review["created_at"])
        if spec:
            for crit in spec["payload"].get("acceptance_criteria", []):
                if crit not in prompt:
                    findings.append(
                        f"review v{v}: acceptance criterion missing from "
                        f"prompt: {crit!r}")
        if impl:
            summary = impl["payload"].get("summary", "")
            if summary and summary in prompt:
                findings.append(
                    f"review v{v}: implementation summary leaked into "
                    f"reviewer prompt (isolation violated)")
        checked.append(v)
    return {"task": task_id, "reviews_checked": checked,
            "findings": findings, "clean": not findings}


def _artifact_at_or_before(task, kind, timestamp):
    candidates = [a for a in task["artifacts"].get(kind, [])
                  if a["created_at"] <= timestamp]
    return max(candidates, key=lambda a: a["version"]) if candidates else None


# Doctor finding kinds. All but the last are *structural* (the task graph is
# malformed); `unaudited_review` is *process hygiene* (a review's isolation was
# never captured) — a different domain concept (Audit Status), separated so the
# presentation layer never conflates the two. See docs/PROJECTION_API.md.
STRUCTURAL_KINDS = ("unreadable", "future_schema", "dangling_edge",
                    "unresolved_ref", "dependency_cycle")


def doctor():
    findings = []
    ids = set()
    tasks_list = []
    future = []

    def add(kind, task, message):
        findings.append({"kind": kind, "task": task, "message": message})

    for p in sorted(store.store_dir().glob("TASK-*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
            tasks_list.append(t)
            ids.add(t["id"])  # a future-schema task still exists (not dangling)
        except (json.JSONDecodeError, KeyError) as exc:
            add("unreadable", p.stem, f"{p.name}: unreadable ({exc})")
    # Future-schema tasks are reported but NOT structurally validated — this
    # engine can't interpret data from a newer version (DESIGN §10.12). doctor
    # is the ONE path that sees them (operational scans skip them).
    for t in tasks_list:
        if store.is_future(t):
            future.append(t)
            add("future_schema", t["id"],
                f"{t['id']}: schema_version {t['schema_version']} is newer "
                f"than this engine ({SCHEMA_VERSION}) — run a newer taskforge "
                f"to operate on it; skipped by operational scans")
    for t in tasks_list:
        if t in future:
            continue  # can't validate structure this engine doesn't understand
        for e in t["edges"]:
            if e["target"] not in ids:
                add("dangling_edge", t["id"],
                    f"{t['id']}: dangling {e['type']} edge -> {e['target']}")
        ref = t.get("decision_ref")
        if ref:
            parent = next((x for x in tasks_list
                           if x["id"] == ref["task_id"]), None)
            versions = ([a["version"] for a in
                         parent["artifacts"].get("decision", [])]
                        if parent else [])
            if not parent or ref["version"] not in versions:
                add("unresolved_ref", t["id"],
                    f"{t['id']}: decision_ref -> {ref['task_id']} "
                    f"v{ref['version']} does not resolve")
        if t["status"] not in TERMINAL:
            ev = evaluate(t)
            if ev["readiness"] == "human":
                add("dependency_cycle", t["id"],
                    f"{t['id']}: dependency cycle "
                    f"{ev.get('cycle')} (will park on next step)")
        for review in t["artifacts"].get("review", []):
            fname = (store.audit_dir()
                     / f"{t['id']}-review-v{review['version']}.prompt.md")
            if not fname.exists():
                add("unaudited_review", t["id"],
                    f"{t['id']}: review v{review['version']} has no "
                    f"recorded reviewer prompt (audit-review will flag)")
    return {"tasks": len(tasks_list), "findings": findings,
            "clean": not findings}


def migrate():
    changed = []
    for t in store.all_tasks():
        if t.get("schema_version", 1) < SCHEMA_VERSION:
            # v1 -> v2: git-aware tasks gained a `delivery` block.
            t.setdefault("delivery",
                         {"branch": None, "pr": None, "landed_at": None})
            t["schema_version"] = SCHEMA_VERSION
            store.save(t)
            changed.append(t["id"])
    return {"schema_version": SCHEMA_VERSION, "migrated": changed}
