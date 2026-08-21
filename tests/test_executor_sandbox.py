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
    ExecutorSandboxError, LeaseDispatcher, TaskCloneError, TaskWorktreeError, TaskWorktreePool,
)
from control_plane.services.executor_sandbox import (
    SANDBOX_EXEC, assert_fail_closed_profile, launch_sandboxed_executor,
    prepare_executor_sandbox, require_sandbox_exec, sandbox_environment, write_sandbox_profile,
)
from control_plane.services.task_clone import (
    assert_independent_clone, import_exact_commit, object_inodes,
)
from control_plane.services.task_worktree import git_common_dir
from control_plane.storage import Repository


WRITE_PROBE = r"""
import errno, json, os, subprocess, sys
from pathlib import Path

def attempt(path):
    path = Path(path)
    existed = path.exists()
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT, 0o644)
        os.write(fd, b"pwned\n")
        os.close(fd)
        return {"path": str(path), "errno": 0, "exists": path.exists(), "existed": existed, "child": False}
    except OSError as error:
        return {
            "path": str(path),
            "errno": int(error.errno),
            "exists": path.exists(),
            "existed": existed,
            "err": errno.errorcode.get(error.errno, "?"),
            "child": False,
        }

payload = json.loads(sys.argv[1])
results = [attempt(item) for item in payload["targets"]]
child = payload.get("child")
if child:
    nested = subprocess.run(
        [sys.executable, "-c",
         "import os,sys\np=sys.argv[1]\ntry:\n fd=os.open(p, os.O_WRONLY|os.O_CREAT, 0o644)\n os.write(fd, b'child\\n')\n os.close(fd)\n sys.exit(0)\nexcept OSError as e:\n sys.exit(e.errno or 1)\n",
         child],
        capture_output=True, text=True,
    )
    results.append({
        "path": child,
        "errno": int(nested.returncode),
        "exists": Path(child).exists(),
        "child": True,
        "stderr": (nested.stderr or "").strip(),
    })
print(json.dumps({"results": results, "env": {
    "HOME": os.environ.get("HOME"),
    "TMPDIR": os.environ.get("TMPDIR"),
    "XDG_CONFIG_HOME": os.environ.get("XDG_CONFIG_HOME"),
    "GIT_DIR": os.environ.get("GIT_DIR"),
    "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY"),
    "LEAK_SENTINEL": os.environ.get("LEAK_SENTINEL"),
}}))
"""

BENIGN_COMMIT = r"""
import json, subprocess, sys
from pathlib import Path
rel, body = sys.argv[1], sys.argv[2]
Path(rel).parent.mkdir(parents=True, exist_ok=True)
Path(rel).write_text(body, encoding="utf-8")
subprocess.run(["git", "add", "--", rel], check=True)
subprocess.run(["git", "commit", "-qm", "benign"], check=True)
print(json.dumps({"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()}))
"""


class ExecutorSandboxTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.runtime = self.base / "runtime"
        self.state = self.base / "state"
        self._init_git(self.runtime, "Runtime")
        src_pkg = Path(control_plane.__file__).resolve().parent
        dest = self.runtime / "src" / "control_plane"
        dest.parent.mkdir(parents=True)
        shutil.copytree(src_pkg, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        (self.runtime / "README").write_text("control-runtime\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.runtime), "add", "README", "src"], check=True)
        subprocess.run(["git", "-C", str(self.runtime), "commit", "-qm", "runtime sources"], check=True)
        self._init_git(self.project, "R6")
        (self.project / "README").write_text("project\n", encoding="utf-8")
        (self.project / ".gitignore").write_text("var/\n", encoding="utf-8")
        (self.project / "reports").mkdir()
        (self.project / "reports" / ".keep").write_text("keep\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.project), "add", "README", ".gitignore", "reports/.keep"], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-qm", "fixture"], check=True)
        self.project = self.project.resolve()
        self.runtime = self.runtime.resolve()
        self.state.mkdir()
        self.state = self.state.resolve()
        self.head = self._head(self.project)
        self.runtime_head = self._head(self.runtime)
        self.pool_root = self.project / "var" / "task-worktrees"
        self.db = self.state / "control-plane.sqlite3"
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

    def tearDown(self):
        self.temp.cleanup()

    def _init_git(self, path, name):
        path.mkdir(parents=True)
        subprocess.run(["git", "init", "-b", "main", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "r6@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", name], check=True)

    def _head(self, root):
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()

    def _porcelain(self, root):
        return subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True)

    def snapshot(self):
        return {
            "runtimeHead": self._head(self.runtime),
            "projectHead": self._head(self.project),
            "runtimePorcelain": self._porcelain(self.runtime),
            "projectPorcelain": self._porcelain(self.project),
            "mainRef": (self.project / ".git" / "refs" / "heads" / "main").read_text(encoding="utf-8"),
            "readme": (self.project / "README").read_text(encoding="utf-8"),
        }

    def assert_hosts_frozen(self, before):
        current = self.snapshot()
        self.assertEqual(current["runtimeHead"], before["runtimeHead"])
        self.assertEqual(current["projectHead"], before["projectHead"])
        self.assertEqual(current["runtimePorcelain"], before["runtimePorcelain"])
        self.assertEqual(current["projectPorcelain"], before["projectPorcelain"])
        self.assertEqual(current["mainRef"], before["mainRef"])
        self.assertEqual(current["readme"], before["readme"])
        self.assertEqual(current["runtimeHead"], self.runtime_head)
        self.assertEqual(current["projectHead"], self.head)

    def test_missing_sandbox_exec_and_non_system_binary_fail_closed(self):
        with self.assertRaises(ExecutorSandboxError):
            require_sandbox_exec(Path("/no/such/sandbox-exec"))
        with self.assertRaises(ExecutorSandboxError):
            require_sandbox_exec(Path("/bin/echo"))
        self.assertTrue(SANDBOX_EXEC.is_file())
        self.assertEqual(require_sandbox_exec(), SANDBOX_EXEC.resolve())

    def test_fail_open_profile_is_rejected_without_starting_executor(self):
        occupancy = self.pool.allocate("TASK-R6-FAILOPEN", self.head)
        clone = Path(occupancy["path"])
        sandbox = prepare_executor_sandbox(
            "TASK-R6-FAILOPEN", clone, self.runtime, self.project, self.pool_root, self.state,
        )
        Path(sandbox["profilePath"]).write_text("(version 1)\n(allow default)\n", encoding="utf-8")
        marker = clone / "started.txt"
        script = self.state / "would-run.py"
        script.write_text("from pathlib import Path\nPath('started.txt').write_text('ran\\n')\n", encoding="utf-8")
        with self.assertRaises(ExecutorSandboxError):
            launch_sandboxed_executor(
                [sys.executable, str(script)], clone, sandbox, "", 10,
            )
        self.assertFalse(marker.exists())
        with self.assertRaises(ExecutorSandboxError):
            assert_fail_closed_profile("(version 1)\n(allow default)\n", clone)

    def test_shared_object_store_is_rejected(self):
        shared = self.base / "shared-clone"
        completed = subprocess.run(
            ["git", "clone", "--shared", "--", str(self.project), str(shared)],
            capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0)
        with self.assertRaises(TaskCloneError):
            assert_independent_clone(shared, self.runtime, self.project)

    def test_symlink_nested_and_reuse_are_rejected(self):
        nested = self.base / "nested-gitfile"
        nested.mkdir()
        (nested / ".git").write_text("gitdir: {}\n".format(self.project / ".git"), encoding="utf-8")
        with self.assertRaises(TaskCloneError):
            assert_independent_clone(nested, self.runtime, self.project)
        self.pool_root.mkdir(parents=True, exist_ok=True)
        symlink = self.pool_root / "TASK-R6-SYMLINK"
        symlink.symlink_to(self.project)
        with self.assertRaises(TaskWorktreeError):
            self.pool.allocate("TASK-R6-SYMLINK", self.head)
        occupied = self.pool.allocate("TASK-R6-REUSE", self.head)
        with self.assertRaises(TaskWorktreeError):
            self.pool.allocate("TASK-R6-REUSE", self.head)
        self.assertTrue(Path(occupied["path"]).is_dir())
        again = self.pool_root / "TASK-R6-EXISTING"
        again.mkdir(parents=True)
        (again / "stain").write_text("nope\n", encoding="utf-8")
        with self.assertRaises(TaskWorktreeError):
            self.pool.allocate("TASK-R6-EXISTING", self.head)

    def test_independent_clone_common_dir_and_inodes(self):
        occupancy = self.pool.allocate("TASK-R6-INODE", self.head)
        clone = Path(occupancy["path"])
        common = git_common_dir(clone)
        self.assertEqual(occupancy["isolation"], "independent-clone")
        self.assertEqual(Path(occupancy["gitCommonDir"]), common)
        self.assertTrue(str(common).startswith(str(clone)))
        self.assertNotEqual(common, git_common_dir(self.project))
        self.assertNotEqual(common, git_common_dir(self.runtime))
        self.assertFalse((clone / ".git" / "objects" / "info" / "alternates").exists())
        self.assertEqual(subprocess.check_output(["git", "-C", str(clone), "remote"], text=True).strip(), "")
        self.assertEqual(object_inodes(clone) & object_inodes(self.project), set())
        self.assertNotEqual(object_inodes(clone), set())

    def test_environment_does_not_leak_and_children_inherit_denies(self):
        occupancy = self.pool.allocate("TASK-R6-ENV", self.head)
        clone = Path(occupancy["path"])
        before = self.snapshot()
        leak_home = self.base / "real-home"
        leak_home.mkdir()
        source_env = {
            "PATH": os.environ.get("PATH", "/usr/bin"),
            "HOME": str(leak_home),
            "TMPDIR": "/tmp",
            "USER": os.environ.get("USER", "pojian"),
            "AWS_SECRET_ACCESS_KEY": "should-not-leak",
            "LEAK_SENTINEL": "should-not-leak",
            "GIT_DIR": str(self.project / ".git"),
        }
        sandbox = prepare_executor_sandbox(
            "TASK-R6-ENV", clone, self.runtime, self.project, self.pool_root, self.state,
            source_env=source_env,
        )
        env = sandbox_environment(clone, source_env)
        self.assertTrue(env["HOME"].startswith(str(clone)))
        self.assertTrue(env["TMPDIR"].startswith(str(clone)))
        self.assertTrue(env["XDG_CONFIG_HOME"].startswith(str(clone)))
        self.assertNotEqual(env["HOME"], str(leak_home))
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertNotIn("LEAK_SENTINEL", env)
        self.assertNotIn("GIT_DIR", env)
        child_target = self.project / "child-sentinel.txt"
        runtime_target = self.runtime / "env-sentinel.txt"
        probe = self.state / "write_probe.py"
        probe.write_text(WRITE_PROBE, encoding="utf-8")
        completed = launch_sandboxed_executor(
            [sys.executable, str(probe), json.dumps({
                "targets": [str(runtime_target)],
                "child": str(child_target),
            })],
            clone, sandbox, "", 20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        body = json.loads(completed.stdout)
        self.assertTrue(body["env"]["HOME"].startswith(str(clone)))
        self.assertIsNone(body["env"]["AWS_SECRET_ACCESS_KEY"])
        self.assertIsNone(body["env"]["LEAK_SENTINEL"])
        self.assertIsNone(body["env"]["GIT_DIR"])
        self.assertFalse(runtime_target.exists())
        self.assertFalse(child_target.exists())
        for item in body["results"]:
            self.assertNotEqual(item["errno"], 0)
            self.assertFalse(Path(item["path"]).exists())
        self.assert_hosts_frozen(before)

    def test_five_protected_targets_are_kernel_denied(self):
        occupancy = self.pool.allocate("TASK-R6-ATTACK", self.head)
        clone = Path(occupancy["path"])
        sandbox = prepare_executor_sandbox(
            "TASK-R6-ATTACK", clone, self.runtime, self.project, self.pool_root, self.state,
        )
        before = self.snapshot()
        decision = self.state / "chief-review-inbox" / "forged-decision.json"
        report = self.state / "execution-reports" / "forged-report.json"
        decision.parent.mkdir(parents=True, exist_ok=True)
        report.parent.mkdir(parents=True, exist_ok=True)
        symlink = clone / "escape-link"
        symlink.symlink_to(self.project / "README")
        runtime_sentinel = self.runtime / "runtime-sentinel.txt"
        main_sentinel = self.project / "main-sentinel.txt"
        main_ref = self.project / ".git" / "refs" / "heads" / "main"
        child = self.project / ".git" / "refs" / "heads" / "main.child"
        probe = self.state / "write_probe.py"
        probe.write_text(WRITE_PROBE, encoding="utf-8")
        completed = launch_sandboxed_executor(
            [sys.executable, str(probe), json.dumps({
                "targets": [
                    str(runtime_sentinel),
                    str(decision),
                    str(report),
                    str(main_sentinel),
                    str(main_ref),
                    str(symlink),
                ],
                "child": str(child),
            })],
            clone, sandbox, "", 20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        body = json.loads(completed.stdout)
        self.assertEqual(len(body["results"]), 7)
        for item in body["results"]:
            self.assertNotEqual(item["errno"], 0, item)
            self.assertEqual(item["errno"], 1, item)
        self.assertFalse(runtime_sentinel.exists())
        self.assertFalse(decision.exists())
        self.assertFalse(report.exists())
        self.assertFalse(main_sentinel.exists())
        self.assertFalse(child.exists())
        self.assertEqual((self.project / "README").read_text(encoding="utf-8"), "project\n")
        self.assert_hosts_frozen(before)

    def test_host_ref_write_and_overlap_do_not_start_executor(self):
        before = self.snapshot()
        occupancy = self.pool.allocate("TASK-R6-REF", self.head)
        clone = Path(occupancy["path"])
        with self.assertRaises(ExecutorSandboxError):
            write_sandbox_profile(
                self.state, "TASK-R6-OVERLAP", self.runtime, self.runtime, self.project, self.pool_root,
            )
        marker = clone / "started.txt"
        sandbox = prepare_executor_sandbox(
            "TASK-R6-REF", clone, self.runtime, self.project, self.pool_root, self.state,
        )
        ref = self.project / ".git" / "refs" / "heads" / "main"
        probe = self.state / "write_probe.py"
        probe.write_text(WRITE_PROBE, encoding="utf-8")
        completed = launch_sandboxed_executor(
            [sys.executable, str(probe), json.dumps({"targets": [str(ref)]})],
            clone, sandbox, "", 20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        body = json.loads(completed.stdout)
        self.assertEqual(body["results"][0]["errno"], 1)
        self.assertFalse(marker.exists())
        self.assert_hosts_frozen(before)

    def test_benign_commit_is_imported_by_parent(self):
        occupancy = self.pool.allocate("TASK-R6-BENIGN", self.head)
        clone = Path(occupancy["path"])
        sandbox = prepare_executor_sandbox(
            "TASK-R6-BENIGN", clone, self.runtime, self.project, self.pool_root, self.state,
        )
        before = self.snapshot()
        script = self.state / "benign.py"
        script.write_text(BENIGN_COMMIT, encoding="utf-8")
        completed = launch_sandboxed_executor(
            [sys.executable, str(script), "reports/TASK-R6-BENIGN.md", "ok\n"],
            clone, sandbox, "", 20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        commit = json.loads(completed.stdout)["commit"]
        self.assertEqual(self._head(clone), commit)
        imported = import_exact_commit(self.project, clone, "task/TASK-R6-BENIGN", commit)
        self.assertEqual(imported.lower(), commit.lower())
        self.assertEqual(
            subprocess.check_output(
                ["git", "-C", str(self.project), "rev-parse", "task/TASK-R6-BENIGN"], text=True,
            ).strip().lower(),
            commit.lower(),
        )
        self.assertFalse((self.project / "reports" / "TASK-R6-BENIGN.md").exists())
        self.assertTrue((clone / "reports" / "TASK-R6-BENIGN.md").is_file())
        self.assert_hosts_frozen(before)
        self.assertNotEqual(git_common_dir(clone), git_common_dir(self.project))


if __name__ == "__main__":
    unittest.main()
