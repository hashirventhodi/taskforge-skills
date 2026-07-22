"""The result application pipeline — the heart of the engine.

Fixed order: idempotency check -> validation -> artifacts (versioning,
supersession, cascades, engine-enforced budgets/breakers) -> generated
tasks -> annotation edges -> signal -> readiness recompute -> persist ->
wake tasks blocked by a closed task.

Circuit-breaker authority (invariant): a park by the version breaker or the
review budget overrides the skill's routing *signal* only. Generated tasks
and edges are durable declared work and are applied regardless of a park —
the engine never discards them. The result is still fully applied, so
result_id is recorded and a retry is a clean no-op.
"""
from engine import store
from engine.model import (CLOSED, KINDS, TERMINAL, TaskforgeError, active,
                          block_on_human, has_edge, new_task, parent_id,
                          record, review_rejections_in_current_cycle,
                          supersede, now)
from engine.readiness import evaluate, refresh_status
from engine.validation import validate_edge_type, validate_result


def apply_result(task, result, actor):
    # Idempotency first: a retry of an already-applied result must be a
    # friendly no-op even if the first application made the task terminal —
    # the retry-after-timeout scenario is exactly what result_id exists for.
    rid = result.get("result_id") if isinstance(result, dict) else None
    if rid and rid in task.get("applied_results", []):
        return {"task": task["id"], "duplicate_of": rid,
                "applied": False, "status": task["status"],
                "readiness": evaluate(task)["readiness"],
                "note": "result_id already applied; no-op"}

    warnings = validate_result(result, actor, task)
    cfg = store.config()
    generated_ids = []

    for art in result.get("artifacts", []):
        add_artifact(task, art, actor, cfg)
        if task["status"] == "blocked_on_human":
            break  # circuit breaker or budget enforcement tripped

    # Generated tasks and annotation edges are durable work the skill
    # declared during execution; they do not depend on whether THIS task may
    # keep iterating. A circuit-breaker park overrides routing, never declared
    # work (CONTRACTS: "Circuit-breaker authority"), so they are applied
    # whether or not the artifact loop parked the task — and they stay
    # coherent on a parked task (a generated prerequisite's blocked_by edge is
    # ignored by readiness while parked, honored on unpark).
    for spec in result.get("generated_tasks", []):
        generated_ids.append(materialize(task, spec, actor))
    for edge in result.get("edges", []):
        add_edge(task, edge, actor)

    # The signal is the skill's routing request; a breaker park is exactly the
    # authority to override it. Suppression is recorded so the history shows
    # what the skill asked for and that the engine overrode it, and the
    # returned/​recorded signal is the authoritative one (none), not the intent.
    requested_signal = result.get("signal", "none")
    if task["status"] == "blocked_on_human":
        applied_signal = "none"
        if requested_signal != "none":
            record(task, "signal_overridden", actor,
                   reason="circuit-breaker park overrides the routing signal",
                   detail={"requested": requested_signal})
    else:
        apply_signal(task, requested_signal,
                     result.get("signal_reason"), actor)
        applied_signal = requested_signal

    if rid:
        task.setdefault("applied_results", []).append(rid)
    if result.get("notes"):
        record(task, "skill_completed", actor, reason=result["notes"],
               detail={"signal": applied_signal})
    refresh_status(task)
    store.save(task)
    if task["status"] in CLOSED:
        refresh_dependents(task["id"])
    return {"task": task["id"], "applied": True,
            "generated_tasks": generated_ids,
            "signal": applied_signal,
            "status": task["status"],
            "readiness": evaluate(task)["readiness"],  # routing string
            "warnings": warnings}


