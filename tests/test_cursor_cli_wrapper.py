import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from control_plane.services.cursor_cli_wrapper import (
    CursorCliWrapperError, build_cli_command, invoke_cursor_cli, load_runner_config,
    main as wrapper_main, parse_task_payload,
)
from control_plane.services.cursor_daemon import CursorDaemon, CursorDaemonError
from control_plane.config import ProjectConfig
from control_plane.domain.models import AgentType, TaskState
from control_plane.services import CursorRunner, LeaseDispatcher, TaskRegistry, task_from_dict
from control_plane.storage import Repository


FAKE_AGENT = """#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
capture = Path(os.environ["FAKE_AGENT_CAPTURE"])
record = {"argv": sys.argv, "cwd": os.getcwd()}
if len(sys.argv) > 1 and sys.argv[1] == "status":
    record["mode"] = "status"
    capture.write_text(json.dumps(record), encoding="utf-8")
    authenticated = os.environ.get("FAKE_AGENT_AUTH", "1") == "1"
    print(json.dumps({"isAuthenticated": authenticated}))
    raise SystemExit(0)
if os.environ.get("FAKE_AGENT_SLEEP"):
    time.sleep(float(os.environ["FAKE_AGENT_SLEEP"]))
if os.environ.get("FAKE_AGENT_FAIL"):
    print("token=sk-live-supersecret", file=sys.stderr)
    raise SystemExit(3)
record["mode"] = "print"
record["stdin"] = sys.stdin.read()
capture.write_text(json.dumps(record), encoding="utf-8")
print(json.dumps({"ok": True}))
"""


class CursorCliWrapperTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cli = self.root / "fake-agent"
        self.cli.write_text(FAKE_AGENT, encoding="utf-8")
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IXUSR)
        self.capture = self.root / "captured.json"
        self.config_path = self.root / "cursor-runner.local.json"
        self.write_config()
        self.payload = {
            "taskId": "TASK-R1-PILOT",
            "projectId": "control-panel",
            "title": "pilot",
            "objective": "Write the fixed report only.",
            "scope": ["reports"],
            "acceptance": ["REVIEW"],
            "workspaceRoots": [str(self.root)],
            "approvalClass": "none",
            "ownerApprovalRef": None,
            "leaseId": "lease-1",
            "taskVersion": 2,
            "baselineRef": "abc123",
        }
        self.env = {
            **os.environ,
            "FAKE_AGENT_CAPTURE": str(self.capture),
            "FAKE_AGENT_AUTH": "1",
        }
        self.env.pop("CURSOR_API_KEY", None)

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self, **updates):
        body = {
            "cliPath": str(self.cli),
            "projectAllowlist": ["control-panel"],
            "timeoutSeconds": 5,
        }
        body.update(updates)
        self.config_path.write_text(json.dumps(body), encoding="utf-8")

    def recorded(self):
        return json.loads(self.capture.read_text(encoding="utf-8"))

    def test_config_refuses_relative_or_bare_cli_path_and_secrets(self):
        with self.assertRaisesRegex(CursorCliWrapperError, "absolute"):
            load_runner_config("cursor-runner.local.json")
        self.write_config(cliPath="agent")
        with self.assertRaisesRegex(CursorCliWrapperError, "absolute executable path"):
            load_runner_config(str(self.config_path))
        self.write_config(cliPath=str(self.cli), apiKey="sk-live-supersecret")
        with self.assertRaisesRegex(CursorCliWrapperError, "must not contain secrets"):
            load_runner_config(str(self.config_path))

    def test_payload_validation_is_strict(self):
        with self.assertRaisesRegex(CursorCliWrapperError, "missing fields"):
            parse_task_payload("{}")
        bad = dict(self.payload)
        bad["extra"] = "nope"
        with self.assertRaisesRegex(CursorCliWrapperError, "unknown fields"):
            parse_task_payload(json.dumps(bad))
        db = dict(self.payload, approvalClass="database_write", ownerApprovalRef=None)
        with self.assertRaisesRegex(CursorCliWrapperError, "ownerApprovalRef is required"):
            parse_task_payload(json.dumps(db))

    def test_success_passes_task_as_argv_data_without_shell_concat(self):
        completed = invoke_cursor_cli(self.payload, load_runner_config(str(self.config_path)), self.env)
        self.assertEqual(completed.returncode, 0)
        recorded = self.recorded()
        self.assertEqual(recorded["mode"], "print")
        self.assertEqual(recorded["argv"][0], str(self.cli))
        self.assertIn("--print", recorded["argv"])
        self.assertIn("--force", recorded["argv"])
        self.assertIn("--trust", recorded["argv"])
        self.assertNotIn("Write the fixed report only.", " ".join(recorded["argv"][:-1]))
        prompt = json.loads(recorded["argv"][-1])
        self.assertEqual(prompt["task"]["objective"], "Write the fixed report only.")
        self.assertEqual(recorded["stdin"], "")
        command = build_cli_command(str(self.cli), self.root, self.payload)
        self.assertFalse(any("&&" in part or ";" in part or "|" in part for part in command[:-1]))

    def test_unauthenticated_refuses_to_start_print_mode(self):
        env = dict(self.env, FAKE_AGENT_AUTH="0")
        with self.assertRaisesRegex(CursorCliWrapperError, "not authenticated"):
            invoke_cursor_cli(self.payload, load_runner_config(str(self.config_path)), env)
        self.assertEqual(self.recorded()["mode"], "status")

    def test_nonzero_exit_is_fail_closed_and_redacted_by_main(self):
        env = dict(self.env, FAKE_AGENT_FAIL="1")
        stderr = StringIO()
        old = sys.stderr
        try:
            sys.stderr = stderr
            code = wrapper_main(
                ["--runner-config", str(self.config_path)],
                stdin=StringIO(json.dumps(self.payload)),
                env=env,
            )
        finally:
            sys.stderr = old
        self.assertEqual(code, 1)
        self.assertNotIn("sk-live-supersecret", stderr.getvalue())
        self.assertIn("[REDACTED]", stderr.getvalue())

    def test_foreign_project_is_rejected_before_cli(self):
        with self.assertRaisesRegex(CursorCliWrapperError, "allowlist"):
            invoke_cursor_cli(
                dict(self.payload, projectId="julius"),
                load_runner_config(str(self.config_path)),
                self.env,
            )
        self.assertFalse(self.capture.exists())

    def test_wrapper_main_requires_explicit_config(self):
        stderr = StringIO()
        old = sys.stderr
        try:
            sys.stderr = stderr
            with self.assertRaises(SystemExit):
                wrapper_main([])
        finally:
            sys.stderr = old


class CursorDaemonTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._init_git()
        self.repository = Repository(self.root / "control.sqlite3")
        self.repository.migrate()
        self.repository.upsert_project(ProjectConfig(
            id="control-panel", name="Panel", kind="control_plane", owner="Owner", root=self.root,
            ledger=self.root / "TASKS.md", status=self.root / "STATE.md",
            knowledge_roots=[], enabled_agents=list(AgentType),
        ))
        self.registry = TaskRegistry(self.repository)
        self.dispatcher = LeaseDispatcher(self.repository, default_ttl_seconds=30)
        self.dispatcher.register_executor("cursor-r1", ["control-panel"], "low")
        self.head = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True,
        ).strip()
        self.dispatcher.set_project_baseline("control-panel", self.head, "planner")
        self.calls = []
        script = self.root / "fake.py"
        script.write_text(
            "import json,sys\nfrom pathlib import Path\n"
            "Path(sys.argv[1]).write_text('called')\n",
            encoding="utf-8",
        )
        self.marker = self.root / "called"
        self.command = [sys.executable, str(script), str(self.marker)]
        self.slept = []

    def tearDown(self):
        self.temp.cleanup()

    def _init_git(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "r1@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "R1"], check=True)
        (self.root / "README").write_text("workspace\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "README"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)

    def runner(self):
        return CursorRunner(self.dispatcher, "cursor-r1", self.command, timeout_seconds=5)

    def test_isolated_project_cannot_start_daemon(self):
        with self.assertRaisesRegex(CursorDaemonError, "not allowed"):
            CursorDaemon(self.runner(), "julius", idle_seconds=0)

    def test_empty_queue_stays_idle_and_does_not_call_executor(self):
        logs = []
        result = CursorDaemon(
            self.runner(), "control-panel", idle_seconds=0, log=logs.append, sleep=self.slept.append,
        ).run(max_cycles=1)
        self.assertEqual(result["status"], "idle")
        self.assertFalse(self.marker.exists())
        self.assertTrue(any("idle" in item for item in logs))
        self.assertEqual(self.slept, [])

    def test_ready_task_runs_once_then_can_idle(self):
        task = self.registry.register(task_from_dict({
            "id": "TASK-R1-PILOT", "projectId": "control-panel", "title": "pilot",
            "objective": "Write the report.", "scope": ["reports"], "acceptance": ["REVIEW"],
            "priority": "P2", "riskLevel": "low", "allowedExecutors": ["cursor-r1"],
            "workspaceRoots": [str(self.root)], "dependencies": [], "approvalClass": "none",
        }), "planner")
        self.registry.transition("TASK-R1-PILOT", TaskState.READY, task["version"], "policy", "safe")
        daemon = CursorDaemon(self.runner(), "control-panel", idle_seconds=0, sleep=self.slept.append)
        first = daemon.run(max_cycles=1)
        self.assertEqual((first["status"], first["task_state"]), ("completed", "REVIEW"))
        self.assertTrue(self.marker.exists())
        self.marker.unlink()
        second = daemon.run(max_cycles=1)
        self.assertEqual(second["status"], "idle")
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.repository.get_task("TASK-R1-PILOT")["state"], "REVIEW")

    def test_unsafe_ready_task_is_logged_and_does_not_crash_or_invoke(self):
        outside = Path(tempfile.mkdtemp())
        try:
            task = self.registry.register(task_from_dict({
                "id": "TASK-R1-BAD", "projectId": "control-panel", "title": "bad",
                "objective": "Reject me.", "scope": ["gate"], "acceptance": ["rejected"],
                "priority": "P2", "riskLevel": "low", "allowedExecutors": ["cursor-r1"],
                "workspaceRoots": [str(outside)], "dependencies": [], "approvalClass": "none",
            }), "planner")
            self.registry.transition("TASK-R1-BAD", TaskState.READY, task["version"], "policy", "safe")
            logs = []
            result = CursorDaemon(
                self.runner(), "control-panel", idle_seconds=0, log=logs.append, sleep=self.slept.append,
            ).run(max_cycles=1)
            self.assertEqual(result["status"], "rejected")
            self.assertIn("outside the authorized project root", result["error"])
            self.assertFalse(self.marker.exists())
            self.assertEqual(self.repository.get_task("TASK-R1-BAD")["state"], "READY")
        finally:
            for child in outside.iterdir():
                if child.is_file():
                    child.unlink()
            outside.rmdir()


if __name__ == "__main__":
    unittest.main()
