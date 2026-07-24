"""Read model: an atomic, deterministic snapshot of the whole store.

This is the engine's read API for clients (a web UI, external tooling): one
call, under the store lock, answering "what is the state of the world?" so no
client ever composes it from per-command calls or — worse — re-derives state.

Provenance rule (DESIGN §10.15): every field traces to exactly one of
  * stored state       — task fields and events, verbatim
  * derived state      — existing engine logic only (evaluate(), active())
  * snapshot metadata  — properties of the snapshot itself
Nothing else. A proposed field that cannot be traced to one of these is
presentation logic or a new concept, and belongs in a client, not here.

Determinism: same store -> same snapshot, byte for byte, except
`generated_at`. Tasks and edges are sorted; the JSON printer sorts keys.

Honesty: tasks this engine cannot read — future-schema (DESIGN §10.12) or
unreadable files — are surfaced in `skipped`, never silently omitted; a
snapshot must not claim to be the world while missing part of it.
"""
import json

from engine import readiness, store
from engine.delivery import resolve_delivery
from engine.model import KINDS, active, now

SNAPSHOT_VERSION = 1


def _task_row(t: dict) -> dict:
    ev = readiness.evaluate(t)
    dlv = resolve_delivery(t)  # one parent-chain walk per row
    row = {
        # stored, verbatim
        "id": t["id"],
        "title": t["title"],
        "status": t["status"],
        "pending_escalation": t.get("pending_escalation"),
        "decision_ref": t.get("decision_ref"),
        "source": t["source"],
        "delivery": t.get("delivery"),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        # derived, existing logic only
        "readiness": ev["readiness"],
        "readiness_detail": {k: v for k, v in ev.items()
                             if k != "readiness"},
        # derived: delivery resolved up the parent chain (DESIGN §10.19), the
        # same stored (`delivery`) vs derived split as status vs readiness.
        "delivery_owner": dlv["owner"] if dlv else None,
        "resolved_delivery": (
            {k: dlv[k] for k in ("branch", "pr", "landed_at")}
            if dlv else None),
        "active_artifacts": {
            k: (a["version"] if (a := active(t, k)) else None)
            for k in KINDS},
    }
    if t["status"] == "blocked_on_human":
        # The latest human_blocked event, verbatim — the raw stored fact.
        # Deliberately NOT classified (proposal vs question): rendering
        # categories are the client's, exactly as they are the hub prompt's.
        events = [e for e in t["history"] if e["type"] == "human_blocked"]
        if events:
            row["human_blocked"] = events[-1]
    return row


def _task_edges(t: dict) -> list:
    edges = [{"type": e["type"], "from": t["id"], "to": e["target"]}
             for e in t["edges"]]
    # decision_ref is stored as a field but IS a semantic edge — a child
    # pinned to a specific version of another task's Decision. Normalizing it
    # here means no client needs the special knowledge that one edge is
    # stored differently from the others.
    ref = t.get("decision_ref")
    if ref:
        edges.append({"type": "decision_ref", "from": t["id"],
                      "to": ref["task_id"], "version": ref["version"]})
    return edges


def build_snapshot() -> dict:
    """Compose the snapshot. Caller holds the store lock — that is what makes
    the snapshot atomic (no torn reads across a mid-cascade store)."""
    tasks_out, edges_out, skipped = [], [], []
    for p in sorted(store.store_dir().glob("TASK-*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            skipped.append({"id": p.stem, "reason": "unreadable"})
            continue
        if store.is_future(t):
            skipped.append({"id": t.get("id", p.stem),
                            "reason": "future_schema",
                            "schema_version": t.get("schema_version")})
            continue
        tasks_out.append(_task_row(t))
        edges_out.extend(_task_edges(t))
    edges_out.sort(key=lambda e: (e["from"], e["type"], e["to"]))
    return {
        "snapshot_version": SNAPSHOT_VERSION,       # metadata
        "generated_at": now(),                      # metadata
        "tasks": tasks_out,
        "edges": edges_out,
        "skipped": skipped,
        "store": {"tasks": len(tasks_out),          # metadata about the read
                  "dir": str(store.store_dir())},
    }
