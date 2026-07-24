"""Pure domain model: constants, errors, and task/artifact/edge helpers.

No IO in this module — everything here operates on plain dicts. This is the
bottom of the engine's dependency graph; every other module may import it,
and it imports nothing of theirs.
"""
import uuid
from datetime import datetime, timezone

SCHEMA_VERSION = 2

KINDS = ["decision", "specification", "implementation", "review"]  # cascade order
SEMANTIC_EDGES = {"parent", "blocked_by", "generated_from"}
FORBIDDEN_EDGES = {
    "child": "parent", "children": "parent",
    "blocks": "blocked_by", "depends_on": "blocked_by",
    "dependency_of": "blocked_by", "duplicated_by": "duplicate_of",
    "generated": "generated_from", "generates": "generated_from",
}
RELATIONS = {"follow_up", "prerequisite", "child"}
SIGNALS = {"none", "done", "cancelled", "escalate_refine",
           "escalate_explore", "block_on_human"}
REASON_REQUIRED_SIGNALS = {"cancelled", "escalate_refine",
                           "escalate_explore", "block_on_human"}
TERMINAL = {"done", "cancelled", "blocked_on_human"}
CLOSED = {"done", "cancelled"}   # release blockers; blocked_on_human doesn't
STATUS_FOR = {"waiting": "waiting", "refine": "needs_refine",
              "explore": "needs_explore", "run": "ready_to_run"}
RESULT_KEYS = {"result_id", "artifacts", "generated_tasks", "edges",
               "signal", "signal_reason", "notes"}


class TaskforgeError(Exception):
    """Any contract violation or unusable input. The CLI maps these to a
    JSON error on stderr with exit code 1."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_task(title: str, description: str, source_type: str = "manual",
             source_ref=None) -> dict:
    title, description = (title or "").strip(), (description or "").strip()
    if not title:
        raise TaskforgeError("a task requires a non-empty title")
    if not description:
        raise TaskforgeError(
            "a task requires a non-empty description (immutable intake text)")
    return {
        "schema_version": SCHEMA_VERSION,
        "id": f"TASK-{uuid.uuid4().hex[:12]}",
        "title": title,
        "description": description,
        "status": "new",
        "created_at": now(), "updated_at": now(),
        "source": {"type": source_type, "reference": source_ref,
                   "synced_at": None},
        # Delivery provenance: where this task's work goes, and whether it
        # landed. `source` is intake (where the task came from); `delivery`
        # is output. `landed_at` (a merged PR) is what gates external-issue
        # closure — decoupled from `done` (reviewed), which does not mean
        # merged. See DESIGN §10.18 and references/sync.md.
        "delivery": {"branch": None, "pr": None, "landed_at": None},
        "edges": [],
        "decision_ref": None,
        "pending_escalation": None,
        "applied_results": [],
        "artifacts": {k: [] for k in KINDS},
        "history": [],
    }


def record(task, etype, actor="tasks.py", reason=None, detail=None):
    task["history"].append({"at": now(), "type": etype, "actor": actor,
                            "reason": reason, "detail": detail or {}})


def active(task, kind):
    live = [a for a in task["artifacts"].get(kind, []) if not a["superseded"]]
    return max(live, key=lambda a: a["version"]) if live else None


def supersede(art, reason):
    if art["superseded"]:
        return  # first reason wins
    art.update(superseded=True, superseded_reason=reason, superseded_at=now())


def has_edge(task, etype, target):
    return any(e["type"] == etype and e["target"] == target
               for e in task["edges"])


def blocker_ids(task):
    return [e["target"] for e in task["edges"] if e["type"] == "blocked_by"]


def parent_id(task):
    return next((e["target"] for e in task["edges"] if e["type"] == "parent"),
                None)


def owns_delivery(task):
    """A task *owns* a delivery iff it has been `link`ed — any of branch/pr/
    landed_at set. The `new_task` all-None default is a non-owner, which
    inherits its nearest owning ancestor's delivery (resolved, not stored;
    DESIGN §10.19). Ownership is a derived predicate, never a stored flag."""
    d = task.get("delivery") or {}
    return any(d.get(k) is not None for k in ("branch", "pr", "landed_at"))


def block_on_human(task, reason, detail, actor="tasks.py"):
    # actor = who parked: the requesting skill for a signal park, the engine
    # ("tasks.py") for enforcement parks (budget, breaker, cycle). History
    # must attribute the park correctly — clients section on it.
    task["status"] = "blocked_on_human"
    record(task, "human_blocked", actor, reason=reason, detail=detail)


def review_rejections_in_current_cycle(task) -> int:
    count = 0
    for e in reversed(task["history"]):
        if e["type"] == "review_rejected":
            count += 1
        elif e["type"] in {"review_approved", "human_updated", "escalated"}:
            break
    return count
