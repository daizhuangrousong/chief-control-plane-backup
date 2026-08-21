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
    main as wrapper_main, parse_task_payload, unpack_cli_json,
)
from control_plane.services.cursor_daemon import CursorDaemon, CursorDaemonError
from control_plane.services.cursor_keychain import (
    CursorKeychainError, executor_environment, load_cursor_api_key,
)
from control_plane.services.cursor_launch import (
    CursorLaunchError, filter_cli_env, parse_executor_command, parse_runner_argv,
    plist_keepalive_is_limited, plist_program_arguments,
)
from control_plane.config import ProjectConfig
from control_plane.domain.models import AgentType, TaskState
from control_plane.services import (
    CursorRunner, LeaseDispatcher, TaskRegistry, task_from_dict, verification_commands_for,
)
from control_plane.storage import Repository


KEYCHAIN_FLAGS = [
    "--cursor-keychain-service", "com.pojian.chief-cursor-api",
    "--cursor-keychain-account", "pojian",
]
CANARY_SECRET = "canary-secret-value-do-not-log"

FAKE_AGENT = """#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
here = Path(__file__).resolve().parent
capture = here / "captured.json"
canaries = ("canary-feishu-secret", "canary-generic-token", "canary-unrelated")
values = [os.environ.get(name) or "" for name in os.environ]
record = {
    "argv": sys.argv,
    "cwd": os.getcwd(),
    "env_names": sorted(os.environ),
    "leaked_canary": any(item in blob for blob in values for item in canaries),
    "has_feishu_secret_name": "FEISHU_APP_SECRET" in os.environ,
    "has_generic_token_name": "GENERIC_TOKEN" in os.environ,
    "has_unrelated_name": "UNRELATED_KEY" in os.environ,
    "has_cursor_api_key_name": "CURSOR_API_KEY" in os.environ,
}
if len(sys.argv) > 1 and sys.argv[1] == "status":
    record["mode"] = "status"
    capture.write_text(json.dumps(record), encoding="utf-8")
    authenticated = (here / "auth").read_text(encoding="utf-8").strip() == "1"
    print(json.dumps({"isAuthenticated": authenticated}))
    raise SystemExit(0)
if (here / "fail").exists():
    print("token=sk-live-supersecret", file=sys.stderr)
    raise SystemExit(3)
record["mode"] = "print"
record["stdin"] = sys.stdin.read()
capture.write_text(json.dumps(record), encoding="utf-8")
if (here / "envelope.json").exists():
    sys.stdout.write((here / "envelope.json").read_text(encoding="utf-8"))
    raise SystemExit(0)
print(json.dumps({"ok": True}))
"""


class CursorCliWrapperTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cli = self.root / "fake-agent"
        self.cli.write_text(FAKE_AGENT, encoding="utf-8")
        self.cli.chmod(self.cli.stat().st_mode | stat.S_IXUSR)
        (self.root / "auth").write_text("1\n", encoding="utf-8")
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
            "verification": [{"id": "verify-1", "criterion": "REVIEW"}],
            "workspaceRoots": [str(self.root)],
            "approvalClass": "none",
            "ownerApprovalRef": None,
            "leaseId": "lease-1",
            "taskVersion": 2,
            "baselineRef": "abc123",
        }
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin"),
            "HOME": str(self.root),
            "LANG": "C",
        }

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
        missing_verification = dict(self.payload)
        del missing_verification["verification"]
        with self.assertRaisesRegex(CursorCliWrapperError, "missing fields"):
            parse_task_payload(json.dumps(missing_verification))
        forged = dict(self.payload, verification=[{"id": "verify-1", "criterion": "REVIEW", "argv": ["rm", "-rf"]}])
        with self.assertRaisesRegex(CursorCliWrapperError, "unknown fields"):
            parse_task_payload(json.dumps(forged))

    def test_prompt_requires_scoped_single_commit_not_model_schema(self):
        command = build_cli_command(str(self.cli), self.root, self.payload)
        prompt = json.loads(command[-1])
        constraints = " ".join(prompt["constraints"])
        self.assertIn("exactly one git commit", constraints)
        self.assertNotIn("executor-result/1.0.0", constraints)
        self.assertIn("not acceptance", constraints)
        self.assertIn("task.scope", constraints)
        self.assertNotIn("Do not run git commit", constraints)
        self.assertNotIn("Do not modify source code", constraints)
        self.assertFalse(any("&&" in part or ";" in part or "|" in part for part in command[:-1]))

    def _executor_result(self, **updates):
        body = {
            "schemaVersion": "executor-result/1.0.0",
            "taskId": self.payload["taskId"],
            "taskVersion": self.payload["taskVersion"],
            "leaseId": self.payload["leaseId"],
            "commitRef": "abc123def",
            "acceptanceChecks": [{
                "criterion": "REVIEW",
                "commandId": "verify-1",
                "status": "pass",
                "evidence": "report exists",
            }],
        }
        body.update(updates)
        return body

    def _cli_envelope(self, result):
        return {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 12,
            "duration_api_ms": 12,
            "result": json.dumps(result) if not isinstance(result, str) else result,
            "session_id": "00000000-0000-0000-0000-000000000001",
        }

    def test_cli_outer_json_discards_inner_payload(self):
        result = self._executor_result()
        unpacked = unpack_cli_json(json.dumps(self._cli_envelope(result)) + "\n")
        self.assertEqual(unpacked, {"status": "ok"})
        self.assertNotIn("taskId", unpacked)
        inner = {"type": "tool_call", "id": "verify-1", "passed": True, "token": "sk-live-inner-secret"}
        (self.root / "envelope.json").write_text(json.dumps(self._cli_envelope(inner)) + "\n", encoding="utf-8")
        stdout = StringIO()
        stderr = StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = stdout, stderr
            code = wrapper_main(
                ["--runner-config", str(self.config_path)],
                stdin=StringIO(json.dumps(self.payload)),
                env=self.env,
            )
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        self.assertEqual(code, 0)
        emitted = json.loads(stdout.getvalue())
        self.assertEqual(emitted, {"status": "ok"})
        self.assertNotIn("session_id", emitted)
        self.assertNotIn("sk-live-inner-secret", stdout.getvalue())
        self.assertNotIn("sk-live-inner-secret", stderr.getvalue())
        self.assertNotIn("passed", stdout.getvalue())

    def test_malicious_multiple_json_and_fake_fields_fail_closed(self):
        result = self._executor_result()
        envelope = json.dumps(self._cli_envelope(result))
        with self.assertRaisesRegex(CursorCliWrapperError, "extra text"):
            unpack_cli_json(envelope + "\n" + envelope)
        with self.assertRaisesRegex(CursorCliWrapperError, "extra text"):
            unpack_cli_json(envelope + '{"type":"result","result":{}}')
        discarded = unpack_cli_json(json.dumps(self._cli_envelope(self._executor_result(pwned=True))))
        self.assertEqual(discarded, {"status": "ok"})
        (self.root / "envelope.json").write_text(
            json.dumps(self._cli_envelope(self._executor_result(taskId="TASK-OTHER"))) + "\n",
            encoding="utf-8",
        )
        stdout = StringIO()
        stderr = StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = stdout, stderr
            code = wrapper_main(
                ["--runner-config", str(self.config_path)],
                stdin=StringIO(json.dumps(self.payload)),
                env=self.env,
            )
        finally:
            sys.stdout, sys.stderr = old_out, old_err
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"status": "ok"})
        self.assertNotIn("TASK-OTHER", stdout.getvalue())
        error_envelope = {
            "type": "result",
            "subtype": "error",
            "is_error": True,
            "result": "boom",
        }
        with self.assertRaisesRegex(CursorCliWrapperError, "error"):
            unpack_cli_json(json.dumps(error_envelope))
        (self.root / "envelope.json").write_text(envelope + "\n" + envelope, encoding="utf-8")
        stderr = StringIO()
        old = sys.stderr
        try:
            sys.stderr = stderr
            code = wrapper_main(
                ["--runner-config", str(self.config_path)],
                stdin=StringIO(json.dumps(self.payload)),
                env=self.env,
            )
        finally:
            sys.stderr = old
        self.assertEqual(code, 2)
        self.assertIn("extra text", stderr.getvalue())

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
        (self.root / "auth").write_text("0\n", encoding="utf-8")
        with self.assertRaisesRegex(CursorCliWrapperError, "not authenticated"):
            invoke_cursor_cli(self.payload, load_runner_config(str(self.config_path)), self.env)
        self.assertEqual(self.recorded()["mode"], "status")

    def test_cli_subprocess_env_drops_canary_secrets(self):
        canaries = {
            "FEISHU_APP_SECRET": "canary-feishu-secret",
            "GENERIC_TOKEN": "canary-generic-token",
            "UNRELATED_KEY": "canary-unrelated",
        }
        status_source = {
            "PATH": self.env["PATH"],
            "HOME": self.env["HOME"],
            "LANG": "C",
            **canaries,
        }
        print_source = dict(status_source)
        print_source["CURSOR_API_KEY"] = "allowed-cursor-auth"
        print_source["PYTHONPATH"] = "/trusted/src"
        filtered = filter_cli_env(print_source)
        self.assertIn("CURSOR_API_KEY", filtered)
        self.assertIn("PYTHONPATH", filtered)
        self.assertNotIn("FEISHU_APP_SECRET", filtered)
        self.assertNotIn("GENERIC_TOKEN", filtered)
        self.assertNotIn("UNRELATED_KEY", filtered)
        filtered_file = filter_cli_env({
            "PATH": "/usr/bin",
            "AGENT_CLI_CREDENTIAL_STORE": "file",
        })
        self.assertEqual(filtered_file.get("AGENT_CLI_CREDENTIAL_STORE"), "file")
        filtered_memory = filter_cli_env({
            "PATH": "/usr/bin",
            "AGENT_CLI_CREDENTIAL_STORE": "memory",
        })
        self.assertEqual(filtered_memory.get("AGENT_CLI_CREDENTIAL_STORE"), "memory")
        for bad in ("default", "keychain", "MEMORY", "memory "):
            dropped = filter_cli_env({
                "PATH": "/usr/bin",
                "AGENT_CLI_CREDENTIAL_STORE": bad,
            })
            self.assertNotIn("AGENT_CLI_CREDENTIAL_STORE", dropped, bad)
        (self.root / "auth").write_text("0\n", encoding="utf-8")
        with self.assertRaisesRegex(CursorCliWrapperError, "not authenticated"):
            invoke_cursor_cli(self.payload, load_runner_config(str(self.config_path)), status_source)
        status = self.recorded()
        self.assertEqual(status["mode"], "status")
        self.assertFalse(status["leaked_canary"])
        self.assertFalse(status["has_feishu_secret_name"])
        self.assertFalse(status["has_generic_token_name"])
        self.assertFalse(status["has_unrelated_name"])
        (self.root / "auth").write_text("1\n", encoding="utf-8")
        completed = invoke_cursor_cli(self.payload, load_runner_config(str(self.config_path)), print_source)
        self.assertEqual(completed.returncode, 0)
        printed = self.recorded()
        self.assertEqual(printed["mode"], "print")
        self.assertFalse(printed["leaked_canary"])
        self.assertFalse(printed["has_feishu_secret_name"])
        self.assertTrue(printed["has_cursor_api_key_name"])

    def test_nonzero_exit_is_fail_closed_and_redacted_by_main(self):
        (self.root / "fail").write_text("1\n", encoding="utf-8")
        stderr = StringIO()
        old = sys.stderr
        try:
            sys.stderr = stderr
            code = wrapper_main(
                ["--runner-config", str(self.config_path)],
                stdin=StringIO(json.dumps(self.payload)),
                env=self.env,
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
            "verificationCommands": verification_commands_for(["REVIEW"]),
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
                "verificationCommands": verification_commands_for(["rejected"]),
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

    def test_identical_rejections_halt_and_restart_stays_stopped(self):
        outside = Path(tempfile.mkdtemp())
        halt = self.root / "cursor-runner.halt.json"
        try:
            task = self.registry.register(task_from_dict({
                "id": "TASK-R1-PERM", "projectId": "control-panel", "title": "permanent",
                "objective": "Reject me forever.", "scope": ["gate"], "acceptance": ["rejected"],
                "verificationCommands": verification_commands_for(["rejected"]),
                "priority": "P2", "riskLevel": "low", "allowedExecutors": ["cursor-r1"],
                "workspaceRoots": [str(outside)], "dependencies": [], "approvalClass": "none",
            }), "planner")
            self.registry.transition("TASK-R1-PERM", TaskState.READY, task["version"], "policy", "safe")
            logs = []
            result = CursorDaemon(
                self.runner(), "control-panel", idle_seconds=5, log=logs.append,
                sleep=self.slept.append, halt_file=halt, reject_limit=3,
            ).run()
            self.assertEqual(result["status"], "halted")
            self.assertEqual(result["waitingFor"], "Chief")
            self.assertEqual(result["cycles"], 3)
            self.assertEqual(self.slept, [5, 5])
            self.assertTrue(halt.is_file())
            halt_text = halt.read_text(encoding="utf-8")
            self.assertIn("circuit breaker", halt_text)
            self.assertNotIn("sk-", halt_text)
            self.assertFalse(self.marker.exists())
            self.assertEqual(self.repository.get_task("TASK-R1-PERM")["state"], "READY")
            restart_sleep = []
            restarted = CursorDaemon(
                self.runner(), "control-panel", idle_seconds=5, sleep=restart_sleep.append,
                halt_file=halt, reject_limit=3,
            ).run()
            self.assertEqual(restarted["status"], "halted")
            self.assertEqual(restarted["cycles"], 0)
            self.assertEqual(restart_sleep, [])
            self.assertFalse(self.marker.exists())
        finally:
            for child in outside.iterdir():
                if child.is_file():
                    child.unlink()
            outside.rmdir()

    def test_idle_does_not_trip_circuit_breaker(self):
        halt = self.root / "cursor-runner.halt.json"
        result = CursorDaemon(
            self.runner(), "control-panel", idle_seconds=0, sleep=self.slept.append,
            halt_file=halt, reject_limit=1,
        ).run(max_cycles=3)
        self.assertEqual(result["status"], "idle")
        self.assertFalse(halt.exists())
        self.assertFalse(self.marker.exists())


class CursorLaunchContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = Path(__file__).resolve().parents[1]
        self.example = self.repo / "scripts" / "com.pojian.chief-cursor-runner.plist.example"

    def tearDown(self):
        self.temp.cleanup()

    def test_executor_command_json_is_unambiguous(self):
        with self.assertRaisesRegex(CursorLaunchError, "JSON array"):
            parse_executor_command("/usr/bin/python3")
        with self.assertRaisesRegex(CursorLaunchError, "absolute"):
            parse_executor_command(json.dumps(["agent", "--print"]))
        command = parse_executor_command(json.dumps([
            "/usr/bin/python3", "/wrapper.py", "--runner-config", "/cfg.json",
        ]))
        self.assertEqual(command[2], "--runner-config")
        self.assertNotIn("--project", command)

    def test_parse_runner_argv_none_reads_process_args(self):
        config_path = self.root / "projects.local.json"
        log_file = self.root / "runner.log"
        halt_file = self.root / "halt.json"
        config_path.write_text("{}", encoding="utf-8")
        process_argv = [
            "run_cursor_runner.py",
            "--config", str(config_path),
            "--executor-id", "cursor-r1",
            "--executor-command", json.dumps(["/usr/bin/python3", "/wrapper.py"]),
            "--project", "control-panel",
            "--log-file", str(log_file),
            "--halt-file", str(halt_file),
            "--lifecycle-config", str(self.root / "execution-lifecycle.json"),
            *KEYCHAIN_FLAGS,
            "--max-cycles", "1",
        ]
        from unittest import mock
        with mock.patch.object(sys, "argv", process_argv):
            args = parse_runner_argv(None)
        self.assertEqual(args.project, "control-panel")
        self.assertEqual(args.max_cycles, 1)
        self.assertEqual(args.executor_command, ["/usr/bin/python3", "/wrapper.py"])
        self.assertTrue(Path(args.lifecycle_config).is_absolute())
        self.assertEqual(args.cursor_keychain_service, "com.pojian.chief-cursor-api")
        self.assertEqual(args.cursor_keychain_account, "pojian")

    def test_plist_syntax_keepalive_and_equivalent_argv_idle(self):
        checked = subprocess.run(["plutil", "-lint", str(self.example)], capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertTrue(plist_keepalive_is_limited(self.example))
        arguments = plist_program_arguments(self.example)
        self.assertEqual(arguments[0], "/usr/bin/python3")
        self.assertIn("--executor-command", arguments)
        self.assertIn("--lifecycle-config", arguments)
        self.assertIn("--cursor-keychain-service", arguments)
        self.assertIn("--cursor-keychain-account", arguments)
        command_index = arguments.index("--executor-command")
        project_index = arguments.index("--project")
        lifecycle_index = arguments.index("--lifecycle-config")
        service_index = arguments.index("--cursor-keychain-service")
        account_index = arguments.index("--cursor-keychain-account")
        self.assertLess(command_index, project_index)
        parse_executor_command(arguments[command_index + 1])
        self.assertEqual(arguments[project_index + 1], "control-panel")
        self.assertTrue(Path(arguments[lifecycle_index + 1]).is_absolute())
        self.assertEqual(arguments[service_index + 1], "com.pojian.chief-cursor-api")
        self.assertEqual(arguments[account_index + 1], "pojian")
        with self.example.open("rb") as handle:
            plist = __import__("plistlib").load(handle)
        env = plist.get("EnvironmentVariables") or {}
        self.assertNotIn("HOME", env)
        self.assertNotIn("CURSOR_API_KEY", env)
        self.assertNotIn("CURSOR_API_KEY", self.example.read_text(encoding="utf-8"))

        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "r11@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "R11"], check=True)
        (self.root / "README").write_text("workspace\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "README"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)
        marker = self.root / "called"
        fake = self.root / "fake.py"
        fake.write_text(
            "from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('called')\n",
            encoding="utf-8",
        )
        config_path = self.root / "projects.local.json"
        config_path.write_text(json.dumps({
            "database": str(self.root / "control.sqlite3"),
            "projects": [{
                "id": "control-panel", "name": "Panel", "kind": "control_plane", "owner": "Owner",
                "root": str(self.root), "ledger": "TASKS.md", "status": "STATE.md",
                "knowledge_roots": [], "enabled_agents": ["knowledge", "observer", "release"],
            }],
        }), encoding="utf-8")
        argv = [
            "--config", str(config_path),
            "--executor-id", "cursor-r1",
            "--executor-command", json.dumps([sys.executable, str(fake), str(marker)]),
            "--project", "control-panel",
            "--idle-seconds", "0",
            "--log-file", str(self.root / "runner.log"),
            "--halt-file", str(self.root / "halt.json"),
            "--lifecycle-config", str(self.root / "execution-lifecycle.json"),
            *KEYCHAIN_FLAGS,
            "--max-cycles", "1",
        ]
        args = parse_runner_argv(argv)
        self.assertEqual(args.project, "control-panel")
        self.assertEqual(args.executor_command, [sys.executable, str(fake), str(marker)])
        self.assertNotIn("--project", args.executor_command)
        self.assertTrue(Path(args.lifecycle_config).is_absolute())

        from control_plane.config import load_settings
        from control_plane.services import CursorRunner, LeaseDispatcher
        from control_plane.storage import Repository
        settings = load_settings(str(config_path))
        repository = Repository(settings.database)
        repository.migrate()
        for project in settings.projects:
            repository.upsert_project(project)
        dispatcher = LeaseDispatcher(repository)
        dispatcher.register_executor("cursor-r1", ["control-panel"], "low")
        head = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        dispatcher.set_project_baseline("control-panel", head, "planner")
        result = CursorDaemon(
            CursorRunner(dispatcher, args.executor_id, args.executor_command, timeout_seconds=5),
            args.project, idle_seconds=args.idle_seconds, halt_file=Path(args.halt_file),
        ).run(max_cycles=args.max_cycles)
        self.assertEqual(result["status"], "idle")
        self.assertFalse(marker.exists())

    def test_real_script_entry_with_none_argv_idles_empty_queue(self):
        import shutil
        import control_plane
        runtime = self.root / "runtime"
        project = self.root / "project"
        state = self.root / "state"
        for path, name in ((runtime, "Runtime"), (project, "Project")):
            path.mkdir(parents=True)
            subprocess.run(["git", "init", "-b", "main", "-q", str(path)], check=True)
            subprocess.run(["git", "-C", str(path), "config", "user.email", "r12@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(path), "config", "user.name", name], check=True)
        dest = runtime / "src" / "control_plane"
        dest.parent.mkdir(parents=True)
        shutil.copytree(
            Path(control_plane.__file__).resolve().parent, dest,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        (runtime / "README").write_text("runtime\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(runtime), "add", "README", "src"], check=True)
        subprocess.run(["git", "-C", str(runtime), "commit", "-qm", "runtime"], check=True)
        (project / "README").write_text("project\n", encoding="utf-8")
        (project / ".gitignore").write_text("var/\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(project), "add", "README", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(project), "commit", "-qm", "fixture"], check=True)
        state.mkdir()
        pool_root = project / "var" / "task-worktrees"
        report_dir = state / "execution-reports"
        marker = state / "called"
        fake = state / "fake.py"
        fake.write_text(
            "from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('called')\n",
            encoding="utf-8",
        )
        config_path = state / "projects.local.json"
        config_path.write_text(json.dumps({
            "database": str(state / "control.sqlite3"),
            "projects": [{
                "id": "control-panel", "name": "Panel", "kind": "control_plane", "owner": "Owner",
                "root": str(project), "ledger": "TASKS.md", "status": "STATE.md",
                "knowledge_roots": [], "enabled_agents": ["knowledge", "observer", "release"],
            }],
        }), encoding="utf-8")
        lifecycle = state / "execution-lifecycle.json"
        lifecycle.write_text(json.dumps({
            "runtimeRoot": str(runtime),
            "projectRoot": str(project),
            "poolRoot": str(pool_root),
            "stateRoot": str(state),
            "executionReportDir": str(report_dir),
            "database": str(state / "control.sqlite3"),
            "executorResultSchemaVersion": "executor-result/1.0.0",
            "verificationCommands": "Chief-authored argv arrays; merger does not re-run them",
            "targetBranch": "main",
            "mergerId": "merge-r4",
            "allowedReviewActors": ["chief"],
            "threatModel": "tier1-same-user-fallible",
            "nextAllowedAttach": "eval-r5",
            "invariants": {"runtimeAndProject": "distinct"},
            "cleanupRollback": {"keepRuntimeHead": True},
        }), encoding="utf-8")
        from control_plane.config import load_settings
        from control_plane.services import LeaseDispatcher
        from control_plane.storage import Repository
        settings = load_settings(str(config_path))
        repository = Repository(settings.database)
        repository.migrate()
        for item in settings.projects:
            repository.upsert_project(item)
        dispatcher = LeaseDispatcher(repository)
        dispatcher.register_executor("cursor-r1", ["control-panel"], "low")
        head = subprocess.check_output(["git", "-C", str(project), "rev-parse", "HEAD"], text=True).strip()
        dispatcher.set_project_baseline("control-panel", head, "planner")
        log_file = state / "runner.log"
        halt_file = state / "halt.json"
        argv = [
            "--config", str(config_path),
            "--executor-id", "cursor-r1",
            "--executor-command", json.dumps([sys.executable, str(fake), str(marker)]),
            "--project", "control-panel",
            "--idle-seconds", "0",
            "--log-file", str(log_file),
            "--halt-file", str(halt_file),
            "--lifecycle-config", str(lifecycle),
            *KEYCHAIN_FLAGS,
            "--max-cycles", "1",
        ]
        script = self.repo / "scripts" / "run_cursor_runner.py"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.repo / "src")
        completed = subprocess.run(
            [sys.executable, str(script), *argv],
            capture_output=True, text=True, env=env, cwd=str(self.root), timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("TypeError", completed.stderr)
        self.assertTrue(log_file.is_file())
        log_text = log_file.read_text(encoding="utf-8")
        self.assertIn("idle: no eligible READY task", log_text)
        self.assertNotIn("rejected", log_text)
        self.assertNotIn("halted", log_text)
        self.assertNotIn("CURSOR_API_KEY=", log_text)
        self.assertFalse(marker.exists())
        self.assertFalse(halt_file.exists())

    def test_old_plist_without_lifecycle_does_not_call_executor(self):
        marker = self.root / "called"
        fake = self.root / "fake.py"
        fake.write_text(
            "from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('called')\n",
            encoding="utf-8",
        )
        config_path = self.root / "projects.local.json"
        config_path.write_text(json.dumps({
            "database": str(self.root / "control.sqlite3"),
            "projects": [{
                "id": "control-panel", "name": "Panel", "kind": "control_plane", "owner": "Owner",
                "root": str(self.root), "ledger": "TASKS.md", "status": "STATE.md",
                "knowledge_roots": [], "enabled_agents": ["knowledge", "observer", "release"],
            }],
        }), encoding="utf-8")
        argv = [
            "--config", str(config_path),
            "--executor-id", "cursor-r1",
            "--executor-command", json.dumps([sys.executable, str(fake), str(marker)]),
            "--project", "control-panel",
            "--idle-seconds", "0",
            "--log-file", str(self.root / "runner.log"),
            "--halt-file", str(self.root / "halt.json"),
            "--max-cycles", "1",
        ]
        script = self.repo / "scripts" / "run_cursor_runner.py"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.repo / "src")
        completed = subprocess.run(
            [sys.executable, str(script), *argv],
            capture_output=True, text=True, env=env, cwd=str(self.root), timeout=20,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertIn("lifecycle-config", (completed.stderr or "").lower())


class CursorKeychainTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _fake_security(self, mode):
        path = self.root / "fake-security-{}".format(mode)
        if mode == "missing":
            body = (
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "sys.stdout.write('secret-must-not-leak\\n')\n"
                "sys.stderr.write('item not found\\n')\n"
                "sys.exit(44)\n"
            )
        elif mode == "empty":
            body = "#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n"
        else:
            body = (
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "argv = sys.argv[1:]\n"
                "if '-w' not in argv or '-s' not in argv or '-a' not in argv:\n"
                "    sys.exit(2)\n"
                "sys.stdout.write(%r)\n"
                "sys.exit(0)\n"
            ) % (CANARY_SECRET + "\n",)
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return path

    def test_missing_or_empty_key_fails_closed_without_leaking_stdout(self):
        missing = self._fake_security("missing")
        with self.assertRaises(CursorKeychainError) as ctx:
            load_cursor_api_key("com.pojian.chief-cursor-api", "pojian", security_binary=missing)
        message = str(ctx.exception)
        self.assertNotIn("secret-must-not-leak", message)
        self.assertNotIn("item not found", message)
        empty = self._fake_security("empty")
        with self.assertRaisesRegex(CursorKeychainError, "empty"):
            load_cursor_api_key("com.pojian.chief-cursor-api", "pojian", security_binary=empty)

    def test_success_injects_child_env_only_and_does_not_log_secret(self):
        fake = self._fake_security("ok")
        parent_before = os.environ.get("CURSOR_API_KEY")
        key = load_cursor_api_key("com.pojian.chief-cursor-api", "pojian", security_binary=fake)
        self.assertEqual(key, CANARY_SECRET)
        self.assertEqual(os.environ.get("CURSOR_API_KEY"), parent_before)
        environment = executor_environment(key, {"PATH": "/usr/bin", "CURSOR_API_KEY": "inherited-must-drop"})
        self.assertEqual(environment["CURSOR_API_KEY"], CANARY_SECRET)
        self.assertEqual(os.environ.get("CURSOR_API_KEY"), parent_before)
        self.assertNotIn(CANARY_SECRET, repr(environment))
        self.assertNotIn(CANARY_SECRET, str(environment))
        from control_plane.services.cursor_runner import CursorRunner
        runner = object.__new__(CursorRunner)
        runner.executor_id = "cursor-r1"
        runner._source_env = dict(environment)
        self.assertNotIn(CANARY_SECRET, repr(runner))
        leaked = []
        for path in self.root.rglob("*"):
            if not path.is_file() or path == fake:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if CANARY_SECRET in text:
                leaked.append(str(path))
        self.assertEqual(leaked, [])


if __name__ == "__main__":
    unittest.main()
