#!/usr/bin/env python3
"""Stage fixture stores for Human Console design and testing.

One store per way the engine can need a human — the park causes — plus a
quiet store (empty queue) and self-verification: every store is built through
real engine commands only and asserted to end in exactly the state it claims
to stage, so each fixture is a state the engine actually produces, never a
hand-authored JSON. Regenerate at will: task ids and timestamps change,
structure does not.

Fixtures:
  topology-proposal    explore parked a decision + decomposition proposal
  research-disposition explore parked a research deliverable (close/spawn/continue)
  blocked-question     refine parked on a question for the human
  review-budget        engine parked: implementation-fault retries exhausted
  version-breaker      engine parked: artifact versions not converging
  dependency-cycle     engine parked: blocked_by cycle (one side parked,
                       the other surfaces via readiness "human")
  quiet                nothing needs a human (empty-queue state)

Usage:  python3 scripts/make_fixtures.py <out_dir>
Layout: <out_dir>/<fixture>/            the .tasks store
        <out_dir>/snapshots/<name>.json its snapshot
"""
import contextlib
import importlib.util
import io
import itertools
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "tasks", ROOT / "taskforge" / "scripts" / "tasks.py")
tasks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tasks)

_rid = itertools.count(1)


def cli(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        tasks.main(argv)
    return json.loads(buf.getvalue())


class Stage:
    """One fixture store: a fresh TASKFORGE_DIR plus command helpers."""

    def __init__(self, out_root, name):
        self.name = name
        self.dir = out_root / name
        self.results = out_root / ".results"
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        self.results.mkdir(exist_ok=True)
        os.environ["TASKFORGE_DIR"] = str(self.dir)

    def create(self, title, desc, explore=False):
        argv = ["create", "--title", title, "--description", desc]
        if explore:
            argv.append("--explore")
        return cli(argv)["id"]

    def apply(self, tid, actor, payload):
        payload.setdefault("result_id", f"fixture-{next(_rid)}")
        p = self.results / "r.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return cli(["apply", tid, str(p), "--actor", actor])

    def expect(self, tid, status=None, readiness=None):
        t = tasks.load(tid)
        if status and t["status"] != status:
            sys.exit(f"{self.name}: {tid} status {t['status']!r}, "
                     f"expected {status!r}")
        actual = tasks.evaluate(t)["readiness"]
        if readiness and actual != readiness:
            sys.exit(f"{self.name}: {tid} readiness {actual!r}, "
                     f"expected {readiness!r}")


def spec(scope, n=1):
    return {"kind": "specification",
            "payload": {"scope": scope,
                        "acceptance_criteria": ["behavior verified by test",
                                                "no regression in suite"],
                        "adopted_from_source": False},
            **({"supersedes_reason": f"rework attempt {n}"} if n > 1 else {})}


def fx_topology_proposal(st):
    tid = st.create(
        "Add SSO login to the dashboard",
        "Customers keep asking for SSO. We currently only have "
        "email+password. Needs to work with their existing IdPs.")
    st.apply(tid, "refine", {
        "signal": "escalate_explore",
        "signal_reason": "IdP protocol choice (SAML vs OIDC) and the session "
                         "model are architectural: they change what work "
                         "exists, so a spec here would be a guess"})
    st.apply(tid, "explore", {
        "artifacts": [{"kind": "decision", "payload": {
            "chosen_approach": "OIDC via Auth0; sessions in signed, httpOnly "
                               "cookies; per-tenant IdP config in the org "
                               "settings table",
            "rationale": "every customer IdP surveyed supports OIDC; Auth0 "
                         "removes protocol edge cases we'd otherwise own",
            "alternatives": [
                {"approach": "SAML via Okta",
                 "rejected_because": "two of nine customer IdPs have no SAML "
                                     "endpoint; ours would need both stacks"},
                {"approach": "hand-rolled OIDC",
                 "rejected_because": "token rotation + key management is "
                                     "undifferentiated risk"}],
            "trade_offs": ["vendor dependency on Auth0",
                           "per-login cost at seat scale"],
            "risks": ["Auth0 tenant migration is one-way"]}}],
        "signal": "block_on_human",
        "signal_reason": (
            "TOPOLOGY PROPOSED FOR APPROVAL — the engine will not let "
            "explore create tasks or dependency edges; the human commits "
            "them.\n\n"
            "DECOMPOSITION:\n"
            "  1. Wire the OIDC redirect flow — Auth0 app config, callback "
            "route, state/nonce handling\n"
            "  2. Issue and validate session cookies — signed httpOnly "
            "cookie, rotation, logout\n"
            "  3. Per-tenant IdP settings — org settings table + admin UI "
            "field\n\n"
            "RELATED FINDINGS outside this task's scope:\n"
            "  - Password-reset flow bypasses rate limiting → recommend: "
            "promote to backlog\n\n"
            "RECOMMENDATION: approve all three children as proposed; promote "
            "the rate-limiting finding."),
        "notes": "decision recorded; topology proposed for human approval"})
    st.expect(tid, status="blocked_on_human")
    return "explore parked: decision + 3-child decomposition + 1 finding"


def fx_research_disposition(st):
    tid = st.create(
        "Should we migrate analytics to ClickHouse?",
        "Query latency on the analytics dashboard is creeping up. "
        "Evaluate whether ClickHouse is worth the migration.",
        explore=True)
    st.apply(tid, "explore", {
        "artifacts": [{"kind": "decision", "payload": {
            "chosen_approach": "Stay on Postgres; add a covering index on "
                               "events(account_id, occurred_at) and a nightly "
                               "rollup table",
            "rationale": "p95 dashboard query is 1.8s from two missing "
                         "indexes, not engine limits; dataset is 40GB, three "
                         "orders below where ClickHouse pays for its ops cost",
            "alternatives": [
                {"approach": "migrate to ClickHouse",
                 "rejected_because": "dual-write migration plus a second "
                                     "query dialect for a dataset Postgres "
                                     "handles after indexing"}],
            "trade_offs": ["revisit if event volume grows ~50x"],
            "risks": ["rollup adds a nightly job to operate"]}}],
        "signal": "block_on_human",
        "signal_reason": (
            "DECISION IS THE DELIVERABLE — this task was created to reach a "
            "direction, not to be specified.\n\n"
            "RECOMMENDED DISPOSITION (pick one):\n"
            "  - close: the answer above is the deliverable\n"
            "  - spawn independent work then close: file 'add covering index "
            "+ nightly rollup' as backlog\n"
            "  - continue: specify and build the indexing work as this task\n\n"
            "RECOMMENDATION: spawn the indexing work as one backlog task, "
            "then close — the research answered the question."),
        "notes": "research decision recorded; parked for disposition"})
    st.expect(tid, status="blocked_on_human")
    return "explore parked: research deliverable awaiting disposition"


def fx_blocked_question(st):
    tid = st.create(
        "Bound cart message body to the WhatsApp 1024-char limit",
        "Large carts render interactive message bodies over the WhatsApp "
        "1024-character limit and the send fails at the API.")
    st.apply(tid, "refine", {
        "signal": "block_on_human",
        "signal_reason": "When a rendered cart body exceeds 1024 chars, "
                         "should we (a) truncate the item list with an "
                         "ellipsis and item count, or (b) reject at our API "
                         "boundary and surface an error to the caller? "
                         "Product call — (a) always delivers but hides "
                         "items; (b) is honest but drops the message. "
                         "Recommend (a).",
        "notes": "spec blocked on a product decision"})
    st.expect(tid, status="blocked_on_human")
    return "refine parked: one question, two options, a recommendation"


def fx_review_budget(st):
    tid = st.create(
        "Guard the plain-text send path against oversized payloads",
        "The plain-text WhatsApp send path has no length guard; oversized "
        "payloads 400 at the provider.")
    st.apply(tid, "refine", {"artifacts": [
        spec("Add a length guard to the plain-text send path; reject over "
             "4096 bytes with a typed error")]})
    for attempt in (1, 2, 3):
        impl = {"kind": "implementation",
                "payload": {"summary": f"guard attempt {attempt}",
                            "diff_ref": f"branch:guard-v{attempt}",
                            "test_results": {"passed": 11, "failed": 1,
                                             "summary": "boundary case red"}}}
        if attempt > 1:
            impl["supersedes_reason"] = "review found the boundary off by one"
        st.apply(tid, "run", {"artifacts": [
            impl,
            {"kind": "review", "payload": {
                "verdict": "rejected", "root_cause": "implementation",
                "findings": [f"attempt {attempt}: guard fires at 4097, "
                             f"spec says over 4096"]}}]})
    st.expect(tid, status="blocked_on_human")
    return "engine parked: 3rd implementation-fault rejection exhausted the budget"


def fx_version_breaker(st):
    tid = st.create(
        "Normalize webhook retry semantics",
        "Webhook consumers see inconsistent retry behavior across "
        "endpoints; agree and enforce one policy.")
    for n in (1, 2, 3, 4):
        st.apply(tid, "refine", {"artifacts": [
            spec(f"retry policy draft {n}: exponential backoff, "
                 f"{n + 2} attempts, dead-letter after", n)]})
    st.expect(tid, status="blocked_on_human")
    return "engine parked: specification hit v4 without converging"


def fx_dependency_cycle(st):
    a = st.create("Extract shared auth middleware",
                  "Both services duplicate token validation; extract one "
                  "middleware package.")
    b = st.create("Migrate session storage to Redis",
                  "Sessions live in process memory; move to Redis so "
                  "instances can share.")
    st.apply(a, "human", {"edges": [{"type": "blocked_by", "target": b}]})
    st.apply(b, "human", {"edges": [{"type": "blocked_by", "target": a}]})
    # The engine parks the task it detected the cycle on; the other side is
    # NOT parked — it surfaces through readiness "human". A console reading
    # only status would show half the problem.
    st.expect(b, status="blocked_on_human")
    st.expect(a, readiness="human")
    return "engine parked one side of a blocked_by cycle; other side is readiness=human"


def fx_quiet(st):
    st.create("Add CSV export to the report page",
              "Users want the on-screen report as a CSV download.")
    t2 = st.create("Rename customer_id to account_id in billing DTOs",
                   "Field predates the accounts refactor; align the DTOs.")
    st.apply(t2, "refine", {"artifacts": [
        spec("Rename the field across billing DTOs and regenerate clients")]})
    st.expect(t2, readiness="run")
    return "nothing needs a human: one refine, one run"


FIXTURES = [
    ("topology-proposal", fx_topology_proposal),
    ("research-disposition", fx_research_disposition),
    ("blocked-question", fx_blocked_question),
    ("review-budget", fx_review_budget),
    ("version-breaker", fx_version_breaker),
    ("dependency-cycle", fx_dependency_cycle),
    ("quiet", fx_quiet),
]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip())
    out_root = Path(sys.argv[1]).resolve()
    snaps = out_root / "snapshots"
    snaps.mkdir(parents=True, exist_ok=True)
    for name, build in FIXTURES:
        st = Stage(out_root, name)
        summary = build(st)
        snap = cli(["snapshot"])
        (snaps / f"{name}.json").write_text(
            json.dumps(snap, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        parked = sum(1 for t in snap["tasks"]
                     if t["status"] == "blocked_on_human")
        print(f"ok {name:22} tasks={len(snap['tasks'])} "
              f"parked={parked}  {summary}")
    os.environ.pop("TASKFORGE_DIR", None)
    shutil.rmtree(out_root / ".results", ignore_errors=True)
    print(f"\nfixtures + snapshots in {out_root}")


if __name__ == "__main__":
    main()
