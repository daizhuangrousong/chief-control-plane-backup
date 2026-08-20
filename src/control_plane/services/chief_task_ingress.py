"""Chief file ingress: outbox JSON envelopes into TaskRegistry + policy, inbox receipts out.

No direct SQL, no second queue, and this module never starts Cursor.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..adapters.git import git_at_root
from ..config import ProjectConfig
from ..domain.models import ControlTask, DecisionFacts, TaskState
from ..storage.repository import DuplicateTaskError, Repository
from .cursor_runner import redact_secrets
from .decision_policy import DecisionPolicyEngine, decision_facts_from_dict
from .dispatcher import LeaseDispatcher
from .project_isolation import ISOLATED_PROJECT_IDS
from .task_registry import (
    ALLOWED_TRANSITIONS, TASK_ID_PATTERN, TaskRegistry, TaskValidationError, source_fingerprint, task_from_dict,
)


ENVELOPE_VERSION = "chief-task-envelope/1.0.0"
RECEIPT_VERSION = "chief-task-receipt/1.0.0"
ENVELOPE_FIELDS = {"schemaVersion", "task", "facts"}
DEFAULT_MAX_BYTES = 262144
DEFAULT_PROJECTS = ("control-panel",)


class ChiefTaskIngressError(TaskValidationError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path = Path(path)
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ChiefTaskIngressError("inbox path must be a regular file or absent")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".chief-task-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def file_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_outbox_bytes(outbox: Path, path: Path, max_bytes: int = DEFAULT_MAX_BYTES) -> bytes:
    outbox_root = Path(outbox).resolve()
    candidate = Path(path)
    if candidate.name.startswith(".") or not candidate.name.endswith(".json"):
        raise ChiefTaskIngressError("outbox entries must be unsuffixed *.json files")
    try:
        info = candidate.lstat()
    except OSError as error:
        raise ChiefTaskIngressError("outbox file is unreadable") from error
    if stat.S_ISLNK(info.st_mode):
        raise ChiefTaskIngressError("symlink is not allowed")
    if not stat.S_ISREG(info.st_mode):
        raise ChiefTaskIngressError("outbox path must be a regular file")
    if info.st_size > max_bytes:
        raise ChiefTaskIngressError("file exceeds maxBytes")
    if not _within(candidate, outbox_root):
        raise ChiefTaskIngressError("path is outside the outbox")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(candidate, flags)
    except OSError as error:
        raise ChiefTaskIngressError("outbox file is unreadable") from error
    try:
        payload = os.read(fd, max_bytes + 1)
    finally:
        os.close(fd)
    if len(payload) > max_bytes:
        raise ChiefTaskIngressError("file exceeds maxBytes")
    return payload


def parse_envelope(payload: bytes) -> Dict[str, Any]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ChiefTaskIngressError("envelope must be UTF-8 JSON") from error
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ChiefTaskIngressError("truncated or invalid JSON") from error
    if not isinstance(parsed, dict):
        raise ChiefTaskIngressError("envelope must be an object")
    unknown = sorted(set(parsed) - ENVELOPE_FIELDS)
    if unknown:
        raise ChiefTaskIngressError("unknown envelope fields: {}".format(", ".join(unknown)))
    missing = sorted(ENVELOPE_FIELDS - set(parsed))
    if missing:
        raise ChiefTaskIngressError("envelope missing fields: {}".format(", ".join(missing)))
    if parsed["schemaVersion"] != ENVELOPE_VERSION:
        raise ChiefTaskIngressError("unsupported schemaVersion")
    if not isinstance(parsed["task"], dict) or not isinstance(parsed["facts"], dict):
        raise ChiefTaskIngressError("task and facts must be objects")
    task = task_from_dict(parsed["task"])
    facts = decision_facts_from_dict(parsed["facts"])
    return {"task": task, "facts": facts, "sourceHash": file_sha256(payload)}


def bind_decision_facts(task: ControlTask, facts: DecisionFacts, project: ProjectConfig) -> DecisionFacts:
    project_root = project.root.resolve()
    workspace_ok = True
    for raw in task.workspace_roots:
        try:
            resolved = Path(raw).expanduser().resolve()
            resolved.relative_to(project_root)
            if not resolved.is_dir():
                workspace_ok = False
        except (ValueError, OSError):
            workspace_ok = False
    baseline_known = False
    if workspace_ok and task.workspace_roots:
        head = git_at_root(Path(task.workspace_roots[0]).expanduser().resolve(), "rev-parse", "HEAD")
        baseline_known = bool(head)
    return DecisionFacts(
        architecture_change=facts.architecture_change,
        production_change=facts.production_change,
        permission_change=facts.permission_change,
        external_communication=facts.external_communication,
        paid_action=facts.paid_action,
        destructive_action=facts.destructive_action,
        release_action=facts.release_action,
        scope_expansion=facts.scope_expansion,
        safety_evidence_complete=facts.safety_evidence_complete,
        baseline_known=bool(facts.baseline_known and baseline_known),
        workspace_authorized=bool(facts.workspace_authorized and workspace_ok),
        acceptance_complete=bool(facts.acceptance_complete and task.acceptance),
        model_advisory=facts.model_advisory,
    )


def short_receipt(
    task_id: str,
    source_hash: Optional[str],
    task_version: Optional[int],
    state: str,
    matched_rules: Sequence[str],
    error: Optional[str] = None,
    lease_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "schemaVersion": RECEIPT_VERSION,
        "taskId": task_id,
        "sourceHash": source_hash,
        "taskVersion": task_version,
        "state": state,
        "matchedRules": list(matched_rules),
        "observedAt": _utc_now(),
        "leaseId": lease_id,
        "error": redact_secrets(error) if error else None,
    }


class ChiefTaskReporter:
    """Read-only inbox publisher. Never transitions REVIEW to DONE."""

    def __init__(self, repository: Repository, inbox: Path, dispatcher: Optional[LeaseDispatcher] = None):
        self.repository = repository
        self.inbox = Path(inbox)
        self.dispatcher = dispatcher

    def receipt_path(self, task_id: str) -> Path:
        return self.inbox / "{}.json".format(task_id)

    def publish_task(
        self,
        task_id: str,
        source_hash: Optional[str] = None,
        matched_rules: Optional[Sequence[str]] = None,
        error: Optional[str] = None,
        lease_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        task = self.repository.get_task(task_id)
        previous = self._previous(task_id)
        if task is None:
            receipt = short_receipt(
                task_id,
                source_hash or (previous or {}).get("sourceHash"),
                None,
                "BLOCKED",
                [],
                error or "task is not registered",
                lease_id or (previous or {}).get("leaseId"),
            )
            atomic_write_json(self.receipt_path(task_id), receipt)
            return receipt
        active_lease = None
        if self.dispatcher is not None:
            active = self.dispatcher.active_lease_for_project(task["project_id"])
            if active and active.get("task_id") == task_id:
                active_lease = active.get("lease_id")
        receipt = short_receipt(
            task_id,
            source_hash or (previous or {}).get("sourceHash"),
            int(task["version"]),
            task["state"],
            matched_rules if matched_rules is not None else (previous or {}).get("matchedRules") or [],
            error,
            lease_id or active_lease or (previous or {}).get("leaseId"),
        )
        atomic_write_json(self.receipt_path(task_id), receipt)
        return receipt

    def report_cycle(self, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        task_id = result.get("task_id")
        if not task_id:
            return None
        error = result.get("error") if result.get("status") in {"rejected", "failed", "halted"} else None
        return self.publish_task(str(task_id), lease_id=result.get("lease_id"), error=error)

    def _previous(self, task_id: str) -> Optional[Dict[str, Any]]:
        path = self.receipt_path(task_id)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise ChiefTaskIngressError("inbox receipt must be a regular file")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        return payload if isinstance(payload, dict) else None


class ChiefTaskImporter:
    """Watch complete outbox files, register DRAFT, run DecisionPolicyEngine, write inbox."""

    def __init__(
        self,
        repository: Repository,
        outbox: Path,
        inbox: Path,
        projects: Iterable[ProjectConfig],
        allowed_projects: Sequence[str] = DEFAULT_PROJECTS,
        max_bytes: int = DEFAULT_MAX_BYTES,
        actor: str = "chief-task-ingress",
        dispatcher: Optional[LeaseDispatcher] = None,
    ):
        self.repository = repository
        self.registry = TaskRegistry(repository)
        self.policy = DecisionPolicyEngine(repository)
        self.outbox = Path(outbox)
        self.inbox = Path(inbox)
        self.reporter = ChiefTaskReporter(repository, self.inbox, dispatcher=dispatcher)
        self.projects = {project.id: project for project in projects}
        self.allowed_projects = tuple(allowed_projects)
        self.max_bytes = max_bytes
        self.actor = actor
        self.outbox.mkdir(parents=True, exist_ok=True)
        self.inbox.mkdir(parents=True, exist_ok=True)

    def ingest_once(self) -> List[Dict[str, Any]]:
        receipts = []
        for path in self._outbox_candidates():
            receipts.append(self.ingest_file(path))
        return receipts

    def ingest_file(self, path: Path) -> Dict[str, Any]:
        path = Path(path)
        task_id = path.name[:-5] if path.name.endswith(".json") else path.name
        try:
            payload = read_outbox_bytes(self.outbox, path, self.max_bytes)
            parsed = parse_envelope(payload)
        except TaskValidationError as error:
            return self._blocked_file(task_id, None, error)
        task: ControlTask = parsed["task"]
        source_hash = parsed["sourceHash"]
        if path.name != "{}.json".format(task.id):
            return self._blocked_file(task.id, source_hash, ChiefTaskIngressError("filename must match task id"))
        try:
            return self._ingest_task(task, parsed["facts"], source_hash)
        except TaskValidationError as error:
            return self._blocked_file(task.id, source_hash, error)

    def _ingest_task(self, task: ControlTask, facts: DecisionFacts, source_hash: str) -> Dict[str, Any]:
        if task.project_id in ISOLATED_PROJECT_IDS:
            raise ChiefTaskIngressError("project is isolated from Chief task ingress")
        if task.project_id not in self.allowed_projects:
            raise ChiefTaskIngressError("project is not allowed for Chief task ingress")
        project = self.projects.get(task.project_id)
        if project is None:
            raise ChiefTaskIngressError("project is not registered: {}".format(task.project_id))
        bound_facts = bind_decision_facts(task, facts, project)
        existing = self.repository.get_task(task.id)
        fingerprint = source_fingerprint(task)
        if existing is not None:
            if existing.get("source_fingerprint") != fingerprint:
                return self._conflict_existing(existing, source_hash)
            return self._idempotent_existing(existing, source_hash, bound_facts)
        try:
            registered = self.registry.register(task, self.actor, request_id="ingress-{}-register".format(source_hash))
        except DuplicateTaskError:
            existing = self.repository.get_task(task.id)
            if existing is None:
                raise ChiefTaskIngressError("source fingerprint already exists for another task")
            if existing.get("source_fingerprint") != fingerprint:
                return self._conflict_existing(existing, source_hash)
            return self._idempotent_existing(existing, source_hash, bound_facts)
        return self._decide_and_receipt(registered, bound_facts, source_hash)

    def _conflict_existing(self, existing: Dict[str, Any], source_hash: str) -> Dict[str, Any]:
        state = TaskState(existing["state"])
        if TaskState.BLOCKED in ALLOWED_TRANSITIONS.get(state, set()):
            existing = self.registry.transition(
                existing["id"], TaskState.BLOCKED, int(existing["version"]), self.actor,
                "duplicate id with different content",
                request_id="ingress-{}-conflict".format(source_hash),
            )
        return self.reporter.publish_task(
            existing["id"],
            source_hash=source_hash,
            matched_rules=["block.duplicate_id_conflict"],
            error="duplicate id with different content",
        )

    def _idempotent_existing(
        self, existing: Dict[str, Any], source_hash: str, facts: DecisionFacts,
    ) -> Dict[str, Any]:
        if TaskState(existing["state"]) is TaskState.DRAFT:
            return self._decide_and_receipt(existing, facts, source_hash)
        decisions = self.repository.list_task_decisions(existing["id"], limit=1)
        matched = decisions[0]["matched_rules"] if decisions else []
        return self.reporter.publish_task(existing["id"], source_hash=source_hash, matched_rules=matched)

    def _decide_and_receipt(
        self, task_row: Dict[str, Any], facts: DecisionFacts, source_hash: str,
    ) -> Dict[str, Any]:
        result = self.policy.decide(
            task_row["id"], facts, int(task_row["version"]), self.actor,
            request_id="ingress-{}-decide".format(source_hash),
        )
        decided = result.get("task") or self.repository.get_task(task_row["id"])
        if decided is None:
            raise ChiefTaskIngressError("task disappeared after policy decision")
        matched = (result.get("decision") or {}).get("matched_rules") or []
        return self.reporter.publish_task(
            decided["id"],
            source_hash=source_hash,
            matched_rules=matched,
        )

    def _blocked_file(self, task_id: str, source_hash: Optional[str], error: Exception) -> Dict[str, Any]:
        safe_id = task_id if TASK_ID_PATTERN.fullmatch(task_id or "") else "TASK-INVALID-INGRESS"
        receipt = short_receipt(
            safe_id, source_hash, None, TaskState.BLOCKED.value, ["block.illegal_input"],
            str(error),
        )
        atomic_write_json(self.reporter.receipt_path(safe_id), receipt)
        return receipt

    def _outbox_candidates(self) -> List[Path]:
        if not self.outbox.is_dir():
            return []
        entries = []
        for item in sorted(self.outbox.iterdir()):
            if item.name.startswith(".") or not item.name.endswith(".json"):
                continue
            entries.append(item)
        return entries


def load_ingress_config(path: str) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ChiefTaskIngressError("ingress config must be an object")
    allowed = {"outboxDir", "inboxDir", "allowedProjects", "maxBytes"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ChiefTaskIngressError("unknown ingress config fields: {}".format(", ".join(unknown)))
    return payload