def add_artifact(task, art, actor, cfg):
    kind, payload = art["kind"], art["payload"]
    prev = active(task, kind)
    if prev is not None:
        reason = art.get("supersedes_reason", "superseded by newer version")
        supersede(prev, reason)
        record(task, "artifact_superseded", actor, reason=reason,
               detail={"kind": kind, "version": prev["version"]})

    versions = task["artifacts"].setdefault(kind, [])
    vnum = max((a["version"] for a in versions), default=0) + 1
    versions.append({"kind": kind, "version": vnum, "payload": payload,
                     "created_by": actor, "created_at": now(),
                     "superseded": False, "superseded_reason": None,
                     "superseded_at": None})
    record(task, "artifact_added", actor,
           detail={"kind": kind, "version": vnum})

    if kind == "decision":
        if task.get("pending_escalation") == "explore":
            task["pending_escalation"] = None
        if prev is not None:
            flag_stale_decision_refs(task, prev["version"], actor)
    if kind == "review":
        verdict = payload.get("verdict")
        record(task, "review_approved" if verdict == "approved"
               else "review_rejected", actor,
               detail={"version": vnum,
                       "root_cause": payload.get("root_cause")})
        # Deterministic budget enforcement (design §3.2.2): implementation-
        # fault rejections beyond the retry budget park the task regardless
        # of what the skill's signal says.
        if (verdict == "rejected"
                and payload.get("root_cause") == "implementation"
                and review_rejections_in_current_cycle(task)
                > cfg["max_review_retries"]):
            block_on_human(
                task,
                f"review retry budget exhausted "
                f"({cfg['max_review_retries']} retries); "
                f"human judgment required",
                {"enforced_by": "engine"})
            return

    if prev is not None:
        cascade(task, kind, f"{kind} v{prev['version']} superseded", actor)

    if vnum >= cfg["max_artifact_versions"] and task["status"] not in TERMINAL:
        block_on_human(task,
                       f"{kind} reached v{vnum}; iteration is not converging",
                       {"kind": kind, "enforced_by": "engine"})


def cascade(task, from_kind, reason, actor):
    for kind in KINDS[KINDS.index(from_kind) + 1:]:
        a = active(task, kind)
        if a is not None:
            supersede(a, reason)
            record(task, "artifact_superseded", actor, reason=reason,
                   detail={"kind": kind, "version": a["version"],
                           "cascade_from": from_kind})


def flag_stale_decision_refs(decided, old_version, actor):
    for t in store.all_tasks():
        ref = t.get("decision_ref")
        if (not ref or ref["task_id"] != decided["id"]
                or ref["version"] != old_version
                or t["status"] in CLOSED or t["id"] == decided["id"]):
            continue
        record(t, "stale_decision_ref", actor,
               reason=f"inherited decision {decided['id']} "
                      f"v{old_version} superseded",
               detail={"decision_task": decided["id"],
                       "old_version": old_version})
        spec = active(t, "specification")
        if spec is not None:
            supersede(spec, "inherited architectural decision superseded")
            record(t, "artifact_superseded", actor,
                   reason="inherited architectural decision superseded",
                   detail={"kind": "specification",
                           "version": spec["version"]})
            cascade(t, "specification",
                    "inherited architectural decision superseded", actor)
        refresh_status(t)
        store.save(t)


def materialize(origin, spec, actor):
    relation = spec.get("relation", "follow_up")
    t = new_task(spec.get("title"), spec.get("description"),
                 source_type="internal")
    record(t, "created", actor, reason=spec.get("reason"),
           detail={"origin": origin["id"], "relation": relation})
    t["edges"].append({"type": "generated_from", "target": origin["id"],
                       "created_at": now(), "reason": spec.get("reason")})
    if relation == "child":
        t["edges"].append({"type": "parent", "target": origin["id"],
                           "created_at": now(), "reason": None})
        dec = active(origin, "decision")
        if dec is not None:
            t["decision_ref"] = {"task_id": origin["id"], "kind": "decision",
                                 "version": dec["version"]}
    refresh_status(t)
    store.save(t)
    if relation in {"prerequisite", "child"}:
        add_edge(origin, {"type": "blocked_by", "target": t["id"],
                          "reason": spec.get("reason")}, actor)
    record(origin, "task_generated", actor, reason=spec.get("reason"),
           detail={"task_id": t["id"], "relation": relation,
                   "title": t["title"]})
    return t["id"]


def add_edge(task, edge, actor):
    etype = validate_edge_type(edge.get("type"))
    target = edge["target"]
    if target == task["id"]:
        raise TaskforgeError(f"edge {etype!r} cannot point at its own task")
    if has_edge(task, etype, target):
        return
    task["edges"].append({"type": etype, "target": target,
                          "created_at": now(),
                          "reason": edge.get("reason")})
    record(task, "edge_added", actor, reason=edge.get("reason"),
           detail={"type": etype, "target": target})
    if etype == "blocked_by":
        record(task, "blocked", actor, reason=edge.get("reason"),
               detail={"by": target})


