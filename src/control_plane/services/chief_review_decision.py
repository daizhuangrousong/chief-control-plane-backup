"""Chief-authored review decisions. Executors cannot write or self-approve these."""

from __future__ import annotations

from typing import Any, Dict, Set

from .task_registry import TaskValidationError, _required_text


DECISION_VERSION = "chief-review-decision/1.0.0"
DECISION_FIELDS = {"schemaVersion", "taskId", "taskVersion", "commitRef", "leaseId", "outcome", "actor", "reasons"}
OUTCOMES = {"approve_merge", "reject"}
CHIEF_ACTORS = {"chief"}


class ChiefReviewDecisionError(TaskValidationError):
    pass


def parse_review_decision(payload: Any, allowed_actors: Set[str] = CHIEF_ACTORS) -> Dict[str, Any]:
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
