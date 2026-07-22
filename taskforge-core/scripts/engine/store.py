"""Storage layer: every filesystem concern of the engine.

Task files, atomic writes, the store lock, configuration, and the
capability matrix. Nothing above this module touches the filesystem for
task state, and this module contains no workflow semantics.
"""
import json
import os
import tempfile
import time
from pathlib import Path

from engine.model import SCHEMA_VERSION, TaskforgeError

LOCK_STALE_SECONDS = 60


def store_dir() -> Path:
    d = Path(os.environ.get("TASKFORGE_DIR", ".tasks"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def audit_dir() -> Path:
    d = store_dir() / "audit"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config() -> dict:
    """Effective configuration: defaults <- config.json <- environment."""
    cfg = {"max_review_retries": 2, "max_artifact_versions": 4,
           "schema_version": SCHEMA_VERSION}
    p = store_dir() / "config.json"
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            raise TaskforgeError(f"config.json is not valid JSON: {p}")
    for key, env in (("max_review_retries", "TASKFORGE_MAX_REVIEW_RETRIES"),
                     ("max_artifact_versions", "TASKFORGE_MAX_VERSIONS")):
        if os.environ.get(env):
            cfg[key] = int(os.environ[env])
    return cfg


def ensure_config_file() -> None:
    # Self-ignoring store (DESIGN.md §1, §10.10): task state is workflow
    # state, orthogonal to code branches. Teams wanting the store tracked
    # in git delete this file and commit .tasks/ from the trunk line only.
    gi = store_dir() / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n", encoding="utf-8")
    p = store_dir() / "config.json"
    if not p.exists():
        p.write_text(json.dumps(
            {"max_review_retries": 2, "max_artifact_versions": 4,
             "schema_version": SCHEMA_VERSION}, indent=2) + "\n",
            encoding="utf-8")


def capabilities() -> dict:
    """actor -> {artifacts, relations, signals}. Deny-by-default for unknown
    actors; 'human' is the universal actor. Ships with taskforge-core."""
    p = Path(__file__).resolve().parents[2] / "capabilities.json"
    if not p.exists():
        raise TaskforgeError(f"capabilities.json not found at {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def path_of(task_id: str) -> Path:
    if ("/" in task_id or "\\" in task_id or task_id.startswith(".")
            or not task_id.startswith("TASK-")):
        raise TaskforgeError(f"invalid task id: {task_id!r}")
    return store_dir() / f"{task_id}.json"


def load(task_id: str) -> dict:
    p = path_of(task_id)
    if not p.exists():
        raise TaskforgeError(f"unknown task: {task_id}")
    task = json.loads(p.read_text(encoding="utf-8"))
    if task.get("schema_version", 1) > SCHEMA_VERSION:
        raise TaskforgeError(
            f"{task_id} has schema_version {task['schema_version']} newer "
            f"than this script ({SCHEMA_VERSION}); upgrade taskforge-core")
    return task


def find(task_id: str):
    try:
        return load(task_id)
    except TaskforgeError:
        return None


def save(task: dict) -> None:
    from engine.model import now
    task["updated_at"] = now()
    p = path_of(task["id"])
    fd, tmp = tempfile.mkstemp(dir=store_dir(), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(task, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def all_tasks():
    for p in sorted(store_dir().glob("TASK-*.json")):
        yield json.loads(p.read_text(encoding="utf-8"))


class store_lock:
    """O_EXCL lock file; portable, stale-broken after LOCK_STALE_SECONDS."""

    def __enter__(self):
        self.path = store_dir() / ".lock"
        deadline = time.time() + 10
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {time.time()}".encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    stamp = float(self.path.read_text().split()[1])
                    if time.time() - stamp > LOCK_STALE_SECONDS:
                        self.path.unlink(missing_ok=True)
                        continue
                except (OSError, IndexError, ValueError):
                    pass
                if time.time() > deadline:
                    raise TaskforgeError(
                        "task store is locked by another session "
                        f"({self.path}); retry, or delete the lock if stale")
                time.sleep(0.2)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)
