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
LOCK_ACQUIRE_TIMEOUT = 10


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
    actors; 'human' is the universal actor. Ships with taskforge."""
    p = Path(__file__).resolve().parents[2] / "capabilities.json"
    if not p.exists():
        raise TaskforgeError(f"capabilities.json not found at {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def path_of(task_id: str) -> Path:
    if ("/" in task_id or "\\" in task_id or task_id.startswith(".")
            or not task_id.startswith("TASK-")):
        raise TaskforgeError(f"invalid task id: {task_id!r}")
    return store_dir() / f"{task_id}.json"


def is_future(task: dict) -> bool:
    """True iff this task was written by a newer engine than this one.

    Schema compatibility is DIRECTIONAL (DESIGN §10.12): an engine may read
    and migrate OLDER data, but must never interpret, mutate, or route on
    NEWER data. This is the single predicate that whole-store paths consult
    to honor that rule."""
    return task.get("schema_version", 1) > SCHEMA_VERSION


def load(task_id: str) -> dict:
    p = path_of(task_id)
    if not p.exists():
        raise TaskforgeError(f"unknown task: {task_id}")
    task = json.loads(p.read_text(encoding="utf-8"))
    if is_future(task):
        raise TaskforgeError(
            f"{task_id} has schema_version {task['schema_version']} newer "
            f"than this script ({SCHEMA_VERSION}); upgrade taskforge")
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
    """Every task this engine is capable of safely reasoning about.

    Future-schema tasks (written by a newer engine) are skipped, not yielded:
    operational scans — listing, routing, cross-task cascades, migration —
    must never route on or mutate data this engine may not fully understand
    (DESIGN §10.12, directional compatibility). Their existence is surfaced
    only by `doctor`, which reads the raw store directly. This is a
    store-level guarantee, so no caller has to remember the rule."""
    for p in sorted(store_dir().glob("TASK-*.json")):
        task = json.loads(p.read_text(encoding="utf-8"))
        if not is_future(task):
            yield task


class store_lock:
    """Portable single-writer lock over the task store.

    Normal acquisition is a single ``O_EXCL`` create — unchanged and fast.
    The one operation that was previously non-atomic — breaking a *stale*
    lock left by a crashed session — is serialized through a second
    ``O_EXCL`` gate (``.lock.break``), so only one session may attempt
    recovery at a time; the breaker re-verifies staleness *under* that gate
    before removing anything, so a fresh lock is never destroyed.

    Design rule — **the break gate is not a second lock.** It exists solely
    to serialize stale-lock recovery and never participates in normal
    acquisition. It is deliberately *not* itself stale-broken: recursively
    stale-breaking the stale-breaker would reintroduce the very race this
    removes. If a session crashes in the microsecond it holds the gate (far
    rarer than crashing while holding the main lock through a whole cascade),
    auto-recovery stops and acquisition raises the "delete the lock if stale"
    error — manual recovery, never a silent loss of mutual exclusion.

    Correctness rests on one invariant: while a stale ``.lock`` exists,
    ``O_EXCL`` blocks any fresh holder from being created — so a lock still
    stale when the sole breaker re-checks it has nothing live beneath it.
    """

    def __init__(self):
        d = store_dir()
        self.path = d / ".lock"
        self.gate = d / ".lock.break"

    def __enter__(self):
        deadline = time.time() + LOCK_ACQUIRE_TIMEOUT
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {time.time()}".encode())
                os.close(fd)
                return self
            except FileExistsError:
                if self._is_stale():
                    self._break_if_stale()
                if time.time() > deadline:
                    raise TaskforgeError(
                        "task store is locked by another session "
                        f"({self.path}); retry, or if a crash left it stale "
                        f"delete {self.path} (and {self.gate} if present)")
                time.sleep(0.2)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)

    def _is_stale(self):
        """True iff the current lock's timestamp is older than the stale
        threshold. A missing or malformed lock is treated as NOT stale — do
        not break what cannot be confirmed dead."""
        try:
            stamp = float(self.path.read_text().split()[1])
        except (OSError, IndexError, ValueError):
            return False
        return time.time() - stamp > LOCK_STALE_SECONDS

    def _break_if_stale(self):
        """Remove the lock ONLY while holding exclusive break rights AND with
        staleness re-confirmed under that exclusion — serialization plus
        re-verify is what makes removal safe. Idempotent: a second breaker
        acquires the gate, re-reads, finds nothing stale, and does nothing."""
        try:
            gfd = os.open(self.gate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return  # another session is already recovering; leave it to them
        try:
            if self._is_stale():
                self.path.unlink(missing_ok=True)
        finally:
            os.close(gfd)
            self.gate.unlink(missing_ok=True)
