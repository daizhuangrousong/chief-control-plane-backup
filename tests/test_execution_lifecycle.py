import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import control_plane
from control_plane.config import ProjectConfig
from control_plane.domain.models import AgentType
from control_plane.services import (
    BaselinePromoter, ChiefReviewDecisionError, ChiefReviewInbox, ChiefTaskImporter, CursorDaemon,
    CursorRunner, DECISION_VERSION, LeaseDispatcher, ProductionRuntimeError, TaskMergeError,
    TaskMerger, TaskWorktreeError, TaskWorktreePool, load_production_runtime,
)
from control_plane.services.chief_task_ingress import ENVELOPE_VERSION, atomic_write_json
from control_plane.services.task_clone import object_inodes
from control_plane.services.task_worktree import git_common_dir
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
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
checks = []
verification = payload.get("verification") or []
for index, criterion in enumerate(payload.get("acceptance") or []):
    command_id = verification[index]["id"] if index < len(verification) else "verify-%s" % (index + 1)
    ran = subprocess.run(["test", "-f", rel])
    checks.append({
        "criterion": criterion,
        "commandId": command_id,
        "status": "pass" if ran.returncode == 0 else "fail",
        "evidence": "test -f %s exited %s" % (rel, ran.returncode),
    })
sys.stdout.write(json.dumps({
    "schemaVersion": "executor-result/1.0.0",
    "taskId": payload["taskId"],
    "taskVersion": payload["taskVersion"],
    "leaseId": payload["leaseId"],
    "commitRef": commit,
    "acceptanceChecks": checks,
}) + "\\n")
"""

FAKE_COMMIT_STORE = """
import json, os, subprocess, sys
from pathlib import Path
payload = json.loads(sys.stdin.read())
rel = sys.argv[1]
store = os.environ.get("AGENT_CLI_CREDENTIAL_STORE") or "missing"
Path(rel).parent.mkdir(parents=True, exist_ok=True)
Path(rel).write_text("store=" + store + "\\n", encoding="utf-8")
subprocess.run(["git", "add", "--", rel], check=True)
subprocess.run(["git", "commit", "-qm", "task " + payload["taskId"]], check=True)
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
checks = []
verification = payload.get("verification") or []
for index, criterion in enumerate(payload.get("acceptance") or []):
    command_id = verification[index]["id"] if index < len(verification) else "verify-%s" % (index + 1)
    ran = subprocess.run(["test", "-f", rel])
    checks.append({
        "criterion": criterion,
        "commandId": command_id,
        "status": "pass" if ran.returncode == 0 else "fail",
        "evidence": "test -f %s exited %s" % (rel, ran.returncode),
    })
sys.stdout.write(json.dumps({
    "schemaVersion": "executor-result/1.0.0",
    "taskId": payload["taskId"],
    "taskVersion": payload["taskVersion"],
    "leaseId": payload["leaseId"],
    "commitRef": commit,
    "acceptanceChecks": checks,
}) + "\\n")
"""

FAKE_FAIL_CHECK = """
import json, subprocess, sys
from pathlib import Path
payload = json.loads(sys.stdin.read())
rel = sys.argv[1]
Path(rel).parent.mkdir(parents=True, exist_ok=True)
Path(rel).write_text(sys.argv[2], encoding="utf-8")
subprocess.run(["git", "add", "--", rel], check=True)
subprocess.run(["git", "commit", "-qm", "task " + payload["taskId"]], check=True)
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
ran = subprocess.run(["test", "-f", "does-not-exist"])
sys.stdout.write(json.dumps({
    "schemaVersion": "executor-result/1.0.0",
    "taskId": payload["taskId"],
    "taskVersion": payload["taskVersion"],
    "leaseId": payload["leaseId"],
    "commitRef": commit,
    "acceptanceChecks": [{
        "criterion": (payload.get("acceptance") or ["Stay in REVIEW"])[0],
        "commandId": ((payload.get("verification") or [{"id": "verify-1"}])[0]).get("id", "verify-1"),
        "status": "fail",
        "evidence": "test -f does-not-exist exited %s" % ran.returncode,
    }],
}) + "\\n")
"""

FAKE_PLAIN = """
import json, subprocess, sys
from pathlib import Path
payload = json.loads(sys.stdin.read())
rel = sys.argv[1]
Path(rel).parent.mkdir(parents=True, exist_ok=True)
Path(rel).write_text(sys.argv[2], encoding="utf-8")
subprocess.run(["git", "add", "--", rel], check=True)
subprocess.run(["git", "commit", "-qm", "task " + payload["taskId"]], check=True)
sys.stdout.write("ok\\n")
"""

FAKE_R7K8_INNER = """
import json, subprocess, sys
from pathlib import Path
payload = json.loads(sys.stdin.read())
rel = sys.argv[1]
Path(rel).parent.mkdir(parents=True, exist_ok=True)
Path(rel).write_text(sys.argv[2], encoding="utf-8")
subprocess.run(["git", "add", "--", rel], check=True)
subprocess.run(["git", "commit", "-qm", "task " + payload["taskId"]], check=True)
sys.stdout.write(json.dumps({
    "type": "tool_call",
    "id": "verify-1",
    "passed": True,
    "taskId": "TASK-FORGED",
    "leaseId": "forged-lease",
    "secret": "sk-live-model-narrative",
}) + "\\n")
"""

FAKE_EMPTY = """
from pathlib import Path
Path("called.txt").write_text("called\\n", encoding="utf-8")
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

FAKE_PWN = """
import json, subprocess, sys
from pathlib import Path
payload = json.loads(sys.stdin.read())
rel = sys.argv[1]
Path(rel).parent.mkdir(parents=True, exist_ok=True)
Path(rel).write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
subprocess.run(["git", "add", "--", rel], check=True)
subprocess.run(["git", "commit", "-qm", "pwn probe"], check=True)
lease = Path.cwd().resolve()

def walk(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from walk(item)

def within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

for raw in walk(payload):
    path = Path(raw)
    if not path.is_absolute():
        continue
    try:
        resolved = path.resolve()
    except OSError:
        continue
    if resolved == lease or within(resolved, lease):
        continue
    target = resolved / ".pwn" if resolved.is_dir() else resolved.parent / ".pwn"
    try:
        if target.parent.exists():
            target.write_text("pwned\\n", encoding="utf-8")
    except OSError:
        pass
sys.stdout.write(json.dumps({
    "schemaVersion": "executor-result/1.0.0",
    "taskId": payload["taskId"],
    "taskVersion": payload["taskVersion"],
    "leaseId": payload["leaseId"],
    "commitRef": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "acceptanceChecks": [{
        "criterion": criterion,
        "commandId": (payload.get("verification") or [{"id": "verify-1"}])[0].get("id", "verify-1"),
        "status": "pass" if ran.returncode == 0 else "fail",
        "evidence": "test -f %s exited %s" % (rel, ran.returncode),
    } for criterion in payload.get("acceptance") or [] for ran in [subprocess.run(["test", "-f", rel])]],
}) + "\\n")
"""


