"""Projection API test suite.

Verifies the presentation layer's three load-bearing properties —
  * read-only    : no projection mutates the store;
  * deterministic: same store -> byte-identical projection;
  * serializable : pure JSON data (no framework/presentation objects);
plus correctness of each of the six domain projections, and the guard that the
layer never re-derives an engine-owned rule (landability).

Loads the facade first (registers the engine package), then the projection
module — both via importlib, matching the engine suite's hermetic style.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_tasks_spec = importlib.util.spec_from_file_location("tasks", _SCRIPTS / "tasks.py")
tasks = importlib.util.module_from_spec(_tasks_spec)
_tasks_spec.loader.exec_module(tasks)                     # registers engine.*

_proj_spec = importlib.util.spec_from_file_location(
    "projections", _SCRIPTS / "projections.py")
proj = importlib.util.module_from_spec(_proj_spec)
_proj_spec.loader.exec_module(proj)

store = sys.modules["engine.store"]
delivery = sys.modules["engine.delivery"]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="taskforge-proj-")
        os.environ["TASKFORGE_DIR"] = self.dir
        os.environ.pop("TASKFORGE_MAX_REVIEW_RETRIES", None)
        self._seq = 0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        os.environ.pop("TASKFORGE_DIR", None)

    # --- scenario builders (via the facade) ------------------------------
    def _rid(self):
        self._seq += 1
        return f"r{self._seq}"

    def apply(self, tid, actor, **kw):
        base = {"result_id": self._rid(), "artifacts": [], "generated_tasks": [],
                "edges": [], "signal": "none", "signal_reason": "", "notes": ""}
        base.update(kw)
        return tasks.apply_result(tasks.load(tid), base, actor)

    def create(self, title, source_type="manual", source_ref=None):
        t = tasks.new_task(title, "the description", source_type=source_type,
                           source_ref=source_ref)
        tasks.record(t, "created", "taskforge")
        tasks.refresh_status(t)
        tasks.save(t)
        return t["id"]

    def children(self, parent, titles):
        r = self.apply(parent, "human", generated_tasks=[
            {"title": t, "description": "d", "relation": "child"} for t in titles])
        return r["generated_tasks"]

    def decision(self, tid):
        self.apply(tid, "explore", artifacts=[
            {"kind": "decision",
             "payload": {"chosen_approach": "A", "rationale": "b"}}])

    def spec(self, tid, criteria=None):
        self.apply(tid, "refine", artifacts=[
            {"kind": "specification",
             "payload": {"scope": "do it",
                         "acceptance_criteria": criteria or ["it works"],
                         "adopted_from_source": False}}])

    def drive_done(self, tid, criteria=None, criteria_results=None):
        self.spec(tid, criteria)
        tasks.build_review_prompt(tid, "the diff", "3 passed")   # records prompt
        review = {"verdict": "approved", "findings": []}
        if criteria_results is not None:
            review["criteria_results"] = criteria_results
        self.apply(tid, "run", signal="done", signal_reason="ok", artifacts=[
            {"kind": "implementation",
             "payload": {"summary": "did it", "diff_ref": "b",
                         "test_results": {"passed": 3, "failed": 0,
                                          "summary": "g"}}},
            {"kind": "review", "payload": review}])

    def set_status(self, tid, status):
        t = tasks.load(tid)
        t["status"] = status
        tasks.save(t)


class TestBoard(Base):
    def test_board_groups_next_queues_counts(self):
        run_ready = self.create("fix cart rounding")
        self.spec(run_ready)                              # -> run
        refine_only = self.create("add taxes")           # -> refine
        parked = self.create("pricing default?")
        self.apply(parked, "refine", signal="block_on_human",
                   signal_reason="which currency fallback?")

        b = proj.board()
        self.assertEqual(b["next"]["id"], run_ready)      # run beats refine
        self.assertEqual(b["next"]["readiness"], "run")   # the domain fact
        self.assertNotIn("command", b["next"])            # no CLI leak
        self.assertEqual([a["id"] for a in b["ready"]["run"]], [run_ready])
        self.assertEqual([a["id"] for a in b["ready"]["refine"]], [refine_only])
        self.assertEqual(b["counts"]["run"], 1)
        self.assertEqual(b["counts"]["awaiting_human"], 1)  # blocked_on_human
        self.assertEqual(b["awaiting_human"][0]["task"]["id"], parked)
        self.assertEqual(b["awaiting_human"][0]["kind"], "question")
        self.assertEqual(b["awaiting_human"][0]["prompt"],
                         "which currency fallback?")

    def test_human_item_with_decision_is_a_proposal(self):
        t = self.create("delivery-status")
        self.apply(t, "refine", signal="escalate_explore",
                   signal_reason="undecided")
        self.decision(t)
        self.apply(t, "explore", signal="block_on_human",
                   signal_reason="approve the 3-child split?")
        b = proj.board()
        item = next(i for i in b["awaiting_human"] if i["task"]["id"] == t)
        self.assertEqual(item["kind"], "proposal")        # holds a decision


class TestTask(Base):
    def test_child_inherits_feature_and_lists_blockers(self):
        feat = self.create("SAP", source_type="github", source_ref="repo#900")
        tasks.link(tasks.load(feat), branch="feature/sap", pr="repo#901")
        a, b = self.children(feat, ["map schema", "nightly job"])
        self.spec(a)

        p = proj.task(a)
        self.assertEqual(p["ref"]["id"], a)
        self.assertEqual(p["feature"], {"id": feat, "title": "SAP"})
        self.assertEqual(p["delivery"]["branch"], "feature/sap")   # inherited
        self.assertEqual(p["delivery"]["owner"]["id"], feat)
        self.assertEqual(p["readiness"], "run")
        self.assertEqual([c["text"] for c in p["spec"]["criteria"]], ["it works"])
        self.assertEqual(p["spec"]["criteria"][0]["result"], "unchecked")
        self.assertIsNone(p["terminal"])                  # active, not terminal
        self.assertNotIn("status", p)                     # no internal cache leak

    def test_standalone_task_has_no_feature_and_own_delivery(self):
        t = self.create("solo")
        tasks.link(tasks.load(t), branch="solo-br")
        p = proj.task(t)
        self.assertIsNone(p["feature"])                   # it is its own unit
        self.assertEqual(p["delivery"]["owner"]["id"], t)


class TestFeature(Base):
    def _feature_with_children(self):
        feat = self.create("SAP", source_type="github", source_ref="repo#900")
        tasks.link(tasks.load(feat), branch="feature/sap", pr="repo#901")
        a, b = self.children(feat, ["map schema", "nightly job"])
        return feat, a, b

    def test_children_progress_and_not_landable(self):
        feat, a, b = self._feature_with_children()
        self.drive_done(a)                                # a done, b open
        f = proj.feature(feat)
        self.assertEqual(f["progress"], {"closed": 1, "total": 2})
        ids = {c["id"]: c for c in f["children"]}
        self.assertEqual(ids[a]["review_state"], "approved")
        self.assertEqual(ids[a]["depth"], 0)
        self.assertFalse(f["landing"]["landable"])
        self.assertEqual([blk["id"] for blk in f["landing"]["blockers"]], [b])
        self.assertEqual(f["audit"]["reviews_unaudited"], 0)  # prompt recorded

    def test_landable_when_all_children_closed(self):
        feat, a, b = self._feature_with_children()
        self.set_status(a, "done")
        self.set_status(b, "cancelled")
        self.set_status(feat, "done")
        f = proj.feature(feat)
        self.assertTrue(f["landing"]["landable"])
        self.assertEqual(f["landing"]["blockers"], [])

    def test_landing_never_re_derives_the_engine_rule(self):
        # The projection must surface, byte-for-byte, what the engine decides.
        feat, a, b = self._feature_with_children()
        self.drive_done(a)
        engine_ls = delivery.landing_status(tasks.load(feat))
        f = proj.feature(feat)
        self.assertEqual(f["landing"]["landable"], engine_ls["landable"])
        self.assertEqual([blk["id"] for blk in f["landing"]["blockers"]],
                         [d["id"] for d in engine_ls["blockers"]])


class TestReview(Base):
    def test_attempts_criteria_audit_budget(self):
        t = self.create("map schema")
        self.spec(t, criteria=["fields mapped", "currency ISO-4217"])
        # attempt 1: rejected
        tasks.build_review_prompt(t, "diff1", "res1")
        self.apply(t, "run", artifacts=[
            {"kind": "implementation", "payload": {"summary": "v1", "diff_ref": "b",
             "test_results": {"passed": 1, "failed": 0, "summary": "g"}}},
            {"kind": "review", "payload": {"verdict": "rejected",
             "root_cause": "implementation", "findings": ["rounding drops paise"]}}])
        # attempt 2: approved, with per-criterion results
        tasks.build_review_prompt(t, "diff2", "res2")
        self.apply(t, "run", signal="done", signal_reason="ok", artifacts=[
            {"kind": "implementation", "payload": {"summary": "v2", "diff_ref": "b",
             "test_results": {"passed": 2, "failed": 0, "summary": "g"}}},
            {"kind": "review", "payload": {"verdict": "approved", "findings": [],
             "criteria_results": [{"criterion": "fields mapped", "passed": True,
                                   "note": ""}]}}])

        r = proj.review(t)
        self.assertEqual([a["version"] for a in r["attempts"]], [1, 2])
        self.assertEqual(r["attempts"][0]["verdict"], "rejected")
        self.assertEqual(r["attempts"][0]["findings"], ["rounding drops paise"])
        self.assertEqual(r["attempts"][1]["verdict"], "approved")
        # criteria joined to results: one pass, one unchecked (never fabricated)
        by_text = {c["text"]: c["result"] for c in r["criteria"]}
        self.assertEqual(by_text["fields mapped"], "pass")
        self.assertEqual(by_text["currency ISO-4217"], "unchecked")
        self.assertTrue(r["audit"]["isolated"])           # prompts recorded
        self.assertEqual(r["budget"]["retries_used"], 1)  # one rejection


class TestHealth(Base):
    def test_done_unlanded_reports_units_not_inherited_children(self):
        # a standalone done task, never linked -> reviewed, not merged
        solo = self.create("fix rounding")
        self.drive_done(solo)
        # a feature landed, with a done child that inherits the landed delivery
        feat = self.create("SAP")
        a, = self.children(feat, ["map schema"])
        self.drive_done(a)
        self.set_status(feat, "done")
        tasks.link(tasks.load(feat), branch="feature/sap", pr="#1", landed=True)

        h = proj.health()
        unl = {c["id"] for c in h["done_unlanded"]}
        self.assertIn(solo, unl)              # standalone, unmerged
        self.assertNotIn(a, unl)              # inherits a LANDED feature
        self.assertNotIn(feat, unl)           # itself landed
        self.assertTrue(h["integrity_ok"])

    def test_unaudited_review_is_flagged(self):
        t = self.create("x")
        self.spec(t)
        # apply a review WITHOUT recording a prompt -> unaudited
        self.apply(t, "run", signal="done", signal_reason="ok", artifacts=[
            {"kind": "implementation", "payload": {"summary": "i", "diff_ref": "b",
             "test_results": {"passed": 1, "failed": 0, "summary": "g"}}},
            {"kind": "review", "payload": {"verdict": "approved", "findings": []}}])
        h = proj.health()
        self.assertTrue(any(u["id"] == t for u in h["unaudited_reviews"]))


class TestDigest(Base):
    def test_groups_events_by_impact_since(self):
        t = self.create("x")
        self.spec(t)
        boundary = tasks.now()                # everything after this counts
        self.drive_done(t)                    # emits a 'done' event
        d = proj.digest(boundary)
        done_ids = {i["task"]["id"] for i in d["groups"]["done"]}
        self.assertIn(t, done_ids)
        self.assertGreaterEqual(d["total"], 1)
        # an event strictly before the boundary is excluded
        self.assertEqual(proj.digest(tasks.now())["total"], 0)


class TestLayerProperties(Base):
    """The three cross-cutting guarantees, exercised over a rich store."""

    def scenario(self):
        feat = self.create("SAP", source_type="github", source_ref="repo#900")
        tasks.link(tasks.load(feat), branch="feature/sap", pr="repo#901")
        a, b = self.children(feat, ["map schema", "nightly job"])
        self.drive_done(a)
        self.spec(b)
        solo = self.create("fix rounding")
        self.spec(solo)
        parked = self.create("pricing?")
        self.apply(parked, "refine", signal="block_on_human",
                   signal_reason="which currency?")
        return {"feat": feat, "child": a, "solo": solo}

    def all_projections(self, ids):
        return {
            "board": proj.board(),
            "health": proj.health(),
            "digest": proj.digest("2000-01-01T00:00:00+00:00"),
            "task": proj.task(ids["child"]),
            "feature": proj.feature(ids["feat"]),
            "review": proj.review(ids["child"]),
        }

    def store_state(self):
        return {p.name: p.read_bytes()
                for p in sorted(store.store_dir().glob("TASK-*.json"))}

    def test_read_only(self):
        ids = self.scenario()
        before = self.store_state()
        self.all_projections(ids)
        self.assertEqual(self.store_state(), before,
                         "a projection mutated the store")

    def test_deterministic(self):
        ids = self.scenario()
        first = self.all_projections(ids)
        second = self.all_projections(ids)
        for name in first:
            self.assertEqual(json.dumps(first[name], sort_keys=True),
                             json.dumps(second[name], sort_keys=True),
                             f"{name} projection is not deterministic")

    def test_pure_serializable_data(self):
        ids = self.scenario()
        for name, p in self.all_projections(ids).items():
            # round-trips through JSON with no custom encoder -> pure data,
            # no framework/presentation objects leaked into the contract.
            self.assertEqual(json.loads(json.dumps(p)), p,
                             f"{name} projection is not pure JSON data")


if __name__ == "__main__":
    unittest.main()
