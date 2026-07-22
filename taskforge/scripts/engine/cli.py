"""CLI: argument parsing and command dispatch. No workflow logic lives
here — every command delegates to the modules that own the behavior."""
import argparse
import json
import sys
from pathlib import Path

from engine import apply as apply_mod
from engine import audit, readiness, store
from engine.model import (KINDS, TaskforgeError, active, has_edge, new_task,
                          record, review_rejections_in_current_cycle)


def summary(task):
    return {"id": task["id"], "title": task["title"],
            "status": task["status"], "readiness": readiness.evaluate(task),
            "pending_escalation": task.get("pending_escalation"),
            "decision_ref": task.get("decision_ref"),
            "edges": task["edges"],
            "active_artifacts": {
                k: (a["version"] if (a := active(task, k)) else None)
                for k in KINDS},
            "source": task["source"]}


def out(obj):
    print(json.dumps(obj, indent=2, sort_keys=True))


def fail(msg):
    print(json.dumps({"error": str(msg)}), file=sys.stderr)
    sys.exit(1)


def text_arg(inline, file_path, flag, strip_newline=True):
    """Resolve a free-text argument that may arrive inline or by file.

    The --<flag>-file form exists as the injection-safe path: text quoted
    from an untrusted source (an issue title, a human's answer) inlined into
    a shell command string is a command-injection vector — backticks/$()
    substitute before this program ever runs. A file is written without a
    shell in the path. Exactly one form is required; both is an error so
    ambiguity is loud. Single-line fields strip one trailing newline
    (editor-written files end with one); the description stays verbatim.
    """
    if inline is not None and file_path is not None:
        raise TaskforgeError(
            f"pass --{flag} or --{flag}-file, not both")
    if file_path is not None:
        text = Path(file_path).read_text(encoding="utf-8")
        return text.rstrip("\n") if strip_newline else text
    if inline is not None:
        return inline
    raise TaskforgeError(f"requires --{flag} or --{flag}-file")


def build_parser():
    p = argparse.ArgumentParser(prog="tasks.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create")
    c.add_argument("--title")
    c.add_argument("--title-file")
    c.add_argument("--description")
    c.add_argument("--description-file")
    c.add_argument("--source-type", default="manual",
                   choices=["manual", "github", "jira", "markdown",
                            "document", "internal"])
    c.add_argument("--source-ref")

    for name in ("show", "readiness", "budget", "blocked-by", "audit-review"):
        sub.add_parser(name).add_argument("id")

    ls = sub.add_parser("list")
    ls.add_argument("--readiness",
                    choices=["refine", "explore", "run", "waiting",
                             "terminal", "human"])

    v = sub.add_parser("validate")
    v.add_argument("result_json")
    v.add_argument("--actor", required=True)
    v.add_argument("--task")

    a = sub.add_parser("apply")
    a.add_argument("id")
    a.add_argument("result_json")
    a.add_argument("--actor", required=True)

    h = sub.add_parser("human-update")
    h.add_argument("id")
    h.add_argument("result_json", nargs="?")
    h.add_argument("--note")
    h.add_argument("--note-file")

    x = sub.add_parser("cancel")
    x.add_argument("id")
    x.add_argument("--reason")
    x.add_argument("--reason-file")

    r = sub.add_parser("record-review-prompt")
    r.add_argument("id")
    r.add_argument("file")
    r.add_argument("--version", type=int, required=True)

    sub.add_parser("config")
    sub.add_parser("doctor")
    sub.add_parser("migrate")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        run_command(args)
    except TaskforgeError as exc:
        fail(exc)


def run_command(args):
    from engine.validation import validate_result

    if args.cmd == "create":
        title = text_arg(args.title, args.title_file, "title")
        desc = text_arg(args.description, args.description_file,
                        "description", strip_newline=False)
        with store.store_lock():
            store.ensure_config_file()
            t = new_task(title, desc, args.source_type, args.source_ref)
            record(t, "created", "taskforge",
                   detail={"source": args.source_type,
                           "reference": args.source_ref})
            readiness.refresh_status(t)
            store.save(t)
        out(summary(t))

    elif args.cmd == "show":
        out(store.load(args.id))
    elif args.cmd == "readiness":
        out({"id": args.id, **readiness.evaluate(store.load(args.id))})
    elif args.cmd == "budget":
        t = store.load(args.id)
        total_reviews = len(t["artifacts"].get("review", []))
        out({"id": args.id,
             "max_review_retries": store.config()["max_review_retries"],
             "review_rejections_in_current_cycle":
                 review_rejections_in_current_cycle(t),
             "total_reviews": total_reviews,
             "next_review_version": total_reviews + 1})
    elif args.cmd == "blocked-by":
        out([t["id"] for t in store.all_tasks()
             if has_edge(t, "blocked_by", args.id)])
    elif args.cmd == "list":
        rows = []
        for t in store.all_tasks():
            ev = readiness.evaluate(t)
            if args.readiness and ev["readiness"] != args.readiness:
                continue
            rows.append({"id": t["id"], "title": t["title"],
                         "status": t["status"],
                         "readiness": ev["readiness"]})
        out(rows)

    elif args.cmd == "validate":
        result = json.loads(
            Path(args.result_json).read_text(encoding="utf-8"))
        task = store.load(args.task) if args.task else None
        warnings = validate_result(result, args.actor, task)
        out({"valid": True, "actor": args.actor, "warnings": warnings})

    elif args.cmd == "apply":
        with store.store_lock():
            t = store.load(args.id)
            result = json.loads(
                Path(args.result_json).read_text(encoding="utf-8"))
            out(apply_mod.apply_result(t, result, actor=args.actor))

    elif args.cmd == "human-update":
        note = text_arg(args.note, args.note_file, "note")
        with store.store_lock():
            t = store.load(args.id)
            if t["status"] == "blocked_on_human":
                t["status"] = "new"
            record(t, "human_updated", "human", reason=note)
            if args.result_json:
                result = json.loads(
                    Path(args.result_json).read_text(encoding="utf-8"))
                out(apply_mod.apply_result(t, result, actor="human"))
            else:
                readiness.refresh_status(t)
                store.save(t)
                out(summary(t))

    elif args.cmd == "cancel":
        reason = text_arg(args.reason, args.reason_file, "reason")
        with store.store_lock():
            t = store.load(args.id)
            t["status"] = "cancelled"
            record(t, "cancelled", "human", reason=reason)
            store.save(t)
            apply_mod.wake_blocked_by(t["id"])
        out(summary(t))

    elif args.cmd == "record-review-prompt":
        with store.store_lock():
            text = Path(args.file).read_text(encoding="utf-8")
            out(audit.record_review_prompt(args.id, args.version, text))

    elif args.cmd == "audit-review":
        out(audit.audit_review(args.id))
    elif args.cmd == "config":
        out(store.config())
    elif args.cmd == "doctor":
        out(audit.doctor())
    elif args.cmd == "migrate":
        with store.store_lock():
            out(audit.migrate())