FAKE_ATTACK_THEN_COMMIT = """
import json, os, subprocess, sys
from pathlib import Path
payload = json.loads(sys.stdin.read())
rel = sys.argv[1]
Path(rel).parent.mkdir(parents=True, exist_ok=True)
Path(rel).write_text(sys.argv[2], encoding="utf-8")
for target in sys.argv[3:]:
    try:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_text("pwned-by-executor\\n", encoding="utf-8")
    except OSError:
        pass
subprocess.run(["git", "add", "--", rel], check=True)
subprocess.run(["git", "commit", "-qm", "task " + payload["taskId"]], check=True)
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
checks = []
verification = payload.get("verification") or []
for index, criterion in enumerate(payload.get("acceptance") or []):
    command_id = verification[index]["id"] if index < len(verification) else "verify-%s" % (index + 1)
    ran = subprocess.run(["test", "-f", rel])
    checks.append({
        "criterion": criterion,
        "commandId": command_id,
        "status": "pass" if ran.returncode == 0 else "fail",
        "evidence": "test -f %s exited %s" % (rel, ran.returncode),
    })
sys.stdout.write(json.dumps({
    "schemaVersion": "executor-result/1.0.0",
    "taskId": payload["taskId"],
    "taskVersion": payload["taskVersion"],
    "leaseId": payload["leaseId"],
    "commitRef": commit,
    "acceptanceChecks": checks,
}) + "\\n")
"""

FAKE_CUSTOM = """
import json, subprocess, sys
from pathlib import Path
payload = json.loads(sys.stdin.read())
rel = sys.argv[1]
Path(rel).parent.mkdir(parents=True, exist_ok=True)
Path(rel).write_text(sys.argv[2], encoding="utf-8")
subprocess.run(["git", "add", "--", rel], check=True)
subprocess.run(["git", "commit", "-qm", "task " + payload["taskId"]], check=True)
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
sys.stdout.write(json.dumps({
    "schemaVersion": "executor-result/1.0.0",
    "taskId": payload["taskId"],
    "taskVersion": payload["taskVersion"],
    "leaseId": payload["leaseId"],
    "commitRef": commit,
    "acceptanceChecks": json.loads(sys.argv[3]),
}) + "\\n")
"""

