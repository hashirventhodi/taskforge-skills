#!/usr/bin/env python3
"""tasks.py — entry point and stable facade of the taskforge engine.

This path is the engine's public interface: skills resolve and invoke it,
and it re-exports the module API so tools and tests have one stable import
surface. The implementation lives in the engine/ package alongside it:

    engine/model.py       pure domain: constants, task/artifact/edge helpers
    engine/store.py       filesystem: task files, lock, config, capabilities
    engine/readiness.py   derived readiness + cycle detection
    engine/validation.py  boundary validation: results, payloads, capabilities
    engine/apply.py       the application pipeline: cascades, relations, signals
    engine/audit.py       reviewer-isolation audit, doctor, migrate
    engine/cli.py         argument parsing and dispatch

Architectural contract (DESIGN.md): a single deterministic engine — one
entry point, one writer of task state. That is a process property, not a
file-count property; this facade is what keeps the invocation path and the
API stable while the implementation is organized for a years-long life.

Stdlib only. All CLI output is JSON.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Stable API surface (used by tests and any tooling built on the engine).
from engine.model import (                                    # noqa: E402,F401
    CLOSED, FORBIDDEN_EDGES, KINDS, RELATIONS, RESULT_KEYS, SCHEMA_VERSION,
    SEMANTIC_EDGES, SIGNALS, STATUS_FOR, TERMINAL, TaskforgeError, active,
    block_on_human, blocker_ids, has_edge, new_task, now, parent_id,
    record, review_rejections_in_current_cycle, supersede)
from engine.store import (                                    # noqa: E402,F401
    all_tasks, audit_dir, capabilities, config, ensure_config_file, find,
    load, path_of, save, store_dir, store_lock)
from engine.readiness import evaluate, find_cycle, refresh_status  # noqa: E402,F401
from engine.validation import (                               # noqa: E402,F401
    validate_edge_type, validate_payload, validate_result)
from engine.apply import (                                    # noqa: E402,F401
    add_artifact, add_edge, apply_result, apply_signal, cascade,
    flag_stale_decision_refs, materialize, wake_blocked_by)
from engine.audit import (                                    # noqa: E402,F401
    audit_review, doctor, migrate, record_review_prompt)
from engine.cli import build_parser, main, run_command, summary  # noqa: E402,F401

if __name__ == "__main__":
    main()
