"""Derived delivery: a task either *owns* a delivery (branch/PR/landing) or
*inherits* the nearest owning ancestor's, resolved up the parent chain.

This is the readiness pattern applied to delivery (DESIGN §10.19): the task's
own `delivery` is stored; the *resolved* delivery is derived here and never
stored — exactly as `status` is stored and `readiness` is derived. No `via`
pointer, no synchronization, no decomposition-time write: resolution reads the
existing `parent` edge at query time.

Consumed only by the read model (cli.summary, snapshot) and the landing gate.
The mutation layer never resolves — it touches a task's own delivery only.
"""
from engine import store
from engine.model import CLOSED, owns_delivery, parent_id


def resolve_delivery(task):
    """The delivery this task ships through: its own if it owns one, else the
    nearest ancestor that owns one (nearest-wins for nested epic→feature→sub
    trees). Cycle-safe. Returns `{owner: {id, title}, branch, pr, landed_at}`
    or None when nothing up the chain owns a delivery yet."""
    seen = set()
    cur = task
    while cur is not None and cur["id"] not in seen:
        seen.add(cur["id"])
        if owns_delivery(cur):
            d = cur["delivery"]
            return {"owner": {"id": cur["id"], "title": cur["title"]},
                    "branch": d["branch"], "pr": d["pr"],
                    "landed_at": d["landed_at"]}
        pid = parent_id(cur)
        cur = store.find(pid) if pid else None
    return None


def descendants(task_id):
    """Every readable task whose parent chain reaches `task_id` (the inverse of
    resolution — walking down instead of up). Cycle-safe, in-memory over one
    `all_tasks` read. Used by the landing gate to assert a feature is complete
    before it can be marked landed."""
    by_id = {t["id"]: t for t in store.all_tasks()}
    out = []
    for t in by_id.values():
        seen = set()
        cur = t
        while cur is not None and cur["id"] not in seen:
            seen.add(cur["id"])
            pid = parent_id(cur)
            if pid == task_id:
                out.append(t)
                break
            cur = by_id.get(pid) if pid else None
    return out


def landing_status(task):
    """The single definition of the landing rule: can `task`'s delivery be
    marked landed, and what blocks it?

    Landing asserts the delivery unit is *complete*: the task must be `done`
    (reviewed and accepted) AND every descendant closed (`done`/`cancelled` —
    a child still in flight, or parked on an open question, means the merge is
    premature). This rule is owned here and consumed by BOTH the `link
    --landed` gate (engine.apply.link) and the feature projection — never
    re-derived by a client. Cycle-safe via `descendants`.

    Returns `{landable, requires_done, blockers}`: `blockers` is the sorted
    list of open-descendant task dicts; `requires_done` is True when the task
    itself is not yet `done`; `landable` is True only when neither holds."""
    open_desc = sorted(
        (d for d in descendants(task["id"]) if d["status"] not in CLOSED),
        key=lambda d: d["id"])
    requires_done = task["status"] != "done"
    return {"landable": not requires_done and not open_desc,
            "requires_done": requires_done,
            "blockers": open_desc}
