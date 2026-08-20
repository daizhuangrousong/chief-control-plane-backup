import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from control_plane.config import ProjectConfig
from control_plane.domain.models import AgentType
from control_plane.services import (
    BaselinePromoter, ChiefReviewDecisionError, ChiefReviewInbox, ChiefTaskImporter, CursorDaemon,
    CursorRunner, DECISION_VERSION, LeaseDispatcher, TaskMergeError, TaskMerger, TaskWorktreeError,
    TaskWorktreePool,
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
        self._init_project()
        subprocess.run(
            ["git", "-C", str(self.project), "worktree", "add", "-b", "runtime", str(self.runtime), "HEAD"],
            check=True, capture_output=True, text=True,
        )
        self.project = self.project.resolve()
        self.runtime = self.runtime.resolve()
        self.head = self._head(self.project)
        self.runtime_head = self._head(self.runtime)
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
        self.review_inbox = ChiefReviewInbox(
            self.runtime / "chief-review-inbox", self.runtime, self.project, self.pool.pool_root,
        )
        self.report_dir = self.runtime / "var" / "execution-reports"
        self.importer = ChiefTaskImporter(
            self.repository, self.outbox, self.inbox, [self.project_cfg], dispatcher=self.dispatcher,
        )
        self.calls = {"executor": 0, "merge": 0, "promote": 0}

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

    def _init_project(self):
        self.project.mkdir()
        subprocess.run(["git", "init", "-b", "main", "-q", str(self.project)], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.email", "r4@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.name", "R4"], check=True)
        (self.project / "README").write_text("project\n", encoding="utf-8")
        (self.project / ".gitignore").write_text(
            "*.sqlite3\nchief-task-outbox/\nchief-task-inbox/\nvar/\nfake_r4.py\nchief-review-inbox/\n",
            encoding="utf-8",
        )
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
        fake = self.project / "fake_r4.py"
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
        merged_b = self.approve(result_b, "merge-B")
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
            TaskWorktreePool(self.project, self.project, self.project / "var" / "other-pool")
        with self.assertRaises(TaskWorktreeError):
            TaskWorktreePool(self.runtime, self.project, self.runtime / "nested-pool")
        self.assertEqual(self._head(self.project), self.head)
        self.assert_runtime_frozen()

    def test_failed_acceptance_cannot_enter_review(self):
        relpath = "reports/TASK-R4-FAILCHECK.md"
        self.drop(self.envelope("TASK-R4-FAILCHECK", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(FAKE_FAIL_CHECK, relpath, "body\n"))
        self.assertEqual(result["task_state"], "FAILED")
        self.assertEqual(self.repository.get_task("TASK-R4-FAILCHECK")["state"], "FAILED")
        self.assertFalse((self.report_dir / "TASK-R4-FAILCHECK.json").exists())
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
        self.assertEqual(result["task_state"], "FAILED")
        self.assertEqual(self.repository.get_task("TASK-R4-PLAIN")["state"], "FAILED")
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
        self.assertEqual(result["task_state"], "FAILED")
        self.assertEqual(self.last_runner.verification_invocations, [])
        self.assertFalse((self.project / "pwned").exists())
        self._enable_executor()

        relpath = "reports/TASK-R4-ABS.md"
        self.drop(self.envelope("TASK-R4-ABS", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(
            FAKE_CUSTOM, relpath, "ok\n",
            json.dumps([self._honest_check(argv=["touch", "/tmp/r4-pwned"], exitCode=0)]),
        ))
        self.assertEqual(result["task_state"], "FAILED")
        self.assertEqual(self.last_runner.verification_invocations, [])
        self.assertFalse(Path("/tmp/r4-pwned").exists())
        self._enable_executor()

        relpath = "reports/TASK-R4-DRIFT.md"
        self.drop(self.envelope("TASK-R4-DRIFT", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(
            FAKE_CUSTOM, relpath, "ok\n",
            json.dumps([self._honest_check(argv=["test", "-f", "other.md"], exitCode=0)]),
        ))
        self.assertEqual(result["task_state"], "FAILED")
        self.assertEqual(self.last_runner.verification_invocations, [])
        self._enable_executor()

        relpath = "reports/TASK-R4-EXTRA.md"
        self.drop(self.envelope("TASK-R4-EXTRA", relpath, "x"))
        self.importer.ingest_once()
        result = self.run_task(self.fake_command(
            FAKE_CUSTOM, relpath, "ok\n",
            json.dumps([self._honest_check(), self._honest_check(commandId="verify-2")]),
        ))
        self.assertEqual(result["task_state"], "FAILED")
        self.assertEqual(self.last_runner.verification_invocations, [])
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
        self.assertEqual(self.last_runner.verification_invocations, [["touch", "../../../.pwn"]])
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


if __name__ == "__main__":
    unittest.main()
