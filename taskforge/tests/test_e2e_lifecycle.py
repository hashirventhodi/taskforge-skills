"""End-to-end lifecycle test — the whole workflow through the real CLI
dispatch (tasks.main), not the facade internals. Unit tests prove each rule in
isolation; this proves they compose correctly across a full feature, with the
emphasis on the interaction boundaries where ownership changes hide:

  explore -> refine -> children -> build-review-prompt -> review -> done ->
  link feature -> children inherit delivery -> landing gate (reopened child
  blocks) -> land -> reopen (landed cleared, children read not-landed) ->
  reland -> sync-back precondition -> doctor clean.

Promoted from the v0.6.0 dogfood run: it caught a real interaction (idempotency
correctly deduping a reused result_id across reopen), and it guards the derived-
delivery model (DESIGN §10.19) against regressions that unit tests would miss.
"""
import contextlib
import importlib.util
import io
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


class TestEndToEndLifecycle(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="taskforge-e2e-")
        os.environ["TASKFORGE_DIR"] = self.dir
        os.environ.pop("TASKFORGE_MAX_REVIEW_RETRIES", None)
        self.seq = 0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        os.environ.pop("TASKFORGE_DIR", None)

    # --- CLI harness -----------------------------------------------------
    def cli(self, argv):
        """Run a command through the real dispatch; return parsed stdout."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            tasks.main(argv)
        txt = buf.getvalue().strip()
        return json.loads(txt) if txt else None

    def cli_error(self, argv):
        """Run a command expected to fail; return the parsed stderr error."""
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit):
                tasks.main(argv)
        return json.loads(buf.getvalue())["error"]

    def uid(self, prefix):
        # Every apply needs a fresh result_id (the run skill mints one per
        # attempt); a reused id is correctly deduped by engine idempotency.
        self.seq += 1
        return f"{prefix}_{self.seq}"

    def rf(self, **kw):
        obj = {"result_id": self.uid("res"), "artifacts": [],
               "generated_tasks": [], "edges": [], "signal": "none",
               "signal_reason": "", "notes": ""}
        obj.update(kw)
        p = Path(self.dir) / f"{obj['result_id']}.json"
        p.write_text(json.dumps(obj), encoding="utf-8")
        return str(p)

    def wf(self, text):
        p = Path(self.dir) / f"{self.uid('f')}.txt"
        p.write_text(text, encoding="utf-8")
        return str(p)

    def spec_art(self, crit):
        return {"kind": "specification",
                "payload": {"scope": "do it", "acceptance_criteria": crit,
                            "adopted_from_source": False}}

    def drive_to_done(self, tid, crit):
        """refine (spec) -> build-review-prompt (E1) -> run (impl+review)."""
        self.cli(["apply", tid, self.rf(artifacts=[self.spec_art(crit)]),
                  "--actor", "refine"])
        self.assertEqual(self.cli(["readiness", tid])["readiness"], "run")
        self.cli(["build-review-prompt", tid,
                  "--diff", self.wf("the change"),
                  "--results", self.wf("3 passed")])
        self.cli(["apply", tid, self.rf(artifacts=[
            {"kind": "implementation",
             "payload": {"summary": "did it", "diff_ref": "feature/sap",
                         "test_results": {"passed": 3, "failed": 0,
                                          "summary": "green"}}},
            {"kind": "review", "payload": {"verdict": "approved",
                                           "findings": []}}],
            signal="done", signal_reason="reviewed"), "--actor", "run"])
        self.assertEqual(self.cli(["readiness", tid])["readiness"], "terminal")

    # --- the whole workflow, one narrative ------------------------------
    def test_full_feature_lifecycle(self):
        # explore intake: a feature that must reach a Decision first
        feat = self.cli(["create", "--title", "SAP Invoice Integration",
                         "--description", "Sync invoices to SAP nightly",
                         "--source-type", "github",
                         "--source-ref", "repo#900"])["id"]
        self.assertEqual(self.cli(["readiness", feat])["readiness"], "refine")

        # refine escalates the architectural fork -> explore
        self.cli(["apply", feat, self.rf(signal="escalate_explore",
                  signal_reason="batch vs streaming"), "--actor", "refine"])
        self.assertEqual(self.cli(["readiness", feat])["readiness"], "explore")

        # explore decides, then the human commits the decomposition
        self.cli(["apply", feat, self.rf(artifacts=[
            {"kind": "decision",
             "payload": {"chosen_approach": "batch nightly sync",
                         "rationale": "low volume"}}]), "--actor", "explore"])
        r = self.cli(["apply", feat, self.rf(generated_tasks=[
            {"title": "map schema", "description": "d", "relation": "child"},
            {"title": "nightly job", "description": "d", "relation": "child"}]),
            "--actor", "human"])
        child_a, child_b = r["generated_tasks"]
        self.assertEqual(self.cli(["readiness", feat])["readiness"], "waiting")

        # implement both children, then the feature's own refine+run
        self.drive_to_done(child_a, ["fields map 1:1 to SAP IDoc"])
        self.drive_to_done(child_b, ["runs nightly at 02:00 UTC"])
        self.assertEqual(self.cli(["readiness", feat])["readiness"], "refine")
        self.drive_to_done(feat, ["end-to-end sync verified"])
        self.assertEqual(self.cli(["show", feat])["status"], "done")

        # link the feature's delivery; children INHERIT it (derived)
        self.cli(["link", feat, "--branch", "feature/sap", "--pr", "repo#901"])
        rows = {t["id"]: t for t in self.cli(["snapshot"])["tasks"]}
        for cid in (child_a, child_b):
            self.assertEqual(rows[cid]["delivery"],
                             {"branch": None, "pr": None, "landed_at": None})
            self.assertEqual(rows[cid]["delivery_owner"]["id"], feat)
            self.assertEqual(rows[cid]["resolved_delivery"]["branch"],
                             "feature/sap")
        self.assertEqual(rows[feat]["delivery_owner"]["id"], feat)  # self

        # landing gate: a reopened child blocks the feature from landing
        self.cli(["reopen", child_a, "--reason", "edge case in mapping"])
        err = self.cli_error(["link", feat, "--landed"])
        self.assertIn("not closed", err)
        self.assertIn(child_a, err)
        self.drive_to_done(child_a, ["edge case handled"])  # re-close it

        # land the feature; status unchanged, children resolve as landed
        out = self.cli(["link", feat, "--landed"])
        landed_ts = out["delivery"]["landed_at"]
        self.assertIsNotNone(landed_ts)
        self.assertEqual(self.cli(["show", feat])["status"], "done")
        rows = {t["id"]: t for t in self.cli(["snapshot"])["tasks"]}
        self.assertEqual(rows[child_a]["resolved_delivery"]["landed_at"],
                         landed_ts)
        # sync-back precondition a skill acts on: github source + resolved land
        self.assertEqual(rows[feat]["source"]["type"], "github")
        self.assertIsNotNone(rows[feat]["resolved_delivery"]["landed_at"])

        # reopen the feature: landing lifted, children read NOT landed
        self.cli(["reopen", feat, "--reason", "SAP changed the IDoc schema"])
        ft = self.cli(["show", feat])
        self.assertIsNone(ft["delivery"]["landed_at"])         # cleared
        self.assertEqual(ft["delivery"]["branch"], "feature/sap")  # kept
        self.assertEqual(ft["delivery"]["pr"], "repo#901")
        hist = [e["type"] for e in ft["history"]]
        self.assertEqual(hist.count("landed"), 1)              # provenance
        self.assertIn("reopened", hist)
        rows = {t["id"]: t for t in self.cli(["snapshot"])["tasks"]}
        self.assertIsNone(rows[child_a]["resolved_delivery"]["landed_at"])
        self.assertEqual(rows[child_a]["resolved_delivery"]["branch"],
                         "feature/sap")                        # still resolves

        # reland: re-review the reopened feature, then land again
        self.assertEqual(self.cli(["readiness", feat])["readiness"], "run")
        self.drive_to_done(feat, ["re-verified against new schema"])
        self.cli(["link", feat, "--landed"])
        ft = self.cli(["show", feat])
        self.assertEqual([e["type"] for e in ft["history"]].count("landed"), 2)

        # integrity across all the ownership churn
        doc = self.cli(["doctor"])
        self.assertTrue(doc["clean"], doc["findings"])


if __name__ == "__main__":
    unittest.main()
