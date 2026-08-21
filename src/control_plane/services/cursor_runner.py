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
from .execution_contract import (
    EXECUTION_REPORT_VERSION, EXECUTOR_RESULT_VERSION, ExecutionContractError,
    execution_report_path, inspect_execution, load_execution_report, parse_executor_result,
    persist_execution_report, run_chief_verification, revalidate_execution_report,
    assert_safe_chief_commands,
)
from .task_registry import TaskValidationError, criteria_of, verification_commands_of
from .task_worktree import TaskWorktreeError, TaskWorktreePool, assert_control_path


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
        execution_report_dir: Optional[Path] = None,
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
        self.verification_invocations: List[List[str]] = []
        if worktree_pool is not None:
            if execution_report_dir is None:
                raise CursorAdapterError("execution report directory is required when a worktree pool is enabled")
            self.execution_report_dir = assert_control_path(
                Path(execution_report_dir), "execution report directory",
                worktree_pool.runtime_root, worktree_pool.project_root, worktree_pool.pool_root,
                worktree_pool.state_root,
            )
        else:
            self.execution_report_dir = Path(execution_report_dir).resolve() if execution_report_dir else None

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
        from .executor_sandbox import ExecutorSandboxError, prepare_executor_sandbox
        from .task_clone import import_exact_commit
        host_snapshot = None
        sandbox = None
        if self.worktree_pool is not None:
            try:
                assert_safe_chief_commands(verification_commands_of(task.get("acceptance")))
                allocated = self.worktree_pool.allocate(task["id"], baseline["baseline_ref"])
                host_snapshot = self.worktree_pool.snapshot_hosts()
                workspace = Path(allocated["path"]).resolve()
                before_ref = allocated["head"]
                sandbox = prepare_executor_sandbox(
                    task["id"],
                    workspace,
                    self.worktree_pool.runtime_root,
                    self.worktree_pool.project_root,
                    self.worktree_pool.pool_root,
                    self.worktree_pool.state_root,
                )
            except (TaskWorktreeError, ExecutionContractError, ExecutorSandboxError) as error:
                return self._fail(lease, baseline["baseline_ref"], request_id, str(error))
        try:
            completed = self._invoke(task, lease, workspace, sandbox)
        except subprocess.TimeoutExpired as error:
            reason = self._reason("executor timed out", error.stdout, error.stderr)
            return self._fail(lease, baseline["baseline_ref"], request_id, reason)
        except ExecutorSandboxError as error:
            return self._fail(lease, baseline["baseline_ref"], request_id, str(error))
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
        expected_review_version = None
        durable = None
        if self.worktree_pool is not None:
            try:
                self.worktree_pool.assert_hosts_unchanged(host_snapshot, baseline["baseline_ref"])
                contract_report = inspect_execution(
                    workspace, before_ref, task.get("scope") or [], self.worktree_pool.runtime_root,
                )
                registered = self.dispatcher.repository.get_task(task["id"])
                commands = verification_commands_of((registered or {}).get("acceptance"))
                if not commands:
                    raise ExecutionContractError("verificationCommands are missing from the registered task")
                view = dict(task)
                view["acceptance"] = criteria_of((registered or {}).get("acceptance"))
                parsed_result = parse_executor_result(
                    completed.stdout, view, lease["lease_id"], contract_report["afterRef"], commands,
                )
                verify_results = run_chief_verification(
                    workspace, commands, timeout=min(30, self.timeout_seconds),
                    invocations=self.verification_invocations,
                )
                self.worktree_pool.assert_hosts_unchanged(host_snapshot, baseline["baseline_ref"])
                post = inspect_execution(
                    workspace, before_ref, task.get("scope") or [], self.worktree_pool.runtime_root,
                )
                if post["afterRef"] != contract_report["afterRef"]:
                    raise ExecutionContractError("verification changed the leased commit")
                if post["changedPaths"] != contract_report["changedPaths"]:
                    raise ExecutionContractError("verification changed task scope")
                import_exact_commit(
                    self.worktree_pool.project_root,
                    workspace,
                    self.worktree_pool.branch_name(task["id"]),
                    contract_report["afterRef"],
                )
                self.worktree_pool.assert_hosts_unchanged(host_snapshot, baseline["baseline_ref"])
            except (TaskWorktreeError, ExecutionContractError) as error:
                return self._fail(lease, baseline["baseline_ref"], request_id, str(error))
            self.worktree_pool.mark_phase(task["id"], "executed")
            running = self.dispatcher.repository.get_task(task["id"])
            expected_review_version = int(running["version"]) + 1
            durable = {
                "schemaVersion": EXECUTION_REPORT_VERSION,
                "taskId": task["id"],
                "taskVersion": expected_review_version,
                "leaseId": lease["lease_id"],
                "baselineRef": before_ref,
                "beforeRef": contract_report["beforeRef"],
                "afterRef": contract_report["afterRef"],
                "changedPaths": contract_report["changedPaths"],
                "commitCount": contract_report["commitCount"],
                "diffCheck": contract_report["diffCheck"],
                "tests": contract_report["tests"],
                "acceptanceChecks": verify_results,
                "executorResult": {
                    "schemaVersion": EXECUTOR_RESULT_VERSION,
                    "taskVersion": parsed_result["taskVersion"],
                    "commitRef": parsed_result["commitRef"],
                },
                "worktree": str(workspace),
            }
            try:
                persist_execution_report(self.execution_report_dir, durable)
                report_path = execution_report_path(self.execution_report_dir, task["id"])
                self._after_persist(report_path)
                loaded = load_execution_report(self.execution_report_dir, task["id"])
                revalidate_execution_report(
                    loaded,
                    workspace,
                    self.worktree_pool.runtime_root,
                    task.get("scope") or [],
                    task["id"],
                    expected_review_version,
                    lease["lease_id"],
                    contract_report["afterRef"],
                    (registered or {}).get("acceptance") or [],
                    before_ref,
                )
            except (OSError, ExecutionContractError) as error:
                return self._fail(
                    lease, baseline["baseline_ref"], request_id,
                    "execution report persist failed: {}".format(error),
                )
            self._before_complete()
        try:
            result = self.dispatcher.complete(
                lease["lease_id"], self.executor_id,
                self._completion_baseline(lease, baseline["baseline_ref"]),
                request_id + ":complete",
            )
        except BaselineConflictError as error:
            return self._fail(
                lease, baseline["baseline_ref"], request_id,
                "completion baseline conflict: {}".format(error),
            )
        if result.get("task_state") != "REVIEW":
            raise CursorAdapterError("success must enter REVIEW, found {}".format(result.get("task_state")))
        if expected_review_version is not None and result.get("task_version") != expected_review_version:
            raise CursorAdapterError("REVIEW taskVersion does not match the persisted report")
        self._emit("completed {} into REVIEW".format(task["id"]))
        if durable is not None:
            result["before_ref"] = durable["beforeRef"]
            result["after_ref"] = durable["afterRef"]
            result["changed_paths"] = durable["changedPaths"]
            result["diff_check"] = durable["diffCheck"]
            result["execution_report"] = durable
        return result

    def _after_persist(self, path: Path) -> None:
        return None

    def _before_complete(self) -> None:
        return None

    def _completion_baseline(self, lease: Dict[str, Any], registered: str) -> str:
        return registered

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

    def _invoke(
        self,
        task: Dict[str, Any],
        lease: Dict[str, Any],
        workspace: Path,
        sandbox: Optional[Dict[str, Any]] = None,
    ) -> subprocess.CompletedProcess:
        payload = {
            "taskId": task["id"],
            "projectId": task["project_id"],
            "title": task["title"],
            "objective": task["objective"],
            "scope": task["scope"],
            "acceptance": criteria_of(task.get("acceptance")),
            "verification": [
                {"id": item["id"], "criterion": item["criterion"]}
                for item in verification_commands_of(task.get("acceptance"))
            ],
            "workspaceRoots": (
                [str(Path(workspace).resolve())]
                if self.worktree_pool is not None
                else list(task["workspace_roots"])
            ),
            "approvalClass": task.get("approval_class") or ApprovalClass.NONE.value,
            "ownerApprovalRef": task.get("owner_approval_ref"),
            "leaseId": lease["lease_id"],
            "taskVersion": task["version"],
            "baselineRef": lease["baseline_ref"],
        }
        payload_text = json.dumps(payload, ensure_ascii=False)
        self._emit("starting injected executor for {}".format(task["id"]))
        if self.worktree_pool is None:
            return subprocess.run(
                list(self.executor_command),
                input=payload_text,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                cwd=str(workspace),
                check=False,
                shell=False,
            )
        from .executor_sandbox import ExecutorSandboxError, launch_sandboxed_executor
        if sandbox is None:
            raise ExecutorSandboxError("executor sandbox was not prepared")
        return launch_sandboxed_executor(
            list(self.executor_command),
            workspace=Path(workspace),
            sandbox=sandbox,
            input_text=payload_text,
            timeout_seconds=self.timeout_seconds,
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
