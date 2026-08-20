"""Single-commit execution contract inside a leased task worktree."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Sequence

from ..adapters.git import GitError, git_checked
from .task_registry import TaskValidationError


class ExecutionContractError(TaskValidationError):
    pass


def inspect_execution(
    worktree: Path,
    before_ref: str,
    scope: Sequence[str],
    runtime_root: Path,
) -> Dict[str, Any]:
    worktree = Path(worktree).resolve()
    runtime_root = Path(runtime_root).resolve()
    if worktree == runtime_root:
        raise ExecutionContractError("refusing to execute inside the resident runtime worktree")
    try:
        after = git_checked(worktree, "rev-parse", "HEAD")
    except GitError as error:
        raise ExecutionContractError("task worktree git HEAD is unknown") from error
    if not after:
        raise ExecutionContractError("task worktree git HEAD is unknown")
    try:
        porcelain = git_checked(worktree, "status", "--porcelain")
    except GitError as error:
        raise ExecutionContractError("task worktree status is unreadable") from error
    if porcelain:
        raise ExecutionContractError("uncommitted changes remain after execution")
    try:
        count_text = git_checked(worktree, "rev-list", "--count", "{}..{}".format(before_ref, after))
        count = int(count_text)
    except (GitError, ValueError) as error:
        raise ExecutionContractError("could not count commits on the leased worktree") from error
    if count == 0:
        raise ExecutionContractError("empty commit masquerading as completion")
    if count > 1:
        raise ExecutionContractError("multiple commits are not allowed")
    try:
        names = git_checked(worktree, "diff", "--name-only", before_ref, after)
    except GitError as error:
        raise ExecutionContractError("could not list changed paths") from error
    paths = [item for item in names.splitlines() if item.strip()]
    if not paths:
        raise ExecutionContractError("empty commit masquerading as completion")
    allowed = set(scope)
    for relative in paths:
        if relative not in allowed:
            raise ExecutionContractError("changed path is outside task scope: {}".format(relative))
        absolute = (worktree / relative).resolve()
        try:
            absolute.relative_to(worktree)
        except ValueError as error:
            raise ExecutionContractError("changed path is outside the leased worktree") from error
        if absolute.is_symlink():
            raise ExecutionContractError("changed path must not be a symlink")
    try:
        git_checked(worktree, "diff", "--check", before_ref, after)
        diff_check = "pass"
    except GitError as error:
        raise ExecutionContractError("git diff --check failed: {}".format(error)) from error
    return {
        "beforeRef": before_ref,
        "afterRef": after,
        "changedPaths": paths,
        "commitCount": count,
        "diffCheck": diff_check,
        "tests": [{"name": "git-diff-check", "status": "pass", "command": "git diff --check"}],
        "worktree": str(worktree),
    }
