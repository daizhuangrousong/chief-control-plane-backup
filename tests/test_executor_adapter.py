import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from control_plane.config import ProjectConfig
from control_plane.domain.models import AgentType, RunStatus, TaskState
from control_plane.executors import (
    CursorGrokExecutor, DispatcherGateway, FakeGrokClient, GrokClient, GrokPrompt, GrokResult,
    PlannedChange, ScopeViolationError, TARGET_NOT_READY, WorktreeVerificationError,
    build_cursor_grok_executor,
)
from control_plane.services import (
    BaselineConflictError, ExecutorUnauthorizedError, LeaseConflictError, LeaseDispatcher,
    ReviewGate, TaskRegistry, task_from_dict,
)
from control_plane.storage import Repository


def make_git_repo(path: Path) -> str:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.local"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "tester"], check=True)
    (path / "README.md").write_text("baseline root\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "baseline"], check=True)
    return subprocess.run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


class CursorGrokExecutorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repository = Repository(self.root / "control.sqlite3")
        self.repository.migrate()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.baseline = make_git_repo(self.repo)
        self.common_dir = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "--absolute-git-dir"],
            capture_output=True, text=True,
        ).stdout.strip()
        self.registry = TaskRegistry(self.repository)
        self.dispatcher = LeaseDispatcher(self.repository, default_ttl_seconds=60)
        self.gateway = DispatcherGateway(self.dispatcher, self.repository)
        self.registry  # keep reference
        self.repository.upsert_project(ProjectConfig(
            id="cp-shadow", name="cp-shadow", kind="control_plane", owner="Owner",
            root=self.repo, ledger=self.root / "TASKS.md", status=self.root / "STATE.md",
            knowledge_roots=[], enabled_agents=list(AgentType),
        ))
        self.dispatcher.register_executor("cursor-grok", ["cp-shadow"], "low")
        self.dispatcher.set_project_baseline("cp-shadow", self.baseline, "planner")

    def tearDown(self):
        self.temp.cleanup()

    def ready_task(self, task_id="TASK-CG", executors=None, project="cp-shadow",
                   workspace_roots=None, acceptance=None):
        payload = {
            "id": task_id, "projectId": project, "title": task_id, "objective": "Execute safely",
            "scope": ["Scoped work inside the authorized root"],
            "acceptance": acceptance or ["Artifact file exists", "Change stays within workspace roots"],
            "priority": "P3", "riskLevel": "low",
            "allowedExecutors": executors or ["cursor-grok"],
            "workspaceRoots": workspace_roots or [str(self.repo)],
            "dependencies": [],
        }
        task = self.registry.register(task_from_dict(payload), "planner")
        return self.registry.transition(task_id, TaskState.READY, task["version"], "policy", "safe")

    def make_worktree(self, name="wt") -> Path:
        wt = self.root / name
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-q", str(wt),
                        "-b", name], check=True)
        return wt

    def executor(self, grok=None) -> CursorGrokExecutor:
        return build_cursor_grok_executor(self.repository, executor_id="cursor-grok", grok=grok)

    # ---- positive: full DRAFT -> READY -> CLAIMED -> RUNNING -> REVIEW -> DONE ----
    def test_full_happy_path_reaches_review_then_reviewer_dones(self):
        task = self.ready_task("TASK-HAPPY")
        wt = self.make_worktree("wt-happy")
        result = self.executor().execute(
            "TASK-HAPPY", wt, self.common_dir, self.baseline, "happy",
        )
        self.assertTrue(result.success)
        self.assertEqual(result.status, "REVIEW")
        self.assertIsNotNone(result.lease_id)
        self.assertIsNotNone(result.run_id)
        self.assertIsNotNone(result.report_id)
        db_task = self.repository.get_task("TASK-HAPPY")
        self.assertEqual(db_task["state"], "REVIEW")

        # Separate Reviewer (ReviewGate) performs the only DONE transition.
        report = self.repository.get_executor_report(result.report_id)["report"]
        review = ReviewGate(self.repository).review(report, "codex-review", "review-happy")
        self.assertEqual(review["review"]["outcome"], "DONE")
        self.assertEqual(self.repository.get_task("TASK-HAPPY")["state"], "DONE")

    # ---- negative 1: wrong executor cannot claim, and no fallback to another READY ----
    def test_wrong_executor_cannot_claim_and_does_not_fallback(self):
        self.ready_task("TASK-OTHER", executors=["cursor-grok"])
        self.ready_task("TASK-WRONG", executors=["workbuddy-hy3"])
        with self.assertRaises(ExecutorUnauthorizedError):
            self.gateway.claim_targeted("TASK-WRONG", "cursor-grok", self.baseline, "req-wrong")
        # The eligible READY task must remain untouched (no fallback claim happened).
        other = self.repository.get_task("TASK-OTHER")
        self.assertEqual(other["state"], "READY")
        leases = self.repository.connect().execute(
            "SELECT * FROM task_lease WHERE task_id='TASK-OTHER' AND status='active'"
        ).fetchall()
        self.assertEqual(len(leases), 0)

    # ---- negative 2: non-existent targeted task returns TARGET_NOT_READY, no fallback ----
    def test_missing_targeted_task_returns_target_not_ready_without_fallback(self):
        self.ready_task("TASK-REAL", executors=["cursor-grok"])
        outcome = self.gateway.claim_targeted("GHOST-TASK", "cursor-grok", self.baseline, "req-ghost")
        self.assertEqual(outcome.status, TARGET_NOT_READY)
        self.assertIn("task not found", outcome.reason)
        real = self.repository.get_task("TASK-REAL")
        self.assertEqual(real["state"], "READY")
        leases = self.repository.connect().execute(
            "SELECT * FROM task_lease WHERE status='active'"
        ).fetchall()
        self.assertEqual(len(leases), 0)

    # ---- negative 3: baseline mismatch must not execute (claim-time + worktree drift) ----
    def test_baseline_mismatch_at_claim_is_rejected(self):
        self.ready_task("TASK-BASE")
        with self.assertRaises(BaselineConflictError):
            self.gateway.claim_targeted("TASK-BASE", "cursor-grok", "deadbeef", "req-base")

    def test_worktree_baseline_drift_fails_closed(self):
        self.ready_task("TASK-DRIFT")
        wt = self.make_worktree("wt-drift")
        # Introduce drift: move the worktree HEAD away from the registered baseline.
        subprocess.run(["git", "-C", str(wt), "commit", "-q", "--allow-empty", "-m", "drift"],
                       check=True)
        result = self.executor().execute("TASK-DRIFT", wt, self.common_dir, self.baseline, "drift")
        self.assertFalse(result.success)
        self.assertEqual(self.repository.get_task("TASK-DRIFT")["state"], "FAILED")

    # ---- negative 4: out-of-scope file is blocked (fail-closed, nothing written) ----
    def test_out_of_scope_change_is_blocked(self):
        self.ready_task("TASK-SCOPE")

        class EscapedGrok(GrokClient):
            def plan(self, prompt: GrokPrompt) -> GrokResult:
                return GrokResult(
                    changes=[PlannedChange(path="/etc/passwd", content="x", rationale="escape")],
                    summary="evil",
                )

        wt = self.make_worktree("wt-scope")
        result = self.executor(grok=EscapedGrok()).execute(
            "TASK-SCOPE", wt, self.common_dir, self.baseline, "scope",
        )
        self.assertFalse(result.success)
        self.assertEqual(self.repository.get_task("TASK-SCOPE")["state"], "FAILED")
        self.assertNotEqual(Path("/etc/passwd").read_text().strip(), "x")

    # ---- negative 5: duplicate complete and report are idempotent ----
    def test_duplicate_complete_and_report_are_idempotent(self):
        task = self.ready_task("TASK-IDEM")
        lease = self.dispatcher.claim(task["id"], "cursor-grok", self.baseline, task["version"], "claim-idem")
        self.dispatcher.heartbeat(lease["lease_id"], "cursor-grok", "hb-idem")
        first = self.dispatcher.complete(lease["lease_id"], "cursor-grok", self.baseline, "complete-idem")
        second = self.dispatcher.complete(lease["lease_id"], "cursor-grok", self.baseline, "complete-idem")
        self.assertEqual(first, second)
        self.assertEqual(self.repository.get_task("TASK-IDEM")["state"], "REVIEW")

        review_task = self.repository.get_task("TASK-IDEM")
        report = {
            "taskId": "TASK-IDEM", "taskVersion": review_task["version"], "reportVersion": "executor-report/1.0.0",
            "baselineRef": self.baseline, "commitRef": self.baseline, "evidenceType": "commit", "executorId": "cursor-grok",
            "leaseId": lease["lease_id"], "summary": "idem report",
            "acceptanceChecks": [{"criterion": c, "status": "pass", "evidence": "ok"}
                                 for c in task["acceptance"]],
            "testResults": [{"name": "t", "status": "pass"}],
            "changedFiles": [str(self.repo / "cp-shadow-artifact.md")],
            "riskFindings": [],
            "provenance": [{"sourceUri": str(self.repo / "cp-shadow-artifact.md"),
                            "sha256": "0" * 64, "note": "fake"}],
        }
        stored1 = self.gateway.submit_report(report, "report-idem")
        stored2 = self.gateway.submit_report(report, "report-idem")
        self.assertEqual(stored1["id"], stored2["id"])

    # ---- negative 6: without valid evidence the task must NOT reach DONE ----
    def test_insufficient_evidence_is_not_done(self):
        task = self.ready_task("TASK-EVID")
        lease = self.dispatcher.claim(task["id"], "cursor-grok", self.baseline, task["version"], "claim-evid")
        self.dispatcher.heartbeat(lease["lease_id"], "cursor-grok", "hb-evid")
        self.dispatcher.complete(lease["lease_id"], "cursor-grok", self.baseline, "complete-evid")
        review_task = self.repository.get_task("TASK-EVID")
        # Evidence omits one registered acceptance criterion -> must stay NEEDS_FIX.
        bad_evidence = {
            "taskId": "TASK-EVID", "taskVersion": review_task["version"], "baselineRef": self.baseline,
            "commitRef": self.baseline, "evidenceType": "commit", "executorId": "cursor-grok",
            "leaseId": lease["lease_id"], "summary": "incomplete",
            "acceptanceChecks": [{"criterion": task["acceptance"][0], "status": "pass", "evidence": "ok"}],
            "testResults": [{"name": "t", "status": "pass"}],
            "changedFiles": [str(self.repo / "cp-shadow-artifact.md")],
            "riskFindings": [],
        }
        evaluation = ReviewGate(self.repository).evaluate(bad_evidence)
        self.assertEqual(evaluation["outcome"], "NEEDS_FIX")
        self.assertEqual(self.repository.get_task("TASK-EVID")["state"], "REVIEW")

    # ---- targeted claim returns TARGET_NOT_READY for an existing non-READY task ----
    def test_existing_non_ready_task_returns_target_not_ready(self):
        draft = self.registry.register(task_from_dict({
            "id": "TASK-DRAFT", "projectId": "cp-shadow", "title": "d", "objective": "o",
            "scope": ["s"], "acceptance": ["a"], "priority": "P3", "riskLevel": "low",
            "allowedExecutors": ["cursor-grok"], "workspaceRoots": [str(self.repo)], "dependencies": [],
        }), "planner")
        self.assertEqual(draft["state"], "DRAFT")
        outcome = self.gateway.claim_targeted("TASK-DRAFT", "cursor-grok", self.baseline, "req-draft")
        self.assertEqual(outcome.status, TARGET_NOT_READY)


if __name__ == "__main__":
    unittest.main()
