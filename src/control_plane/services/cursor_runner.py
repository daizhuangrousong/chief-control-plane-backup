import json
import re
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..adapters.git import git_at_root
from ..domain.models import ApprovalClass, ready_requires_owner_approval
from .dispatcher import BaselineConflictError, LeaseConflictError, LeaseDispatcher
from .project_isolation import ISOLATED_PROJECT_IDS
from .execution_contract import ExecutionContractError, inspect_execution
from .task_registry import TaskValidationError
from .task_worktree import TaskWorktreeError, TaskWorktreePool


DEFAULT_EXECUTOR_COMMAND = None
SECRET_ASSIGNMENT = re.compile(
    r"(?i)((?:token|secret|password|passwd|api[_-]?key|authorization|access[_-]?key)\s*[:=]\s*)\S+"
)
BEARER_TOKEN = re.compile(r"(?i)(\bbearer\s+)\S+")
SK_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


class CursorAdapterError(TaskValidationError):
    pass


def redact_secrets(text: str) -> str:
    if not text:
        return text
    redacted = SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", text)
    redacted = BEARER_TOKEN.sub(r"\1[REDACTED]", redacted)
    return SK_TOKEN.sub("[REDACTED]", redacted)


class CursorRunner:
    """R0 isolated Cursor adapter. Production default never discovers or starts Cursor."""

    def __init__(
        self,
        dispatcher: LeaseDispatcher,
        executor_id: str,
        executor_command: Optional[Sequence[str]] = DEFAULT_EXECUTOR_COMMAND,
        timeout_seconds: int = 300,
        log: Optional[Callable[[str], None]] = None,
        isolated_project_ids=None,
        worktree_pool: Optional[TaskWorktreePool] = None,
    ):
        if isinstance(executor_command, str) or not executor_command:
            raise CursorAdapterError(
                "executor command must be injected; R0 refuses to discover or start Cursor"
            )
        command = tuple(str(part) for part in executor_command)
        if any(not part.strip() for part in command):
            raise CursorAdapterError("executor command must be a non-empty argument list")
        self.dispatcher = dispatcher
        self.executor_id = executor_id
        self.executor_command = command
        self.timeout_seconds = timeout_seconds
        self._log = log or (lambda _message: None)
        self.isolated_project_ids = (
            ISOLATED_PROJECT_IDS if isolated_project_ids is None else frozenset(isolated_project_ids)
        )
        self._project_guard = threading.Lock()
        self.worktree_pool = worktree_pool

    def run_next(self, project_id: Optional[str] = None, request_id: Optional[str] = None) -> Dict[str, Any]:
        request_id = request_id or str(uuid.uuid4())
        task = self.dispatcher.next(self.executor_id, project_id)
        if task is None:
            return {"status": "idle", "reason": "no eligible READY task"}
        try:
            return self._claim_and_run(task, request_id)
        except CursorAdapterError as error:
            error.task_id = task["id"]
            raise

    def _claim_and_run(self, task: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        self._assert_safe_to_claim(task)
        baseline = self.dispatcher.get_project_baseline(task["project_id"])
        contract_report = None
        before_ref = baseline["baseline_ref"]
        if self.worktree_pool is None:
            workspace = self._workspace(task)
            git_head = git_at_root(workspace, "rev-parse", "HEAD")
            if not git_head:
                raise CursorAdapterError("workspace git HEAD is unknown; refusing to claim")
            if git_head != baseline["baseline_ref"]:
                raise CursorAdapterError(
                    "baseline drift: workspace HEAD {} != registered {}".format(
                        git_head, baseline["baseline_ref"]
                    )
                )
        else:
            workspace = self._workspace(task)
        with self._project_guard:
            active = self.dispatcher.active_lease_for_project(task["project_id"])
            if active:
                raise CursorAdapterError(
                    "project already has an active execution on {}".format(active["task_id"])
                )
            try:
                lease = self.dispatcher.claim(
                    task["id"], self.executor_id, baseline["baseline_ref"],
                    task["version"], request_id + ":claim",
                )
            except LeaseConflictError as error:
                raise CursorAdapterError("duplicate claim rejected: {}".format(error)) from error
        self.dispatcher.heartbeat(lease["lease_id"], self.executor_id, request_id + ":heartbeat")
        if self.worktree_pool is not None:
            try:
                allocated = self.worktree_pool.allocate(task["id"], baseline["baseline_ref"])
            except TaskWorktreeError as error:
                return self._fail(lease, baseline["baseline_ref"], request_id, str(error))
            workspace = Path(allocated["path"])
            before_ref = allocated["head"]
        try:
            completed = self._invoke(task, lease, workspace)
        except subprocess.TimeoutExpired as error:
            reason = self._reason("executor timed out", error.stdout, error.stderr)
            return self._fail(lease, baseline["baseline_ref"], request_id, reason)
        except OSError as error:
            return self._fail(
                lease, baseline["baseline_ref"], request_id,
                redact_secrets("executor command could not be started: {}".format(error)),
            )
        if completed.returncode != 0:
            reason = self._reason(
                "executor exited {}".format(completed.returncode),
                completed.stdout, completed.stderr,
            )
            return self._fail(lease, baseline["baseline_ref"], request_id, reason)
        if self.worktree_pool is not None:
            try:
                contract_report = inspect_execution(
                    workspace, before_ref, task.get("scope") or [], self.worktree_pool.runtime_root,
                )
            except ExecutionContractError as error:
                return self._fail(lease, baseline["baseline_ref"], request_id, str(error))
            self.worktree_pool.mark_phase(task["id"], "executed")
        try:
            result = self.dispatcher.complete(
                lease["lease_id"], self.executor_id, baseline["baseline_ref"], request_id + ":complete",
            )
        except BaselineConflictError as error:
            return self._fail(
                lease, baseline["baseline_ref"], request_id,
                "completion baseline conflict: {}".format(error),
            )
        if result.get("task_state") != "REVIEW":
            raise CursorAdapterError("success must enter REVIEW, found {}".format(result.get("task_state")))
        self._emit("completed {} into REVIEW".format(task["id"]))
        if contract_report is not None:
            result["before_ref"] = contract_report["beforeRef"]
            result["after_ref"] = contract_report["afterRef"]
            result["changed_paths"] = contract_report["changedPaths"]
            result["diff_check"] = contract_report["diffCheck"]
            result["execution_report"] = contract_report
        return result

    def _assert_safe_to_claim(self, task: Dict[str, Any]) -> None:
        if task["project_id"] in self.isolated_project_ids:
            raise CursorAdapterError("project is isolated from this runner: {}".format(task["project_id"]))
        if ready_requires_owner_approval(task.get("approval_class"), task.get("owner_approval_ref")):
            raise CursorAdapterError(
                "ownerApprovalRef is required for {} tasks".format(
                    task.get("approval_class") or ApprovalClass.NONE.value
                )
            )
        self._workspace(task)

    def _workspace(self, task: Dict[str, Any]) -> Path:
        project = self.dispatcher.repository.get_project(task["project_id"])
        if project is None:
            raise CursorAdapterError("project is not registered: {}".format(task["project_id"]))
        project_root = Path(project["config"]["root"]).resolve()
        roots = task.get("workspace_roots") or []
        if not roots:
            raise CursorAdapterError("task has no workspaceRoots")
        resolved: List[Path] = []
        for raw in roots:
            path = Path(raw).resolve()
            try:
                path.relative_to(project_root)
            except ValueError as error:
                raise CursorAdapterError(
                    "workspace is outside the authorized project root: {}".format(path)
                ) from error
            if not path.exists() or not path.is_dir():
                raise CursorAdapterError("workspace root does not exist: {}".format(path))
            resolved.append(path)
        return resolved[0]

    def _invoke(self, task: Dict[str, Any], lease: Dict[str, Any], workspace: Path) -> subprocess.CompletedProcess:
        payload = {
            "taskId": task["id"],
            "projectId": task["project_id"],
            "title": task["title"],
            "objective": task["objective"],
            "scope": task["scope"],
            "acceptance": task["acceptance"],
            "workspaceRoots": task["workspace_roots"],
            "approvalClass": task.get("approval_class") or ApprovalClass.NONE.value,
            "ownerApprovalRef": task.get("owner_approval_ref"),
            "leaseId": lease["lease_id"],
            "taskVersion": task["version"],
            "baselineRef": lease["baseline_ref"],
        }
        self._emit("starting injected executor for {}".format(task["id"]))
        return subprocess.run(
            list(self.executor_command),
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            cwd=str(workspace),
            check=False,
            shell=False,
        )

    def _fail(self, lease: Dict[str, Any], baseline_ref: str, request_id: str, reason: str) -> Dict[str, Any]:
        self._emit(reason)
        return self.dispatcher.fail(
            lease["lease_id"], self.executor_id, baseline_ref, request_id + ":fail", reason,
        )

    def _reason(self, prefix: str, stdout: Optional[str], stderr: Optional[str]) -> str:
        blob = redact_secrets("\n".join(part for part in (stdout or "", stderr or "") if part)).strip()
        if len(blob) > 800:
            blob = blob[:800] + "…"
        return "{}: {}".format(prefix, blob) if blob else prefix

    def _emit(self, message: str) -> None:
        self._log(redact_secrets(message))
