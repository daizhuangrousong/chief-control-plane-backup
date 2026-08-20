import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from control_plane.config import ProjectConfig
from control_plane.domain.models import AgentType, TaskState
from control_plane.services import (
    CursorDaemon, CursorRunner, LeaseDispatcher,
)
from control_plane.services.chief_task_ingress import (
    DEFAULT_MAX_BYTES, ENVELOPE_VERSION, ChiefTaskImporter, ChiefTaskReporter,
    atomic_write_json, parse_envelope, read_outbox_bytes,
)
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

FAKE_EXECUTOR = """
import sys
from pathlib import Path
Path(sys.argv[1]).write_text('called\\n', encoding='utf-8')
"""


class ChiefTaskIngressTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._init_git()
        self.db = self.root / "r2-ingress.sqlite3"
        self.outbox = self.root / "chief-task-outbox"
        self.inbox = self.root / "chief-task-inbox"
        self.outbox.mkdir()
        self.inbox.mkdir()
        self.marker = self.root / "executor-called"
        self.repository = Repository(self.db)
        self.repository.migrate()
        self.project = ProjectConfig(
            id="control-panel", name="Panel", kind="control_plane", owner="Owner",
            root=self.root, ledger=self.root / "TASKS.md", status=self.root / "STATE.md",
            knowledge_roots=[], enabled_agents=list(AgentType),
        )
        self.repository.upsert_project(self.project)
        self.dispatcher = LeaseDispatcher(self.repository, default_ttl_seconds=30)
        self.dispatcher.register_executor("cursor-r2", ["control-panel"], "low")
        self.head = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        self.dispatcher.set_project_baseline("control-panel", self.head, "planner")
        fake = self.root / "fake_executor.py"
        fake.write_text(FAKE_EXECUTOR, encoding="utf-8")
        self.command = [sys.executable, str(fake), str(self.marker)]
        self.importer = ChiefTaskImporter(
            self.repository, self.outbox, self.inbox, [self.project],
            dispatcher=self.dispatcher,
        )
        self.reporter = self.importer.reporter
        self.assertTrue(str(self.db).startswith(str(self.root)))

    def tearDown(self):
        self.temp.cleanup()

    def _init_git(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "r2@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "R2"], check=True)
        (self.root / "README").write_text("workspace\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "README"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)

    def envelope(self, task_id="TASK-R2-FLOW", **updates):
        task = {
            "id": task_id,
            "projectId": "control-panel",
            "title": "R2 {}".format(task_id),
            "objective": "Exercise the Chief file ingress with a fake executor.",
            "scope": ["README"],
            "acceptance": ["Stay in REVIEW"],
            "priority": "P2",
            "riskLevel": "low",
            "allowedExecutors": ["cursor-r2"],
            "workspaceRoots": [str(self.root)],
            "dependencies": [],
            "sourceUri": "chief-task-outbox/{}.json".format(task_id),
            "approvalClass": "none",
        }
        task.update(updates)
        return {"schemaVersion": ENVELOPE_VERSION, "task": task, "facts": dict(CLEAR_FACTS)}

    def drop(self, payload, task_id=None):
        task_id = task_id or payload["task"]["id"]
        path = self.outbox / "{}.json".format(task_id)
        atomic_write_json(path, payload)
        return path

    def run_daemon(self):
        daemon = CursorDaemon(
            CursorRunner(self.dispatcher, "cursor-r2", self.command, timeout_seconds=5),
            "control-panel", idle_seconds=0, reporter=self.reporter.report_cycle,
        )
        return daemon.run(max_cycles=1)

    def test_example_envelope_is_strict_fake_data(self):
        repo = Path(__file__).resolve().parents[1]
        example = json.loads((repo / "config" / "chief-task-envelope.example.json").read_text(encoding="utf-8"))
        parsed = parse_envelope(json.dumps(example, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(parsed["task"].id, "TASK-R2-EXAMPLE")
        self.assertIn("fake", parsed["task"].objective.casefold())
        gitignore = (repo / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("chief-task-outbox/", gitignore)
        self.assertIn("chief-task-inbox/", gitignore)
        source = Path(__import__("control_plane.services.chief_task_ingress", fromlist=["chief_task_ingress"]).__file__).read_text(
            encoding="utf-8",
        )
        self.assertIn("os.replace", source)
        self.assertIn("os.fsync", source)
        self.assertIn("O_NOFOLLOW", source)

    def test_end_to_end_file_to_review_inbox_and_repeat_is_idempotent(self):
        path = self.drop(self.envelope())
        first = self.importer.ingest_once()
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["state"], "READY")
        self.assertEqual(first[0]["taskId"], "TASK-R2-FLOW")
        self.assertEqual(len(first[0]["sourceHash"]), 64)
        self.assertIsNone(first[0]["error"])
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.repository.get_task("TASK-R2-FLOW")["state"], "READY")
        second = self.importer.ingest_once()
        self.assertEqual(second[0]["state"], "READY")
        self.assertEqual(second[0]["sourceHash"], first[0]["sourceHash"])
        self.assertEqual(self.repository.get_task("TASK-R2-FLOW")["version"], first[0]["taskVersion"])
        result = self.run_daemon()
        self.assertEqual((result["status"], result["task_state"]), ("completed", "REVIEW"))
        self.assertTrue(self.marker.exists())
        receipt = json.loads((self.inbox / "TASK-R2-FLOW.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["state"], "REVIEW")
        self.assertEqual(receipt["leaseId"], result["lease_id"])
        self.assertEqual(receipt["sourceHash"], first[0]["sourceHash"])
        self.assertEqual(self.repository.get_task("TASK-R2-FLOW")["state"], "REVIEW")
        third = self.importer.ingest_file(path)
        self.assertEqual(third["state"], "REVIEW")
        self.assertEqual(self.repository.get_task("TASK-R2-FLOW")["state"], "REVIEW")
        self.assertEqual(self.marker.read_text(encoding="utf-8").count("called"), 1)
        idle = self.run_daemon()
        self.assertEqual(idle["status"], "idle")
        self.assertEqual(self.marker.read_text(encoding="utf-8").count("called"), 1)

    def test_missing_owner_approval_blocks_with_zero_executor_calls(self):
        self.drop(self.envelope(
            "TASK-R2-OWNER", approvalClass="database_write", title="Needs owner",
        ))
        receipt = self.importer.ingest_once()[0]
        self.assertEqual(receipt["state"], "BLOCKED")
        self.assertIn("block.owner_approval_missing", receipt["matchedRules"])
        self.run_daemon()
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.repository.get_task("TASK-R2-OWNER")["state"], "BLOCKED")

    def test_out_of_bounds_workspace_blocks_with_zero_executor_calls(self):
        outside = Path("/private/tmp")
        self.drop(self.envelope(
            "TASK-R2-BOUNDS", workspaceRoots=[str(outside)], title="Out of bounds",
        ))
        receipt = self.importer.ingest_once()[0]
        self.assertEqual(receipt["state"], "BLOCKED")
        self.assertIn("block.workspace_not_authorized", receipt["matchedRules"])
        self.run_daemon()
        self.assertFalse(self.marker.exists())

    def test_same_id_different_content_blocks_with_zero_executor_calls(self):
        self.drop(self.envelope("TASK-R2-DUP", title="Original"))
        self.importer.ingest_once()
        self.assertEqual(self.repository.get_task("TASK-R2-DUP")["state"], "READY")
        self.drop(self.envelope("TASK-R2-DUP", title="Changed after drop"))
        receipt = self.importer.ingest_once()[0]
        self.assertEqual(receipt["state"], "BLOCKED")
        self.assertIn("block.duplicate_id_conflict", receipt["matchedRules"])
        self.run_daemon()
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.repository.get_task("TASK-R2-DUP")["state"], "BLOCKED")

    def test_symlink_is_rejected_with_zero_executor_calls(self):
        real = self.root / "elsewhere.json"
        atomic_write_json(real, self.envelope("TASK-R2-LINK"))
        link = self.outbox / "TASK-R2-LINK.json"
        link.symlink_to(real)
        receipt = self.importer.ingest_once()[0]
        self.assertEqual(receipt["state"], "BLOCKED")
        self.assertIn("symlink", receipt["error"] or "")
        self.assertIsNone(self.repository.get_task("TASK-R2-LINK"))
        self.run_daemon()
        self.assertFalse(self.marker.exists())

    def test_truncated_json_is_rejected_with_zero_executor_calls(self):
        path = self.outbox / "TASK-R2-TRUNC.json"
        path.write_text('{"schemaVersion":', encoding="utf-8")
        receipt = self.importer.ingest_once()[0]
        self.assertEqual(receipt["state"], "BLOCKED")
        self.assertIn("JSON", receipt["error"] or "")
        self.assertIsNone(self.repository.get_task("TASK-R2-TRUNC"))
        self.run_daemon()
        self.assertFalse(self.marker.exists())

    def test_unknown_fields_and_oversized_files_are_rejected(self):
        payload = self.envelope("TASK-R2-EXTRA")
        payload["extra"] = "nope"
        self.drop(payload)
        receipt = self.importer.ingest_once()[0]
        self.assertEqual(receipt["state"], "BLOCKED")
        self.assertIn("unknown envelope fields", receipt["error"] or "")
        huge = self.outbox / "TASK-R2-HUGE.json"
        huge.write_bytes(b"x" * (DEFAULT_MAX_BYTES + 1))
        with self.assertRaisesRegex(Exception, "maxBytes"):
            read_outbox_bytes(self.outbox, huge, DEFAULT_MAX_BYTES)
        self.run_daemon()
        self.assertFalse(self.marker.exists())

    def test_reporter_does_not_mark_review_done(self):
        self.drop(self.envelope("TASK-R2-HOLD"))
        self.importer.ingest_once()
        self.run_daemon()
        self.assertEqual(self.repository.get_task("TASK-R2-HOLD")["state"], "REVIEW")
        again = self.reporter.publish_task("TASK-R2-HOLD")
        self.assertEqual(again["state"], "REVIEW")
        self.assertEqual(self.repository.get_task("TASK-R2-HOLD")["state"], "REVIEW")
        self.assertNotEqual(again["state"], "DONE")

    def test_atomic_write_replaces_regular_files_only(self):
        target = self.inbox / "TASK-R2-PERM.json"
        atomic_write_json(target, {"ok": True})
        self.assertTrue(target.is_file())
        self.assertFalse(target.is_symlink())
        info = target.stat()
        self.assertTrue(stat.S_ISREG(info.st_mode))
        atomic_write_json(target, {"ok": False, "schemaVersion": "chief-task-receipt/1.0.0"})
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(payload["ok"], False)


if __name__ == "__main__":
    unittest.main()
