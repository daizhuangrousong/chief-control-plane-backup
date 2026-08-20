"""Isolated task worktrees. Resident runtime code is never loaded from a task tree."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from ..adapters.git import GitError, git_at_root, git_checked
from .task_registry import TASK_ID_PATTERN, TaskValidationError


OCCUPANCY_VERSION = "task-worktree-occupancy/1.0.0"
TASK_BRANCH_PREFIX = "task/"


class TaskWorktreeError(TaskValidationError):
    pass


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".occupancy-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _reject_symlink(path: Path, label: str) -> Path:
    resolved = Path(path)
    if resolved.exists() and resolved.is_symlink():
        raise TaskWorktreeError("{} must not be a symlink".format(label))
    return resolved.resolve() if resolved.exists() else resolved.absolute()


class TaskWorktreePool:
    """Create one branch and one worktree per task from a registered baseline."""

    def __init__(self, runtime_root: Path, project_root: Path, pool_root: Path):
        runtime = Path(runtime_root)
        project = Path(project_root)
        pool = Path(pool_root)
        pool.mkdir(parents=True, exist_ok=True)
        self.runtime_root = _reject_symlink(runtime, "runtime root")
        self.project_root = _reject_symlink(project, "project root")
        self.pool_root = _reject_symlink(pool, "task worktree pool")
        if self.pool_root == self.runtime_root:
            raise TaskWorktreeError("task worktree pool must not be the runtime root")
        try:
            self.pool_root.relative_to(self.project_root)
        except ValueError as error:
            raise TaskWorktreeError("task worktree pool is outside the authorized project root") from error
        toplevel = git_at_root(self.project_root, "rev-parse", "--show-toplevel")
        if not toplevel:
            raise TaskWorktreeError("project root git HEAD is unknown")
        if self.pool_root.is_symlink():
            raise TaskWorktreeError("task worktree pool must not be a symlink")

    def occupancy_path(self, task_id: str) -> Path:
        return self.pool_root / "{}.occupancy.json".format(task_id)

    def worktree_path(self, task_id: str) -> Path:
        return self.pool_root / task_id

    def branch_name(self, task_id: str) -> str:
        return TASK_BRANCH_PREFIX + task_id

    def read_occupancy(self, task_id: str) -> Optional[Dict[str, Any]]:
        path = self.occupancy_path(task_id)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise TaskWorktreeError("occupancy must be a regular file")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise TaskWorktreeError("occupancy is unreadable") from error
        if not isinstance(payload, dict):
            raise TaskWorktreeError("occupancy is invalid")
        return payload

    def allocate(self, task_id: str, baseline_ref: str) -> Dict[str, Any]:
        if not TASK_ID_PATTERN.fullmatch(task_id or ""):
            raise TaskWorktreeError("task id is invalid")
        if not str(baseline_ref or "").strip():
            raise TaskWorktreeError("baseline ref is required")
        existing = self.read_occupancy(task_id)
        if existing is not None:
            raise TaskWorktreeError("task worktree already allocated; refusing to re-execute")
        worktree = self.worktree_path(task_id)
        if worktree.exists() or worktree.is_symlink():
            if worktree.is_symlink():
                raise TaskWorktreeError("task worktree path must not be a symlink")
            porcelain = git_at_root(worktree, "status", "--porcelain")
            head = git_at_root(worktree, "rev-parse", "HEAD")
            if porcelain or not head:
                raise TaskWorktreeError("refusing to reuse a dirty worktree")
            raise TaskWorktreeError("task worktree path is already occupied")
        try:
            git_checked(
                self.project_root, "worktree", "add", "-b", self.branch_name(task_id),
                str(worktree), baseline_ref,
            )
        except GitError as error:
            raise TaskWorktreeError("could not create task worktree: {}".format(error)) from error
        if worktree.is_symlink():
            self._remove_worktree(worktree)
            raise TaskWorktreeError("task worktree path must not be a symlink")
        head = git_at_root(worktree, "rev-parse", "HEAD")
        if not head:
            self._remove_worktree(worktree)
            raise TaskWorktreeError("task worktree git HEAD is unknown")
        if head != baseline_ref:
            self._remove_worktree(worktree)
            raise TaskWorktreeError(
                "task worktree HEAD {} != registered baseline {}".format(head, baseline_ref)
            )
        occupancy = {
            "schemaVersion": OCCUPANCY_VERSION,
            "taskId": task_id,
            "path": str(worktree),
            "branch": self.branch_name(task_id),
            "baselineRef": baseline_ref,
            "head": head,
            "phase": "allocated",
        }
        _atomic_write_json(self.occupancy_path(task_id), occupancy)
        return occupancy

    def mark_phase(self, task_id: str, phase: str) -> Dict[str, Any]:
        occupancy = self.read_occupancy(task_id)
        if occupancy is None:
            raise TaskWorktreeError("task worktree is not allocated")
        occupancy = dict(occupancy)
        occupancy["phase"] = phase
        _atomic_write_json(self.occupancy_path(task_id), occupancy)
        return occupancy

    def release(self, task_id: str) -> None:
        occupancy = self.read_occupancy(task_id)
        worktree = self.worktree_path(task_id)
        if occupancy or worktree.exists():
            self._remove_worktree(worktree)
        path = self.occupancy_path(task_id)
        if path.exists() and path.is_file() and not path.is_symlink():
            os.unlink(path)

    def _remove_worktree(self, worktree: Path) -> None:
        try:
            git_checked(self.project_root, "worktree", "remove", "--force", str(worktree))
        except GitError:
            if worktree.exists():
                raise
