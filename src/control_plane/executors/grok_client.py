import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class GrokPrompt:
    task_id: str
    objective: str
    scope: List[str]
    workspace_roots: List[str]
    baseline_ref: str


@dataclass(frozen=True)
class PlannedChange:
    path: str          # absolute path, MUST lie inside one of the workspace roots
    content: str
    rationale: str


@dataclass(frozen=True)
class GrokResult:
    changes: List[PlannedChange]
    summary: str


class GrokClient(ABC):
    """Execution backend that turns a task prompt into a scoped set of file changes.

    Implementations must be injectable so the control plane can be validated without
    touching any paid API. A real ``PaidGrokClient`` would read its credential from an
    environment variable at call time and would be the ONLY place a network call happens;
    it is intentionally NOT shipped here so no token/cookie/key is ever read or logged.
    """

    @abstractmethod
    def plan(self, prompt: GrokPrompt) -> GrokResult:
        ...


class FakeGrokClient(GrokClient):
    """Deterministic, offline stand-in for Grok.

    Produces exactly one in-scope artifact under the first authorized workspace root.
    Used for protocol validation and the low-risk Shadow run. Never contacts a network
    and never reads any secret.
    """

    def __init__(self, artifact_name: str = "cp-shadow-artifact.md"):
        self.artifact_name = artifact_name

    def plan(self, prompt: GrokPrompt) -> GrokResult:
        root = prompt.workspace_roots[0] if prompt.workspace_roots else "/tmp"
        path = os.path.join(os.path.normpath(root), self.artifact_name)
        content = (
            "# cursor-grok execution artifact\n\n"
            "task: {task_id}\n"
            "baseline: {baseline}\n"
            "objective: {objective}\n\n"
            "This file is the only artifact produced by the offline FakeGrokClient during\n"
            "protocol validation. It is scoped to the task's authorized workspace root.\n"
        ).format(task_id=prompt.task_id, baseline=prompt.baseline_ref, objective=prompt.objective)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        return GrokResult(
            changes=[PlannedChange(path=path, content=content, rationale="shadow scoped artifact " + digest)],
            summary="proposed one scoped artifact inside the authorized workspace root",
        )
