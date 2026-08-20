import json
import stat
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
    CursorDaemon, CursorRunner, LeaseDispatcher,
)
from control_plane.services.chief_task_ingress import (
    DEFAULT_MAX_BYTES, ENVELOPE_VERSION, ChiefTaskImporter, ChiefTaskIngressError,
    ChiefTaskReporter, atomic_write_json, load_ingress_config, parse_envelope, read_outbox_bytes,
)
from control_plane.services.cursor_launch import plist_keepalive_is_limited, plist_program_arguments
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

FAKE_SLOW = """
import sys, time
from pathlib import Path
Path(sys.argv[1]).write_text('started\\n', encoding='utf-8')
time.sleep(1.5)
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
        self.assertIn("fstat", source)
        loaded = load_ingress_config(str(repo / "config" / "chief-task-ingress.example.json"))
        self.assertEqual(loaded["allowedProjects"], ["control-panel"])

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
        first = self.drop(self.envelope("TASK-R2-DUP", title="Original"))
        original = self.importer.ingest_once()[0]
        before = self.repository.get_task("TASK-R2-DUP")
        self.assertEqual(before["state"], "READY")
        self.drop(self.envelope("TASK-R2-DUP", title="Changed after drop"))
        receipt = self.importer.ingest_once()[0]
        after = self.repository.get_task("TASK-R2-DUP")
        self.assertEqual(after["state"], "READY")
        self.assertEqual(after["version"], before["version"])
        self.assertEqual(receipt["originalHash"], original["sourceHash"])
        self.assertNotEqual(receipt["attemptedHash"], original["sourceHash"])
        self.assertEqual(receipt["sourceHash"], original["sourceHash"])
        self.assertIn("block.duplicate_id_conflict", receipt["matchedRules"])
        self.assertFalse(self.marker.exists())
        self.assertTrue(first.is_file())

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

    def test_conflict_on_review_does_not_mutate_task(self):
        self.drop(self.envelope("TASK-R2-REV", title="Original review"))
        first = self.importer.ingest_once()[0]
        result = self.run_daemon()
        self.assertEqual(result["task_state"], "REVIEW")
        before = self.repository.get_task("TASK-R2-REV")
        self.drop(self.envelope("TASK-R2-REV", title="Conflict after review"))
        receipt = self.importer.ingest_once()[0]
        after = self.repository.get_task("TASK-R2-REV")
        self.assertEqual(after["state"], "REVIEW")
        self.assertEqual(after["version"], before["version"])
        self.assertEqual(receipt["originalHash"], first["sourceHash"])
        self.assertNotEqual(receipt["attemptedHash"], receipt["originalHash"])
        self.assertEqual(receipt["sourceHash"], first["sourceHash"])
        self.assertIn("block.duplicate_id_conflict", receipt["matchedRules"])
        self.run_daemon()
        self.assertEqual(self.marker.read_text(encoding="utf-8").count("called"), 1)

    def test_facts_only_drift_conflicts_and_keeps_original_hash(self):
        payload = self.envelope("TASK-R2-FACTS")
        self.drop(payload)
        first = self.importer.ingest_once()[0]
        payload["facts"]["architectureChange"] = True
        self.drop(payload)
        receipt = self.importer.ingest_once()[0]
        task = self.repository.get_task("TASK-R2-FACTS")
        self.assertEqual(task["state"], "READY")
        self.assertEqual(task["version"], first["taskVersion"])
        self.assertEqual(receipt["originalHash"], first["sourceHash"])
        self.assertNotEqual(receipt["attemptedHash"], first["sourceHash"])
        self.assertEqual(receipt["sourceHash"], first["sourceHash"])
        self.assertIn("block.duplicate_id_conflict", receipt["matchedRules"])
        self.assertFalse(self.marker.exists())

    def test_real_runner_script_writes_inbox_receipt(self):
        self.drop(self.envelope("TASK-R2-SCRIPT"))
        self.importer.ingest_once()
        self.assertEqual(self.repository.get_task("TASK-R2-SCRIPT")["state"], "READY")
        config_path = self.root / "projects.local.json"
        config_path.write_text(json.dumps({
            "database": str(self.db),
            "projects": [{
                "id": "control-panel", "name": "Panel", "kind": "control_plane", "owner": "Owner",
                "root": str(self.root), "ledger": "TASKS.md", "status": "STATE.md",
                "knowledge_roots": [], "enabled_agents": ["knowledge", "observer", "release"],
            }],
        }), encoding="utf-8")
        script = Path(__file__).resolve().parents[1] / "scripts" / "run_cursor_runner.py"
        argv = [
            sys.executable, str(script),
            "--config", str(config_path),
            "--executor-id", "cursor-r2",
            "--executor-command", json.dumps(self.command),
            "--project", "control-panel",
            "--idle-seconds", "0",
            "--log-file", str(self.root / "runner.log"),
            "--halt-file", str(self.root / "halt.json"),
            "--max-cycles", "1",
            "--inbox-dir", str(self.inbox),
        ]
        env = dict(__import__("os").environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        completed = subprocess.run(argv, capture_output=True, text=True, env=env, cwd=str(self.root), timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.repository.get_task("TASK-R2-SCRIPT")["state"], "REVIEW")
        receipt = json.loads((self.inbox / "TASK-R2-SCRIPT.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["state"], "REVIEW")
        self.assertTrue(receipt.get("leaseId"))
        self.assertEqual(self.marker.read_text(encoding="utf-8").count("called"), 1)
        completed_again = subprocess.run(argv, capture_output=True, text=True, env=env, cwd=str(self.root), timeout=20)
        self.assertEqual(completed_again.returncode, 0, completed_again.stderr)
        self.assertEqual(self.marker.read_text(encoding="utf-8").count("called"), 1)

    def test_baseline_mismatch_blocks_with_zero_executor_calls(self):
        self.dispatcher.set_project_baseline("control-panel", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", "planner")
        self.drop(self.envelope("TASK-R2-BASE", title="Baseline mismatch"))
        receipt = self.importer.ingest_once()[0]
        self.assertEqual(receipt["state"], "BLOCKED")
        self.assertTrue(
            "baseline" in (receipt["error"] or "").casefold()
            or any("baseline" in item for item in receipt["matchedRules"])
        )
        self.run_daemon()
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.repository.get_task("TASK-R2-BASE")["state"], "BLOCKED")

    def test_missing_config_and_path_overlap_fail_closed(self):
        empty = self.root / "empty-ingress.json"
        empty.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(ChiefTaskIngressError):
            load_ingress_config(str(empty))
        nested_out = self.root / "nested-out"
        nested_in = nested_out / "inbox"
        nested_out.mkdir()
        nested_in.mkdir()
        overlap = self.root / "overlap-ingress.json"
        overlap.write_text(json.dumps({
            "outboxDir": str(nested_out.resolve()),
            "inboxDir": str(nested_in.resolve()),
            "allowedProjects": ["control-panel"],
            "maxBytes": 1024,
        }), encoding="utf-8")
        with self.assertRaises(ChiefTaskIngressError):
            load_ingress_config(str(overlap))
        unknown = self.root / "unknown-ingress.json"
        unknown.write_text(json.dumps({
            "outboxDir": str(self.outbox.resolve()),
            "inboxDir": str(self.inbox.resolve()),
            "allowedProjects": ["control-panel"],
            "maxBytes": 1024,
            "extra": True,
        }), encoding="utf-8")
        with self.assertRaises(ChiefTaskIngressError):
            load_ingress_config(str(unknown))
        self.assertFalse(self.marker.exists())

    def test_corrupt_sidecar_fail_closed_does_not_rerun(self):
        self.drop(self.envelope("TASK-R2-SIDE", title="Has identity"))
        first = self.importer.ingest_once()[0]
        sidecar = self.inbox / "TASK-R2-SIDE.identity.json"
        self.assertTrue(sidecar.is_file())
        sidecar.write_text("{not-json", encoding="utf-8")
        receipt = self.importer.ingest_once()[0]
        after = self.repository.get_task("TASK-R2-SIDE")
        self.assertEqual(after["state"], "READY")
        self.assertEqual(after["version"], first["taskVersion"])
        self.assertIn("identity", (receipt["error"] or "").casefold())
        self.assertFalse(self.marker.exists())

    def test_identity_publisher_sees_running_then_review(self):
        with self.repository.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        slow = self.root / "slow_executor.py"
        slow.write_text(FAKE_SLOW, encoding="utf-8")
        self.command = [sys.executable, str(slow), str(self.marker)]
        self.drop(self.envelope("TASK-R3-SLOW", title="Slow fake"))
        self.importer.ingest_once()
        seen = []
        stop = threading.Event()

        def pump():
            while not stop.is_set():
                self.importer.reporter.publish_identities()
                path = self.inbox / "TASK-R3-SLOW.json"
                if path.is_file():
                    seen.append(json.loads(path.read_text(encoding="utf-8"))["state"])
                    if seen[-1] == "REVIEW":
                        return
                time.sleep(0.05)

        worker = threading.Thread(target=pump)
        worker.start()
        try:
            result = self.run_daemon()
        finally:
            stop.set()
            worker.join(timeout=5)
        self.assertEqual(result["task_state"], "REVIEW")
        self.assertTrue(any(state in {"CLAIMED", "RUNNING"} for state in seen))
        self.assertEqual(self.repository.get_task("TASK-R3-SLOW")["state"], "REVIEW")
        receipt = json.loads((self.inbox / "TASK-R3-SLOW.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["state"], "REVIEW")
        self.assertTrue(receipt.get("leaseId"))
        self.assertTrue(receipt.get("originalHash"))

    def test_halt_publishes_final_receipt_without_changing_task(self):
        self.drop(self.envelope("TASK-R3-HALT", title="Will halt"))
        first = self.importer.ingest_once()[0]
        self.assertEqual(first["state"], "READY")
        self.dispatcher.set_project_baseline("control-panel", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", "planner")
        halt = self.root / "halt.json"
        result = CursorDaemon(
            CursorRunner(self.dispatcher, "cursor-r2", self.command, timeout_seconds=5),
            "control-panel", idle_seconds=0, halt_file=halt, reject_limit=3,
            reporter=self.reporter.report_cycle,
        ).run()
        self.assertEqual(result["status"], "halted")
        after = self.repository.get_task("TASK-R3-HALT")
        self.assertEqual(after["state"], "READY")
        self.assertEqual(after["version"], first["taskVersion"])
        receipt = json.loads((self.inbox / "TASK-R3-HALT.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["state"], "READY")
        self.assertEqual(receipt["originalHash"], first["sourceHash"])
        self.assertTrue(receipt.get("error"))
        self.assertFalse(self.marker.exists())

    def test_empty_queue_does_not_rewrite_unrelated_inbox_files(self):
        self.drop(self.envelope("TASK-R3-IDLE", title="Stable identity"))
        self.importer.ingest_once()
        receipt_path = self.inbox / "TASK-R3-IDLE.json"
        identity_path = self.inbox / "TASK-R3-IDLE.identity.json"
        decoy = self.inbox / "noise.txt"
        decoy.write_text("leave me\n", encoding="utf-8")
        before = {
            "receipt": receipt_path.stat().st_mtime_ns,
            "identity": identity_path.stat().st_mtime_ns,
            "decoy": decoy.stat().st_mtime_ns,
        }
        names = sorted(p.name for p in self.inbox.iterdir())
        updated = self.importer.reporter.publish_identities()
        self.assertEqual(updated, [])
        self.assertEqual(sorted(p.name for p in self.inbox.iterdir()), names)
        self.assertEqual(receipt_path.stat().st_mtime_ns, before["receipt"])
        self.assertEqual(identity_path.stat().st_mtime_ns, before["identity"])
        self.assertEqual(decoy.read_text(encoding="utf-8"), "leave me\n")
        idle = self.importer.cycle()
        self.assertEqual(idle["published"], [])
        self.assertEqual(receipt_path.stat().st_mtime_ns, before["receipt"])
        self.assertFalse(self.marker.exists())

    def test_ingress_and_runner_plist_examples_lint(self):
        repo = Path(__file__).resolve().parents[1]
        runner = repo / "scripts" / "com.pojian.chief-cursor-runner.plist.example"
        ingress = repo / "scripts" / "com.pojian.chief-task-ingress.plist.example"
        for path in (runner, ingress):
            checked = subprocess.run(["plutil", "-lint", str(path)], capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertTrue(plist_keepalive_is_limited(path))
        arguments = plist_program_arguments(runner)
        self.assertIn("--inbox-dir", arguments)
        ingress_args = plist_program_arguments(ingress)
        self.assertIn("--ingress-config", ingress_args)
        self.assertIn("--halt-file", ingress_args)
        self.assertIn("--log-file", ingress_args)

    def test_real_ingress_script_idle_cycle_does_not_start_executor(self):
        config_path = self.root / "projects.local.json"
        config_path.write_text(json.dumps({
            "database": str(self.db),
            "projects": [{
                "id": "control-panel", "name": "Panel", "kind": "control_plane", "owner": "Owner",
                "root": str(self.root), "ledger": "TASKS.md", "status": "STATE.md",
                "knowledge_roots": [], "enabled_agents": ["knowledge", "observer", "release"],
            }],
        }), encoding="utf-8")
        ingress_config = self.root / "ingress.local.json"
        ingress_config.write_text(json.dumps({
            "outboxDir": str(self.outbox.resolve()),
            "inboxDir": str(self.inbox.resolve()),
            "allowedProjects": ["control-panel"],
            "maxBytes": DEFAULT_MAX_BYTES,
        }), encoding="utf-8")
        script = Path(__file__).resolve().parents[1] / "scripts" / "run_chief_task_ingress.py"
        argv = [
            sys.executable, str(script),
            "--config", str(config_path),
            "--ingress-config", str(ingress_config),
            "--idle-seconds", "0",
            "--max-cycles", "1",
            "--log-file", str(self.root / "ingress.log"),
            "--halt-file", str(self.root / "ingress.halt.json"),
        ]
        env = dict(__import__("os").environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        completed = subprocess.run(argv, capture_output=True, text=True, env=env, cwd=str(self.root), timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / "ingress.halt.json").exists())


if __name__ == "__main__":
    unittest.main()
