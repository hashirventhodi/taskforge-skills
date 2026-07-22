"""Derived readiness: the routing rules of the workflow, in one place.

Rule order (first match): terminal > waiting (cycle -> human) > pending
explore escalation > no active specification (refine) > run.
"""
from engine import store
from engine.model import (CLOSED, STATUS_FOR, TERMINAL, active,
                          block_on_human, blocker_ids)


def evaluate(task) -> dict:
    if task["status"] in TERMINAL:
        return {"readiness": "terminal", "reason": f"status={task['status']}"}
    cycle = find_cycle(task)
    if cycle:
        return {"readiness": "human",
                "reason": "circular dependency in blocked_by graph",
                "cycle": cycle}
    open_blockers = [bid for bid in blocker_ids(task)
                     if (b := store.find(bid)) is None
                     or b["status"] not in CLOSED]
    if open_blockers:
        return {"readiness": "waiting",
                "reason": f"blocked by {len(open_blockers)} open task(s)",
                "blocking_ids": open_blockers}
    if task.get("pending_escalation") == "explore":
        return {"readiness": "explore",
                "reason": "explicit escalation to explore is pending"}
    if active(task, "specification") is None:
        return {"readiness": "refine", "reason": "no active specification"}
    return {"readiness": "run",
            "reason": "active specification present, no open blockers"}


def find_cycle(task):
    path, on_path, visited = [], set(), set()

    def walk(t):
        tid = t["id"]
        if tid in on_path:
            return path[path.index(tid):] + [tid]
        if tid in visited:
            return []
        visited.add(tid)
        on_path.add(tid)
        path.append(tid)
        try:
            for bid in blocker_ids(t):
                nxt = store.find(bid)
                if nxt is not None and nxt["status"] not in CLOSED:
                    if (found := walk(nxt)):
                        return found
        finally:
            on_path.discard(tid)
            path.pop()
        return []

    return walk(task)


def refresh_status(task):
    if task["status"] in TERMINAL:
        return
    ev = evaluate(task)
    if ev["readiness"] == "human":
        block_on_human(task, ev["reason"], {"cycle": ev.get("cycle", [])})
        return
    task["status"] = STATUS_FOR.get(ev["readiness"], task["status"])
