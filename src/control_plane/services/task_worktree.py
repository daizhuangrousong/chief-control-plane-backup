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
RUNTIME_SOURCE_MARKER = Path("src") / "control_plane" / "__init__.py"


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


def git_is_clean(root: Path, label: str) -> str:
    try:
        head = git_checked(root, "rev-parse", "HEAD")
        porcelain = git_checked(root, "status", "--porcelain")
    except GitError as error:
        raise TaskWorktreeError("{} git status is unreadable".format(label)) from error
    if not head:
        raise TaskWorktreeError("{} git HEAD is unknown".format(label))
    if porcelain:
        raise TaskWorktreeError("{} must be a clean git checkout".format(label))
    return head


def enclosing_git_root(path: Path) -> Optional[Path]:
    current = Path(path).resolve()
    for candidate in [current, *current.parents]:
        git_dir = candidate / ".git"
        if git_dir.exists():
            return candidate
    return None


def assert_runtime_sources(runtime_root: Path) -> None:
    marker = Path(runtime_root).resolve() / RUNTIME_SOURCE_MARKER
    if marker.is_symlink() or not marker.is_file():
        raise TaskWorktreeError("runtime root does not contain Control Plane sources")


def assert_module_not_from_target(project_root: Path, pool_root: Path) -> None:
    import control_plane

    loaded = Path(control_plane.__file__).resolve()
    if path_within(loaded, project_root) or path_within(loaded, pool_root):
        raise TaskWorktreeError("control plane module must not load from the target repository")


def assert_state_path(
    path: Path,
    label: str,
    state_root: Path,
    runtime_root: Path,
    project_root: Path,
    pool_root: Path,
) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    path = resolve_existing_dir(path, label)
    state_root = Path(state_root).resolve()
    runtime_root = Path(runtime_root).resolve()
    project_root = Path(project_root).resolve()
    pool_root = Path(pool_root).resolve()
    if not path_within(path, state_root):
        raise TaskWorktreeError("{} must sit inside the state root".format(label))
    if path_within(path, runtime_root):
        raise TaskWorktreeError("{} must not sit inside the runtime checkout".format(label))
    if path_within(path, project_root):
        raise TaskWorktreeError("{} must not sit inside the project checkout".format(label))
    if path_within(path, pool_root):
        raise TaskWorktreeError("{} must not sit inside the task worktree pool".format(label))
    return path


def assert_control_path(
    path: Path,
    label: str,
    runtime_root: Path,
    project_root: Path,
    pool_root: Path,
    state_root: Path,
) -> Path:
    return assert_state_path(path, label, state_root, runtime_root, project_root, pool_root)


class TaskWorktreePool:
    """Create one branch and one worktree per task from a registered target baseline."""

    def __init__(self, runtime_root: Path, project_root: Path, pool_root: Path, state_root: Path):
        runtime = resolve_existing_dir(runtime_root, "runtime root")
        project = resolve_existing_dir(project_root, "project root")
        pool = Path(pool_root)
        pool.mkdir(parents=True, exist_ok=True)
        pool = resolve_existing_dir(pool, "task worktree pool")
        state = Path(state_root)
        if state.exists() and state.is_symlink():
            raise TaskWorktreeError("state root must not be a symlink")
        state.mkdir(parents=True, exist_ok=True)
        state = resolve_existing_dir(state, "state root")
        if paths_equal(runtime, project):
            raise TaskWorktreeError("runtime root must not be the project root")
        if path_within(runtime, project) or path_within(project, runtime):
            raise TaskWorktreeError("runtime root and project root must not nest")
        if paths_equal(pool, runtime) or path_within(pool, runtime) or path_within(runtime, pool):
            raise TaskWorktreeError("runtime root and task worktree pool must not nest")
        if not path_within(pool, project) or paths_equal(pool, project):
            raise TaskWorktreeError("task worktree pool is outside the authorized project root")
        if (
            path_within(state, runtime)
            or path_within(state, project)
            or path_within(state, pool)
            or paths_equal(state, runtime)
            or paths_equal(state, project)
            or paths_equal(state, pool)
        ):
            raise TaskWorktreeError("state root must sit outside runtime, project, and pool")
        git_enclosing = enclosing_git_root(state)
        if git_enclosing is not None:
            raise TaskWorktreeError("state root must not sit inside a git repository")
        try:
            runtime_top = git_toplevel(runtime)
            project_top = git_toplevel(project)
        except TaskWorktreeError as error:
            raise TaskWorktreeError("runtime and project must be independent git repositories") from error
        if runtime_top != runtime:
            raise TaskWorktreeError("unexpected Git toplevel for runtime root")
        if project_top != project:
            raise TaskWorktreeError("unexpected Git toplevel for project root")
        if git_common_dir(runtime) == git_common_dir(project):
            raise TaskWorktreeError("runtime and project must not share a git common dir")
        if pool.is_symlink():
            raise TaskWorktreeError("task worktree pool must not be a symlink")
        assert_runtime_sources(runtime)
        assert_module_not_from_target(project, pool)
        runtime_head = git_is_clean(runtime, "runtime root")
        project_head = git_is_clean(project, "project root")
        (state / "occupancy").mkdir(parents=True, exist_ok=True)
        self.runtime_root = runtime
        self.project_root = project
        self.pool_root = pool
        self.state_root = state
        self.runtime_head = runtime_head
        self.project_head = project_head

    def occupancy_path(self, task_id: str) -> Path:
        return self.state_root / "occupancy" / "{}.occupancy.json".format(task_id)

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
        if current["runtimeHead"] != self.runtime_head:
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
        from .task_clone import create_independent_clone
        try:
            cloned = create_independent_clone(
                self.project_root, worktree, baseline_ref, self.runtime_root, self.pool_root,
            )
        except TaskWorktreeError:
            raise
        worktree = Path(cloned["path"]).resolve()
        head = cloned["head"]
        occupancy = {
            "schemaVersion": OCCUPANCY_VERSION,
            "taskId": task_id,
            "path": str(worktree),
            "branch": self.branch_name(task_id),
            "baselineRef": baseline_ref,
            "head": head,
            "phase": "allocated",
            "gitCommonDir": cloned["gitCommonDir"],
            "isolation": cloned["isolation"],
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
        from .task_clone import remove_clone
        try:
            remove_clone(worktree, self.pool_root)
        except TaskWorktreeError:
            if Path(worktree).exists():
                raise
