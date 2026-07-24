"""The Projection API — TaskForge's presentation layer.

Pure, deterministic composition of engine facts into typed, serializable
projection objects. This layer is the single source of truth for *how humans
consume* engine state; the engine remains the single source of truth for the
state itself and for every business rule.

Framework-agnostic by contract: it knows nothing about any client — no HTML,
no terminal formatting, no colors, no icons, no HTTP. It returns plain
JSON-serializable dicts (str/int/bool/None/list/dict) only. Every renderer —
Web UI, CLI, MCP, SDK, or a client that does not exist yet — consumes these
exact shapes without modification. The stable contract is documented in
docs/PROJECTION_API.md and treated as a public interface: evolve it additively.

Read-only: it composes engine reads (store, readiness, delivery, audit, doctor)
under the store lock and never mutates the store. It never re-derives a rule
the engine owns — readiness, resolved delivery, and landability come from the
engine; the layer only filters, groups, joins, and formats.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import audit, readiness, store          # noqa: E402
from engine.delivery import (landing_status,         # noqa: E402
                             resolve_delivery)
from engine.model import (CLOSED, active,            # noqa: E402
                          blocker_ids, owns_delivery, parent_id)

# Bump only for an additive, backwards-compatible change; a breaking change to
# any shape below is a major event, mirroring engine PUBLIC_API discipline.
PROJECTION_API_VERSION = 1

# The authoritative terminal statuses (PUBLIC_API): the only status values the
# engine promises. Every other status is a non-authoritative display cache, so
# it is never exposed — clients route on `readiness` and disambiguate finished
# work via the `terminal` field.
_TERMINAL_STATUS = ("done", "cancelled", "blocked_on_human")


# --------------------------------------------------------------------------- #
# World: one atomic read of the store, shared by every cross-task projection.
# --------------------------------------------------------------------------- #
def _world():
    """Read every operable task once (future-schema skipped, as everywhere),
    plus the parent -> [child ids] index. Taken under the caller's store lock
    so a projection is a single consistent view, never torn across a cascade."""
    tasks = list(store.all_tasks())      # all_tasks yields — materialize once
    by_id = {t["id"]: t for t in tasks}
    children = {}
    for t in tasks:
        p = parent_id(t)
        if p:
            children.setdefault(p, []).append(t["id"])
    return by_id, children


# --------------------------------------------------------------------------- #
# Shared sub-shapes (reused across projections — this is the reuse mechanism).
# --------------------------------------------------------------------------- #
def _ref(t):
    return {"id": t["id"], "title": t["title"]}


def _feature_ref(t):
    """The delivery owner this task *inherits* from, or None when the task is
    its own unit (owns its delivery, or has no owning ancestor)."""
    r = resolve_delivery(t)
    if r and r["owner"]["id"] != t["id"]:
        return {"id": r["owner"]["id"], "title": r["owner"]["title"]}
    return None


def _terminal(t):
    """The authoritative terminal status, or None if the task is still active.
    Never the raw engine status (that intermediate cache is not part of the
    engine's contract, PUBLIC_API); `readiness` carries the active routing."""
    return t["status"] if t["status"] in _TERMINAL_STATUS else None


def _card(t, children):
    """The reusable lightweight projection of a task — appears in the board,
    a feature's children, blocker/blocks lists, and health lists."""
    is_feature = owns_delivery(t) or t["id"] in children
    return {
        "id": t["id"], "title": t["title"],
        "readiness": readiness.evaluate(t)["readiness"],
        "terminal": _terminal(t),
        "feature": _feature_ref(t),
        "is_feature": is_feature,
        # landability is an engine-owned rule; surfaced only where meaningful.
        "landable": landing_status(t)["landable"] if is_feature else None,
    }


def _criteria(t, acceptance):
    """Each acceptance criterion, joined to its result from the latest review's
    `criteria_results` IF the reviewer recorded them. Never fabricated: a
    criterion with no recorded result is 'unchecked', not assumed passed."""
    results = {}
    rev = active(t, "review")
    if rev:
        for cr in rev["payload"].get("criteria_results") or []:
            if "criterion" in cr and "passed" in cr:
                results[cr["criterion"]] = cr["passed"]
    out = []
    for text in acceptance:
        if text in results:
            out.append({"text": text,
                        "result": "pass" if results[text] else "fail"})
        else:
            out.append({"text": text, "result": "unchecked"})
    return out


def _spec(t):
    s = active(t, "specification")
    if s is None:
        return None
    p = s["payload"]
    return {"version": s["version"],
            "scope": p.get("scope", ""),
            "criteria": _criteria(t, p.get("acceptance_criteria", [])),
            "constraints": p.get("constraints", []),
            "edge_cases": p.get("edge_cases", [])}


def _reviews_sorted(t):
    return sorted(t["artifacts"].get("review", []), key=lambda a: a["version"])


def _review_summary(t):
    revs = _reviews_sorted(t)
    if not revs:
        return None
    return {"latest_verdict": revs[-1]["payload"].get("verdict"),
            "attempts": len(revs),
            "audited": audit.audit_review(t["id"])["clean"]}


def _review_state(t):
    revs = t["artifacts"].get("review", [])
    if not revs:
        return "none"
    verdict = max(revs, key=lambda a: a["version"])["payload"].get("verdict")
    return verdict if verdict in ("approved", "rejected") else "none"


def _unaudited_versions(t):
    """Review versions whose reviewer prompt was never recorded — the precise
    'unaudited' signal (an isolation blind spot doctor also flags)."""
    out = []
    for r in t["artifacts"].get("review", []):
        f = store.audit_dir() / f"{t['id']}-review-v{r['version']}.prompt.md"
        if not f.exists():
            out.append(r["version"])
    return out


def _blocks(task_id, by_id):
    """Cards for tasks that are blocked_by `task_id` (what waits on this)."""
    return [_id for _id in sorted(by_id)
            if any(e["type"] == "blocked_by" and e["target"] == task_id
                   for e in by_id[_id]["edges"])]


def _follow_up_ids(task_id, by_id):
    """Tasks generated from `task_id` that are not children (follow-ups):
    a generated_from edge and no parent edge."""
    return [_id for _id in sorted(by_id)
            if parent_id(by_id[_id]) is None
            and any(e["type"] == "generated_from" and e["target"] == task_id
                    for e in by_id[_id]["edges"])]


# --------------------------------------------------------------------------- #
# The six domain projections.
# --------------------------------------------------------------------------- #
def task(task_id):
    """One task, fully composed — everything needed to work on it in one view:
    spec + criteria, review summary, resolved delivery, blockers, what it
    blocks, follow-ups, and the next command."""
    with store.store_lock():
        by_id, children = _world()
        t = by_id.get(task_id) or store.load(task_id)  # load raises if unknown
        return {
            "ref": _ref(t),
            "description": t["description"],
            "readiness": readiness.evaluate(t)["readiness"],
            "terminal": _terminal(t),
            "feature": _feature_ref(t),
            "spec": _spec(t),
            "review": _review_summary(t),
            "delivery": resolve_delivery(t),
            "blockers": [_card(by_id[b], children)
                         for b in blocker_ids(t) if b in by_id],
            "blocks": [_card(by_id[i], children)
                       for i in _blocks(t["id"], by_id)],
            "follow_ups": [_card(by_id[i], children)
                           for i in _follow_up_ids(t["id"], by_id)],
        }


def feature(task_id):
    """A delivery unit — its descendant tree, child progress, landing
    readiness (engine-owned), audit health, and follow-ups."""
    with store.store_lock():
        by_id, children = _world()
        t = by_id.get(task_id) or store.load(task_id)

        rows, reviews_total, reviews_unaudited = [], 0, 0

        def walk(pid, depth):
            nonlocal reviews_total, reviews_unaudited
            for cid in sorted(children.get(pid, [])):
                c = by_id[cid]
                row = _card(c, children)
                row["review_state"] = _review_state(c)
                row["depth"] = depth
                rows.append(row)
                reviews_total += len(c["artifacts"].get("review", []))
                reviews_unaudited += len(_unaudited_versions(c))
                walk(cid, depth + 1)

        walk(t["id"], 0)
        reviews_total += len(t["artifacts"].get("review", []))
        reviews_unaudited += len(_unaudited_versions(t))

        ls = landing_status(t)
        closed = sum(1 for r in rows if by_id[r["id"]]["status"] in CLOSED)
        return {
            "ref": _ref(t),
            "readiness": readiness.evaluate(t)["readiness"],
            "terminal": _terminal(t),
            "delivery": t.get("delivery")
            or {"branch": None, "pr": None, "landed_at": None},
            "children": rows,
            "progress": {"closed": closed, "total": len(rows)},
            "landing": {"landable": ls["landable"],
                        "blockers": [_card(b, children) for b in ls["blockers"]]},
            "audit": {"reviews_total": reviews_total,
                      "reviews_unaudited": reviews_unaudited},
            "follow_ups": [_card(by_id[i], children)
                           for i in _follow_up_ids(t["id"], by_id)],
        }


def review(task_id):
    """One task's review domain — the acceptance checklist, every attempt in
    order, the isolation audit, and the retry budget."""
    with store.store_lock():
        t = store.load(task_id)
        spec = active(t, "specification")
        acceptance = spec["payload"].get("acceptance_criteria", []) if spec else []
        ar = audit.audit_review(t["id"])
        cfg = store.config()
        return {
            "ref": _ref(t),
            "criteria": _criteria(t, acceptance),
            "attempts": [{"version": r["version"],
                          "verdict": r["payload"].get("verdict"),
                          "root_cause": r["payload"].get("root_cause"),
                          "findings": r["payload"].get("findings", [])}
                         for r in _reviews_sorted(t)],
            "audit": {"isolated": ar["clean"],
                      "findings": ar["findings"],
                      "reviews_checked": ar["reviews_checked"]},
            # How many rejections this task went through — a faithful count of
            # rejected attempts, not the engine's live per-cycle breaker
            # counter (which resets and reads 0 once the task is approved).
            "budget": {"retries_used": sum(
                           1 for r in _reviews_sorted(t)
                           if r["payload"].get("verdict") == "rejected"),
                       "retries_max": cfg["max_review_retries"]},
        }


def health():
    """Store soundness — integrity, done-but-unlanded units (reviewed, not
    merged), and reviews whose isolation was never recorded."""
    with store.store_lock():
        by_id, children = _world()
        doc = audit.doctor()
        done_unlanded, unaudited = [], []
        for t in by_id.values():
            # A 'unit' that is done but not landed: reviewed work still
            # unmerged. Children that inherit a feature are excluded — their
            # landing is the feature's, reported once on the feature.
            if t["status"] == "done" and _feature_ref(t) is None:
                r = resolve_delivery(t)
                if r is None or r["landed_at"] is None:
                    done_unlanded.append(_card(t, children))
            for v in _unaudited_versions(t):
                unaudited.append({"id": t["id"], "title": t["title"],
                                  "version": v})
        return {
            "integrity_ok": doc["clean"],
            "findings": list(doc["findings"]),   # diagnostic text, verbatim
            "done_unlanded": sorted(done_unlanded, key=lambda c: c["id"]),
            "unaudited_reviews": sorted(unaudited,
                                        key=lambda u: (u["id"], u["version"])),
        }


def digest(since):
    """Meaningful changes after `since` (an ISO timestamp), grouped by impact
    rather than a raw chronological log. Composed purely from task history —
    which the raw store carries — so it needs no engine change."""
    _event_group = {"landed": "landed", "done": "done",
                    "human_blocked": "awaiting_human", "escalated": "escalated",
                    "reopened": "reopened"}
    with store.store_lock():
        by_id, _ = _world()
        groups = {"landed": [], "done": [], "awaiting_human": [],
                  "escalated": [], "reopened": []}
        total = 0
        for t in by_id.values():
            for e in t["history"]:
                g = _event_group.get(e["type"])
                if g and e["at"] > since:
                    groups[g].append({"task": _ref(t), "at": e["at"],
                                      "note": e.get("reason") or ""})
                    total += 1
        for items in groups.values():
            items.sort(key=lambda i: (i["at"], i["task"]["id"]), reverse=True)
        return {"since": since, "groups": groups, "total": total}


def board():
    """The actionable collection — the single next action, work grouped by the
    skill it needs, the waiting and human-needs-you queues, and counts. Backs
    the Dashboard and CLI `next`/`status`."""
    with store.store_lock():
        by_id, children = _world()
        ready = {"run": [], "refine": [], "explore": []}
        waiting, awaiting_human = [], []
        counts = {k: 0 for k in ("run", "refine", "explore",
                                 "waiting", "awaiting_human", "terminal")}
        for t in sorted(by_id.values(), key=lambda t: (t["created_at"], t["id"])):
            # The human queue is a *status* fact (blocked_on_human), whose
            # readiness is 'terminal'; cycle-parked ('human') also needs a
            # human. Everything else routes by readiness.
            if t["status"] == "blocked_on_human":
                awaiting_human.append(_human_item(t))
                counts["awaiting_human"] += 1
                continue
            r = readiness.evaluate(t)["readiness"]
            if r in ready:
                ready[r].append(_card(t, children))
                counts[r] += 1
            elif r == "waiting":
                waiting.append(_card(t, children))
                counts["waiting"] += 1
            elif r == "human":              # dependency cycle to break
                awaiting_human.append(_human_item(t))
                counts["awaiting_human"] += 1
            elif r == "terminal":
                counts["terminal"] += 1
        nxt = next((a for grp in ("run", "refine", "explore")
                    for a in ready[grp]), None)
        return {"next": nxt, "ready": ready, "waiting": waiting,
                "awaiting_human": awaiting_human, "counts": counts}


def _human_item(t):
    events = [e for e in t["history"] if e["type"] == "human_blocked"]
    # Heuristic classification (the engine deliberately leaves this to the
    # client, DESIGN §snapshot): a parked task that holds a Decision is a
    # proposal awaiting disposition; otherwise it is a question awaiting an
    # answer.
    kind = "proposal" if active(t, "decision") else "question"
    return {"task": _ref(t), "kind": kind,
            "prompt": events[-1]["reason"] if events else ""}
