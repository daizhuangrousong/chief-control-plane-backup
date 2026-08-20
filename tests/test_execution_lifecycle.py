import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from control_plane.config import ProjectConfig
from control_plane.domain.models import AgentType
from control_plane.services import (
    BaselinePromoter, ChiefReviewDecisionError, ChiefTaskImporter, CursorDaemon, CursorRunner,
    DECISION_VERSION, LeaseDispatcher, TaskMergeError, TaskMerger, TaskWorktreeError, TaskWorktreePool,
)
from control_plane.services.chief_task_ingress import ENVELOPE_VERSION, atomic_write_json
from control_plane.storage import Repository


CLEAR_FACTS = {
    "architectureChange": False,
    "productionChange": False,
    "permissionChange": False,
    "externalCommunication": False,
    "paidAction": False,
    "destructiveAction": False,
    "releaseAction": False,
    "scopeExpansion": False,
    "safetyEvidenceComplete": True,
    "baselineKnown": True,
    "workspaceAuthorized": True,
    "acceptanceComplete": True,
}

FAKE_COMMIT = """
import json, subprocess, sys
from pathlib import Path
payload = json.loads(sys.stdin.read())
rel = sys.argv[1]
Path(rel).parent.mkdir(parents=True, exist_ok=True)
Path(rel).write_text(sys.argv[2], encoding="utf-8")
subprocess.run(["git", "add", "--", rel], check=True)
subprocess.run(["git", "commit", "-qm", "task " + payload["taskId"]], check=True)
"""

FAKE_EMPTY = """
import sys
from pathlib import Path
Path(sys.argv[1]).write_text("called\\n", encoding="utf-8")
"""

FAKE_OOB = """
import subprocess
from pathlib import Path
Path("secret.txt").write_text("nope\\n", encoding="utf-8")
subprocess.run(["git", "add", "--", "secret.txt"], check=True)
subprocess.run(["git", "commit", "-qm", "oob"], check=True)
"""

FAKE_DOUBLE = """
import subprocess
from pathlib import Path
Path("reports/a.md").parent.mkdir(parents=True, exist_ok=True)
Path("reports/a.md").write_text("one\\n", encoding="utf-8")
subprocess.run(["git", "add", "--", "reports/a.md"], check=True)
subprocess.run(["git", "commit", "-qm", "one"], check=True)
Path("reports/a.md").write_text("two\\n", encoding="utf-8")
subprocess.run(["git", "add", "--", "reports/a.md"], check=True)
subprocess.run(["git", "commit", "-qm", "two"], check=True)
"""


class ExecutionLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.temp.name) / "runtime"
        self.project = Path(self.temp.name) / "project"
        self.runtime.mkdir()
        self.sentinel = self.runtime / "RUNTIME_SENTINEL"
        self.sentinel.write_text("untouched\n", encoding="utf-8")
        self.sentinel_mtime = self.sentinel.stat().st_mtime_ns
        self._init_project()
        self.db = self.project / "r4.sqlite3"
        self.outbox = self.project / "chief-task-outbox"
        self.inbox = self.project / "chief-task-inbox"
        self.outbox.mkdir()
        self.inbox.mkdir()
        self.pool_root = self.project / "var" / "task-worktrees"
        self.repository = Repository(self.db)
        self.repository.migrate()
        self.project_cfg = ProjectConfig(
            id="control-panel", name="Panel", kind="control_plane", owner="Owner",
            root=self.project, ledger=self.project / "PROGRESS.md", status=self.project / "BLOCKED.md",
            knowledge_roots=[], enabled_agents=list(AgentType),
        )
        self.repository.upsert_project(self.project_cfg)
        self.dispatcher = LeaseDispatcher(self.repository, default_ttl_seconds=30)
        self.dispatcher.register_executor("cursor-r1", ["control-panel"], "low")
        self.dispatcher.set_project_baseline("control-panel", self.head, "planner")
        self.pool = TaskWorktreePool(self.runtime, self.project, self.pool_root)
        self.importer = ChiefTaskImporter(
            self.repository, self.outbox, self.inbox, [self.project_cfg], dispatcher=self.dispatcher,
        )
        self.calls = {"executor": 0, "merge": 0, "promote": 0}

    def tearDown(self):
        self.temp.cleanup()

    def _init_project(self):
        self.project.mkdir()
        subprocess.run(["git", "init", "-b", "main", "-q", str(self.project)], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.email", "r4@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.name", "R4"], check=True)
        (self.project / "README").write_text("project\n", encoding="utf-8")
        (self.project / ".gitignore").write_text(
            "*.sqlite3\nchief-task-outbox/\nchief-task-inbox/\nvar/\nfake_r4.py\n",
            encoding="utf-8",
        )
        (self.project / "reports").mkdir()
        (self.project / "reports" / ".keep").write_text("keep\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.project), "add", "README", ".gitignore", "reports/.keep"], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-qm", "fixture"], check=True)
        self.head = subprocess.check_output(["git", "-C", str(self.project), "rev-parse", "HEAD"], text=True).strip()

    def runtime_clean(self):
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"), "untouched\n")
        self.assertEqual(self.sentinel.stat().st_mtime_ns, self.sentinel_mtime)
        self.assertFalse((self.runtime / ".git").exists())

    def envelope(self, task_id, relpath, body):
        return {
            "schemaVersion": ENVELOPE_VERSION,
            "task": {
                "id": task_id,
                "projectId": "control-panel",
                "title": task_id,
                "objective": "Write {} with fake executor.".format(relpath),
                "scope": [relpath],
                "acceptance": ["Stay in REVIEW"],
                "priority": "P2",
                "riskLevel": "low",
                "allowedExecutors": ["cursor-r1"],
                "workspaceRoots": [str(self.project)],
                "dependencies": [],
                "sourceUri": "chief-task-outbox/{}.json".format(task_id),
                "approvalClass": "none",
            },
            "facts": dict(CLEAR_FACTS),
        }

    def drop(self, payload):
        path = self.outbox / "{}.json".format(payload["task"]["id"])
        atomic_write_json(path, payload)
        return path

    def fake_command(self, script, *args):
        fake = self.project / "fake_r4.py"
        fake.write_text(script, encoding="utf-8")
        return [sys.executable, str(fake), *args]

    def run_task(self, command):
        self.calls["executor"] += 1
        runner = CursorRunner(
            self.dispatcher, "cursor-r1", command, timeout_seconds=20, worktree_pool=self.pool,
        )
        return CursorDaemon(runner, "control-panel", idle_seconds=0, reporter=self.importer.reporter.report_cycle).run(max_cycles=1)

    def decide(self, result):
        return {
            "schemaVersion": DECISION_VERSION,
            "taskId": result["task_id"],
            "taskVersion": result["task_version"],
            "commitRef": result["after_ref"],
            "leaseId": result["lease_id"],
            "outcome": "approve_merge",
            "actor": "chief",
            "reasons": ["Evidence matches the leased commit."],
        }

    def merger(self):
        return TaskMerger(
            self.repository, self.dispatcher, self.project, self.pool,
            receipt_dir=self.inbox, target_branch="main",
        )

    def test_two_consecutive_tasks_across_baseline_promotion(self):
        first_path = "reports/TASK-R4-A.md"
        self.drop(self.envelope("TASK-R4-A", first_path, "A"))
        first = self.importer.ingest_once()[0]
        self.assertEqual(first["state"], "READY")
        self.assertEqual(first["taskState"], "READY")
        self.assertEqual(first["runnerStatus"], "READY")
        result_a = self.run_task(self.fake_command(FAKE_COMMIT, first_path, "alpha\n"))
        self.assertEqual(result_a["task_state"], "REVIEW")
        self.assertEqual(result_a["diff_check"], "pass")
        self.assertEqual(result_a["changed_paths"], [first_path])
        self.assertEqual(self.repository.get_task("TASK-R4-A")["state"], "REVIEW")
        receipt_a = json.loads((self.inbox / "TASK-R4-A.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt_a["taskState"], "REVIEW")
        self.assertEqual(receipt_a["runnerStatus"], "REVIEW")
        self.calls["merge"] += 1
        merged = self.merger().merge(self.decide(result_a), "merge-r4", "merge-A")
        self.assertEqual(merged["status"], "merged")
        promoter = BaselinePromoter(self.dispatcher, self.project, self.runtime)
        self.calls["promote"] += 1
        promoted = promoter.promote("control-panel", merged["commitRef"], "promote-A")
        self.assertEqual(promoted["status"], "promoted")
        self.assertEqual(promoted["previousBaselineRef"], self.head)
        self.assertEqual(self.dispatcher.get_project_baseline("control-panel")["baseline_ref"], merged["commitRef"])
        self.runtime_clean()

        second_path = "reports/TASK-R4-B.md"
        dropped_b = self.drop(self.envelope("TASK-R4-B", second_path, "B"))
        ingested_b = self.importer.ingest_once()
        second = [item for item in ingested_b if item["taskId"] == "TASK-R4-B"][0]
        self.assertEqual(second["state"], "READY")
        self.assertTrue(dropped_b.is_file())
        result_b = self.run_task(self.fake_command(FAKE_COMMIT, second_path, "beta\n"))
        self.assertEqual(result_b["task_state"], "REVIEW")
        self.assertEqual(result_b["before_ref"], merged["commitRef"])
        self.calls["merge"] += 1
        merged_b = self.merger().merge(self.decide(result_b), "merge-r4", "merge-B")
        self.calls["promote"] += 1
        promoted_b = promoter.promote("control-panel", merged_b["commitRef"], "promote-B")
        self.assertEqual(promoted_b["status"], "promoted")
        self.assertEqual(promoted_b["previousBaselineRef"], merged["commitRef"])
        self.assertEqual(self.calls, {"executor": 2, "merge": 2, "promote": 2})
        self.runtime_clean()
        self.assertTrue((self.project / first_path).is_file())
        self.assertTrue((self.project / second_path).is_file())

    def test_dirty_worktree_out_of_bounds_and_empty_commit_fail_closed(self):
        dirty = self.pool_root / "TASK-R4-DIRTY"
        dirty.mkdir(parents=True)
        (dirty / "stain").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(TaskWorktreeError):
            self.pool.allocate("TASK-R4-DIRTY", self.head)
        self.assertEqual(self.dispatcher.get_project_baseline("control-panel")["baseline_ref"], self.head)

        self.drop(self.envelope("TASK-R4-OOB", "reports/a.md", "x"))
        self.importer.ingest_once()
        oob = self.run_task(self.fake_command(FAKE_OOB))
        self.assertEqual(oob["task_state"], "FAILED")
        self.assertEqual(self.dispatcher.get_project_baseline("control-panel")["baseline_ref"], self.head)
        self.dispatcher.register_executor("cursor-r1", ["control-panel"], "low", enabled=True)

        self.drop(self.envelope("TASK-R4-EMPTY", "reports/a.md", "x"))
        self.importer.ingest_once()
        empty = self.run_task(self.fake_command(FAKE_EMPTY, str(self.runtime / "empty-marker")))
        self.assertEqual(empty["task_state"], "FAILED")
        self.assertEqual(self.dispatcher.get_project_baseline("control-panel")["baseline_ref"], self.head)
        self.dispatcher.register_executor("cursor-r1", ["control-panel"], "low", enabled=True)
        self.runtime_clean()

    def test_multiple_commits_unauthorized_conflict_duplicate_health_and_old_outbox(self):
        self.drop(self.envelope("TASK-R4-MULTI", "reports/a.md", "x"))
        self.importer.ingest_once()
        multi = self.run_task(self.fake_command(FAKE_DOUBLE))
        self.assertEqual(multi["task_state"], "FAILED")
        self.dispatcher.register_executor("cursor-r1", ["control-panel"], "low", enabled=True)

        path = "reports/TASK-R4-C.md"
        self.drop(self.envelope("TASK-R4-C", path, "c"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_COMMIT, path, "ok\n"))
        self.assertEqual(result["task_state"], "REVIEW")
        decision = self.decide(result)
        with self.assertRaises(TaskMergeError):
            self.merger().merge(decision, "cursor-r1", "merge-self")
        rogue = dict(decision)
        rogue["actor"] = "cursor-r1"
        with self.assertRaises(ChiefReviewDecisionError):
            self.merger().merge(rogue, "merge-r4", "merge-unauth")
        occupancy = self.pool.read_occupancy("TASK-R4-C")
        subprocess.run(
            ["git", "-C", occupancy["path"], "commit", "--allow-empty", "-qm", "conflict"],
            check=True,
        )
        with self.assertRaises(TaskMergeError):
            self.merger().merge(decision, "merge-r4", "merge-conflict")
        subprocess.run(["git", "-C", occupancy["path"], "reset", "-q", "--hard", result["after_ref"]], check=True)
        merged = self.merger().merge(decision, "merge-r4", "merge-C")
        with self.assertRaises(TaskMergeError):
            self.merger().merge(decision, "merge-r4", "merge-dup")
        failed = BaselinePromoter(
            self.dispatcher, self.project, self.runtime, runtime_healthy=lambda: False,
        ).promote("control-panel", merged["commitRef"], "promote-fail")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["baselineRef"], self.head)
        self.assertEqual(self.dispatcher.get_project_baseline("control-panel")["baseline_ref"], self.head)
        self.assertEqual(failed["rollbackPlan"]["keepBaseline"], self.head)
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.project), "rev-parse", "HEAD"], text=True).strip(), merged["commitRef"])

        receipt = self.inbox / "TASK-R4-C.json"
        before = receipt.stat().st_mtime_ns
        again = self.importer.ingest_once()
        self.assertTrue(any(item["taskId"] == "TASK-R4-C" for item in again))
        self.assertEqual(receipt.stat().st_mtime_ns, before)
        with self.assertRaises(TaskWorktreeError):
            self.pool.allocate("TASK-R4-C", self.head)
        self.runtime_clean()


if __name__ == "__main__":
    unittest.main()
