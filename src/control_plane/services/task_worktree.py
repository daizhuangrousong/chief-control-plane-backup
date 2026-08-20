"""Isolated task worktrees. Resident runtime code is never loaded from a task tree."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from ..adapters.git import GitError, git_checked
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
    return resolved


def resolve_existing_dir(path: Path, label: str) -> Path:
    path = _reject_symlink(Path(path), label)
    if not path.exists() or not path.is_dir():
        raise TaskWorktreeError("{} must be an existing directory".format(label))
    return path.resolve()


def paths_equal(left: Path, right: Path) -> bool:
    return Path(left).resolve() == Path(right).resolve()


def path_within(path: Path, root: Path) -> bool:
    path = Path(path).resolve()
    root = Path(root).resolve()
    if path == root:
        return True
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def git_common_dir(root: Path) -> Path:
    try:
        raw = git_checked(root, "rev-parse", "--git-common-dir")
    except GitError as error:
        raise TaskWorktreeError("git common dir is unknown") from error
    common = Path(raw)
    if not common.is_absolute():
        common = Path(root) / common
    return common.resolve()


def git_toplevel(root: Path) -> Path:
    try:
        raw = git_checked(root, "rev-parse", "--show-toplevel")
    except GitError as error:
        raise TaskWorktreeError("git toplevel is unknown") from error
    return Path(raw).resolve()


def assert_control_path(
    path: Path,
    label: str,
    runtime_root: Path,
    project_root: Path,
    pool_root: Path,
) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    path = resolve_existing_dir(path, label)
    runtime_root = Path(runtime_root).resolve()
    project_root = Path(project_root).resolve()
    pool_root = Path(pool_root).resolve()
    if path == runtime_root:
        raise TaskWorktreeError("{} must sit inside the runtime control directory".format(label))
    if not path_within(path, runtime_root):
        raise TaskWorktreeError("{} must sit inside the runtime control directory".format(label))
    if path_within(path, project_root):
        raise TaskWorktreeError("{} must not sit inside the project checkout".format(label))
    if path_within(path, pool_root):
        raise TaskWorktreeError("{} must not sit inside the task worktree pool".format(label))
    return path


class TaskWorktreePool:
    """Create one branch and one worktree per task from a registered baseline."""

    def __init__(self, runtime_root: Path, project_root: Path, pool_root: Path):
        runtime = resolve_existing_dir(runtime_root, "runtime root")
        project = resolve_existing_dir(project_root, "project root")
        pool = Path(pool_root)
        pool.mkdir(parents=True, exist_ok=True)
        pool = resolve_existing_dir(pool, "task worktree pool")
        if paths_equal(runtime, project):
            raise TaskWorktreeError("runtime root must not be the project root")
        if paths_equal(pool, runtime) or path_within(pool, runtime) or path_within(runtime, pool):
            raise TaskWorktreeError("runtime root and task worktree pool must not nest")
        if not path_within(pool, project) or paths_equal(pool, project):
            raise TaskWorktreeError("task worktree pool is outside the authorized project root")
        try:
            runtime_top = git_toplevel(runtime)
            project_top = git_toplevel(project)
        except TaskWorktreeError as error:
            raise TaskWorktreeError("runtime and project must be git worktrees of the same repository") from error
        if runtime_top != runtime:
            raise TaskWorktreeError("unexpected Git toplevel for runtime root")
        if project_top != project:
            raise TaskWorktreeError("unexpected Git toplevel for project root")
        if git_common_dir(runtime) != git_common_dir(project):
            raise TaskWorktreeError("runtime root is not a worktree of the project repository")
        if pool.is_symlink():
            raise TaskWorktreeError("task worktree pool must not be a symlink")
        self.runtime_root = runtime
        self.project_root = project
        self.pool_root = pool

    def occupancy_path(self, task_id: str) -> Path:
        return self.pool_root / "{}.occupancy.json".format(task_id)

    def worktree_path(self, task_id: str) -> Path:
        return self.pool_root / task_id

    def branch_name(self, task_id: str) -> str:
        return TASK_BRANCH_PREFIX + task_id

    def snapshot_hosts(self) -> Dict[str, str]:
        try:
            return {
                "runtimeHead": git_checked(self.runtime_root, "rev-parse", "HEAD"),
                "projectHead": git_checked(self.project_root, "rev-parse", "HEAD"),
                "runtimePorcelain": git_checked(self.runtime_root, "status", "--porcelain"),
                "projectPorcelain": git_checked(self.project_root, "status", "--porcelain"),
            }
        except GitError as error:
            raise TaskWorktreeError("could not snapshot runtime or project checkout") from error

    def assert_hosts_unchanged(self, snapshot: Dict[str, str], baseline_ref: str) -> None:
        current = self.snapshot_hosts()
        if current["runtimeHead"] != snapshot["runtimeHead"]:
            raise TaskWorktreeError("runtime HEAD was modified")
        if current["projectHead"] != snapshot["projectHead"]:
            raise TaskWorktreeError("target checkout was modified")
        if current["projectHead"] != baseline_ref:
            raise TaskWorktreeError("baseline checkout was modified")
        if current["runtimePorcelain"] != snapshot["runtimePorcelain"]:
            raise TaskWorktreeError("runtime worktree was modified")
        if current["projectPorcelain"] != snapshot["projectPorcelain"]:
            raise TaskWorktreeError("target checkout was modified")

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
            try:
                porcelain = git_checked(worktree, "status", "--porcelain")
                head = git_checked(worktree, "rev-parse", "HEAD")
            except GitError:
                porcelain, head = "unreadable", ""
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
        worktree = worktree.resolve()
        if worktree.is_symlink():
            self._remove_worktree(worktree)
            raise TaskWorktreeError("task worktree path must not be a symlink")
        if not path_within(worktree, self.pool_root) or paths_equal(worktree, self.pool_root):
            self._remove_worktree(worktree)
            raise TaskWorktreeError("task worktree escaped the pool")
        try:
            head = git_checked(worktree, "rev-parse", "HEAD")
            toplevel = git_toplevel(worktree)
        except (GitError, TaskWorktreeError) as error:
            self._remove_worktree(worktree)
            raise TaskWorktreeError("task worktree git HEAD is unknown") from error
        if not head:
            self._remove_worktree(worktree)
            raise TaskWorktreeError("task worktree git HEAD is unknown")
        if toplevel != worktree:
            self._remove_worktree(worktree)
            raise TaskWorktreeError("unexpected Git toplevel for task worktree")
        if git_common_dir(worktree) != git_common_dir(self.project_root):
            self._remove_worktree(worktree)
            raise TaskWorktreeError("task worktree is not in the project repository")
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
