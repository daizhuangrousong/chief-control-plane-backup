"""Strict production lifecycle loader. Resident entry has no unsandboxed path."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .cursor_runner import CursorAdapterError
from .executor_sandbox import ExecutorSandboxError, require_sandbox_exec
from .task_worktree import (
    TaskWorktreeError, TaskWorktreePool, assert_control_path, path_within, paths_equal,
)


LIFECYCLE_REQUIRED = (
    "runtimeRoot", "projectRoot", "poolRoot", "stateRoot", "executionReportDir",
)
LIFECYCLE_ALLOWED = {
    "runtimeRoot", "projectRoot", "poolRoot", "stateRoot", "database",
    "chiefReviewInbox", "executionReportDir", "receiptDir", "occupancyDir",
    "executorResultSchemaVersion", "verificationCommands", "targetBranch",
    "mergerId", "allowedReviewActors", "threatModel", "nextAllowedAttach",
    "invariants", "cleanupRollback",
}
OPTIONAL_STATE_DIRS = ("database", "chiefReviewInbox", "receiptDir", "occupancyDir")


class ProductionRuntimeError(CursorAdapterError):
    pass


def _absolute_path(raw: Any, label: str) -> Path:
    text = str(raw or "").strip()
    if not text:
        raise ProductionRuntimeError("{} is required".format(label))
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ProductionRuntimeError("{} must be an absolute path".format(label))
    if path.exists() and path.is_symlink():
        raise ProductionRuntimeError("{} must not be a symlink".format(label))
    return path


def _reject_overlap(left: Path, right: Path, left_label: str, right_label: str) -> None:
    if paths_equal(left, right) or path_within(left, right) or path_within(right, left):
        raise ProductionRuntimeError("{} and {} must not overlap".format(left_label, right_label))


def load_production_runtime(
    path: str,
    registered_project_root: Path,
    source_env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    del source_env
    config_path = _absolute_path(path, "lifecycle config")
    if not config_path.is_file() or config_path.is_symlink():
        raise ProductionRuntimeError("lifecycle config is missing")
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ProductionRuntimeError("lifecycle config is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ProductionRuntimeError("lifecycle config must be a JSON object")
    unknown = sorted(set(payload) - LIFECYCLE_ALLOWED)
    if unknown:
        raise ProductionRuntimeError("lifecycle config has unknown fields: {}".format(", ".join(unknown)))
    missing = [key for key in LIFECYCLE_REQUIRED if key not in payload]
    if missing:
        raise ProductionRuntimeError("lifecycle config missing fields: {}".format(", ".join(missing)))
    try:
        require_sandbox_exec()
    except ExecutorSandboxError as error:
        raise ProductionRuntimeError(str(error)) from error
    runtime_root = _absolute_path(payload["runtimeRoot"], "runtimeRoot")
    project_root = _absolute_path(payload["projectRoot"], "projectRoot")
    pool_root = _absolute_path(payload["poolRoot"], "poolRoot")
    state_root = _absolute_path(payload["stateRoot"], "stateRoot")
    report_dir = _absolute_path(payload["executionReportDir"], "executionReportDir")
    registered = Path(registered_project_root).expanduser().resolve()
    if not project_root.exists():
        raise ProductionRuntimeError("projectRoot must be an existing directory")
    if project_root.resolve() != registered:
        raise ProductionRuntimeError("projectRoot must match the registered project root")
    _reject_overlap(runtime_root, project_root, "runtimeRoot", "projectRoot")
    _reject_overlap(runtime_root, state_root, "runtimeRoot", "stateRoot")
    _reject_overlap(project_root, state_root, "projectRoot", "stateRoot")
    _reject_overlap(runtime_root, pool_root, "runtimeRoot", "poolRoot")
    _reject_overlap(state_root, pool_root, "stateRoot", "poolRoot")
    if paths_equal(pool_root, project_root) or path_within(project_root, pool_root):
        raise ProductionRuntimeError("poolRoot must sit inside projectRoot and must not equal it")
    if not path_within(pool_root, project_root):
        raise ProductionRuntimeError("poolRoot must sit inside projectRoot")
    if path_within(report_dir, runtime_root) or path_within(report_dir, project_root) or path_within(report_dir, pool_root):
        raise ProductionRuntimeError("executionReportDir escaped the state root")
    if not path_within(report_dir, state_root) and not paths_equal(report_dir, state_root):
        # report must be inside state; equal-to-state is also refused by assert_control_path mkdir later
        raise ProductionRuntimeError("executionReportDir must sit inside the state root")
    for key in OPTIONAL_STATE_DIRS:
        if key not in payload:
            continue
        extra = _absolute_path(payload[key], key)
        if key == "database":
            if not path_within(extra, state_root) and extra.parent.resolve() != state_root.resolve():
                raise ProductionRuntimeError("database must sit inside the state root")
            continue
        if not path_within(extra, state_root) and not paths_equal(extra, state_root):
            raise ProductionRuntimeError("{} must sit inside the state root".format(key))
    try:
        pool = TaskWorktreePool(runtime_root, project_root, pool_root, state_root)
        execution_report_dir = assert_control_path(
            report_dir, "execution report directory",
            pool.runtime_root, pool.project_root, pool.pool_root, pool.state_root,
        )
    except TaskWorktreeError as error:
        raise ProductionRuntimeError(str(error)) from error
    return {
        "pool": pool,
        "execution_report_dir": execution_report_dir,
        "payload": payload,
    }
