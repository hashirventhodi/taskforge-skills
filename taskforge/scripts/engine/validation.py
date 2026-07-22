"""Boundary validation: everything checked before any mutation.

`validate_result` is pure (writes nothing) and is called both by the CLI
`validate` subcommand and by `apply` — so validate-then-apply and apply-only
enforce identical rules by construction.
"""
from engine import store
from engine.model import (FORBIDDEN_EDGES, KINDS, REASON_REQUIRED_SIGNALS,
                          RELATIONS, RESULT_KEYS, SIGNALS, TERMINAL,
                          TaskforgeError, active)


def validate_edge_type(t: str) -> str:
    t = (t or "").strip().lower()
    if not t or not t.replace("_", "").isalnum():
        raise TaskforgeError(
            f"edge type must be a snake_case identifier, got {t!r}")
    if t in FORBIDDEN_EDGES:
        raise TaskforgeError(
            f"edge type {t!r} is a non-canonical inverse; store the canonical"
            f" direction ({FORBIDDEN_EDGES[t]!r}) on the task that owns it")
    return t


def validate_payload(kind, p):
    if not isinstance(p, dict) or not p:
        raise TaskforgeError(
            f"artifact {kind} requires a non-empty object payload")

    def need(fields):
        missing = [f for f in fields if not p.get(f)]
        if missing:
            raise TaskforgeError(
                f"{kind} payload missing required fields: {missing}")
    if kind == "decision":
        need(["chosen_approach", "rationale"])
    elif kind == "specification":
        need(["scope", "acceptance_criteria"])
        if not isinstance(p["acceptance_criteria"], list) \
                or not p["acceptance_criteria"]:
            raise TaskforgeError(
                "specification.acceptance_criteria must be a non-empty list")
        p.setdefault("adopted_from_source", False)
    elif kind == "implementation":
        need(["summary", "diff_ref"])
    elif kind == "review":
        if p.get("verdict") not in {"approved", "rejected"}:
            raise TaskforgeError(
                "review.verdict must be 'approved' or 'rejected'")
        if p["verdict"] == "rejected" and p.get("root_cause") not in {
                "implementation", "specification", "architecture"}:
            raise TaskforgeError(
                "a rejected review must classify root_cause as "
                "implementation|specification|architecture")


def validate_result(result: dict, actor: str, task=None) -> list:
    """Full structural + capability + coherence validation. Returns a list
    of non-fatal warnings; raises TaskforgeError on any violation. Pure."""
    warnings = []
    if not isinstance(result, dict):
        raise TaskforgeError("result must be a JSON object")
    unknown = set(result) - RESULT_KEYS
    if unknown:
        raise TaskforgeError(f"unknown result keys: {sorted(unknown)}")

    caps = store.capabilities()
    if actor not in caps:
        raise TaskforgeError(
            f"unknown actor {actor!r}: add it to taskforge/"
            f"capabilities.json to grant capabilities (deny-by-default)")
    cap = caps[actor]

    def allowed(field, value):
        allow = cap.get(field, [])
        return allow == "*" or value in allow

    if not result.get("result_id"):
        warnings.append("result has no result_id; double-apply protection "
                        "is disabled for this result")

    signal = result.get("signal", "none")
    if signal not in SIGNALS:
        raise TaskforgeError(f"unknown signal: {signal!r}")
    if not allowed("signals", signal):
        raise TaskforgeError(
            f"actor {actor!r} may not emit signal {signal!r} "
            f"(allowed: {cap.get('signals')})")
    if signal in REASON_REQUIRED_SIGNALS and not result.get("signal_reason"):
        raise TaskforgeError(f"signal {signal!r} requires signal_reason")

    arts = result.get("artifacts", [])
    if not isinstance(arts, list):
        raise TaskforgeError("artifacts must be a list")
    for a in arts:
        kind = a.get("kind")
        if kind not in KINDS:
            raise TaskforgeError(f"unknown artifact kind: {kind!r}")
        if not allowed("artifacts", kind):
            raise TaskforgeError(
                f"actor {actor!r} may not produce {kind!r} artifacts "
                f"(allowed: {cap.get('artifacts')})")
        validate_payload(kind, a.get("payload"))

    # Verdict/signal coherence: done requires the review that will be active
    # after this result to be an approval. Binds capability-constrained
    # actors (a model cannot talk a task into done); the universal 'human'
    # actor is exempt — a clarification task closed by a business answer has
    # no diff to review — and the exemption is auditable (event actor).
    if signal == "done" and cap.get("artifacts") != "*":
        reviews = [a for a in arts if a["kind"] == "review"]
        final_verdict = (reviews[-1]["payload"]["verdict"] if reviews
                         else (task and (r := active(task, "review"))
                               and r["payload"].get("verdict")))
        if final_verdict != "approved":
            raise TaskforgeError(
                "signal 'done' requires the active review to be approved; "
                f"the result's final review verdict is {final_verdict!r}")

    for g in result.get("generated_tasks", []):
        rel = g.get("relation", "follow_up")
        if rel not in RELATIONS:
            raise TaskforgeError(f"unknown relation: {rel!r}")
        if not allowed("relations", rel):
            raise TaskforgeError(
                f"actor {actor!r} may not generate {rel!r} tasks "
                f"(allowed: {cap.get('relations')})")
        if not (g.get("title") or "").strip() \
                or not (g.get("description") or "").strip():
            raise TaskforgeError(
                "generated tasks require non-empty title and description")

    for e in result.get("edges", []):
        validate_edge_type(e.get("type", ""))
        if not e.get("target"):
            raise TaskforgeError("edge requires a target task id")
        if task is not None and e["target"] == task["id"]:
            raise TaskforgeError(
                f"edge {e['type']!r} cannot point at its own task")

    if task is not None and task["status"] in TERMINAL and actor != "human":
        raise TaskforgeError(
            f"task {task['id']} is {task['status']}; only 'human' "
            f"(via human-update) may modify a terminal task")
    return warnings
