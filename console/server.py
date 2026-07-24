#!/usr/bin/env python3
"""Human Console server — a thin local client of the taskforge engine.

The Console hosts the projection-driven Web UI, one of several presentation
adapters over the Projection API (docs/ARCHITECTURE.md). This server adds NO
behavior of its own (docs/console/design-principles.md):

  * reads are Projection API calls (`projections.*`, docs/PROJECTION_API.md) —
    pure, read-only compositions of engine facts, served as JSON at `/api/p/…`;
  * writes are real engine CLI invocations (`tasks.main(argv)` in-process, same
    store lock, validation, and refusals), so the engine stays the sole writer;
  * write commands are whitelisted to the human's surface (`human-update`,
    `cancel`, `reopen`, `create`); anything else is refused here before the
    engine ever sees it;
  * free text typed in the browser is untrusted and reaches the engine only
    through file-input flags (--note-file/--reason-file/--title-file/
    --description-file), never inline argv — CONTRACTS: "Untrusted text is
    data, never code";
  * loopback-bound, single-user, no accounts, no database, no websockets.

Usage:  python3 console/server.py [--port 7373] [--dir /path/to/.tasks]
Then open http://127.0.0.1:7373
"""
import argparse
import contextlib
import importlib.util
import io
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"

_spec = importlib.util.spec_from_file_location(
    "tasks", ROOT / "taskforge" / "scripts" / "tasks.py")
tasks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tasks)

# The presentation layer (docs/PROJECTION_API.md): read-only, pure composition
# of engine facts. The Web UI renders these projections; the CLI renders the
# same ones. Served here as JSON — the HTTP layer is just a transport.
_pspec = importlib.util.spec_from_file_location(
    "projections", ROOT / "taskforge" / "scripts" / "projections.py")
projections = importlib.util.module_from_spec(_pspec)
_pspec.loader.exec_module(projections)

# The only write commands the Console may issue: the human actor's surface.
WRITE_COMMANDS = {"human-update", "cancel", "reopen", "create"}
# Free-text fields per command -> the file-input flag that carries them.
TEXT_FLAGS = {
    "human-update": [("note", "--note-file")],
    "cancel": [("reason", "--reason-file")],
    "reopen": [("reason", "--reason-file")],
    "create": [("title", "--title-file"), ("description", "--description-file")],
}
CONTENT_TYPES = {".html": "text/html; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8",
                 ".svg": "image/svg+xml"}


def run_cli(argv):
    """Invoke the engine CLI in-process. Returns (http_status, payload).

    Success: the command's JSON from stdout. Failure: the engine's
    {"error": ...} from stderr, verbatim — the Console shows refusals, it
    never papers over them."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            tasks.main(argv)
    except SystemExit:
        try:
            payload = json.loads(err.getvalue())
        except (ValueError, json.JSONDecodeError):
            payload = {"error": err.getvalue().strip() or "command failed"}
        return 422, payload
    raw = out.getvalue()
    return 200, (json.loads(raw) if raw.strip() else {})


def build_write_argv(body, workdir):
    """Translate a Console write request into engine argv.

    {"command": "...", "id": "...", "text": {...}, "result": {...},
     "args": {...}}. Text fields are written to files under workdir and
    passed by flag; a result object is written to result.json and passed
    positionally (validate/apply style) or via --result (human-update)."""
    cmd = body.get("command")
    if cmd not in WRITE_COMMANDS:
        raise ValueError(f"command not allowed: {cmd!r}")
    argv = [cmd]
    if cmd != "create":
        tid = body.get("id")
        if not isinstance(tid, str) or not tid.startswith("TASK-"):
            raise ValueError("a valid task id is required")
        argv.append(tid)
    texts = body.get("text") or {}
    for field, flag in TEXT_FLAGS[cmd]:
        if field in texts:
            p = Path(workdir) / f"{field}.txt"
            p.write_text(str(texts[field]), encoding="utf-8")
            argv += [flag, str(p)]
    if body.get("result") is not None:
        if cmd != "human-update":
            raise ValueError("result is only valid for human-update")
        p = Path(workdir) / "result.json"
        p.write_text(json.dumps(body["result"]), encoding="utf-8")
        argv += ["--result", str(p)]
    if cmd == "create" and body.get("explore"):
        argv.append("--explore")
    return argv


class Handler(BaseHTTPRequestHandler):
    server_version = "taskforge-console"

    def log_message(self, fmt, *args):  # quiet by default
        pass

    def send_json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_projection(self, name):
        """Render one projection to JSON. Read-only, no arguments beyond the
        task id / since query — pure presentation-layer composition."""
        from urllib.parse import parse_qs, urlparse
        try:
            if name == "board":
                return self.send_json(200, projections.board())
            if name == "health":
                return self.send_json(200, projections.health())
            if name == "digest":
                since = parse_qs(urlparse(self.path).query).get(
                    "since", ["1970-01-01T00:00:00+00:00"])[0]
                return self.send_json(200, projections.digest(since))
            for prefix, fn in (("task/", projections.task),
                               ("feature/", projections.feature),
                               ("review/", projections.review)):
                if name.startswith(prefix):
                    tid = name[len(prefix):]
                    if not tid.startswith("TASK-"):
                        return self.send_json(400, {"error": "bad task id"})
                    return self.send_json(200, fn(tid))
        except tasks.TaskforgeError as exc:
            return self.send_json(404, {"error": str(exc)})
        return self.send_json(404, {"error": "unknown projection"})

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        # Reads are Projection API calls (docs/PROJECTION_API.md); the raw
        # snapshot/show endpoints of the old snapshot Console were removed.
        if path.startswith("/api/p/"):
            return self.serve_projection(path[len("/api/p/"):])
        # Static: / -> index.html; anything else must resolve inside STATIC.
        name = "index.html" if path == "/" else path.lstrip("/")
        f = (STATIC / name).resolve()
        if STATIC.resolve() not in f.parents or not f.is_file():
            return self.send_json(404, {"error": "not found"})
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type",
                         CONTENT_TYPES.get(f.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/api/command":
            return self.send_json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            with tempfile.TemporaryDirectory(prefix="console-") as workdir:
                argv = build_write_argv(body, workdir)
                status, payload = run_cli(argv)
            return self.send_json(status, payload)
        except (ValueError, json.JSONDecodeError) as exc:
            return self.send_json(400, {"error": str(exc)})


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=7373)
    ap.add_argument("--dir", help="task store (default: .tasks, or TASKFORGE_DIR)")
    args = ap.parse_args()
    if args.dir:
        os.environ["TASKFORGE_DIR"] = args.dir
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"TaskForge Web UI: http://127.0.0.1:{args.port}  "
          f"(store: {os.environ.get('TASKFORGE_DIR', '.tasks')})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
