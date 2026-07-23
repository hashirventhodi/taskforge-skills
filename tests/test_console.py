"""Console server tests — the thin-client contract, enforced.

The Human Console server (console/server.py) must add no behavior of its own:
every operation is a real engine CLI invocation, writes are whitelisted to
the human's command surface, and untrusted browser text reaches the engine
only through file-input flags. These tests run the real server (loopback,
ephemeral port) against a real store built through the engine.

Stdlib only. Run: python3 -m unittest discover tests
"""
import importlib.util
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_sspec = importlib.util.spec_from_file_location(
    "console_server", ROOT / "console" / "server.py")
server = importlib.util.module_from_spec(_sspec)
_sspec.loader.exec_module(server)
tasks = server.tasks  # the engine facade the server itself uses


class ConsoleBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="console-test-")
        os.environ["TASKFORGE_DIR"] = self.dir

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        os.environ.pop("TASKFORGE_DIR", None)

    def http(self, path, body=None):
        """Return (status, parsed_json). Never raises on HTTP error codes."""
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"} if body else {},
        )
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                return e.code, json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                return e.code, {"raw": raw}

    def parked_question(self):
        t = tasks.new_task("q-task", "needs an answer")
        tasks.record(t, "created", "taskforge")
        tasks.refresh_status(t)
        tasks.save(t)
        tasks.apply_result(t, {"result_id": "p1", "signal": "block_on_human",
                               "signal_reason": "which option?"}, "refine")
        return t["id"]


class TestReads(ConsoleBase):
    def test_snapshot_is_the_engine_snapshot(self):
        self.parked_question()
        status, snap = self.http("/api/snapshot")
        self.assertEqual(status, 200)
        for key in ("snapshot_version", "tasks", "edges", "skipped"):
            self.assertIn(key, snap)
        self.assertEqual(len(snap["tasks"]), 1)
        self.assertEqual(snap["tasks"][0]["human_blocked"]["actor"], "refine")

    def test_task_detail_bundles_show_and_budget(self):
        tid = self.parked_question()
        status, d = self.http(f"/api/task/{tid}")
        self.assertEqual(status, 200)
        self.assertEqual(d["task"]["id"], tid)
        self.assertIn("history", d["task"])
        self.assertIn("next_review_version", d["budget"])

    def test_unknown_task_is_an_engine_error(self):
        status, d = self.http("/api/task/TASK-doesnotexist1")
        self.assertEqual(status, 422)
        self.assertIn("error", d)

    def test_static_index_served_and_traversal_blocked(self):
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertEqual(r.status, 200)
            self.assertIn(b"Human Console", r.read())
        status, _ = self.http("/../../etc/hosts")
        self.assertEqual(status, 404)


class TestWrites(ConsoleBase):
    def test_answer_resumes_park_and_hostile_note_is_data(self):
        # The injection-safe path, end to end through the web layer: hostile
        # browser text must reach the store verbatim as data. Teeth: passing
        # the note inline in argv instead of by file would shell-expand
        # nothing here (no shell), but would violate the file-form contract —
        # this asserts the stored event, the observable outcome.
        tid = self.parked_question()
        hostile = "pick (a) `rm -rf /` $(evil)"
        status, out = self.http("/api/command", {
            "command": "human-update", "id": tid, "text": {"note": hostile}})
        self.assertEqual(status, 200)
        self.assertEqual(out["readiness"], "refine")
        t = tasks.load(tid)
        ev = [e for e in t["history"] if e["type"] == "human_updated"][-1]
        self.assertEqual(ev["reason"], hostile)

    def test_disposition_close_via_result(self):
        tid = self.parked_question()
        status, out = self.http("/api/command", {
            "command": "human-update", "id": tid,
            "text": {"note": "closing"},
            "result": {"result_id": "r-close", "signal": "done"}})
        self.assertEqual(status, 200)
        self.assertEqual(tasks.load(tid)["status"], "done")

    def test_non_whitelisted_command_refused_before_the_engine(self):
        # The server's own gate: apply/validate/etc. are skill commands, not
        # the human surface. Teeth: removing the whitelist makes this 200.
        status, d = self.http("/api/command",
                              {"command": "apply", "id": "TASK-x"})
        self.assertEqual(status, 400)
        self.assertIn("not allowed", d["error"])

    def test_engine_refusal_surfaces_verbatim(self):
        tid = self.parked_question()
        status, d = self.http("/api/command", {
            "command": "reopen", "id": tid, "text": {"reason": "x"}})
        self.assertEqual(status, 422)  # parked, not a closed terminal
        self.assertIn("error", d)

    def test_result_only_valid_for_human_update(self):
        tid = self.parked_question()
        status, d = self.http("/api/command", {
            "command": "cancel", "id": tid, "text": {"reason": "r"},
            "result": {"signal": "done"}})
        self.assertEqual(status, 400)


class TestMarkdownWiring(ConsoleBase):
    """The markdown renderer stays wired. Semantic + XSS coverage lives in the
    browser assertion page (console/static/md-test.html) because rendering is
    client-side and CI is Python-only; this guards the plumbing deterministically
    so the renderer can't be silently unhooked or mis-served."""

    STATIC = ROOT / "console" / "static"

    def test_md_js_served_as_javascript(self):
        with urllib.request.urlopen(self.base + "/md.js") as r:
            self.assertEqual(r.status, 200)
            self.assertIn("javascript", r.headers.get("Content-Type", ""))
            self.assertIn(b"renderMarkdown", r.read())

    def test_index_loads_md_before_app(self):
        html = (self.STATIC / "index.html").read_text()
        self.assertIn('src="/md.js"', html)
        self.assertLess(html.index('src="/md.js"'), html.index('src="/app.js"'),
                        "md.js must load before app.js (app.js calls renderMarkdown)")

    def test_md_defines_the_public_renderers(self):
        src = (self.STATIC / "md.js").read_text()
        for name in ("renderMarkdown", "renderMarkdownInline", "safeHref"):
            self.assertIn(name, src)

    def test_test_page_is_served(self):
        with urllib.request.urlopen(self.base + "/md-test.html") as r:
            self.assertEqual(r.status, 200)
            self.assertIn(b"__mdTestResult", r.read())


if __name__ == "__main__":
    unittest.main()