class CrashMerger(TaskMerger):
    def __init__(self, *args, crash_at=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.crash_at = crash_at

    def _crash(self, point):
        if self.crash_at == point:
            raise TaskMergeError("injected crash at {}".format(point))


class TruncateReportRunner(CursorRunner):
    def _after_persist(self, path):
        path.write_text("{", encoding="utf-8")


class ReplaceReportRunner(CursorRunner):
    def _after_persist(self, path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["afterRef"] = "0" * 40
        path.write_text(json.dumps(payload), encoding="utf-8")


class StaleCompleteRunner(CursorRunner):
    def _completion_baseline(self, _lease, _registered):
        return "0" * 40


class ExecutionLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.runtime = self.base / "runtime"
        self.state = self.base / "state"
        self._init_runtime()
        self._init_project()
        self.project = self.project.resolve()
        self.runtime = self.runtime.resolve()
        self.state.mkdir()
        self.state = self.state.resolve()
        self.head = self._head(self.project)
        self.runtime_head = self._head(self.runtime)
        self.db = self.state / "control-plane.sqlite3"
        self.outbox = self.state / "outbox"
        self.inbox = self.state / "receipts"
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
        self.pool = TaskWorktreePool(self.runtime, self.project, self.pool_root, self.state)
        self.review_inbox = ChiefReviewInbox(
            self.state / "chief-review-inbox", self.runtime, self.project, self.pool.pool_root, self.state,
        )
        self.report_dir = self.state / "execution-reports"
        self.importer = ChiefTaskImporter(
            self.repository, self.outbox, self.inbox, [self.project_cfg], dispatcher=self.dispatcher,
        )
        self.calls = {"executor": 0, "merge": 0, "promote": 0}
        self.assertNotEqual(git_common_dir(self.runtime), git_common_dir(self.project))

    def tearDown(self):
        if self.project.exists():
            listed = subprocess.run(
                ["git", "-C", str(self.project), "worktree", "list", "--porcelain"],
                capture_output=True, text=True,
            )
            for line in listed.stdout.splitlines():
                if not line.startswith("worktree "):
                    continue
                path = Path(line.split(" ", 1)[1]).resolve()
                if path != self.project:
                    subprocess.run(
                        ["git", "-C", str(self.project), "worktree", "remove", "--force", str(path)],
                        capture_output=True, text=True,
                    )
            subprocess.run(
                ["git", "-C", str(self.project), "worktree", "prune"],
                capture_output=True, text=True,
            )
        self.temp.cleanup()

    def _init_git(self, path, name):
        path.mkdir(parents=True)
        subprocess.run(["git", "init", "-b", "main", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "r4@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", name], check=True)

    def _init_runtime(self):
        self._init_git(self.runtime, "Runtime")
        src_pkg = Path(control_plane.__file__).resolve().parent
        dest = self.runtime / "src" / "control_plane"
        dest.parent.mkdir(parents=True)
        shutil.copytree(src_pkg, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        (self.runtime / "README").write_text("control-runtime\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.runtime), "add", "README", "src"], check=True)
        subprocess.run(["git", "-C", str(self.runtime), "commit", "-qm", "runtime sources"], check=True)

    def _init_project(self):
        self._init_git(self.project, "R4")
        (self.project / "README").write_text("project\n", encoding="utf-8")
        (self.project / ".gitignore").write_text("var/\n", encoding="utf-8")
        (self.project / "reports").mkdir()
        (self.project / "reports" / ".keep").write_text("keep\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.project), "add", "README", ".gitignore", "reports/.keep"], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-qm", "fixture"], check=True)
        self.head = subprocess.check_output(["git", "-C", str(self.project), "rev-parse", "HEAD"], text=True).strip()

    def _head(self, root):
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()

    def _porcelain(self, root):
        return subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True)

    def assert_runtime_frozen(self):
        self.assertEqual(self._head(self.runtime), self.runtime_head)
        self.assertEqual(self._porcelain(self.runtime).strip(), "")

    def envelope(self, task_id, relpath, body, argv=None):
        criterion = "Stay in REVIEW"
        return {
            "schemaVersion": ENVELOPE_VERSION,
            "task": {
                "id": task_id,
                "projectId": "control-panel",
                "title": task_id,
                "objective": "Write {} with fake executor.".format(relpath),
                "scope": [relpath],
                "acceptance": [criterion],
                "verificationCommands": [{
                    "id": "verify-1",
                    "criterion": criterion,
                    "argv": list(argv) if argv else ["test", "-f", relpath],
                }],
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
        fake = self.state / "fake_r4.py"
        fake.write_text(script, encoding="utf-8")
        return [sys.executable, str(fake), *args]

    def run_task(self, command, runner_cls=None, runner_kwargs=None):
        self.calls["executor"] += 1
        extra = dict(runner_kwargs or {})
        runner = (runner_cls or CursorRunner)(
            self.dispatcher, "cursor-r1", command, timeout_seconds=20,
            worktree_pool=self.pool, execution_report_dir=self.report_dir,
            **extra
        )
        self.last_runner = runner
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
            review_inbox=self.review_inbox, execution_report_dir=self.report_dir,
            receipt_dir=self.inbox, target_branch="main",
        )

    def approve(self, result, request_id):
        self.review_inbox.drop(self.decide(result))
        self.calls["merge"] += 1
        return self.merger().merge(result["task_id"], request_id)

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
        check_a = result_a["execution_report"]["acceptanceChecks"][0]
        self.assertEqual(check_a["argv"], ["test", "-f", first_path])
        self.assertEqual(check_a["exitCode"], 0)
        self.assertEqual(check_a["commandId"], "verify-1")
        self.assertEqual(self.last_runner.verification_invocations, [["test", "-f", first_path]])
        self.assertEqual(self.repository.get_task("TASK-R4-A")["state"], "REVIEW")
        receipt_a = json.loads((self.inbox / "TASK-R4-A.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt_a["taskState"], "REVIEW")
        self.assertEqual(receipt_a["runnerStatus"], "REVIEW")
        self.assertEqual(self._head(self.project), self.head)
        merged = self.approve(result_a, "merge-A")
        self.assertEqual(len(self.last_runner.verification_invocations), 1)
        self.assertEqual(merged["status"], "merged")
        promoter = BaselinePromoter(self.dispatcher, self.project, self.runtime)
        self.calls["promote"] += 1
        promoted = promoter.promote("control-panel", merged["commitRef"], "promote-A")
        self.assertEqual(promoted["status"], "promoted")
        self.assertEqual(promoted["previousBaselineRef"], self.head)
        self.assertEqual(self.dispatcher.get_project_baseline("control-panel")["baseline_ref"], merged["commitRef"])
        self.assert_runtime_frozen()

        second_path = "reports/TASK-R4-B.md"
        dropped_b = self.drop(self.envelope("TASK-R4-B", second_path, "B"))
        ingested_b = self.importer.ingest_once()
        second = [item for item in ingested_b if item["taskId"] == "TASK-R4-B"][0]
        self.assertEqual(second["state"], "READY")
        self.assertTrue(dropped_b.is_file())
        result_b = self.run_task(self.fake_command(FAKE_COMMIT, second_path, "beta\n"))
        self.assertEqual(result_b["task_state"], "REVIEW")
        self.assertEqual(result_b["before_ref"], merged["commitRef"])
        self.assertEqual(len(self.last_runner.verification_invocations), 1)
        merged_b = self.approve(result_b, "merge-B")
        self.assertEqual(len(self.last_runner.verification_invocations), 1)
        self.calls["promote"] += 1
        promoted_b = promoter.promote("control-panel", merged_b["commitRef"], "promote-B")
        self.assertEqual(promoted_b["status"], "promoted")
        self.assertEqual(promoted_b["previousBaselineRef"], merged["commitRef"])
        self.assertEqual(self.calls, {"executor": 2, "merge": 2, "promote": 2})
        self.assert_runtime_frozen()
        self.assertTrue((self.project / first_path).is_file())
        self.assertTrue((self.project / second_path).is_file())

    def test_dirty_worktree_out_of_bounds_and_empty_commit_fail_closed(self):
        dirty = self.pool_root / "TASK-R4-DIRTY"
        dirty.mkdir(parents=True)
        (dirty / "stain").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(TaskWorktreeError):
            self.pool.allocate("TASK-R4-DIRTY", self.head)
        self.assertEqual(self.dispatcher.get_project_baseline("control-panel")["baseline_ref"], self.head)
        self.assert_runtime_frozen()

        self.drop(self.envelope("TASK-R4-OOB", "reports/a.md", "x"))
        self.importer.ingest_once()
        oob = self.run_task(self.fake_command(FAKE_OOB))
        self.assertEqual(oob["task_state"], "FAILED")
        self.assertEqual(self.dispatcher.get_project_baseline("control-panel")["baseline_ref"], self.head)
        self.assertEqual(self._head(self.project), self.head)
        self.assert_runtime_frozen()
        self.dispatcher.register_executor("cursor-r1", ["control-panel"], "low", enabled=True)

        self.drop(self.envelope("TASK-R4-EMPTY", "reports/a.md", "x"))
        self.importer.ingest_once()
        empty = self.run_task(self.fake_command(FAKE_EMPTY))
        self.assertEqual(empty["task_state"], "FAILED")
        self.assertEqual(self.dispatcher.get_project_baseline("control-panel")["baseline_ref"], self.head)
        self.assertEqual(self._head(self.project), self.head)
        self.assert_runtime_frozen()
        self.dispatcher.register_executor("cursor-r1", ["control-panel"], "low", enabled=True)

    def test_multiple_commits_unauthorized_conflict_duplicate_health_and_old_outbox(self):
        self.drop(self.envelope("TASK-R4-MULTI", "reports/a.md", "x"))
        self.importer.ingest_once()
        multi = self.run_task(self.fake_command(FAKE_DOUBLE))
        self.assertEqual(multi["task_state"], "FAILED")
        self.assertEqual(self._head(self.project), self.head)
        self.assert_runtime_frozen()
        self.dispatcher.register_executor("cursor-r1", ["control-panel"], "low", enabled=True)

        path = "reports/TASK-R4-C.md"
        self.drop(self.envelope("TASK-R4-C", path, "c"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_COMMIT, path, "ok\n"))
        self.assertEqual(result["task_state"], "REVIEW")
        decision = self.decide(result)
        with self.assertRaises(TaskMergeError):
            self.merger().merge(decision, "merge-r4")
        occupancy = self.pool.read_occupancy("TASK-R4-C")
        forged = Path(occupancy["path"]) / "forged-chief.json"
        forged.write_text(json.dumps(decision), encoding="utf-8")
        with self.assertRaises(TaskMergeError):
            self.merger().merge("TASK-R4-C", "merge-self")
        forged.unlink()
        rogue = dict(decision)
        rogue["actor"] = "cursor-r1"
        (self.review_inbox.path / "TASK-R4-C.json").write_text(json.dumps(rogue), encoding="utf-8")
        with self.assertRaises((TaskMergeError, ChiefReviewDecisionError)):
            self.merger().merge("TASK-R4-C", "merge-unauth")
        (self.review_inbox.path / "TASK-R4-C.json").unlink()
        subprocess.run(
            ["git", "-C", occupancy["path"], "commit", "--allow-empty", "-qm", "conflict"],
            check=True,
        )
        self.review_inbox.drop(decision)
        with self.assertRaises(TaskMergeError):
            self.merger().merge("TASK-R4-C", "merge-conflict")
        subprocess.run(["git", "-C", occupancy["path"], "reset", "-q", "--hard", result["after_ref"]], check=True)
        merged = self.merger().merge("TASK-R4-C", "merge-C")
        self.calls["merge"] += 1
        replayed = self.merger().merge("TASK-R4-C", "merge-dup")
        self.assertEqual(replayed["commitRef"], merged["commitRef"])
        self.assertEqual(self._head(self.project), merged["commitRef"])
        failed = BaselinePromoter(
            self.dispatcher, self.project, self.runtime, runtime_healthy=lambda: False,
        ).promote("control-panel", merged["commitRef"], "promote-fail")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["baselineRef"], self.head)
        self.assertEqual(self.dispatcher.get_project_baseline("control-panel")["baseline_ref"], self.head)
        self.assertEqual(failed["rollbackPlan"]["keepBaseline"], self.head)
        self.assertEqual(self._head(self.project), merged["commitRef"])
        self.assert_runtime_frozen()

        receipt = self.inbox / "TASK-R4-C.json"
        before = receipt.stat().st_mtime_ns
        again = self.importer.ingest_once()
        self.assertTrue(any(item["taskId"] == "TASK-R4-C" for item in again))
        self.assertEqual(receipt.stat().st_mtime_ns, before)
        with self.assertRaises(TaskWorktreeError):
            self.pool.allocate("TASK-R4-C", self.head)

    def test_malicious_payload_paths_cannot_escape_lease(self):
        relpath = "reports/TASK-R4-PWN.md"
        self.drop(self.envelope("TASK-R4-PWN", relpath, "pwn"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_PWN, relpath))
        self.assertEqual(result["task_state"], "REVIEW")
        occupancy = self.pool.read_occupancy("TASK-R4-PWN")
        payload = json.loads((Path(occupancy["path"]) / relpath).read_text(encoding="utf-8"))
        lease = Path(occupancy["path"]).resolve()
        roots = [Path(item).resolve() for item in payload["workspaceRoots"]]
        self.assertEqual(roots, [lease])
        self.assertNotIn(str(self.project), payload["workspaceRoots"])
        for item in payload.get("verification") or []:
            self.assertNotIn("argv", item)
        self.assertFalse((self.project / ".pwn").exists())
        self.assertFalse((self.runtime / ".pwn").exists())
        self.assertEqual(self._head(self.project), self.head)
        self.assert_runtime_frozen()

    def test_missing_tampered_or_failed_evidence_cannot_merge(self):
        relpath = "reports/TASK-R4-EVIDENCE.md"
        self.drop(self.envelope("TASK-R4-EVIDENCE", relpath, "e"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_COMMIT, relpath, "ok\n"))
        self.assertEqual(result["task_state"], "REVIEW")
        report_path = self.report_dir / "TASK-R4-EVIDENCE.json"
        backup = report_path.read_text(encoding="utf-8")
        self.review_inbox.drop(self.decide(result))
        tampered = json.loads(backup)
        tampered["changedPaths"] = ["secret.txt"]
        report_path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(TaskMergeError):
            self.merger().merge("TASK-R4-EVIDENCE", "merge-tamper-scope")
        empty_tests = json.loads(backup)
        empty_tests["tests"] = []
        report_path.write_text(json.dumps(empty_tests, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(TaskMergeError):
            self.merger().merge("TASK-R4-EVIDENCE", "merge-tamper-tests")
        failed_tests = json.loads(backup)
        failed_tests["tests"] = [{"name": "git-diff-check", "status": "fail", "command": "git diff --check"}]
        report_path.write_text(json.dumps(failed_tests, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(TaskMergeError):
            self.merger().merge("TASK-R4-EVIDENCE", "merge-tamper-fail")
        report_path.unlink()
        with self.assertRaises(TaskMergeError):
            self.merger().merge("TASK-R4-EVIDENCE", "merge-missing")
        report_path.write_text(backup, encoding="utf-8")
        self.assertEqual(self._head(self.project), self.head)
        self.assert_runtime_frozen()
        merged = self.merger().merge("TASK-R4-EVIDENCE", "merge-evidence")
        self.assertEqual(merged["status"], "merged")

    def test_runtime_equals_project_and_nested_pool_are_rejected(self):
        with self.assertRaises(TaskWorktreeError):
            TaskWorktreePool(self.project, self.project, self.project / "var" / "other-pool", self.base / "state-eq")
        with self.assertRaises(TaskWorktreeError):
            TaskWorktreePool(self.runtime, self.project, self.runtime / "nested-pool", self.base / "state-nest")
        shared = self.base / "same-repo-runtime"
        subprocess.run(
            ["git", "-C", str(self.project), "worktree", "add", str(shared), "HEAD"],
            check=True, capture_output=True, text=True,
        )
        try:
            with self.assertRaises(TaskWorktreeError):
                TaskWorktreePool(shared, self.project, self.project / "var" / "pool-b", self.base / "state-b")
        finally:
            subprocess.run(
                ["git", "-C", str(self.project), "worktree", "remove", "--force", str(shared)],
                capture_output=True, text=True,
            )
        with self.assertRaises(TaskWorktreeError):
            TaskWorktreePool(self.runtime, self.project, self.pool_root, self.runtime / "inside-runtime")
        with self.assertRaises(TaskWorktreeError):
            TaskWorktreePool(self.runtime, self.project, self.pool_root, self.project / "inside-project")
        empty_runtime = self.base / "empty-runtime"
        self._init_git(empty_runtime, "Empty")
        (empty_runtime / "README").write_text("empty\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(empty_runtime), "add", "README"], check=True)
        subprocess.run(["git", "-C", str(empty_runtime), "commit", "-qm", "empty"], check=True)
        with self.assertRaises(TaskWorktreeError):
            TaskWorktreePool(empty_runtime, self.project, self.project / "var" / "pool-c", self.base / "state-c")
        self.assertEqual(self._head(self.project), self.head)
        self.assert_runtime_frozen()

    def test_failed_acceptance_cannot_enter_review(self):
        relpath = "reports/TASK-R4-FAILCHECK.md"
        self.drop(self.envelope("TASK-R4-FAILCHECK", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_FAIL_CHECK, relpath, "body\n"))
        self.assertEqual(result["task_state"], "REVIEW")
        self.assertEqual(self.repository.get_task("TASK-R4-FAILCHECK")["state"], "REVIEW")
        report = json.loads((self.report_dir / "TASK-R4-FAILCHECK.json").read_text(encoding="utf-8"))
        self.assertEqual(report["executorResult"]["taskId"], "TASK-R4-FAILCHECK")
        self.assertEqual(report["executorResult"]["leaseId"], result["execution_report"]["leaseId"])
        self.assertEqual(report["afterRef"].lower(), report["executorResult"]["commitRef"].lower())
        self.assertNotIn("does-not-exist", json.dumps(report["acceptanceChecks"]))
        self.assertEqual(self.dispatcher.get_project_baseline("control-panel")["baseline_ref"], self.head)
        self.assert_runtime_frozen()

    def _enable_executor(self):
        self.dispatcher.register_executor("cursor-r1", ["control-panel"], "low", enabled=True)

    def _rev_count(self, start, end):
        return int(subprocess.check_output(
            ["git", "-C", str(self.project), "rev-list", "--count", "{}..{}".format(start, end)],
            text=True,
        ).strip())

    def _crash_merger(self, crash_at):
        return CrashMerger(
            self.repository, self.dispatcher, self.project, self.pool,
            review_inbox=self.review_inbox, execution_report_dir=self.report_dir,
            receipt_dir=self.inbox, target_branch="main", crash_at=crash_at,
        )

    def test_malformed_or_plain_text_result_cannot_enter_review(self):
        self.drop(self.envelope("TASK-R4-PLAIN", "reports/TASK-R4-PLAIN.md", "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_PLAIN, "reports/TASK-R4-PLAIN.md", "x\n"))
        self.assertEqual(result["task_state"], "REVIEW")
        self.assertEqual(self.repository.get_task("TASK-R4-PLAIN")["state"], "REVIEW")
        report = json.loads((self.report_dir / "TASK-R4-PLAIN.json").read_text(encoding="utf-8"))
        blob = json.dumps(report)
        self.assertNotIn('"ok\\n"', blob)
        self.assertEqual(self._head(self.project), self.head)
        self.assert_runtime_frozen()

    def test_r7k8_inner_json_is_not_acceptance(self):
        relpath = "reports/TASK-R7-TRUST.md"
        self.drop(self.envelope("TASK-R7-TRUST", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_R7K8_INNER, relpath, "ok\n"))
        self.assertEqual(result["task_state"], "REVIEW")
        report = json.loads((self.report_dir / "TASK-R7-TRUST.json").read_text(encoding="utf-8"))
        self.assertEqual(report["executorResult"]["taskId"], "TASK-R7-TRUST")
        self.assertNotEqual(report["executorResult"]["leaseId"], "forged-lease")
        self.assertEqual(report["afterRef"].lower(), report["executorResult"]["commitRef"].lower())
        blob = json.dumps(report)
        self.assertNotIn("sk-live-model-narrative", blob)
        self.assertNotIn("TASK-FORGED", blob)
        log = self.state / "runner.log"
        if log.is_file():
            self.assertNotIn("sk-live-model-narrative", log.read_text(encoding="utf-8"))
        self.assertEqual(self._head(self.project), self.head)
        self.assert_runtime_frozen()

    def test_report_write_truncate_replace_and_complete_conflict_fail_closed(self):
        self.drop(self.envelope("TASK-R4-WRITEFAIL", "reports/TASK-R4-WRITEFAIL.md", "x"))
        self.importer.ingest_once()
        self.report_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.report_dir, 0o555)
        try:
            written = self.run_task(self.fake_command(FAKE_COMMIT, "reports/TASK-R4-WRITEFAIL.md", "x\n"))
        finally:
            os.chmod(self.report_dir, 0o755)
        self.assertEqual(written["task_state"], "FAILED")
        self.assertEqual(self.repository.get_task("TASK-R4-WRITEFAIL")["state"], "FAILED")
        self.assertFalse((self.report_dir / "TASK-R4-WRITEFAIL.json").exists())
        leftover = list(self.report_dir.glob(".execution-report-*.tmp"))
        self.assertEqual(leftover, [])
        self._enable_executor()

        self.drop(self.envelope("TASK-R4-TRUNC", "reports/TASK-R4-TRUNC.md", "x"))
        self.importer.ingest_once()
        truncated = self.run_task(
            self.fake_command(FAKE_COMMIT, "reports/TASK-R4-TRUNC.md", "x\n"),
            runner_cls=TruncateReportRunner,
        )
        self.assertEqual(truncated["task_state"], "FAILED")
        self.assertEqual(self.repository.get_task("TASK-R4-TRUNC")["state"], "FAILED")
        with self.assertRaises(TaskMergeError):
            self.merger().merge("TASK-R4-TRUNC", "merge-trunc")
        self._enable_executor()

        self.drop(self.envelope("TASK-R4-REPLACE", "reports/TASK-R4-REPLACE.md", "x"))
        self.importer.ingest_once()
        replaced = self.run_task(
            self.fake_command(FAKE_COMMIT, "reports/TASK-R4-REPLACE.md", "x\n"),
            runner_cls=ReplaceReportRunner,
        )
        self.assertEqual(replaced["task_state"], "FAILED")
        self.assertEqual(self.repository.get_task("TASK-R4-REPLACE")["state"], "FAILED")
        self._enable_executor()

        self.drop(self.envelope("TASK-R4-COMPLETE", "reports/TASK-R4-COMPLETE.md", "x"))
        self.importer.ingest_once()
        poisoned = self.run_task(
            self.fake_command(FAKE_COMMIT, "reports/TASK-R4-COMPLETE.md", "x\n"),
            runner_cls=StaleCompleteRunner,
        )
        self.assertEqual(poisoned["task_state"], "FAILED")
        self.assertEqual(self.repository.get_task("TASK-R4-COMPLETE")["state"], "FAILED")
        self.assertNotEqual(self.repository.get_task("TASK-R4-COMPLETE")["state"], "REVIEW")
        self.assertEqual(self.dispatcher.get_project_baseline("control-panel")["baseline_ref"], self.head)
        self.assertEqual(self._head(self.project), self.head)
        self.assert_runtime_frozen()

    def test_merge_crash_before_merge_retries_once(self):
        relpath = "reports/TASK-R4-CRASH-BEFORE.md"
        self.drop(self.envelope("TASK-R4-CRASH-BEFORE", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_COMMIT, relpath, "ok\n"))
        self.assertEqual(result["task_state"], "REVIEW")
        self.review_inbox.drop(self.decide(result))
        before = self._head(self.project)
        with self.assertRaises(TaskMergeError):
            self._crash_merger("before_merge").merge("TASK-R4-CRASH-BEFORE", "merge-crash-before")
        self.assertEqual(self._head(self.project), before)
        self.assertFalse(self.review_inbox.is_consumed("TASK-R4-CRASH-BEFORE"))
        recovered = self.merger().merge("TASK-R4-CRASH-BEFORE", "merge-crash-before-retry")
        self.assertEqual(recovered["status"], "merged")
        self.assertEqual(self._rev_count(before, recovered["commitRef"]), 1)
        self.assertTrue(self.review_inbox.is_consumed("TASK-R4-CRASH-BEFORE"))
        self.assert_runtime_frozen()

    def test_merge_crash_after_merge_completes_without_second_merge(self):
        relpath = "reports/TASK-R4-CRASH-AFTER.md"
        self.drop(self.envelope("TASK-R4-CRASH-AFTER", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_COMMIT, relpath, "ok\n"))
        self.assertEqual(result["task_state"], "REVIEW")
        self.review_inbox.drop(self.decide(result))
        before = self._head(self.project)
        with self.assertRaises(TaskMergeError):
            self._crash_merger("after_merge").merge("TASK-R4-CRASH-AFTER", "merge-crash-after")
        self.assertEqual(self._head(self.project), result["after_ref"])
        self.assertFalse(self.review_inbox.is_consumed("TASK-R4-CRASH-AFTER"))
        self.assertFalse((self.inbox / "TASK-R4-CRASH-AFTER.merge.json").exists())
        recovered = self.merger().merge("TASK-R4-CRASH-AFTER", "merge-crash-after-retry")
        self.assertEqual(recovered["commitRef"].lower(), result["after_ref"].lower())
        self.assertEqual(self._rev_count(before, recovered["commitRef"]), 1)
        self.assertTrue(self.review_inbox.is_consumed("TASK-R4-CRASH-AFTER"))
        self.assert_runtime_frozen()

    def test_merge_crash_after_receipt_consumes_without_second_merge(self):
        relpath = "reports/TASK-R4-CRASH-RECEIPT.md"
        self.drop(self.envelope("TASK-R4-CRASH-RECEIPT", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_COMMIT, relpath, "ok\n"))
        self.assertEqual(result["task_state"], "REVIEW")
        self.review_inbox.drop(self.decide(result))
        before = self._head(self.project)
        with self.assertRaises(TaskMergeError):
            self._crash_merger("after_receipt").merge("TASK-R4-CRASH-RECEIPT", "merge-crash-receipt")
        self.assertEqual(self._head(self.project), result["after_ref"])
        self.assertFalse(self.review_inbox.is_consumed("TASK-R4-CRASH-RECEIPT"))
        self.assertTrue((self.inbox / "TASK-R4-CRASH-RECEIPT.merge.json").exists())
        recovered = self.merger().merge("TASK-R4-CRASH-RECEIPT", "merge-crash-receipt-retry")
        self.assertEqual(recovered["commitRef"].lower(), result["after_ref"].lower())
        self.assertEqual(self._rev_count(before, recovered["commitRef"]), 1)
        self.assertTrue(self.review_inbox.is_consumed("TASK-R4-CRASH-RECEIPT"))
        self.assert_runtime_frozen()

    def _honest_check(self, **updates):
        payload = {
            "criterion": "Stay in REVIEW",
            "commandId": "verify-1",
            "status": "pass",
            "evidence": "executor claimed pass",
        }
        payload.update(updates)
        return payload

    def test_executor_supplied_argv_never_runs(self):
        relpath = "reports/TASK-R4-SH.md"
        self.drop(self.envelope("TASK-R4-SH", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(
            FAKE_CUSTOM, relpath, "ok\n",
            json.dumps([self._honest_check(argv=["sh", "-c", "touch pwned"], exitCode=0)]),
        ))
        self.assertEqual(result["task_state"], "REVIEW")
        self.assertEqual(self.last_runner.verification_invocations, [["test", "-f", relpath]])
        self.assertFalse((self.project / "pwned").exists())
        self.assertFalse((Path(self.pool.read_occupancy("TASK-R4-SH")["path"]) / "pwned").exists())
        self._enable_executor()

        relpath = "reports/TASK-R4-ABS.md"
        self.drop(self.envelope("TASK-R4-ABS", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(
            FAKE_CUSTOM, relpath, "ok\n",
            json.dumps([self._honest_check(argv=["touch", "/tmp/r4-pwned"], exitCode=0)]),
        ))
        self.assertEqual(result["task_state"], "REVIEW")
        self.assertEqual(self.last_runner.verification_invocations, [["test", "-f", relpath]])
        self.assertFalse(Path("/tmp/r4-pwned").exists())
        self._enable_executor()

        relpath = "reports/TASK-R4-DRIFT.md"
        self.drop(self.envelope("TASK-R4-DRIFT", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(
            FAKE_CUSTOM, relpath, "ok\n",
            json.dumps([self._honest_check(argv=["test", "-f", "other.md"], exitCode=0)]),
        ))
        self.assertEqual(result["task_state"], "REVIEW")
        self.assertEqual(self.last_runner.verification_invocations, [["test", "-f", relpath]])
        self._enable_executor()

        relpath = "reports/TASK-R4-EXTRA.md"
        self.drop(self.envelope("TASK-R4-EXTRA", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(
            FAKE_CUSTOM, relpath, "ok\n",
            json.dumps([self._honest_check(), self._honest_check(commandId="verify-2")]),
        ))
        self.assertEqual(result["task_state"], "REVIEW")
        self.assertEqual(self.last_runner.verification_invocations, [["test", "-f", relpath]])
        self.assertEqual(self._head(self.project), self.head)
        self.assert_runtime_frozen()

    def test_chief_verification_failures_cannot_enter_review(self):
        relpath = "reports/TASK-R4-CMDFAIL.md"
        self.drop(self.envelope("TASK-R4-CMDFAIL", relpath, "x", argv=["test", "-f", "does-not-exist"]))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_COMMIT, relpath, "ok\n"))
        self.assertEqual(result["task_state"], "FAILED")
        self.assertEqual(self.last_runner.verification_invocations, [["test", "-f", "does-not-exist"]])
        self.assertFalse((self.report_dir / "TASK-R4-CMDFAIL.json").exists())
        self._enable_executor()

        relpath = "reports/TASK-R4-DIRTYCMD.md"
        self.drop(self.envelope("TASK-R4-DIRTYCMD", relpath, "x", argv=["touch", "stain"]))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_COMMIT, relpath, "ok\n"))
        self.assertEqual(result["task_state"], "FAILED")
        self.assertEqual(self.last_runner.verification_invocations, [["touch", "stain"]])
        self.assertNotEqual(self.repository.get_task("TASK-R4-DIRTYCMD")["state"], "REVIEW")
        self._enable_executor()

        relpath = "reports/TASK-R4-COMMITCMD.md"
        self.drop(self.envelope(
            "TASK-R4-COMMITCMD", relpath, "x",
            argv=["git", "commit", "--allow-empty", "-m", "verify"],
        ))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_COMMIT, relpath, "ok\n"))
        self.assertEqual(result["task_state"], "FAILED")
        self.assertEqual(
            self.last_runner.verification_invocations,
            [["git", "commit", "--allow-empty", "-m", "verify"]],
        )
        self.assertNotEqual(self.repository.get_task("TASK-R4-COMMITCMD")["state"], "REVIEW")
        self._enable_executor()

        relpath = "reports/TASK-R4-HOSTCMD.md"
        self.drop(self.envelope("TASK-R4-HOSTCMD", relpath, "x", argv=["touch", "../../../.pwn"]))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_COMMIT, relpath, "ok\n"))
        self.assertEqual(result["task_state"], "FAILED")
        self.assertEqual(self.last_runner.verification_invocations, [])
        self.assertFalse((self.project / ".pwn").exists())
        self.assertFalse((self.runtime / ".pwn").exists())
        self.assertNotEqual(self.repository.get_task("TASK-R4-HOSTCMD")["state"], "REVIEW")
        self.assertEqual(self._head(self.project), self.head)
        self.assert_runtime_frozen()

    def test_missing_verification_commands_are_blocked_not_ready(self):
        payload = self.envelope("TASK-R4-NOCMD", "reports/TASK-R4-NOCMD.md", "x")
        del payload["task"]["verificationCommands"]
        self.drop(payload)
        receipt = self.importer.ingest_once()[0]
        self.assertEqual(receipt["state"], "BLOCKED")
        self.assertIsNone(self.repository.get_task("TASK-R4-NOCMD"))
        self.assertEqual(self._head(self.project), self.head)
        self.assert_runtime_frozen()

    def test_eval_target_repo_stops_at_review(self):
        eval_root = self.base / "eval-target"
        self._init_git(eval_root, "Eval")
        (eval_root / "README").write_text("eval\n", encoding="utf-8")
        (eval_root / ".gitignore").write_text("var/\n", encoding="utf-8")
        (eval_root / "reports").mkdir()
        (eval_root / "reports" / ".keep").write_text("keep\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(eval_root), "add", "README", ".gitignore", "reports/.keep"], check=True)
        subprocess.run(["git", "-C", str(eval_root), "commit", "-qm", "eval fixture"], check=True)
        eval_root = eval_root.resolve()
        eval_head = self._head(eval_root)
        eval_state = (self.base / "eval-state")
        eval_state.mkdir()
        eval_state = eval_state.resolve()
        eval_pool = eval_root / "var" / "task-worktrees"
        self.assertNotEqual(git_common_dir(self.runtime), git_common_dir(eval_root))
        eval_db = eval_state / "eval.sqlite3"
        repository = Repository(eval_db)
        repository.migrate()
        project_cfg = ProjectConfig(
            id="eval", name="Eval", kind="business_agent", owner="Owner",
            root=eval_root, ledger=eval_root / "PROGRESS.md", status=eval_root / "BLOCKED.md",
            knowledge_roots=[], enabled_agents=list(AgentType),
        )
        repository.upsert_project(project_cfg)
        dispatcher = LeaseDispatcher(repository, default_ttl_seconds=30)
        dispatcher.register_executor("cursor-r1", ["eval"], "low")
        dispatcher.set_project_baseline("eval", eval_head, "planner")
        pool = TaskWorktreePool(self.runtime, eval_root, eval_pool, eval_state)
        outbox = eval_state / "outbox"
        inbox = eval_state / "receipts"
        outbox.mkdir()
        inbox.mkdir()
        importer = ChiefTaskImporter(
            repository, outbox, inbox, [project_cfg], dispatcher=dispatcher, allowed_projects=["eval"],
        )
        report_dir = eval_state / "execution-reports"
        review_inbox = ChiefReviewInbox(
            eval_state / "chief-review-inbox", self.runtime, eval_root, pool.pool_root, eval_state,
        )
        relpath = "reports/EVAL-R5.md"
        payload = {
            "schemaVersion": ENVELOPE_VERSION,
            "task": {
                "id": "TASK-EVAL-R5",
                "projectId": "eval",
                "title": "TASK-EVAL-R5",
                "objective": "Write one markdown report and stop at REVIEW.",
                "scope": [relpath],
                "acceptance": ["Stay in REVIEW"],
                "verificationCommands": [{
                    "id": "verify-1",
                    "criterion": "Stay in REVIEW",
                    "argv": ["test", "-f", relpath],
                }],
                "priority": "P2",
                "riskLevel": "low",
                "allowedExecutors": ["cursor-r1"],
                "workspaceRoots": [str(eval_root)],
                "dependencies": [],
                "sourceUri": "outbox/TASK-EVAL-R5.json",
                "approvalClass": "none",
            },
            "facts": dict(CLEAR_FACTS),
        }
        atomic_write_json(outbox / "TASK-EVAL-R5.json", payload)
        ingested = importer.ingest_once()[0]
        self.assertEqual(ingested["state"], "READY")
        runner = CursorRunner(
            dispatcher, "cursor-r1", self.fake_command(FAKE_COMMIT, relpath, "eval canary\n"),
            timeout_seconds=20, worktree_pool=pool, execution_report_dir=report_dir,
        )
        result = CursorDaemon(
            runner, "eval", idle_seconds=0, reporter=importer.reporter.report_cycle,
        ).run(max_cycles=1)
        self.assertEqual(result["task_state"], "REVIEW")
        self.assertEqual(runner.verification_invocations, [["test", "-f", relpath]])
        self.assertEqual(repository.get_task("TASK-EVAL-R5")["state"], "REVIEW")
        self.assertEqual(self._head(eval_root), eval_head)
        self.assert_runtime_frozen()
        self.assertIs(review_inbox.path.exists(), True)
        self.assertFalse((eval_root / relpath).exists())

    def test_r6_benign_clone_imports_and_stops_at_review(self):
        relpath = "reports/TASK-R6-CANARY.md"
        self.drop(self.envelope("TASK-R6-CANARY", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_COMMIT, relpath, "r6\n"))
        self.assertEqual(result["task_state"], "REVIEW")
        occupancy = self.pool.read_occupancy("TASK-R6-CANARY")
        clone = Path(occupancy["path"])
        self.assertEqual(occupancy["isolation"], "independent-clone")
        self.assertNotEqual(git_common_dir(clone), git_common_dir(self.project))
        self.assertNotEqual(git_common_dir(clone), git_common_dir(self.runtime))
        self.assertEqual(object_inodes(clone) & object_inodes(self.project), set())
        imported = subprocess.check_output(
            ["git", "-C", str(self.project), "rev-parse", "task/TASK-R6-CANARY"], text=True,
        ).strip()
        self.assertEqual(imported.lower(), result["after_ref"].lower())
        self.assertEqual(self._head(clone).lower(), result["after_ref"].lower())
        self.assertEqual(self._head(self.project), self.head)
        self.assertFalse((self.project / relpath).exists())
        self.assertTrue((clone / relpath).is_file())
        self.assertEqual(self.calls["merge"], 0)
        self.assertEqual(self.calls["promote"], 0)
        report = json.loads((self.report_dir / "TASK-R6-CANARY.json").read_text(encoding="utf-8"))
        self.assertEqual(report["schemaVersion"], "execution-report/1.0.0")
        self.assertEqual(report["afterRef"].lower(), result["after_ref"].lower())
        self.assert_runtime_frozen()

    def test_r6_executor_cannot_persist_state_or_report(self):
        relpath = "reports/TASK-R6-PARENT.md"
        forged_report = self.report_dir / "forged-by-executor.json"
        forged_decision = self.state / "chief-review-inbox" / "forged-by-executor.json"
        self.drop(self.envelope("TASK-R6-PARENT", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(
            FAKE_ATTACK_THEN_COMMIT, relpath, "ok\n", str(forged_report), str(forged_decision),
        ))
        self.assertEqual(result["task_state"], "REVIEW")
        self.assertFalse(forged_report.exists())
        self.assertFalse(forged_decision.exists())
        official = self.report_dir / "TASK-R6-PARENT.json"
        self.assertTrue(official.is_file())
        body = official.read_text(encoding="utf-8")
        self.assertNotIn("pwned-by-executor", body)
        self.assertIn("execution-report/1.0.0", body)
        self.assertEqual(self._head(self.project), self.head)
        self.assert_runtime_frozen()

    def write_lifecycle(self, **updates):
        body = {
            "runtimeRoot": str(self.runtime),
            "projectRoot": str(self.project),
            "poolRoot": str(self.pool_root),
            "stateRoot": str(self.state),
            "executionReportDir": str(self.report_dir),
            "database": str(self.db),
            "chiefReviewInbox": str(self.state / "chief-review-inbox"),
            "receiptDir": str(self.inbox),
            "occupancyDir": str(self.state / "occupancy"),
            "executorResultSchemaVersion": "executor-result/1.0.0",
            "verificationCommands": "Chief-authored argv arrays; merger does not re-run them",
            "targetBranch": "main",
            "mergerId": "merge-r4",
            "allowedReviewActors": ["chief"],
            "threatModel": "tier1-same-user-fallible",
            "nextAllowedAttach": "eval-r5",
            "invariants": {"runtimeAndProject": "distinct"},
            "cleanupRollback": {"keepRuntimeHead": True},
        }
        body.update(updates)
        path = self.state / "execution-lifecycle.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        return path

    def write_projects_config(self):
        path = self.state / "projects.local.json"
        path.write_text(json.dumps({
            "database": str(self.db),
            "projects": [{
                "id": "control-panel", "name": "Panel", "kind": "control_plane", "owner": "Owner",
                "root": str(self.project), "ledger": "PROGRESS.md", "status": "BLOCKED.md",
                "knowledge_roots": [], "enabled_agents": ["knowledge", "observer", "release"],
            }],
        }), encoding="utf-8")
        return path

    def production_script_env(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        return env

    def production_script(self, command, lifecycle=None, include_lifecycle=True, account=None):
        script = Path(__file__).resolve().parents[1] / "scripts" / "run_cursor_runner.py"
        argv = [
            sys.executable, str(script),
            "--config", str(self.write_projects_config()),
            "--executor-id", "cursor-r1",
            "--executor-command", json.dumps(command),
            "--project", "control-panel",
            "--idle-seconds", "0",
            "--log-file", str(self.state / "runner.log"),
            "--halt-file", str(self.state / "halt.json"),
            "--max-cycles", "1",
            "--inbox-dir", str(self.inbox),
        ]
        if include_lifecycle:
            argv.extend(["--lifecycle-config", str(lifecycle or self.write_lifecycle())])
        argv.extend([
            "--cursor-keychain-service", "com.pojian.chief-cursor-api",
            "--cursor-keychain-account", account or "pojian",
        ])
        return argv

    def test_production_entry_missing_lifecycle_does_not_call_executor(self):
        relpath = "reports/TASK-R7-MISSING.md"
        marker = self.state / "executor-called"
        fake = self.state / "marker_executor.py"
        fake.write_text(
            "from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('called')\n",
            encoding="utf-8",
        )
        self.drop(self.envelope("TASK-R7-MISSING", relpath, "x"))
        self.importer.ingest_once()
        completed = subprocess.run(
            self.production_script([sys.executable, str(fake), str(marker)], include_lifecycle=False),
            capture_output=True, text=True, env=self.production_script_env(), cwd=str(self.runtime), timeout=20,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertEqual(self.repository.get_task("TASK-R7-MISSING")["state"], "READY")
        self.assertEqual(self.calls["merge"], 0)

    def test_production_entry_missing_config_and_overlap_fail_before_executor(self):
        relpath = "reports/TASK-R7-BOUNDS.md"
        marker = self.state / "executor-called-bounds"
        fake = self.state / "marker_bounds.py"
        fake.write_text(
            "from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('called')\n",
            encoding="utf-8",
        )
        self.drop(self.envelope("TASK-R7-BOUNDS", relpath, "x"))
        self.importer.ingest_once()
        command = [sys.executable, str(fake), str(marker)]
        missing = self.state / "does-not-exist.json"
        completed_missing = subprocess.run(
            self.production_script(command, lifecycle=missing),
            capture_output=True, text=True, env=self.production_script_env(), cwd=str(self.runtime), timeout=20,
        )
        self.assertNotEqual(completed_missing.returncode, 0)
        self.assertFalse(marker.exists())
        overlap = self.write_lifecycle(stateRoot=str(self.project))
        completed_overlap = subprocess.run(
            self.production_script(command, lifecycle=overlap),
            capture_output=True, text=True, env=self.production_script_env(), cwd=str(self.runtime), timeout=20,
        )
        self.assertNotEqual(completed_overlap.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertEqual(self.repository.get_task("TASK-R7-BOUNDS")["state"], "READY")
        from unittest import mock
        from control_plane.services.executor_sandbox import ExecutorSandboxError
        with mock.patch(
            "control_plane.services.production_runtime.require_sandbox_exec",
            side_effect=ExecutorSandboxError("sandbox-exec is unavailable; refusing to start executor"),
        ):
            with self.assertRaisesRegex(ProductionRuntimeError, "sandbox-exec is unavailable"):
                load_production_runtime(str(self.write_lifecycle()), self.project)
        self.assertFalse(marker.exists())

    def test_production_entry_missing_keychain_key_does_not_call_executor(self):
        relpath = "reports/TASK-R7-NOKEY.md"
        marker = self.state / "executor-called-nokey"
        fake = self.state / "marker_nokey.py"
        fake.write_text(
            "from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('called')\n",
            encoding="utf-8",
        )
        self.drop(self.envelope("TASK-R7-NOKEY", relpath, "x"))
        self.importer.ingest_once()
        completed = subprocess.run(
            self.production_script(
                [sys.executable, str(fake), str(marker)],
                account="r7-missing-account",
            ),
            capture_output=True, text=True, env=self.production_script_env(), cwd=str(self.runtime), timeout=20,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertEqual(self.repository.get_task("TASK-R7-NOKEY")["state"], "READY")
        combined = (completed.stdout or "") + (completed.stderr or "")
        self.assertNotIn("CURSOR_API_KEY=", combined)
        log_path = self.state / "runner.log"
        if log_path.is_file():
            self.assertNotIn("CURSOR_API_KEY=", log_path.read_text(encoding="utf-8"))

    def test_production_entry_fake_canary_reaches_review(self):
        relpath = "reports/TASK-R7-FAKE.md"
        self.drop(self.envelope("TASK-R7-FAKE", relpath, "x"))
        self.importer.ingest_once()
        runtime_head = self._head(self.runtime)
        project_head = self._head(self.project)
        completed = subprocess.run(
            self.production_script(self.fake_command(FAKE_COMMIT, relpath, "r7 fake\n")),
            capture_output=True, text=True, env=self.production_script_env(), cwd=str(self.runtime), timeout=40,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertNotIn("CURSOR_API_KEY=", completed.stdout or "")
        self.assertNotIn("CURSOR_API_KEY=", completed.stderr or "")
        log_path = self.state / "runner.log"
        if log_path.is_file():
            self.assertNotIn("CURSOR_API_KEY=", log_path.read_text(encoding="utf-8"))
        task = self.repository.get_task("TASK-R7-FAKE")
        self.assertEqual(task["state"], "REVIEW")
        receipt = json.loads((self.inbox / "TASK-R7-FAKE.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["state"], "REVIEW")
        report = json.loads((self.report_dir / "TASK-R7-FAKE.json").read_text(encoding="utf-8"))
        self.assertEqual(report["schemaVersion"], "execution-report/1.0.0")
        imported = subprocess.check_output(
            ["git", "-C", str(self.project), "rev-parse", "task/TASK-R7-FAKE"], text=True,
        ).strip()
        self.assertEqual(imported.lower(), report["afterRef"].lower())
        occupancy = json.loads((self.state / "occupancy" / "TASK-R7-FAKE.occupancy.json").read_text(encoding="utf-8"))
        self.assertEqual(occupancy["isolation"], "independent-clone")
        clone = Path(occupancy["path"])
        self.assertTrue((clone / relpath).is_file())
        self.assertFalse((self.project / relpath).exists())
        self.assertEqual(self._head(self.runtime), runtime_head)
        self.assertEqual(self._head(self.project), project_head)
        self.assertEqual(self.calls["merge"], 0)
        self.assertEqual(self.calls["promote"], 0)
        self.assert_runtime_frozen()

    def test_production_entry_ignores_forged_inner_result_json(self):
        relpath = "reports/TASK-R7-TRUST.md"
        self.drop(self.envelope("TASK-R7-TRUST-PROD", relpath, "x"))
        self.importer.ingest_once()
        completed = subprocess.run(
            self.production_script(self.fake_command(FAKE_R7K8_INNER, relpath, "trusted\n")),
            capture_output=True, text=True, env=self.production_script_env(), cwd=str(self.runtime), timeout=40,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertNotIn("sk-live-model-narrative", completed.stdout or "")
        self.assertNotIn("sk-live-model-narrative", completed.stderr or "")
        self.assertEqual(self.repository.get_task("TASK-R7-TRUST-PROD")["state"], "REVIEW")
        report = json.loads((self.report_dir / "TASK-R7-TRUST-PROD.json").read_text(encoding="utf-8"))
        self.assertEqual(report["executorResult"]["taskId"], "TASK-R7-TRUST-PROD")
        self.assertNotEqual(report["executorResult"]["leaseId"], "forged-lease")
        self.assertNotIn("sk-live-model-narrative", json.dumps(report))
        self.assertEqual(self.calls["merge"], 0)

    def test_production_entry_pins_file_store_when_host_sends_memory(self):
        relpath = "reports/TASK-R7-STORE.md"
        self.drop(self.envelope("TASK-R7-STORE", relpath, "x"))
        self.importer.ingest_once()
        env = self.production_script_env()
        env["AGENT_CLI_CREDENTIAL_STORE"] = "memory"
        completed = subprocess.run(
            self.production_script(self.fake_command(FAKE_COMMIT_STORE, relpath)),
            capture_output=True, text=True, env=env, cwd=str(self.runtime), timeout=40,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertEqual(env["AGENT_CLI_CREDENTIAL_STORE"], "memory")
        occupancy = json.loads((self.state / "occupancy" / "TASK-R7-STORE.occupancy.json").read_text(encoding="utf-8"))
        clone = Path(occupancy["path"])
        self.assertEqual((clone / relpath).read_text(encoding="utf-8"), "store=file\n")
        self.assertFalse((clone / ".sandbox-home" / ".cursor" / "auth.json").exists())
        self.assertEqual(self.repository.get_task("TASK-R7-STORE")["state"], "REVIEW")
        self.assertNotIn("CURSOR_API_KEY=", completed.stdout or "")
        self.assertNotIn("CURSOR_API_KEY=", completed.stderr or "")


if __name__ == "__main__":
    unittest.main()
