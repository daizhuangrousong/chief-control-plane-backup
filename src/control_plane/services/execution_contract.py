"""Single-commit execution contract inside a leased task worktree."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from ..adapters.git import GitError, git_checked
from .task_registry import TaskValidationError


EXECUTION_REPORT_VERSION = "execution-report/1.0.0"
EXECUTOR_RESULT_VERSION = "executor-result/1.0.0"
RESULT_FIELDS = {"schemaVersion", "taskId", "taskVersion", "leaseId", "commitRef", "acceptanceChecks"}
COMMAND_CHECK_FIELDS = {"criterion", "checkType", "status", "evidence", "argv", "exitCode"}
HUMAN_CHECK_FIELDS = {"criterion", "checkType", "status", "evidence"}
CHECK_TYPES = {"command", "human"}
CHECK_STATUSES = {"pass", "fail"}


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
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = execution_report_path(directory, str(report.get("taskId") or ""))
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise ExecutionContractError("execution report path is not a regular file")
        descriptor, temporary = tempfile.mkstemp(prefix=".execution-report-", suffix=".tmp", dir=str(directory))
    except OSError as error:
        raise ExecutionContractError("could not persist execution report") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as error:
        raise ExecutionContractError("could not persist execution report") from error
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def load_execution_report(directory: Path, task_id: str) -> Dict[str, Any]:
    path = execution_report_path(directory, task_id)
    if path.is_symlink() or not path.is_file() or path.name.startswith("."):
        raise ExecutionContractError("execution report is missing")
    if path.suffix != ".json" or path.name.endswith(".tmp"):
        raise ExecutionContractError("execution report is not durable")
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
    for item in checks:
        if not str(item.get("evidence") or "").strip():
            raise ExecutionContractError("acceptance evidence is empty")
        if item.get("checkType") not in CHECK_TYPES:
            raise ExecutionContractError("acceptance checkType is invalid")
        if item.get("checkType") == "command" and item.get("exitCode") != 0:
            raise ExecutionContractError("acceptance command failed")
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
    replay_acceptance_commands(worktree, checks)
    return fresh


def parse_executor_result(
    raw: str,
    task: Dict[str, Any],
    lease_id: str,
    commit_ref: str,
) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise ExecutionContractError("executor result is missing")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ExecutionContractError("executor result is not JSON") from error
    if not isinstance(payload, dict):
        raise ExecutionContractError("executor result must be an object")
    extra = sorted(set(payload) - RESULT_FIELDS)
    if extra:
        raise ExecutionContractError("unknown executor result fields: {}".format(", ".join(extra)))
    missing = sorted(RESULT_FIELDS - set(payload))
    if missing:
        raise ExecutionContractError("executor result missing fields: {}".format(", ".join(missing)))
    if payload["schemaVersion"] != EXECUTOR_RESULT_VERSION:
        raise ExecutionContractError("unsupported executor result schemaVersion")
    if payload.get("taskId") != task.get("id"):
        raise ExecutionContractError("executor result taskId mismatch")
    version = payload.get("taskVersion")
    if not isinstance(version, int) or isinstance(version, bool) or version != int(task.get("version")):
        raise ExecutionContractError("executor result taskVersion mismatch")
    if payload.get("leaseId") != lease_id:
        raise ExecutionContractError("executor result leaseId mismatch")
    if (payload.get("commitRef") or "").lower() != (commit_ref or "").lower():
        raise ExecutionContractError("executor result commit does not match the leased HEAD")
    expected = [str(item) for item in (task.get("acceptance") or [])]
    if not expected:
        raise ExecutionContractError("task acceptance is missing")
    checks = payload.get("acceptanceChecks")
    if not isinstance(checks, list) or len(checks) != len(expected):
        raise ExecutionContractError("acceptance checks are missing or the wrong length")
    parsed = []
    for index, item in enumerate(checks):
        if not isinstance(item, dict):
            raise ExecutionContractError("acceptance check must be an object")
        if str(item.get("criterion") or "") != expected[index]:
            raise ExecutionContractError("acceptance checks are out of order")
        check_type = item.get("checkType")
        if check_type not in CHECK_TYPES:
            raise ExecutionContractError("acceptance checkType is invalid")
        status = item.get("status")
        if status not in CHECK_STATUSES:
            raise ExecutionContractError("acceptance status is invalid")
        evidence = item.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ExecutionContractError("acceptance evidence is empty")
        if check_type == "command":
            extra_fields = sorted(set(item) - COMMAND_CHECK_FIELDS)
            if extra_fields:
                raise ExecutionContractError("unknown command check fields: {}".format(", ".join(extra_fields)))
            missing_fields = sorted(COMMAND_CHECK_FIELDS - set(item))
            if missing_fields:
                raise ExecutionContractError("command check missing fields: {}".format(", ".join(missing_fields)))
            argv = item["argv"]
            if (
                not isinstance(argv, list)
                or not argv
                or any(not isinstance(part, str) or not part.strip() for part in argv)
            ):
                raise ExecutionContractError("acceptance argv is invalid")
            exit_code = item["exitCode"]
            if not isinstance(exit_code, int) or isinstance(exit_code, bool):
                raise ExecutionContractError("acceptance exitCode is invalid")
            if status == "pass" and exit_code != 0:
                raise ExecutionContractError("passing acceptance has a non-zero exit code")
            if status != "pass" or exit_code != 0:
                raise ExecutionContractError("acceptance command failed")
            parsed.append({
                "criterion": expected[index],
                "checkType": "command",
                "status": "pass",
                "evidence": evidence.strip(),
                "argv": [str(part) for part in argv],
                "exitCode": exit_code,
            })
            continue
        extra_fields = sorted(set(item) - HUMAN_CHECK_FIELDS)
        if extra_fields:
            raise ExecutionContractError("unknown human check fields: {}".format(", ".join(extra_fields)))
        if status != "pass":
            raise ExecutionContractError("human acceptance failed")
        parsed.append({
            "criterion": expected[index],
            "checkType": "human",
            "status": "pass",
            "evidence": evidence.strip(),
        })
    return {
        "schemaVersion": EXECUTOR_RESULT_VERSION,
        "taskId": task["id"],
        "taskVersion": version,
        "leaseId": lease_id,
        "commitRef": commit_ref.lower(),
        "acceptanceChecks": parsed,
    }


def replay_acceptance_commands(worktree: Path, checks: Sequence[Dict[str, Any]]) -> None:
    worktree = Path(worktree)
    for item in checks:
        if item.get("checkType") != "command":
            continue
        argv = item.get("argv")
        if not isinstance(argv, list) or not argv:
            raise ExecutionContractError("acceptance argv is invalid")
        try:
            completed = subprocess.run(
                [str(part) for part in argv],
                cwd=str(worktree),
                capture_output=True,
                text=True,
                check=False,
                shell=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ExecutionContractError("acceptance command could not be replayed") from error
        if completed.returncode != item.get("exitCode"):
            raise ExecutionContractError("acceptance command exit code does not replay")
        if completed.returncode != 0:
            raise ExecutionContractError("acceptance command failed on replay")
