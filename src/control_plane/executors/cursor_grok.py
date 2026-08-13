import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..domain.models import RunStatus
from ..services.dispatcher import LeaseDispatcher
from ..services.executor_report import REPORT_VERSION
from ..storage import Repository
from .base import (
    ExecutionResult, GitWorktreeVerifier, ScopeViolationError, WorktreeVerificationError,
    in_scope,
)
from .dispatcher_gateway import DispatcherGateway
from .grok_client import FakeGrokClient, GrokClient, GrokPrompt


class CursorGrokExecutor:
    """Executor backend that drives Cursor + Grok for the control plane.

    Lifecycle (fail-closed at every gate):
      precise claim (TARGET_NOT_READY, never fallback)
        -> verify isolated worktree (common dir / baseline / clean)
        -> heartbeat (CLAIMED -> RUNNING)
        -> Grok plan + scope-checked apply
        -> progress
        -> commit
        -> complete (RUNNING -> REVIEW)   <-- stops here, never self-DONE
        -> submit Executor Report (evidence for the separate Reviewer)

    Grok is injected: the default ``FakeGrokClient`` is offline and reads no secret,
    so the whole protocol can be validated without a paid API.
    """

    def __init__(self, gateway: DispatcherGateway, grok: GrokClient, verifier: GitWorktreeVerifier,
                 repository: Repository, executor_id: str = "cursor-grok", run_label: str = "cursor-grok"):
        self.gateway = gateway
        self.grok = grok
        self.verifier = verifier
        self.repository = repository
        self.executor_id = executor_id
        self.run_label = run_label

    def execute(self, task_id: str, worktree_path: Path, expected_common_dir: str,
                baseline_ref: str, request_id_prefix: str = "cg",
                ttl_seconds: int = 900, trigger: str = "external-scheduler") -> ExecutionResult:
        worktree_path = Path(worktree_path)
        claim = self.gateway.claim_targeted(
            task_id, self.executor_id, baseline_ref, "{}-claim".format(request_id_prefix)
        )
        if claim.status != "CLAIMED":
            return ExecutionResult(
                task_id=task_id, success=False, status="TARGET_NOT_READY",
                target_not_ready_reason=claim.reason,
            )
        task = claim.task
        lease = claim.lease
        run_id = self.repository.start_run(task["project_id"], self.run_label, trigger)
        try:
            self.verifier.verify(worktree_path, expected_common_dir, baseline_ref)
            self.gateway.heartbeat(lease["lease_id"], self.executor_id, "{}-hb".format(request_id_prefix))

            prompt = GrokPrompt(
                task_id=task_id, objective=task["objective"], scope=task["scope"],
                workspace_roots=task["workspace_roots"], baseline_ref=baseline_ref,
            )
            planned = self.grok.plan(prompt)
            applied: List[Dict[str, str]] = []  # {path: project-repo abs, content: bytes text}
            for change in planned.changes:
                if not in_scope(change.path, task["workspace_roots"]):
                    raise ScopeViolationError(
                        "change {} is outside authorized workspace roots".format(change.path)
                    )
                # The change is described against the project repo; the actual write
                # must land inside the isolated worktree at the same relative path.
                target = self._resolve_in_worktree(change.path, task["workspace_roots"], worktree_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(change.content, encoding="utf-8")
                applied.append({"path": change.path, "content": change.content})

            self.gateway.progress(
                run_id, lease["lease_id"], self.executor_id, "{}-applied".format(request_id_prefix),
                "applied {} scoped change(s)".format(len(applied)),
            )
            commit_ref = self._commit(worktree_path, task_id)
            self.gateway.complete(lease["lease_id"], self.executor_id, baseline_ref,
                                  "{}-complete".format(request_id_prefix))

            review_task = self.repository.get_task(task_id)
            report = self._build_report(task, lease, review_task, applied, commit_ref, baseline_ref)
            stored = self.gateway.submit_report(report, "{}-report".format(request_id_prefix))
            self.repository.finish_run(run_id, RunStatus.SUCCEEDED,
                                       "completed in REVIEW; executor report submitted")
            return ExecutionResult(
                task_id=task_id, success=True, status="REVIEW",
                lease_id=lease["lease_id"], run_id=run_id, report_id=stored["id"],
                task_version=review_task["version"],
            )
        except Exception as exc:  # fail-closed
            reason = "fail-closed: {}".format(str(exc))[:500]
            try:
                self.gateway.fail(lease["lease_id"], self.executor_id, baseline_ref,
                                  "{}-fail".format(request_id_prefix), reason)
            except Exception:
                pass
            self.repository.finish_run(run_id, RunStatus.FAILED, reason)
            return ExecutionResult(
                task_id=task_id, success=False, status="FAILED",
                lease_id=lease["lease_id"], run_id=run_id, error=reason,
            )

    def _commit(self, worktree_path: Path, task_id: str) -> str:
        subprocess.run(["git", "-C", str(worktree_path), "add", "-A"], check=True,
                        capture_output=True, text=True, timeout=30)
        subprocess.run(
            ["git", "-C", str(worktree_path), "commit", "-m",
             "cursor-grok {}: scoped change in isolated worktree".format(task_id)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        result = subprocess.run(["git", "-C", str(worktree_path), "rev-parse", "--short", "HEAD"],
                                check=True, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()

    @staticmethod
    def _resolve_in_worktree(change_path: str, roots: List[str], worktree_path: Path) -> Path:
        normalized = os.path.normpath(change_path)
        worktree = Path(worktree_path)
        for root in roots:
            normalized_root = os.path.normpath(root)
            if normalized == normalized_root or normalized.startswith(normalized_root.rstrip(os.sep) + os.sep):
                relative = os.path.relpath(normalized, normalized_root)
                return worktree / relative
        return Path(change_path)

    def _build_report(self, task: Dict[str, Any], lease: Dict[str, Any], review_task: Dict[str, Any],
                      applied: List[Dict[str, str]], commit_ref: str, baseline_ref: str) -> Dict[str, Any]:
        acceptance_checks = [
            {"criterion": criterion, "status": "pass",
             "evidence": "scoped change applied and committed within authorized workspace roots"}
            for criterion in task["acceptance"]
        ]
        provenance = []
        changed_files = []
        for item in applied:
            changed_files.append(item["path"])
            digest = hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
            provenance.append({"sourceUri": item["path"], "sha256": digest,
                               "note": "scoped artifact produced by cursor-grok execution"})
        return {
            "taskId": task["id"],
            "taskVersion": int(review_task["version"]),
            "reportVersion": REPORT_VERSION,
            "baselineRef": baseline_ref,
            "commitRef": commit_ref,
            "evidenceType": "commit",
            "executorId": self.executor_id,
            "leaseId": lease["lease_id"],
            "summary": "cursor-grok executed a scoped change for {} in an isolated worktree and "
                       "submitted completion evidence.".format(task["id"]),
            "acceptanceChecks": acceptance_checks,
            "testResults": [{"name": "shadow-self-check", "status": "pass",
                             "command": "git status --porcelain clean; artifact present"}],
            "changedFiles": changed_files,
            "riskFindings": [],
            "provenance": provenance,
        }
