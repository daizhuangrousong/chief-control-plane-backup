"""Independent no-hardlinks task clones. Executors never share the project git store."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

from ..adapters.git import GitError, git_checked
from .task_worktree import (
    TaskWorktreeError,
    git_common_dir,
    git_is_clean,
    git_toplevel,
    path_within,
    paths_equal,
)


class TaskCloneError(TaskWorktreeError):
    pass


Inode = Tuple[int, int]


def _rmtree_within(path: Path, root: Path, label: str) -> None:
    path = Path(path)
    root = Path(root).resolve()
    if path.is_symlink():
        resolved_parent = path.parent.resolve()
        if not path_within(resolved_parent, root) and resolved_parent != root:
            raise TaskCloneError("refusing to delete {} outside the pool".format(label))
        path.unlink()
        return
    if not path.exists():
        return
    resolved = path.resolve()
    if not path_within(resolved, root) or paths_equal(resolved, root):
        raise TaskCloneError("refusing to delete {} outside the pool".format(label))
    shutil.rmtree(resolved)


def _git_dir(root: Path) -> Path:
    git_dir = Path(root) / ".git"
    if git_dir.is_symlink() or not git_dir.is_dir():
        raise TaskCloneError("task clone .git must be a directory inside the clone")
    return git_dir.resolve()


def _object_inodes(git_dir: Path) -> Set[Inode]:
    objects = Path(git_dir) / "objects"
    found: Set[Inode] = set()
    if not objects.is_dir() or objects.is_symlink():
        return found
    for dirpath, dirnames, filenames in os.walk(objects):
        dirnames[:] = [name for name in dirnames if name not in {".", ".."}]
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink():
                raise TaskCloneError("git object must not be a symlink")
            if not path.is_file():
                continue
            stat = path.stat()
            found.add((stat.st_dev, stat.st_ino))
    return found


def _copy_identity(source: Path, clone: Path) -> None:
    for key, fallback in (("user.name", "task-clone"), ("user.email", "task-clone@invalid")):
        try:
            value = git_checked(source, "config", "--local", "--get", key)
        except GitError:
            value = fallback
        if not value.strip():
            value = fallback
        git_checked(clone, "config", "--local", key, value)
    git_checked(clone, "config", "--local", "commit.gpgsign", "false")
    git_checked(clone, "config", "--local", "advice.detachedHead", "false")


def _exclude_sandbox_dirs(clone: Path) -> None:
    info = _git_dir(clone) / "info"
    info.mkdir(parents=True, exist_ok=True)
    exclude = info / "exclude"
    extra = [
        ".sandbox-home/",
        ".sandbox-tmp/",
        ".sandbox-xdg/",
    ]
    existing = ""
    if exclude.is_file() and not exclude.is_symlink():
        existing = exclude.read_text(encoding="utf-8")
    lines = existing.splitlines()
    for rule in extra:
        if rule not in lines:
            lines.append(rule)
    text = "\n".join(lines).rstrip() + "\n"
    exclude.write_text(text, encoding="utf-8")


def _remove_remotes(clone: Path) -> None:
    try:
        remotes = git_checked(clone, "remote")
    except GitError as error:
        raise TaskCloneError("could not list clone remotes") from error
    for name in remotes.splitlines():
        remote = name.strip()
        if remote:
            git_checked(clone, "remote", "remove", remote)
    leftover = git_checked(clone, "remote")
    if leftover.strip():
        raise TaskCloneError("task clone still has remotes")


def assert_independent_clone(
    clone: Path,
    runtime_root: Path,
    project_root: Path,
    pool_root: Optional[Path] = None,
) -> Path:
    clone = Path(clone)
    if clone.is_symlink():
        raise TaskCloneError("task clone path must not be a symlink")
    if not clone.exists() or not clone.is_dir():
        raise TaskCloneError("task clone does not exist")
    clone = clone.resolve()
    runtime_root = Path(runtime_root).resolve()
    project_root = Path(project_root).resolve()
    git_dir = _git_dir(clone)
    if not path_within(git_dir, clone) or paths_equal(git_dir, clone):
        raise TaskCloneError("task clone git dir escaped the clone")
    try:
        common = git_common_dir(clone)
        toplevel = git_toplevel(clone)
    except TaskWorktreeError as error:
        raise TaskCloneError("task clone git metadata is unreadable") from error
    if toplevel != clone:
        raise TaskCloneError("unexpected Git toplevel for task clone")
    if not path_within(common, clone):
        raise TaskCloneError("task clone git common dir escaped the clone")
    if common != git_dir:
        raise TaskCloneError("task clone must not use a separate git common dir")
    if common == git_common_dir(runtime_root):
        raise TaskCloneError("task clone must not share the runtime repository")
    if common == git_common_dir(project_root):
        raise TaskCloneError("task clone must not share the project repository")
    alternates = git_dir / "objects" / "info" / "alternates"
    if alternates.exists():
        raise TaskCloneError("task clone must not use a shared object store")
    clone_inodes = _object_inodes(git_dir)
    project_inodes = _object_inodes(_git_dir(project_root) if (project_root / ".git").is_dir() else git_common_dir(project_root))
    if not clone_inodes:
        raise TaskCloneError("task clone has no git objects")
    if clone_inodes & project_inodes:
        raise TaskCloneError("task clone shares git objects with the project")
    runtime_git = Path(runtime_root) / ".git"
    runtime_store = runtime_git.resolve() if runtime_git.is_dir() and not runtime_git.is_symlink() else git_common_dir(runtime_root)
    runtime_inodes = _object_inodes(runtime_store)
    if clone_inodes & runtime_inodes:
        raise TaskCloneError("task clone shares git objects with the runtime")
    leftover = git_checked(clone, "remote")
    if leftover.strip():
        raise TaskCloneError("task clone must not have remotes")
    if pool_root is not None:
        pool_root = Path(pool_root).resolve()
        if not path_within(clone, pool_root) or paths_equal(clone, pool_root):
            raise TaskCloneError("task clone escaped the pool")
    return common


def create_independent_clone(
    source: Path,
    destination: Path,
    baseline_ref: str,
    runtime_root: Path,
    pool_root: Path,
) -> Dict[str, str]:
    source = Path(source).resolve()
    destination = Path(destination)
    pool_root = Path(pool_root).resolve()
    runtime_root = Path(runtime_root).resolve()
    if destination.exists() or destination.is_symlink():
        raise TaskCloneError("refusing to reuse an existing clone path")
    parent = destination.parent
    if parent.resolve() != pool_root:
        raise TaskCloneError("task clone must sit directly in the pool")
    if destination.is_symlink():
        raise TaskCloneError("task clone path must not be a symlink")
    git_is_clean(source, "project root")
    completed = subprocess.run(
        ["git", "clone", "--no-hardlinks", "--", str(source), str(destination)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        _rmtree_within(destination, pool_root, "partial clone")
        message = (completed.stderr or completed.stdout or "git clone failed").strip()
        raise TaskCloneError("could not create independent task clone: {}".format(message))
    try:
        if destination.is_symlink():
            raise TaskCloneError("task clone path must not be a symlink")
        destination = destination.resolve()
        if not path_within(destination, pool_root) or paths_equal(destination, pool_root):
            raise TaskCloneError("task clone escaped the pool")
        _remove_remotes(destination)
        git_checked(destination, "checkout", "--detach", baseline_ref)
        _copy_identity(source, destination)
        _exclude_sandbox_dirs(destination)
        head = git_checked(destination, "rev-parse", "HEAD")
        if head != baseline_ref:
            raise TaskCloneError(
                "task clone HEAD {} != registered baseline {}".format(head, baseline_ref)
            )
        common = assert_independent_clone(destination, runtime_root, source, pool_root)
    except (GitError, TaskWorktreeError, OSError) as error:
        _rmtree_within(destination, pool_root, "failed clone")
        if isinstance(error, TaskCloneError):
            raise
        raise TaskCloneError("could not initialize independent task clone: {}".format(error)) from error
    return {
        "path": str(destination),
        "head": head,
        "gitCommonDir": str(common),
        "isolation": "independent-clone",
    }


def import_exact_commit(project_root: Path, clone: Path, branch: str, commit: str) -> str:
    project_root = Path(project_root).resolve()
    clone = Path(clone).resolve()
    if not str(branch or "").startswith("task/"):
        raise TaskCloneError("imported ref must be a task branch")
    if not str(commit or "").strip():
        raise TaskCloneError("import commit is required")
    try:
        clone_head = git_checked(clone, "rev-parse", "HEAD")
    except GitError as error:
        raise TaskCloneError("could not read clone HEAD") from error
    if clone_head.lower() != commit.lower():
        raise TaskCloneError("import commit is not the clone HEAD")
    dest_ref = "refs/heads/{}".format(branch)
    try:
        git_checked(
            project_root,
            "fetch",
            "--no-tags",
            "--no-recurse-submodules",
            "--",
            str(clone),
            "{}:{}".format(commit, dest_ref),
            timeout=60,
        )
        imported = git_checked(project_root, "rev-parse", dest_ref)
        current = git_checked(project_root, "rev-parse", "--abbrev-ref", "HEAD")
        head = git_checked(project_root, "rev-parse", "HEAD")
    except GitError as error:
        raise TaskCloneError("could not import task commit: {}".format(error)) from error
    if imported.lower() != commit.lower():
        raise TaskCloneError("imported ref does not match the exact commit")
    if current == branch:
        raise TaskCloneError("refusing to import onto the checked-out branch")
    return imported


def object_inodes(root: Path) -> Set[Inode]:
    git_dir = Path(root) / ".git"
    if git_dir.is_dir() and not git_dir.is_symlink():
        return _object_inodes(git_dir.resolve())
    return _object_inodes(git_common_dir(root))


def remove_clone(path: Path, pool_root: Path) -> None:
    _rmtree_within(path, pool_root, "task clone")