def apply_signal(task, signal, reason, actor):
    if signal == "none":
        return
    if signal == "done":
        task["status"] = "done"
        record(task, "done", actor, reason=reason)
    elif signal == "cancelled":
        task["status"] = "cancelled"
        record(task, "cancelled", actor, reason=reason)
    elif signal == "escalate_refine":
        record(task, "escalated", actor, reason=reason,
               detail={"to": "refine"})
        spec = active(task, "specification")
        if spec is not None:
            supersede(spec, f"escalated to refine: {reason}")
            record(task, "artifact_superseded", actor,
                   reason=f"escalated to refine: {reason}",
                   detail={"kind": "specification",
                           "version": spec["version"]})
            cascade(task, "specification",
                    f"escalated to refine: {reason}", actor)
    elif signal == "escalate_explore":
        record(task, "escalated", actor, reason=reason,
               detail={"to": "explore"})
        task["pending_escalation"] = "explore"
        dec = active(task, "decision")
        if dec is not None:
            supersede(dec, f"escalated to explore: {reason}")
            record(task, "artifact_superseded", actor,
                   reason=f"escalated to explore: {reason}",
                   detail={"kind": "decision", "version": dec["version"]})
            cascade(task, "decision", f"escalated to explore: {reason}",
                    actor)
            flag_stale_decision_refs(task, dec["version"], actor)
        else:
            spec = active(task, "specification")
            if spec is not None:
                supersede(spec, f"escalated to explore: {reason}")
                cascade(task, "specification",
                        f"escalated to explore: {reason}", actor)
        pid = parent_id(task)
        if pid and (parent := store.find(pid)) is not None \
                and parent["status"] not in TERMINAL:
            parent["pending_escalation"] = "explore"
            record(parent, "escalated", actor,
                   reason=f"child {task['id']} escalated: {reason}",
                   detail={"to": "explore", "from_child": task["id"]})
            refresh_status(parent)
            store.save(parent)
    elif signal == "block_on_human":
        block_on_human(task, reason or "", {}, actor)


def refresh_dependents(blocker_id):
    """Re-sync the display-cache status of every non-terminal task
    blocked_by ``blocker_id``, and log the transition.

    Called when the blocker CLOSES (a waiter may now proceed -> ``unblocked``)
    and when it REOPENS (a still-open waiter re-blocks -> ``reblocked``).
    Readiness derives blocker-openness live, so this only keeps the cached
    status and the history honest — the event fires solely on an actual
    cache-status transition, and a cycle-parked dependent (blocked_on_human)
    is labelled by neither (block_on_human already recorded that)."""
    for t in store.all_tasks():
        if t["status"] in TERMINAL \
                or not has_edge(t, "blocked_by", blocker_id):
            continue
        was_waiting = t["status"] == "waiting"
        refresh_status(t)
        now_waiting = evaluate(t)["readiness"] == "waiting"
        if now_waiting and not was_waiting:
            record(t, "reblocked", detail={"blocker": blocker_id},
                   reason=f"blocker {blocker_id} reopened")
        elif was_waiting and not now_waiting:
            record(t, "unblocked", detail={"blocker": blocker_id},
                   reason=f"blocker {blocker_id} closed")
        store.save(t)


def reopen(task, reason, actor="human"):
    """Restore a closed terminal task (done/cancelled) to active work.

    Artifacts, reviews, decisions and history are preserved untouched — the
    task re-enters the workflow at whatever its derived readiness now says
    (spec present -> run; none -> refine; pending escalation -> explore; open
    blocker -> waiting). Reopening a task others were blocked_by re-blocks
    any still-active dependent. blocked_on_human is not a closed terminal —
    it resumes via human-update, not here."""
    status = task["status"]
    if status == "blocked_on_human":
        raise TaskforgeError(
            "task is blocked_on_human, not a closed terminal — resume it "
            "with human-update, which captures the human's answer")
    if status not in CLOSED:
        raise TaskforgeError(
            f"task is {status!r}, not a closed terminal (done/cancelled); "
            "there is nothing to reopen")
    record(task, "reopened", actor, reason=reason)
    task["status"] = "new"
    refresh_status(task)
    store.save(task)
    refresh_dependents(task["id"])
    return task
