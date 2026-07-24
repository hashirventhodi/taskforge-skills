"""tf (terminal client) test suite.

The CLI is a presentation *adapter* over the Projection API — it must render
projections faithfully and add no logic of its own. These tests assert that:
  * each command renders without error and surfaces the projection's facts;
  * it shares the Web UI's terminology (the domain-concept vocabulary);
  * the audit label it prints is exactly the projection's Audit Status, mapped
    (never independently computed) — the client-agnosticism guarantee.
"""
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_S = Path(__file__).resolve().parent.parent / "scripts"
_t = importlib.util.spec_from_file_location("tasks", _S / "tasks.py")
tasks = importlib.util.module_from_spec(_t)
_t.loader.exec_module(tasks)
_c = importlib.util.spec_from_file_location("tf", _S / "tf.py")
tf = importlib.util.module_from_spec(_c)
_c.loader.exec_module(tf)
proj = sys.modules.get("projections")


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="taskforge-cli-")
        os.environ["TASKFORGE_DIR"] = self.dir
        os.environ["NO_COLOR"] = "1"
        self._n = 0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        os.environ.pop("TASKFORGE_DIR", None)
        os.environ.pop("NO_COLOR", None)

    def run_tf(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tf.main(list(argv))
        return buf.getvalue()

    def _apply(self, tid, actor, **kw):
        b = {"result_id": f"r{self._n}", "artifacts": [], "generated_tasks": [],
             "edges": [], "signal": "none", "signal_reason": "", "notes": ""}
        self._n += 1
        b.update(kw)
        return tasks.apply_result(tasks.load(tid), b, actor)

    def audited_done(self, title="map schema"):
        t = tasks.new_task(title, "d")
        tasks.record(t, "created", "taskforge"); tasks.refresh_status(t); tasks.save(t)
        tid = t["id"]
        self._apply(tid, "refine", artifacts=[{"kind": "specification", "payload": {
            "scope": "do it", "acceptance_criteria": ["it works"],
            "adopted_from_source": False}}])
        tasks.build_review_prompt(tid, "the diff", "3 passed")
        self._apply(tid, "run", signal="done", signal_reason="ok", artifacts=[
            {"kind": "implementation", "payload": {"summary": "did it", "diff_ref": "b",
             "test_results": {"passed": 3, "failed": 0, "summary": "g"}}},
            {"kind": "review", "payload": {"verdict": "approved", "findings": []}}])
        return tid

    def import_projections(self):
        with contextlib.redirect_stdout(io.StringIO()):
            tf.main(["health"])  # forces tf's lazy `import projections`
        return sys.modules["projections"]


class TestCli(Base):
    def test_task_shows_review_result_and_audit_status_separately(self):
        tid = self.audited_done()
        out = self.run_tf("task", tid)
        self.assertIn("map schema", out)
        self.assertIn("approved", out)          # Review Result
        self.assertIn("isolated", out)          # Audit Status (verified -> "isolated")
        self.assertIn("did the work pass", out)
        self.assertIn("can the review be trusted", out)

    def test_health_uses_the_domain_vocabulary(self):
        self.audited_done()
        out = self.run_tf("health").lower()
        for term in ("structural integrity", "sound", "review audit", "verified",
                     "done but not landed"):
            self.assertIn(term, out)
        self.assertNotIn("integrity issues", out)   # audit never dressed as integrity

    def test_board_renders_and_dedups_next(self):
        # a run-ready task becomes the single "next" and is not repeated in Ready
        t = tasks.new_task("solo", "d")
        tasks.record(t, "created", "taskforge"); tasks.refresh_status(t); tasks.save(t)
        self._apply(t["id"], "refine", artifacts=[{"kind": "specification", "payload": {
            "scope": "s", "acceptance_criteria": ["w"], "adopted_from_source": False}}])
        out = self.run_tf("board")
        self.assertIn("NEXT", out)
        self.assertIn("taskforge-run", out)     # CLI-only command hint from readiness
        self.assertEqual(out.count("solo"), 1)  # deduped: hero only, not in Ready

    def test_audit_label_matches_the_projection_exactly(self):
        # The CLI never computes audit status — it maps the projection's value.
        tid = self.audited_done()
        P = self.import_projections()
        status = P.task(tid)["audit"]["status"]     # projection's fact
        label = {"verified": "isolated", "breach": "isolation breach",
                 "unrecorded": "unaudited", "none": "no review"}[status]
        self.assertIn(label, self.run_tf("task", tid))

    def test_unknown_task_is_an_engine_error(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            code = tf.main(["task", "TASK-doesnotexist1"])
        self.assertEqual(code, 2)
        self.assertIn("error", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
