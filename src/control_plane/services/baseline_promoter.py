"""Promote Dispatcher baseline only after a verified local merge. Never self-approve."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..adapters.git import GitError, git_checked
from .dispatcher import LeaseDispatcher
from .task_registry import TaskValidationError


class BaselinePromotionError(TaskValidationError):
    pass


class BaselinePromoter:
    def __init__(
        self,
        dispatcher: LeaseDispatcher,
        project_root: Path,
        runtime_root: Path,
        actor: str = "baseline-promoter",
        runtime_healthy: Optional[Callable[[], bool]] = None,
    ):
        self.dispatcher = dispatcher
        self.project_root = Path(project_root)
        self.runtime_root = Path(runtime_root).resolve()
        self.actor = actor
        self.runtime_healthy = runtime_healthy or (lambda: True)

    def promote(self, project_id: str, merge_commit: str, request_id: str) -> Dict[str, Any]:
        previous = self.dispatcher.get_project_baseline(project_id)
        old_ref = previous["baseline_ref"]
        rollback_plan = {
            "keepBaseline": old_ref,
            "restoreCommand": [
                "git", "-C", str(self.project_root), "reset", "--keep", old_ref,
            ],
            "note": "Failure keeps the registered baseline. Do not run restore unless Chief approves.",
        }
        if merge_commit == old_ref:
            return {
                "status": "already_promoted",
                "projectId": project_id,
                "baselineRef": old_ref,
                "previousBaselineRef": old_ref,
                "requestId": request_id,
            }
        if self.dispatcher.active_lease_for_project(project_id):
            return self._failed("project still has an active execution", previous, rollback_plan, request_id)
        try:
            inside = git_checked(self.runtime_root, "rev-parse", "--is-inside-work-tree")
        except GitError:
            inside = ""
        if inside == "true":
            runtime_status = git_checked(self.runtime_root, "status", "--porcelain")
            if runtime_status:
                return self._failed("runtime worktree is dirty", previous, rollback_plan, request_id)
        try:
            target_status = git_checked(self.project_root, "status", "--porcelain")
        except GitError as error:
            return self._failed("target branch status is unreadable: {}".format(error), previous, rollback_plan, request_id)
        if target_status:
            return self._failed("target branch is dirty", previous, rollback_plan, request_id)
        try:
            kind = git_checked(self.project_root, "cat-file", "-t", merge_commit)
            head = git_checked(self.project_root, "rev-parse", "HEAD")
        except GitError as error:
            return self._failed("merge commit is not verifiable: {}".format(error), previous, rollback_plan, request_id)
        if kind != "commit" or head != merge_commit:
            return self._failed("merge commit is not the target HEAD", previous, rollback_plan, request_id)
        if not self.runtime_healthy():
            return self._failed("runtime health check failed after merge", previous, rollback_plan, request_id)
        updated = self.dispatcher.set_project_baseline(project_id, merge_commit, self.actor)
        return {
            "status": "promoted",
            "projectId": project_id,
            "baselineRef": updated["baseline_ref"],
            "previousBaselineRef": old_ref,
            "requestId": request_id,
            "rollbackPlan": rollback_plan,
        }

    def _failed(
        self, reason: str, previous: Dict[str, Any], rollback_plan: Dict[str, Any], request_id: str,
    ) -> Dict[str, Any]:
        current = self.dispatcher.get_project_baseline(previous["project_id"])
        if current["baseline_ref"] != previous["baseline_ref"]:
            raise BaselinePromotionError("baseline changed unexpectedly during failed promotion")
        return {
            "status": "failed",
            "reason": reason,
            "projectId": previous["project_id"],
            "baselineRef": previous["baseline_ref"],
            "previousBaselineRef": previous["baseline_ref"],
            "rollbackPlan": rollback_plan,
            "requestId": request_id,
        }
