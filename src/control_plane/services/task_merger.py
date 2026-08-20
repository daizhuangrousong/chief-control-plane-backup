"""Independent merger. Task executors cannot merge their own work."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Set

from ..adapters.git import GitError, git_checked
from ..domain.models import TaskState
from ..storage.repository import Repository
from .chief_review_decision import ChiefReviewDecisionError, ChiefReviewInbox
from .chief_task_ingress import atomic_write_json
from .dispatcher import LeaseDispatcher
from .execution_contract import ExecutionContractError, load_execution_report, revalidate_execution_report
from .task_registry import TASK_ID_PATTERN, TaskValidationError
from .task_worktree import TaskWorktreePool, assert_control_path


class TaskMergeError(TaskValidationError):
    pass


class TaskMerger:
    def __init__(
        self,
        repository: Repository,
        dispatcher: LeaseDispatcher,
        project_root: Path,
        pool: TaskWorktreePool,
        review_inbox: ChiefReviewInbox,
        execution_report_dir: Path,
        executor_id: str = "merge-r4",
        target_branch: str = "main",
        allowed_review_actors: Set[str] = None,
        receipt_dir: Optional[Path] = None,
    ):
        self.repository = repository
        self.dispatcher = dispatcher
        self.project_root = Path(project_root).resolve()
        self.pool = pool
        self.review_inbox = review_inbox
        self.execution_report_dir = assert_control_path(
            Path(execution_report_dir), "execution report directory",
            pool.runtime_root, pool.project_root, pool.pool_root,
        )
        self.executor_id = executor_id
        self.target_branch = target_branch
        self.allowed_review_actors = allowed_review_actors or {"chief"}
        self.receipt_dir = Path(receipt_dir) if receipt_dir else None

    def merge(self, task_id: str, request_id: str) -> Dict[str, Any]:
        if not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id):
            raise TaskMergeError("merge requires a task id from the Chief inbox, not a caller-supplied decision")
        if not isinstance(request_id, str) or not request_id.strip():
            raise TaskMergeError("request id is required")
        existing = self._receipt(task_id)
        if existing is not None:
            if existing.get("requestId") == request_id:
                return existing
            raise TaskMergeError("duplicate review/merge is not allowed")
        try:
            decision = self.review_inbox.load(task_id)
        except ChiefReviewDecisionError as error:
            raise TaskMergeError(str(error)) from error
        if decision["actor"] not in self.allowed_review_actors:
            raise TaskMergeError("review decision actor is not authorized")
        if decision["outcome"] != "approve_merge":
            raise TaskMergeError("review decision did not approve a merge")
        task = self.repository.get_task(decision["taskId"])
        if task is None:
            raise TaskMergeError("task is not registered")
        if task["state"] != TaskState.REVIEW.value:
            raise TaskMergeError("task is not in REVIEW")
        if int(task["version"]) != int(decision["taskVersion"]):
            raise TaskMergeError("review decision taskVersion does not match the task")
        if self.executor_id in (task.get("allowed_executors") or []):
            raise TaskMergeError("merger identity must be independent of the task executor")
        occupancy = self.pool.read_occupancy(task["id"])
        if occupancy is None:
            raise TaskMergeError("task worktree occupancy is missing")
        worktree = Path(occupancy["path"]).resolve()
        branch = occupancy["branch"]
        try:
            branch_head = git_checked(self.project_root, "rev-parse", branch)
        except GitError as error:
            raise TaskMergeError("task branch is missing") from error
        if branch_head.lower() != decision["commitRef"].lower():
            raise TaskMergeError("conflicting commit on the task branch")
        lease = self.repository.get_task_lease(decision["leaseId"])
        if lease is None or lease["task_id"] != task["id"]:
            raise TaskMergeError("review lease does not belong to the task")
        if lease["status"] != "completed":
            raise TaskMergeError("merge requires a completed lease")
        if self.dispatcher.active_lease_for_project(task["project_id"]):
            raise TaskMergeError("project still has an active execution")
        try:
            report = load_execution_report(self.execution_report_dir, task["id"])
            revalidate_execution_report(
                report,
                worktree,
                self.pool.runtime_root,
                task.get("scope") or [],
                task["id"],
                int(task["version"]),
                lease["id"],
                decision["commitRef"],
                task.get("acceptance") or [],
                occupancy.get("baselineRef") or lease["baseline_ref"],
            )
        except ExecutionContractError as error:
            raise TaskMergeError(str(error)) from error
        current = git_checked(self.project_root, "rev-parse", "--abbrev-ref", "HEAD")
        if current != self.target_branch:
            raise TaskMergeError("project HEAD is not the merge target branch")
        porcelain = git_checked(self.project_root, "status", "--porcelain")
        if porcelain:
            raise TaskMergeError("target branch is dirty")
        try:
            self.review_inbox.consume(task_id, decision["sourceHash"])
        except ChiefReviewDecisionError as error:
            raise TaskMergeError(str(error)) from error
        try:
            git_checked(self.project_root, "merge", "--ff-only", branch)
        except GitError as error:
            raise TaskMergeError("local merge failed: {}".format(error)) from error
        merged = git_checked(self.project_root, "rev-parse", "HEAD")
        receipt = {
            "status": "merged",
            "taskId": task["id"],
            "taskVersion": task["version"],
            "commitRef": merged,
            "branch": branch,
            "targetBranch": self.target_branch,
            "leaseId": lease["id"],
            "requestId": request_id,
            "merger": self.executor_id,
        }
        if self.receipt_dir is not None:
            atomic_write_json(self.receipt_dir / "{}.merge.json".format(task["id"]), receipt)
        self.pool.mark_phase(task["id"], "merged")
        return receipt

    def _receipt(self, task_id: str) -> Optional[Dict[str, Any]]:
        if self.receipt_dir is None:
            return None
        path = self.receipt_dir / "{}.merge.json".format(task_id)
        if not path.is_file() or path.is_symlink():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None
