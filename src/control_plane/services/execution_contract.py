"""Single-commit execution contract inside a leased task worktree."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from ..adapters.git import GitError, git_checked
from .task_registry import TaskValidationError


EXECUTION_REPORT_VERSION = "execution-report/1.0.0"


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
        "tests": [
            {"name": "git-diff-check", "status": "pass", "command": "git diff --check"},
            {"name": "single-commit", "status": "pass", "command": "git rev-list --count"},
            {"name": "scope", "status": "pass", "command": "git diff --name-only"},
        ],
        "worktree": str(worktree),
    }


def execution_report_path(directory: Path, task_id: str) -> Path:
    return Path(directory) / "{}.json".format(task_id)


def persist_execution_report(directory: Path, report: Dict[str, Any]) -> Path:
    if not isinstance(report, dict) or report.get("schemaVersion") != EXECUTION_REPORT_VERSION:
        raise ExecutionContractError("execution report schemaVersion is invalid")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = execution_report_path(directory, str(report.get("taskId") or ""))
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ExecutionContractError("execution report path is not a regular file")
    descriptor, temporary = tempfile.mkstemp(prefix=".execution-report-", suffix=".tmp", dir=str(directory))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def load_execution_report(directory: Path, task_id: str) -> Dict[str, Any]:
    path = execution_report_path(directory, task_id)
    if path.is_symlink() or not path.is_file():
        raise ExecutionContractError("execution report is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExecutionContractError("execution report is unreadable") from error
    if not isinstance(payload, dict) or payload.get("schemaVersion") != EXECUTION_REPORT_VERSION:
        raise ExecutionContractError("execution report is invalid")
    if payload.get("taskId") != task_id:
        raise ExecutionContractError("execution report taskId mismatch")
    return payload


def revalidate_execution_report(
    report: Dict[str, Any],
    worktree: Path,
    runtime_root: Path,
    scope: Sequence[str],
    task_id: str,
    task_version: int,
    lease_id: str,
    commit_ref: str,
    acceptance: Sequence[str],
    baseline_ref: Optional[str] = None,
) -> Dict[str, Any]:
    if not isinstance(report, dict) or report.get("schemaVersion") != EXECUTION_REPORT_VERSION:
        raise ExecutionContractError("execution report is invalid")
    if report.get("taskId") != task_id:
        raise ExecutionContractError("execution report taskId mismatch")
    if int(report.get("taskVersion") or 0) != int(task_version):
        raise ExecutionContractError("execution report taskVersion mismatch")
    if report.get("leaseId") != lease_id:
        raise ExecutionContractError("execution report leaseId mismatch")
    if (report.get("afterRef") or "").lower() != (commit_ref or "").lower():
        raise ExecutionContractError("execution report commit does not match the review decision")
    if baseline_ref and report.get("baselineRef") != baseline_ref:
        raise ExecutionContractError("execution report baseline mismatch")
    tests = report.get("tests")
    if not isinstance(tests, list) or not tests:
        raise ExecutionContractError("execution tests are missing")
    if any(not isinstance(item, dict) or item.get("status") != "pass" for item in tests):
        raise ExecutionContractError("execution tests failed")
    checks = report.get("acceptanceChecks")
    if not isinstance(checks, list) or not checks:
        raise ExecutionContractError("acceptance checks are missing")
    if any(not isinstance(item, dict) or item.get("status") != "pass" for item in checks):
        raise ExecutionContractError("acceptance checks failed")
    expected_acceptance = [str(item) for item in acceptance]
    reported_acceptance = [str(item.get("criterion") or "") for item in checks]
    if reported_acceptance != expected_acceptance:
        raise ExecutionContractError("acceptance checks drifted")
    if report.get("diffCheck") != "pass":
        raise ExecutionContractError("execution diff-check is not pass")
    fresh = inspect_execution(worktree, str(report.get("beforeRef") or ""), scope, runtime_root)
    if fresh["afterRef"] != report.get("afterRef"):
        raise ExecutionContractError("execution report afterRef was tampered")
    if fresh["beforeRef"] != report.get("beforeRef"):
        raise ExecutionContractError("execution report beforeRef was tampered")
    if fresh["changedPaths"] != report.get("changedPaths"):
        raise ExecutionContractError("execution scope drifted")
    if fresh["commitCount"] != report.get("commitCount"):
        raise ExecutionContractError("execution commit count drifted")
    if fresh["diffCheck"] != "pass":
        raise ExecutionContractError("recomputed diff-check failed")
    reported_tree = Path(str(report.get("worktree") or "")).resolve()
    if reported_tree != Path(worktree).resolve():
        raise ExecutionContractError("execution report worktree mismatch")
    return fresh
