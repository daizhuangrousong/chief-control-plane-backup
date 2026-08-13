import uuid
from typing import Any, Dict, Optional

from ..services.dispatcher import (
    BaselineConflictError, ExecutorUnauthorizedError, LeaseConflictError, LeaseDispatcher,
)
from ..services.executor_report import ExecutorReportService
from ..services.project_isolation import ISOLATED_PROJECT_IDS
from ..storage import Repository
from ..storage.repository import utc_now
from .base import TARGET_NOT_READY, TargetedClaimResult


class DispatcherGateway:
    """Thin, fail-closed client over the existing Chief dispatch primitives.

    Every method composes ``LeaseDispatcher`` / ``ExecutorReportService`` and the
    repository; this gateway never calls ``dispatcher.next()`` and therefore never
    falls back to a different task when a precise targeted claim cannot proceed.
    """

    def __init__(self, dispatcher: LeaseDispatcher, repository: Repository):
        self.dispatcher = dispatcher
        self.repository = repository

    def claim_targeted(self, task_id: str, executor_id: str, baseline_ref: str,
                       request_id: str, ttl_seconds: Optional[int] = None) -> TargetedClaimResult:
        """Precise claim of ONE specified task.

        Returns ``TARGET_NOT_READY`` (and does nothing else) when the task is
        missing or not in READY state. For any other ineligibility the underlying
        dispatcher raises its normal error — there is no fallback to another task.
        """
        task = self.repository.get_task(task_id)
        if task is None:
            return TargetedClaimResult(status=TARGET_NOT_READY, task_id=task_id,
                                       reason="task not found")
        if task["state"] != "READY":
            return TargetedClaimResult(
                status=TARGET_NOT_READY, task_id=task_id, task=task,
                reason="task is {} not READY".format(task["state"]),
            )
        # Delegate enforcement (project/executor/risk/baseline/version) to the
        # dispatcher. It raises on ineligibility and never claims a different task.
        lease = self.dispatcher.claim(
            task_id, executor_id, baseline_ref, int(task["version"]), request_id, ttl_seconds
        )
        return TargetedClaimResult(status="CLAIMED", task_id=task_id, task=task, lease=lease)

    def heartbeat(self, lease_id: str, executor_id: str, request_id: str,
                  ttl_seconds: Optional[int] = None) -> Dict[str, Any]:
        return self.dispatcher.heartbeat(lease_id, executor_id, request_id, ttl_seconds)

    def complete(self, lease_id: str, executor_id: str, baseline_ref: str,
                 request_id: str) -> Dict[str, Any]:
        return self.dispatcher.complete(lease_id, executor_id, baseline_ref, request_id)

    def fail(self, lease_id: str, executor_id: str, baseline_ref: str, request_id: str,
             reason: str) -> Dict[str, Any]:
        return self.dispatcher.fail(lease_id, executor_id, baseline_ref, request_id, reason)

    def submit_report(self, report: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        return ExecutorReportService(self.repository).submit(report, request_id)

    def progress(self, run_id: Optional[str], lease_id: str, executor_id: str,
                 request_id: str, message: str) -> Dict[str, Any]:
        record_id = str(uuid.uuid4())
        with self.repository.connect() as connection:
            connection.execute(
                """INSERT INTO task_progress
                   (id, run_id, lease_id, executor_id, message, request_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (record_id, run_id, lease_id, executor_id, message, request_id, utc_now()),
            )
        return {"id": record_id, "lease_id": lease_id, "message": message}
