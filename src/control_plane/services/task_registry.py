import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..domain.models import ApprovalClass, ControlTask, TaskPriority, TaskRisk, TaskState, ready_requires_owner_approval
from ..storage.repository import Repository, TaskNotFoundError


TASK_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
EXECUTOR_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
COMMAND_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
UNSAFE_ARGV = re.compile(r"[|><;&`\n$]|&&|\|\|")
SHELL_PROGRAMS = {"sh", "bash", "zsh", "csh", "ksh", "fish", "dash", "env"}
VERIFICATION_FIELDS = {"id", "criterion", "argv"}
TASK_FIELDS = {
    "id", "projectId", "title", "objective", "scope", "acceptance", "priority", "riskLevel",
    "allowedExecutors", "workspaceRoots", "dependencies", "sourceUri", "approvalClass",
    "ownerApprovalRef", "verificationCommands",
}
APPROVAL_CLASS_VALUES = tuple(item.value for item in ApprovalClass)

ALLOWED_TRANSITIONS = {
    TaskState.DRAFT: {TaskState.NEEDS_DECISION, TaskState.READY, TaskState.BLOCKED},
    TaskState.NEEDS_DECISION: {TaskState.READY, TaskState.BLOCKED},
    TaskState.READY: {TaskState.CLAIMED, TaskState.BLOCKED},
    TaskState.CLAIMED: {TaskState.RUNNING, TaskState.READY, TaskState.BLOCKED, TaskState.FAILED},
    TaskState.RUNNING: {TaskState.REVIEW, TaskState.READY, TaskState.BLOCKED, TaskState.FAILED},
    TaskState.REVIEW: {TaskState.DONE, TaskState.READY, TaskState.BLOCKED, TaskState.FAILED},
    TaskState.BLOCKED: {TaskState.DRAFT, TaskState.NEEDS_DECISION, TaskState.READY},
    TaskState.FAILED: {TaskState.READY, TaskState.BLOCKED},
    TaskState.DONE: set(),
}


class TaskValidationError(ValueError):
    pass


class IllegalTaskTransitionError(ValueError):
    pass


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise TaskValidationError("{} is required".format(field_name))
    return text


