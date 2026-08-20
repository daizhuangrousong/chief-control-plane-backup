import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from control_plane.config import ProjectConfig
from control_plane.domain.models import AgentType, TaskState
from control_plane.services import (
    CursorAdapterError, CursorRunner, LeaseDispatcher, TaskRegistry, task_from_dict,
)
from control_plane.storage import Repository


SUCCESS_FAKE = """
import json, sys
from pathlib import Path
payload = json.load(sys.stdin)
Path(sys.argv[1]).write_text(json.dumps({"argv": sys.argv, "payload": payload}), encoding="utf-8")
"""

FAIL_FAKE = """
import sys
print("token=sk-live-supersecret", file=sys.stderr)
raise SystemExit(3)
"""

TIMEOUT_FAKE = """
import time
time.sleep(30)
"""


class CursorRunnerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._init_git()
        self.repository = Repository(self.root / "control.sqlite3")
        self.repository.migrate()
        self.repository.upsert_project(ProjectConfig(
            id="panel", name="Panel", kind="control_plane", owner="Owner", root=self.root,
            ledger=self.root / "TASKS.md", status=self.root / "STATE.md",
            knowledge_roots=[], enabled_agents=list(AgentType),
        ))
        self.registry = TaskRegistry(self.repository)
        self.dispatcher = LeaseDispatcher(self.repository, default_ttl_seconds=30)
        self.dispatcher.register_executor("cursor-r0", ["panel"], "low")
        self.head = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True,
        ).strip()
        self.dispatcher.set_project_baseline("panel", self.head, "planner")
        self.logs = []

    def tearDown(self):
        self.temp.cleanup()

    def _init_git(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "r0@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "R0"], check=True)
        (self.root / "README").write_text("workspace\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "README"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)

    def fake(self, body, capture_name="captured.json"):
        script = self.root / "fake_executor.py"
        script.write_text(body, encoding="utf-8")
        capture = self.root / capture_name
        return [sys.executable, str(script), str(capture)], capture

    def runner(self, command, timeout=5):
        return CursorRunner(
            self.dispatcher, "cursor-r0", executor_command=command,
            timeout_seconds=timeout, log=self.logs.append,
        )

    def ready_task(self, task_id="TASK-R0-RUN", workspace=None, **updates):
        payload = {
            "id": task_id, "projectId": "panel", "title": task_id,
            "objective": "Execute the isolated adapter path.",
            "scope": ["Adapter"], "acceptance": ["Stay in REVIEW"],
            "priority": "P1", "riskLevel": "low",
            "allowedExecutors": ["cursor-r0"],
            "workspaceRoots": [str(workspace or self.root)], "dependencies": [],
        }
        payload.update(updates)
        task = self.registry.register(task_from_dict(payload), "planner")
        return self.registry.transition(task_id, TaskState.READY, task["version"], "policy", "safe")

    def test_production_default_refuses_to_discover_cursor(self):
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        decoy = bin_dir / "cursor-agent"
        decoy.write_text("#!/bin/sh\necho SHOULD_NOT_RUN\n", encoding="utf-8")
        decoy.chmod(0o755)
        source = Path(__import__("control_plane.services.cursor_runner", fromlist=["cursor_runner"]).__file__).read_text(
            encoding="utf-8"
        )
        self.assertNotIn("shutil.which", source)
        self.assertNotIn("cursor-agent", source)
        with self.assertRaisesRegex(CursorAdapterError, "refuses to discover or start Cursor"):
            CursorRunner(self.dispatcher, "cursor-r0")
        with self.assertRaises(CursorAdapterError):
            CursorRunner(self.dispatcher, "cursor-r0", executor_command=None)

    def test_success_passes_task_as_data_and_stops_at_review(self):
        command, capture = self.fake(SUCCESS_FAKE)
        self.ready_task("TASK-OK")
        result = self.runner(command).run_next(request_id="ok-1")
        self.assertEqual((result["status"], result["task_state"]), ("completed", "REVIEW"))
        self.assertEqual(self.repository.get_task("TASK-OK")["state"], "REVIEW")
        recorded = json.loads(capture.read_text(encoding="utf-8"))
        self.assertEqual(recorded["payload"]["taskId"], "TASK-OK")
        self.assertEqual(recorded["payload"]["objective"], "Execute the isolated adapter path.")
        self.assertNotIn("TASK-OK", recorded["argv"][0])
        self.assertNotIn("Execute the isolated adapter path.", " ".join(recorded["argv"]))

    def test_nonzero_exit_fails_and_redacts_secrets(self):
        command, _capture = self.fake(FAIL_FAKE)
        self.ready_task("TASK-FAIL")
        result = self.runner(command).run_next(request_id="fail-1")
        self.assertEqual((result["status"], result["task_state"]), ("failed", "FAILED"))
        reason = self.repository.list_task_transitions("TASK-FAIL")[-1]["reason"]
        self.assertIn("executor exited 3", reason)
        self.assertNotIn("sk-live-supersecret", reason)
        self.assertIn("[REDACTED]", reason)
        self.assertFalse(any("sk-live-supersecret" in item for item in self.logs))

    def test_timeout_fails_the_lease(self):
        command, _capture = self.fake(TIMEOUT_FAKE)
        self.ready_task("TASK-SLOW")
        result = self.runner(command, timeout=1).run_next(request_id="slow-1")
        self.assertEqual((result["status"], result["task_state"]), ("failed", "FAILED"))
        self.assertIn("timed out", self.repository.list_task_transitions("TASK-SLOW")[-1]["reason"])

    def test_out_of_bounds_workspace_is_rejected_before_claim(self):
        outside = Path(tempfile.mkdtemp())
        try:
            self.ready_task("TASK-BOUNDS", workspace=outside)
            command, _capture = self.fake(SUCCESS_FAKE)
            with self.assertRaisesRegex(CursorAdapterError, "outside the authorized project root"):
                self.runner(command).run_next(request_id="bounds-1")
            self.assertEqual(self.repository.get_task("TASK-BOUNDS")["state"], "READY")
            self.assertIsNone(self.dispatcher.active_lease_for_project("panel"))
        finally:
            for child in outside.iterdir():
                if child.is_file():
                    child.unlink()
            outside.rmdir()

    def test_baseline_drift_is_rejected_before_claim(self):
        self.ready_task("TASK-DRIFT")
        (self.root / "README").write_text("drifted\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "README"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "drift"], check=True)
        command, _capture = self.fake(SUCCESS_FAKE)
        with self.assertRaisesRegex(CursorAdapterError, "baseline drift"):
            self.runner(command).run_next(request_id="drift-1")
        self.assertEqual(self.repository.get_task("TASK-DRIFT")["state"], "READY")

    def test_missing_owner_approval_is_rejected(self):
        self.ready_task("TASK-DB-READY")
        with self.repository.connect() as connection:
            connection.execute(
                "UPDATE control_task SET approval_class = 'database_write', owner_approval_ref = NULL "
                "WHERE id = 'TASK-DB-READY'"
            )
        command, _capture = self.fake(SUCCESS_FAKE)
        with self.assertRaisesRegex(CursorAdapterError, "ownerApprovalRef is required"):
            self.runner(command).run_next(request_id="db-1")
        self.assertEqual(self.repository.get_task("TASK-DB-READY")["state"], "READY")

    def test_project_allows_only_one_active_execution(self):
        self.ready_task("TASK-ONE")
        self.ready_task("TASK-TWO")
        release = self.root / "release-lock"
        script = self.root / "blocking.py"
        script.write_text(
            "import sys, time\nfrom pathlib import Path\n"
            "target = Path(sys.argv[1])\n"
            "while not target.exists():\n    time.sleep(0.05)\n",
            encoding="utf-8",
        )
        blocking = [sys.executable, str(script), str(release)]
        outcomes = []

        def run_first():
            outcomes.append(self.runner(blocking, timeout=8).run_next(request_id="block-1"))

        thread = threading.Thread(target=run_first)
        thread.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            if self.repository.get_task("TASK-ONE")["state"] in {"CLAIMED", "RUNNING"}:
                break
            time.sleep(0.05)
        self.assertIn(self.repository.get_task("TASK-ONE")["state"], {"CLAIMED", "RUNNING"})
        with self.assertRaisesRegex(CursorAdapterError, "active execution"):
            self.runner(self.fake(SUCCESS_FAKE)[0]).run_next(request_id="block-2")
        self.assertEqual(self.repository.get_task("TASK-TWO")["state"], "READY")
        release.write_text("go", encoding="utf-8")
        thread.join(timeout=8)
        self.assertTrue(outcomes)
        self.assertEqual(outcomes[0]["task_state"], "REVIEW")

    def test_duplicate_claim_race_rejects_the_loser(self):
        self.ready_task("TASK-RACE")
        command, _capture = self.fake(SUCCESS_FAKE)
        barrier = threading.Barrier(3)
        outcomes = []

        def run(request_id):
            barrier.wait()
            try:
                outcomes.append(("won", self.runner(command).run_next(request_id=request_id)))
            except CursorAdapterError as error:
                outcomes.append(("lost", str(error)))

        threads = [
            threading.Thread(target=run, args=("race-a",)),
            threading.Thread(target=run, args=("race-b",)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        reviews = [item for item in outcomes if item[0] == "won" and item[1].get("task_state") == "REVIEW"]
        rejected = [
            item for item in outcomes
            if item[0] == "lost" or (item[0] == "won" and item[1].get("status") == "idle")
        ]
        self.assertEqual(len(reviews), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(self.repository.get_task("TASK-RACE")["state"], "REVIEW")

    def test_julius_isolation_flag_is_unchanged(self):
        from control_plane.services.project_isolation import ISOLATED_PROJECT_IDS
        self.assertIn("julius", ISOLATED_PROJECT_IDS)


if __name__ == "__main__":
    unittest.main()
