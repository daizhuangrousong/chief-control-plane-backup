"""Chief-authored review decisions. Identity comes from the inbox file, not caller strings."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Set

from .task_registry import TASK_ID_PATTERN, TaskValidationError, _required_text


DECISION_VERSION = "chief-review-decision/1.0.0"
DECISION_FIELDS = {"schemaVersion", "taskId", "taskVersion", "commitRef", "leaseId", "outcome", "actor", "reasons"}
OUTCOMES = {"approve_merge", "reject"}
CHIEF_ACTORS = {"chief"}
CONSUMED_VERSION = "chief-review-consumed/1.0.0"


class ChiefReviewDecisionError(TaskValidationError):
    pass


def parse_review_decision(payload: Any, allowed_actors: Set[str] = None) -> Dict[str, Any]:
    allowed_actors = allowed_actors or CHIEF_ACTORS
    if not isinstance(payload, dict):
        raise ChiefReviewDecisionError("review decision must be an object")
    unknown = sorted(set(payload) - DECISION_FIELDS)
    if unknown:
        raise ChiefReviewDecisionError("unknown review decision fields: {}".format(", ".join(unknown)))
    missing = sorted(DECISION_FIELDS - set(payload))
    if missing:
        raise ChiefReviewDecisionError("review decision missing fields: {}".format(", ".join(missing)))
    if payload["schemaVersion"] != DECISION_VERSION:
        raise ChiefReviewDecisionError("unsupported review decision schemaVersion")
    actor = _required_text(payload["actor"], "actor")
    if actor not in allowed_actors:
        raise ChiefReviewDecisionError("review decision actor is not authorized")
    outcome = _required_text(payload["outcome"], "outcome")
    if outcome not in OUTCOMES:
        raise ChiefReviewDecisionError("review decision outcome is not allowed")
    reasons = payload["reasons"]
    if not isinstance(reasons, list) or not reasons or any(not str(item).strip() for item in reasons):
        raise ChiefReviewDecisionError("reasons must be a non-empty string list")
    version = payload["taskVersion"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ChiefReviewDecisionError("taskVersion must be a positive integer")
    return {
        "schemaVersion": DECISION_VERSION,
        "taskId": _required_text(payload["taskId"], "taskId"),
        "taskVersion": version,
        "commitRef": _required_text(payload["commitRef"], "commitRef").lower(),
        "leaseId": _required_text(payload["leaseId"], "leaseId"),
        "outcome": outcome,
        "actor": actor,
        "reasons": [str(item).strip() for item in reasons],
    }


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".chief-review-", suffix=".tmp", dir=str(path.parent))
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


class ChiefReviewInbox:
    """Chief-only review inbox. Must sit on the runtime control side, never a task tree."""

    def __init__(self, path: Path, runtime_root: Path, project_root: Path, pool_root: Path):
        from .task_worktree import assert_control_path

        self.path = assert_control_path(
            Path(path), "chief review inbox", runtime_root, project_root, pool_root,
        )

    def decision_path(self, task_id: str) -> Path:
        return self.path / "{}.json".format(task_id)

    def consumed_path(self, task_id: str) -> Path:
        return self.path / "{}.consumed.json".format(task_id)

    def drop(self, decision: Dict[str, Any]) -> Path:
        parsed = parse_review_decision(decision)
        path = self.decision_path(parsed["taskId"])
        _atomic_write_json(path, parsed)
        return path

    def is_consumed(self, task_id: str) -> bool:
        return self.consumed_path(task_id).exists()

    def read(self, task_id: str) -> Dict[str, Any]:
        if not TASK_ID_PATTERN.fullmatch(task_id or ""):
            raise ChiefReviewDecisionError("task id is invalid")
        path = self.decision_path(task_id)
        if path.is_symlink() or not path.is_file():
            raise ChiefReviewDecisionError("review decision is missing from the Chief inbox")
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ChiefReviewDecisionError("review decision is unreadable") from error
        parsed = parse_review_decision(payload)
        if parsed["taskId"] != task_id:
            raise ChiefReviewDecisionError("review decision taskId mismatch")
        parsed["sourceHash"] = hashlib.sha256(raw).hexdigest()
        if self.is_consumed(task_id):
            try:
                sidecar = json.loads(self.consumed_path(task_id).read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ChiefReviewDecisionError("review consume sidecar is unreadable") from error
            if not isinstance(sidecar, dict) or sidecar.get("sourceHash") != parsed["sourceHash"]:
                raise ChiefReviewDecisionError("review consume sidecar does not match the decision")
            parsed["consumed"] = True
        else:
            parsed["consumed"] = False
        return parsed

    def load(self, task_id: str) -> Dict[str, Any]:
        parsed = self.read(task_id)
        if parsed.get("consumed"):
            raise ChiefReviewDecisionError("review decision already consumed")
        return parsed

    def consume(self, task_id: str, source_hash: str) -> None:
        parsed = self.read(task_id)
        if parsed.get("sourceHash") != source_hash:
            raise ChiefReviewDecisionError("review decision changed before consume")
        if parsed.get("consumed"):
            return
        _atomic_write_json(self.consumed_path(task_id), {
            "schemaVersion": CONSUMED_VERSION,
            "taskId": task_id,
            "sourceHash": source_hash,
        })