def _string_list(value: Any, field_name: str, allow_empty: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise TaskValidationError("{} must be a list".format(field_name))
    result = [_required_text(item, field_name) for item in value]
    if not allow_empty and not result:
        raise TaskValidationError("{} must not be empty".format(field_name))
    if len(result) != len(set(result)):
        raise TaskValidationError("{} contains duplicates".format(field_name))
    return result


def criteria_of(acceptance: Any) -> List[str]:
    if isinstance(acceptance, dict):
        return [str(item) for item in acceptance.keys()]
    if isinstance(acceptance, list):
        return [str(item) for item in acceptance]
    return []


def verification_commands_of(acceptance: Any) -> List[Dict[str, Any]]:
    if not isinstance(acceptance, dict) or not acceptance:
        return []
    commands = []
    for criterion, body in acceptance.items():
        if not isinstance(body, dict) or "id" not in body or "argv" not in body:
            return []
        commands.append({
            "id": body["id"],
            "criterion": str(criterion),
            "argv": list(body["argv"]),
        })
    return commands


def _validate_argv(argv: Any, field_name: str) -> List[str]:
    if isinstance(argv, str):
        raise TaskValidationError("{} must be an argv array, not a shell string".format(field_name))
    if not isinstance(argv, list) or not argv:
        raise TaskValidationError("{} must be a non-empty argv array".format(field_name))
    parts = []
    for item in argv:
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            raise TaskValidationError("{} contains an empty or padded argument".format(field_name))
        if UNSAFE_ARGV.search(item):
            raise TaskValidationError("{} contains shell redirection or pipe syntax".format(field_name))
        if item.startswith("/") or item.startswith("~") or "\\" in item:
            raise TaskValidationError("{} must not contain absolute paths".format(field_name))
        if item == "-c":
            raise TaskValidationError("{} must not use -c".format(field_name))
        parts.append(item)
    if "/" in parts[0] or "\\" in parts[0]:
        raise TaskValidationError("{} program must be a bare command name".format(field_name))
    program = parts[0].rsplit("/", 1)[-1].lower()
    if program in SHELL_PROGRAMS:
        raise TaskValidationError("{} must not invoke a shell".format(field_name))
    return parts


def parse_verification_commands(value: Any, criteria: List[str]) -> List[Dict[str, Any]]:
    if value is None:
        raise TaskValidationError("verificationCommands is required")
    if not isinstance(value, list):
        raise TaskValidationError("verificationCommands must be a list")
    if len(value) != len(criteria):
        raise TaskValidationError("verificationCommands must match acceptance 1:1")
    parsed = []
    seen_ids = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise TaskValidationError("verificationCommands items must be objects")
        extra = sorted(set(item) - VERIFICATION_FIELDS)
        if extra:
            raise TaskValidationError("unknown verificationCommands fields: {}".format(", ".join(extra)))
        missing = sorted(VERIFICATION_FIELDS - set(item))
        if missing:
            raise TaskValidationError("verificationCommands missing fields: {}".format(", ".join(missing)))
        command_id = _required_text(item.get("id"), "verificationCommands.id")
        if not COMMAND_ID_PATTERN.fullmatch(command_id):
            raise TaskValidationError("verificationCommands.id must be a lowercase hyphenated id")
        if command_id in seen_ids:
            raise TaskValidationError("verificationCommands.id contains duplicates")
        seen_ids.add(command_id)
        criterion = _required_text(item.get("criterion"), "verificationCommands.criterion")
        if criterion != criteria[index]:
            raise TaskValidationError("verificationCommands are missing, extra, or out of order")
        argv = _validate_argv(item.get("argv"), "verificationCommands.argv")
        parsed.append({"id": command_id, "criterion": criterion, "argv": argv})
    return parsed


def encode_acceptance(criteria: List[str], commands: List[Dict[str, Any]]) -> Dict[str, Any]:
    encoded: Dict[str, Any] = {}
    for criterion, command in zip(criteria, commands):
        encoded[criterion] = {"id": command["id"], "argv": list(command["argv"])}
    return encoded


def verification_commands_for(criteria: Sequence[str], argv: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    command_argv = list(argv) if argv else ["test", "-n", "x"]
    return [
        {"id": "verify-{}".format(index + 1), "criterion": item, "argv": list(command_argv)}
        for index, item in enumerate(criteria)
    ]


def task_from_dict(payload: Dict[str, Any]) -> ControlTask:
    if not isinstance(payload, dict):
        raise TaskValidationError("task payload must be an object")
    unknown = sorted(set(payload) - TASK_FIELDS)
    if unknown:
        raise TaskValidationError("unknown task fields: {}".format(", ".join(unknown)))
    task_id = _required_text(payload.get("id"), "id")
    if not TASK_ID_PATTERN.fullmatch(task_id):
        raise TaskValidationError("id must be an uppercase hyphenated task id")
    try:
        priority = TaskPriority(_required_text(payload.get("priority"), "priority"))
        risk_level = TaskRisk(_required_text(payload.get("riskLevel"), "riskLevel"))
    except ValueError as error:
        raise TaskValidationError(str(error)) from error
    allowed_executors = _string_list(payload.get("allowedExecutors"), "allowedExecutors")
    if any(not EXECUTOR_PATTERN.fullmatch(item) for item in allowed_executors):
        raise TaskValidationError("allowedExecutors must use lowercase executor ids")
    dependencies = _string_list(payload.get("dependencies", []), "dependencies", allow_empty=True)
    if task_id in dependencies:
        raise TaskValidationError("task cannot depend on itself")
    approval_raw = payload.get("approvalClass", ApprovalClass.NONE.value)
    if approval_raw is None:
        approval_raw = ApprovalClass.NONE.value
    try:
        approval_class = ApprovalClass(_required_text(approval_raw, "approvalClass"))
    except ValueError as error:
        raise TaskValidationError(
            "approvalClass must be one of {}".format(", ".join(APPROVAL_CLASS_VALUES))
        ) from error
    owner_ref = payload.get("ownerApprovalRef")
    if owner_ref is not None:
        owner_ref = _required_text(owner_ref, "ownerApprovalRef")
    criteria = _string_list(payload.get("acceptance"), "acceptance")
    commands = parse_verification_commands(payload.get("verificationCommands"), criteria)
    return ControlTask(
        id=task_id,
        project_id=_required_text(payload.get("projectId"), "projectId"),
        title=_required_text(payload.get("title"), "title"),
        objective=_required_text(payload.get("objective"), "objective"),
        scope=_string_list(payload.get("scope"), "scope"),
        acceptance=encode_acceptance(criteria, commands),
        priority=priority,
        risk_level=risk_level,
        allowed_executors=allowed_executors,
        workspace_roots=_string_list(payload.get("workspaceRoots"), "workspaceRoots"),
        dependencies=dependencies,
        source_uri=str(payload["sourceUri"]).strip() if payload.get("sourceUri") else None,
        approval_class=approval_class,
        owner_approval_ref=owner_ref,
    )


def source_fingerprint(task: ControlTask) -> str:
    normalized = json.dumps({
        "project_id": task.project_id,
        "title": task.title,
        "objective": task.objective,
        "scope": task.scope,
        "acceptance": criteria_of(task.acceptance),
        "verificationCommands": verification_commands_of(task.acceptance),
        "priority": task.priority.value,
        "risk_level": task.risk_level.value,
        "allowed_executors": task.allowed_executors,
        "workspace_roots": task.workspace_roots,
        "dependencies": task.dependencies,
        "source_uri": task.source_uri,
        "approval_class": task.approval_class.value,
        "owner_approval_ref": task.owner_approval_ref,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class TaskRegistry:
    def __init__(self, repository: Repository):
        self.repository = repository

    def register(self, task: ControlTask, actor: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        self._validate_task(task)
        return self.repository.register_task(
            task, source_fingerprint(task), _required_text(actor, "actor"), request_id or str(uuid.uuid4())
        )

    def transition(self, task_id: str, to_state: TaskState, expected_version: int, actor: str,
                   reason: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        task = self.repository.get_task(task_id)
        if task is None:
            raise TaskNotFoundError("task is not registered: {}".format(task_id))
        from_state = TaskState(task["state"])
        if to_state not in ALLOWED_TRANSITIONS[from_state]:
            raise IllegalTaskTransitionError("{} cannot transition to {}".format(from_state.value, to_state.value))
        if to_state is TaskState.READY and ready_requires_owner_approval(
            task.get("approval_class") or ApprovalClass.NONE.value, task.get("owner_approval_ref")
        ):
            raise TaskValidationError(
                "ownerApprovalRef is required before READY for approvalClass={}".format(
                    task.get("approval_class") or ApprovalClass.NONE.value
                )
            )
        if to_state is TaskState.READY and not verification_commands_of(task.get("acceptance")):
            raise TaskValidationError("verificationCommands are required before READY")
        if expected_version < 1:
            raise TaskValidationError("expected_version must be positive")
        return self.repository.transition_task(
            task_id, from_state, to_state, expected_version, _required_text(actor, "actor"),
            _required_text(reason, "reason"), request_id or str(uuid.uuid4()),
        )

    def reconstruct_state(self, task_id: str) -> Tuple[TaskState, int]:
        transitions = self.repository.list_task_transitions(task_id)
        if not transitions:
            raise TaskNotFoundError("task has no transition history: {}".format(task_id))
        state: Optional[TaskState] = None
        version = 0
        for transition in transitions:
            if transition["previous_version"] != version:
                raise TaskValidationError("transition history has a version gap")
            expected_from = state.value if state else None
            if transition["from_state"] != expected_from:
                raise TaskValidationError("transition history has a state gap")
            state = TaskState(transition["to_state"])
            version = int(transition["result_version"])
        if state is None:
            raise TaskValidationError("transition history is empty")
        return state, version

    def render_markdown(self, project_id: Optional[str] = None) -> str:
        tasks = self.repository.list_tasks(project_id=project_id, limit=10000)
        lines = [
            "# Chief Task Registry",
            "",
            "> Generated from Chief state. Do not edit this projection by hand.",
            "",
        ]
        for state in TaskState:
            items = [task for task in tasks if task["state"] == state.value]
            lines.extend(["## {}".format(state.value), ""])
            if not items:
                lines.extend(["No tasks.", ""])
                continue
            for task in items:
                lines.extend([
                    "### {} — {}".format(task["id"], task["title"]),
                    "",
                    "- Project: `{}`".format(task["project_id"]),
                    "- Priority: `{}`".format(task["priority"]),
                    "- Risk: `{}`".format(task["risk_level"]),
                    "- Version: `{}`".format(task["version"]),
                    "- Allowed executors: {}".format(", ".join("`{}`".format(item) for item in task["allowed_executors"])),
                    "- Approval: `{}`".format(task.get("approval_class") or ApprovalClass.NONE.value),
                    "- Owner approval: {}".format(
                        "`{}`".format(task["owner_approval_ref"]) if task.get("owner_approval_ref") else "none"
                    ),
                    "- Dependencies: {}".format(", ".join("`{}`".format(item) for item in task["dependencies"]) or "none"),
                    "",
                    "Objective: {}".format(task["objective"]),
                    "",
                    "Scope:",
                    "",
                ])
                lines.extend("- {}".format(item) for item in task["scope"])
                lines.extend(["", "Acceptance:", ""])
                lines.extend("- {}".format(item) for item in criteria_of(task.get("acceptance")))
                commands = verification_commands_of(task.get("acceptance"))
                if commands:
                    lines.extend(["", "Verification:", ""])
                    lines.extend(
                        "- `{}`: `{}`".format(item["id"], " ".join(item["argv"]))
                        for item in commands
                    )
                lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def render_to_file(self, output: Path, project_id: Optional[str] = None) -> None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.render_markdown(project_id), encoding="utf-8")

    def _validate_task(self, task: ControlTask) -> None:
        criteria = criteria_of(task.acceptance)
        commands = verification_commands_of(task.acceptance)
        payload = {
            "id": task.id,
            "projectId": task.project_id,
            "title": task.title,
            "objective": task.objective,
            "scope": task.scope,
            "acceptance": criteria,
            "priority": task.priority.value,
            "riskLevel": task.risk_level.value,
            "allowedExecutors": task.allowed_executors,
            "workspaceRoots": task.workspace_roots,
            "dependencies": task.dependencies,
            "sourceUri": task.source_uri,
            "approvalClass": task.approval_class.value,
            "verificationCommands": commands,
        }
        if task.owner_approval_ref:
            payload["ownerApprovalRef"] = task.owner_approval_ref
        if not commands:
            raise TaskValidationError("verificationCommands is required")
        task_from_dict(payload)
