#!/usr/bin/env python3
"""tf — the TaskForge terminal client.

A presentation *adapter* over the Projection API (docs/ARCHITECTURE.md), peer
to the Web UI. It calls the exact same projection functions and renders them as
text — the terminal equivalent of the Web experience, sharing its terminology
and semantics. It contains no business logic and no engine reads of its own:
every fact comes from a projection. The only thing it decides is how a
projection *state* looks in a terminal (a colour, a glyph) — the presentation
mapping the Web UI makes with pills.

If a view here ever needs a fact the projections don't provide, that is a
signal to add it to the Projection API (additively), never to compute it here.

Usage:  tf [--dir DIR] [board|task|feature|review|activity|health] [args]
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# --- colour (presentation only) ------------------------------------------- #
_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
_C = {"run": "36", "refine": "33", "explore": "33", "waiting": "90",
      "terminal": "32", "done": "32", "cancelled": "90", "approved": "32",
      "landed": "32", "verified": "32", "blocked_on_human": "31", "human": "31",
      "rejected": "31", "breach": "31", "open": "31", "unrecorded": "33",
      "dim": "90", "accent": "36", "good": "32", "warn": "33", "crit": "31",
      "bold": "1"}


def c(name, s):
    if not _USE_COLOR or name not in _C:
        return s
    return f"\033[{_C[name]}m{s}\033[0m"


def pill(readiness, terminal=None):
    v = terminal or readiness
    return c(v if v in _C else "dim", f"[{v}]")


# Audit Status — same vocabulary and labels as the Web UI (AUDIT map).
_AUDIT = {"verified": ("good", "isolated"), "breach": ("crit", "isolation breach"),
          "unrecorded": ("warn", "unaudited"), "none": ("dim", "no review")}


def audit_label(status):
    col, label = _AUDIT.get(status, _AUDIT["none"])
    return c(col, label)


def rel_time(iso):
    try:
        delta = (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    except ValueError:
        return iso
    for u, n in (("y", 31536000), ("mo", 2592000), ("d", 86400), ("h", 3600), ("m", 60)):
        if delta >= n:
            return f"{int(delta // n)}{u} ago"
    return "just now"


def short(tid):
    return tid[:9]


def h1(title):
    print(c("bold", title))


def kick(label):
    print("\n" + c("dim", label.upper()))


def row(indent, *cols):
    print(" " * indent + "  ".join(str(x) for x in cols if x != ""))


# --- the command that a readiness routes to (CLI-only presentation) ------- #
_SKILL = {"refine": "taskforge-refine", "explore": "taskforge-explore",
          "run": "taskforge-run"}


def card_line(card, indent=4, show_feature=True):
    tag = pill(card["readiness"], card.get("terminal"))
    meta = []
    if show_feature and card.get("feature"):
        meta.append(c("dim", "▸ " + card["feature"]["title"]))
    meta.append(c("dim", short(card["id"])))
    land = ""
    if card.get("is_feature") and card.get("landable") is not None:
        land = c("good" if card["landable"] else "crit",
                 "landable" if card["landable"] else "blocked")
    row(indent, tag, card["title"], land, "  ".join(meta))


# --- renderers (one per projection / composition) ------------------------- #
def render_board(P):
    b, hh = P.board(), P.health()
    h1("Dashboard")
    print(c("dim", "what needs you, and what to do next"))
    if b["next"]:
        n = b["next"]
        cmd = _SKILL.get(n["readiness"])
        kick("Next — do this")
        card_line(n)
        if cmd:
            row(4, c("accent", f"→ {cmd} {n['id']}"))
    else:
        kick("Next — do this")
        row(4, c("dim", "nothing actionable — you're caught up"))

    kick(f"Needs you ({len(b['awaiting_human'])})")
    if b["awaiting_human"]:
        for i in b["awaiting_human"]:
            row(4, c("crit", i["kind"]), i["prompt"] or i["task"]["title"],
                c("dim", short(i["task"]["id"])))
    else:
        row(4, c("dim", "nothing needs you right now"))

    next_id = b["next"]["id"] if b["next"] else None
    ready = [(k, [x for x in v if x["id"] != next_id]) for k, v in b["ready"].items()]
    ready = [(k, v) for k, v in ready if v]
    if ready:
        kick("Ready")
        for k, items in ready:
            for card in items:
                card_line(card)

    # In flight — the Dashboard composition: board + feature() summaries.
    feat_ids = {}
    for card in (b["ready"]["run"] + b["ready"]["refine"]
                 + b["ready"]["explore"] + b["waiting"]):
        if card["is_feature"]:
            feat_ids[card["id"]] = True
        if card.get("feature"):
            feat_ids[card["feature"]["id"]] = True
    inflight = []
    for fid in feat_ids:
        try:
            f = P.feature(fid)
        except Exception:
            continue
        if f["delivery"]["branch"] and not f["delivery"]["landed_at"]:
            inflight.append(f)
    if inflight:
        kick(f"In flight ({len(inflight)})")
        for f in inflight:
            badge = c("good" if f["landing"]["landable"] else "warn",
                      f"{f['progress']['closed']}/{f['progress']['total']}")
            row(4, f["ref"]["title"], badge, c("dim", f["delivery"]["branch"]))

    kick("Health")
    row(4, c("good", "✓") if hh["structural"]["sound"] else c("crit", "✕"),
        "structural integrity " + ("sound" if hh["structural"]["sound"] else "issues"))
    a = hh["audit"]
    row(4, c("crit", "✕") if a["breach"] else c("warn", "•") if a["unrecorded"] else c("good", "✓"),
        f"reviews · {a['breach']} breach · {a['unrecorded']} unaudited")
    row(4, c("warn", "•"), f"{len(hh['delivery']['done_unlanded'])} done, not landed")
    counts = b["counts"]
    print("\n" + c("dim", f"run {counts['run']} · refine {counts['refine']} · "
                   f"explore {counts['explore']} · wait {counts['waiting']} · "
                   f"you {counts['awaiting_human']} · done {counts['terminal']}"))


def render_task(P, tid):
    t = P.task(tid)
    if t.get("feature"):
        print(c("dim", f"{t['feature']['title']} / {t['ref']['title']}"))
    h1(f"{t['ref']['title']} {pill(t['readiness'], t.get('terminal'))}")

    kick("Specification")
    if t["spec"]:
        print(f"    {c('dim', 'v' + str(t['spec']['version']) + ' — the contract')}")
        row(4, t["spec"]["scope"])
        for cr in t["spec"]["criteria"]:
            glyph = {"pass": c("good", "✓"), "fail": c("crit", "✕")}.get(cr["result"], c("warn", "•"))
            row(4, glyph, cr["text"])
    else:
        row(4, c("dim", f"no active spec — routes to {t['readiness']}"))

    kick("Review")
    if t["review"]:
        row(4, c(t["review"]["verdict"] or "dim", t["review"]["verdict"] or "in review"),
            f"{t['review']['attempts']} attempt(s) · did the work pass")
        row(4, audit_label(t["audit"]["status"]),
            c("dim", "can the review be trusted (isolation)"))
    else:
        row(4, c("dim", "no review yet"))

    kick("Delivery")
    d = t["delivery"]
    if d:
        label = "branch" if d["owner"]["id"] == t["ref"]["id"] else "via " + d["owner"]["title"]
        row(4, c("dim", label + ":"), d["branch"] or "—")
        row(4, c("dim", "pr:"), d["pr"] or "—")
        row(4, c("dim", "landed:"), rel_time(d["landed_at"]) if d["landed_at"] else "not yet")
    else:
        row(4, c("dim", "not linked to a branch yet"))

    for label, arr in (("Blocked by", t["blockers"]), ("Blocks", t["blocks"]),
                       ("Follow-ups", t["follow_ups"])):
        if arr:
            kick(label)
            for card in arr:
                card_line(card)

    kick("Description")
    for line in t["description"].splitlines() or [""]:
        row(4, line)


def render_feature(P, tid):
    f = P.feature(tid)
    print(c("dim", f"Dashboard / {f['ref']['title']}"))
    h1(f"{f['ref']['title']} {pill(f['readiness'], f.get('terminal'))}")

    kick("Delivery")
    d = f["delivery"]
    row(4, c("dim", "branch:"), d["branch"] or "—")
    row(4, c("dim", "pr:"), d["pr"] or "—")
    row(4, c("dim", "landed:"), rel_time(d["landed_at"]) if d["landed_at"] else "not yet")

    kick("Land readiness")
    ls = f["landing"]
    row(4, c("good", "✓ ready to land") if ls["landable"] else c("crit", "✕ not landable"))
    for card in ls["blockers"]:
        card_line(card)
    a = f["audit"]
    row(4, "review audit:", audit_label(a["status"]),
        c("dim", f"{a['breach']} breach · {a['unrecorded']} unaudited · {a['verified']} verified"))

    kick(f"Children — {f['progress']['closed']}/{f['progress']['total']} closed")
    if f["children"]:
        for ch in f["children"]:
            state = "" if ch["review_state"] == "none" else c(ch["review_state"], ch["review_state"])
            row(4 + ch["depth"] * 2, pill(ch["readiness"], ch.get("terminal")),
                ch["title"], state, c("dim", short(ch["id"])))
    else:
        row(4, c("dim", "no children — a standalone unit"))


def render_review(P, tid):
    r = P.review(tid)
    print(c("dim", f"{r['ref']['title']} / review"))
    h1(f"Review — {r['ref']['title']}")

    kick("Acceptance")
    for cr in r["criteria"] or []:
        glyph = {"pass": c("good", "✓"), "fail": c("crit", "✕")}.get(cr["result"], c("warn", "•"))
        row(4, glyph, cr["text"])
    if not r["criteria"]:
        row(4, c("dim", "no criteria"))

    kick("Isolation audit")
    row(4, audit_label(r["audit"]["status"]))
    for fnd in r["audit"]["findings"]:
        row(4, c("crit", "✕"), fnd)
    row(4, c("dim", "budget:"), f"{r['budget']['retries_used']} of {r['budget']['retries_max']} retries used")

    kick("Attempts")
    for a in r["attempts"]:
        detail = ((c("bold", a["root_cause"] + ": ") if a["root_cause"] else "")
                  + "; ".join(a["findings"] or []) or "—")
        row(4, c(a["verdict"], f"v{a['version']} {a['verdict']}"), detail)
    if not r["attempts"]:
        row(4, c("dim", "no reviews yet"))


_RANGE_HOURS = {"24h": 24, "7d": 168, "30d": 720}


def render_activity(P, rng):
    if rng == "all":
        since = "0000-01-01T00:00:00+00:00"
    else:
        hrs = _RANGE_HOURS.get(rng, 168)
        since = (datetime.now(timezone.utc).timestamp() - hrs * 3600)
        since = datetime.fromtimestamp(since, timezone.utc).isoformat()
    d = P.digest(since)
    h1("Activity")
    print(c("dim", f"meaningful changes in the last {rng}, grouped by impact"))
    labels = {"awaiting_human": "Now needs you", "landed": "Landed", "done": "Done",
              "escalated": "Escalated", "reopened": "Reopened"}
    if not d["total"]:
        print("\n" + c("dim", "nothing changed in this range — try a wider one (--range all)"))
        return
    for k, label in labels.items():
        items = d["groups"][k]
        if not items:
            continue
        kick(f"{label} ({len(items)})")
        for i in items:
            note = c("dim", i["note"]) if i["note"] else ""
            row(4, i["task"]["title"], note, c("dim", rel_time(i["at"])))


def render_health(P):
    hh = P.health()
    h1("Health")
    print(c("dim", "three separate concerns — never conflated"))

    kick("Structural integrity")
    if hh["structural"]["sound"]:
        row(4, c("good", "✓"), "graph sound — no dangling edges, cycles, or bad refs")
    else:
        for i in hh["structural"]["issues"]:
            row(4, c("crit", "✕"), i["message"])

    a = hh["audit"]
    kick(f"Review audit — {a['breach']} breach · {a['unrecorded']} unaudited · {a['verified']} verified")
    if a["needs_attention"]:
        for n in a["needs_attention"]:
            row(4, audit_label(n["status"]), n["task"]["title"], c("dim", short(n["task"]["id"])))
    else:
        row(4, c("good", "✓"), "every review is isolated and recorded")

    kick(f"Delivery — done but not landed ({len(hh['delivery']['done_unlanded'])})")
    if hh["delivery"]["done_unlanded"]:
        for card in hh["delivery"]["done_unlanded"]:
            card_line(card)
    else:
        row(4, c("good", "✓"), "nothing reviewed is sitting unmerged")


def main(argv=None):
    p = argparse.ArgumentParser(prog="tf", description="TaskForge terminal client")
    p.add_argument("--dir", help="path to the .tasks store (else $TASKFORGE_DIR)")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("board")
    for name in ("task", "feature", "review"):
        sub.add_parser(name).add_argument("id")
    act = sub.add_parser("activity")
    act.add_argument("--range", default="7d", choices=["24h", "7d", "30d", "all"])
    sub.add_parser("health")
    args = p.parse_args(argv)

    if args.dir:
        os.environ["TASKFORGE_DIR"] = args.dir
    import projections as P
    from engine.model import TaskforgeError
    try:
        if args.cmd == "task":
            render_task(P, args.id)
        elif args.cmd == "feature":
            render_feature(P, args.id)
        elif args.cmd == "review":
            render_review(P, args.id)
        elif args.cmd == "activity":
            render_activity(P, args.range)
        elif args.cmd == "health":
            render_health(P)
        else:
            render_board(P)
    except TaskforgeError as exc:
        print(c("crit", f"error: {exc}"), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
