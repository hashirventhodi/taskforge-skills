"""Auditing and maintenance: reviewer-isolation verification, store
integrity (doctor), and schema migration."""
import hashlib
import json

from engine import store
from engine.model import SCHEMA_VERSION, TERMINAL, record
from engine.readiness import evaluate


def record_review_prompt(task_id, version, prompt_text):
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


def doctor():
    findings = []
    ids = set()
    tasks_list = []
    future = []
    for p in sorted(store.store_dir().glob("TASK-*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
            tasks_list.append(t)
            ids.add(t["id"])  # a future-schema task still exists (not dangling)
        except (json.JSONDecodeError, KeyError) as exc:
            findings.append(f"{p.name}: unreadable ({exc})")
    # Future-schema tasks are reported but NOT structurally validated — this
    # engine can't interpret data from a newer version (DESIGN §10.12). doctor
    # is the ONE path that sees them (operational scans skip them).
    for t in tasks_list:
        if store.is_future(t):
            future.append(t)
            findings.append(
                f"{t['id']}: schema_version {t['schema_version']} is newer "
                f"than this engine ({SCHEMA_VERSION}) — run a newer taskforge "
                f"to operate on it; skipped by operational scans")
    for t in tasks_list:
        if t in future:
            continue  # can't validate structure this engine doesn't understand
        for e in t["edges"]:
            if e["target"] not in ids:
                findings.append(
                    f"{t['id']}: dangling {e['type']} edge -> {e['target']}")
        ref = t.get("decision_ref")
        if ref:
            parent = next((x for x in tasks_list
                           if x["id"] == ref["task_id"]), None)
            versions = ([a["version"] for a in
                         parent["artifacts"].get("decision", [])]
                        if parent else [])
            if not parent or ref["version"] not in versions:
                findings.append(
                    f"{t['id']}: decision_ref -> {ref['task_id']} "
                    f"v{ref['version']} does not resolve")
        if t["status"] not in TERMINAL:
            ev = evaluate(t)
            if ev["readiness"] == "human":
                findings.append(
                    f"{t['id']}: dependency cycle "
                    f"{ev.get('cycle')} (will park on next step)")
        for review in t["artifacts"].get("review", []):
            fname = (store.audit_dir()
                     / f"{t['id']}-review-v{review['version']}.prompt.md")
            if not fname.exists():
                findings.append(
                    f"{t['id']}: review v{review['version']} has no "
                    f"recorded reviewer prompt (audit-review will flag)")
    return {"tasks": len(tasks_list), "findings": findings,
            "clean": not findings}


def migrate():
    changed = []
    for t in store.all_tasks():
        if t.get("schema_version", 1) < SCHEMA_VERSION:
            t["schema_version"] = SCHEMA_VERSION  # v1: nothing else to do
            store.save(t)
            changed.append(t["id"])
    return {"schema_version": SCHEMA_VERSION, "migrated": changed}
