import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from hashlib import sha256
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
from control_plane.services.cursor_launch import (
    CREDENTIAL_STORE_KEY, PRODUCTION_CREDENTIAL_STORE, filter_cli_env,
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
    "AGENT_CLI_CREDENTIAL_STORE": os.environ.get("AGENT_CLI_CREDENTIAL_STORE"),
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

FAKE_KEYCHAIN_CURSOR = r"""
import json, os, sys
from pathlib import Path
marker = Path(sys.argv[1])
store = os.environ.get("AGENT_CLI_CREDENTIAL_STORE") or ""
home = Path(os.environ.get("HOME") or "")
auth = home / ".cursor" / "auth.json"
keychain_hit = store not in ("memory", "file")
if keychain_hit:
    marker.write_text("keychain\n", encoding="utf-8")
if store == "file":
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_text("{}\n", encoding="utf-8")
print(json.dumps({
    "store": store or "missing",
    "keychain": keychain_hit,
    "authExists": auth.is_file(),
    "home": str(home),
}))
"""

FAKE_FILE_STORE = r"""
import json, os, sys, time
from pathlib import Path
mode = sys.argv[1] if len(sys.argv) > 1 else "ok"
store = os.environ.get("AGENT_CLI_CREDENTIAL_STORE") or ""
home = Path(os.environ.get("HOME") or "")
auth = home / ".cursor" / "auth.json"
if store == "file":
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_text("{}\n", encoding="utf-8")
existed = auth.is_file()
if mode == "sleep":
    print(json.dumps({"store": store, "authExists": existed}), flush=True)
    time.sleep(30)
if mode == "fail":
    print(json.dumps({"store": store, "authExists": existed}))
    raise SystemExit(2)
print(json.dumps({"store": store, "authExists": existed}))
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
        self.assertEqual(body["env"]["AGENT_CLI_CREDENTIAL_STORE"], "file")
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
        host_home = self.base / "host-home-attack"
        host_home.mkdir()
        host_sentinel = host_home / "host-sentinel.txt"
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
                    str(host_sentinel),
                ],
                "child": str(child),
            })],
            clone, sandbox, "", 20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        body = json.loads(completed.stdout)
        self.assertEqual(len(body["results"]), 8)
        for item in body["results"]:
            self.assertNotEqual(item["errno"], 0, item)
            self.assertEqual(item["errno"], 1, item)
        self.assertFalse(runtime_sentinel.exists())
        self.assertFalse(decision.exists())
        self.assertFalse(report.exists())
        self.assertFalse(main_sentinel.exists())
        self.assertFalse(child.exists())
        self.assertFalse(host_sentinel.exists())
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

    def test_clone_home_is_writable_and_host_home_writes_are_denied(self):
        occupancy = self.pool.allocate("TASK-R7-HOME-RO", self.head)
        clone = Path(occupancy["path"])
        host_home = self.base / "host-home"
        host_home.mkdir()
        existing = host_home / "login-marker"
        existing.write_text("login-state\n", encoding="utf-8")
        before_sha = sha256(existing.read_bytes()).hexdigest()
        source_env = {
            "PATH": os.environ.get("PATH", "/usr/bin"),
            "HOME": str(host_home),
            "LANG": "C",
            "USER": os.environ.get("USER", "pojian"),
            "CURSOR_API_KEY": "canary-secret-value-do-not-log",
        }
        sandbox = prepare_executor_sandbox(
            "TASK-R7-HOME-RO", clone, self.runtime, self.project, self.pool_root, self.state,
            source_env=source_env,
        )
        env = sandbox["environment"]
        clone_home = clone / ".sandbox-home"
        self.assertEqual(env["HOME"], str(clone_home))
        self.assertNotEqual(env["HOME"], str(host_home))
        self.assertTrue(str(env["TMPDIR"]).startswith(str(clone)))
        self.assertTrue(str(env["XDG_CONFIG_HOME"]).startswith(str(clone)))
        self.assertEqual(env.get("CURSOR_API_KEY"), "canary-secret-value-do-not-log")
        profile = Path(sandbox["profilePath"]).read_text(encoding="utf-8")
        self.assertEqual(sum(1 for line in profile.splitlines() if line.strip().startswith("(allow file-write")), 2)
        self.assertIn('(literal "/dev/null")', profile)
        self.assertIn('(subpath "{}")'.format(clone), profile)
        self.assertNotIn(str(host_home), profile)

        created = host_home / "new-sentinel.txt"
        overwrite = existing
        symlink = clone / "escape-home"
        symlink.symlink_to(existing)
        child_target = host_home / "child-sentinel.txt"
        probe = self.state / "home_write_probe.py"
        probe.write_text(WRITE_PROBE, encoding="utf-8")
        completed = launch_sandboxed_executor(
            [sys.executable, str(probe), json.dumps({
                "targets": [str(created), str(overwrite), str(symlink)],
                "child": str(child_target),
            })],
            clone, sandbox, "", 20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        body = json.loads(completed.stdout)
        self.assertTrue(body["env"]["HOME"].startswith(str(clone)))
        self.assertEqual(len(body["results"]), 4)
        for item in body["results"]:
            self.assertEqual(item["errno"], 1, item)
            if item["path"] != str(overwrite) and item["path"] != str(symlink):
                self.assertFalse(Path(item["path"]).exists(), item)
        self.assertEqual(sha256(existing.read_bytes()).hexdigest(), before_sha)
        self.assertEqual(existing.read_text(encoding="utf-8"), "login-state\n")
        self.assertFalse(created.exists())
        self.assertFalse(child_target.exists())

        project_dir = clone_home / ".cursor" / "projects" / "canary"
        write_ok = self.state / "clone_home_write.py"
        write_ok.write_text(
            "from pathlib import Path\n"
            "p = Path.home() / '.cursor' / 'projects' / 'canary'\n"
            "p.mkdir(parents=True)\n"
            "(p / 'ok.txt').write_text('ok\\n', encoding='utf-8')\n"
            "print(p / 'ok.txt')\n",
            encoding="utf-8",
        )
        writable = launch_sandboxed_executor(
            [sys.executable, str(write_ok)], clone, sandbox, "", 20,
        )
        self.assertEqual(writable.returncode, 0, writable.stderr + writable.stdout)
        self.assertTrue((project_dir / "ok.txt").is_file())
        self.assertEqual((project_dir / "ok.txt").read_text(encoding="utf-8"), "ok\n")

        benign = self.state / "home_benign.py"
        benign.write_text(BENIGN_COMMIT, encoding="utf-8")
        committed = launch_sandboxed_executor(
            [sys.executable, str(benign), "reports/TASK-R7-HOME-RO.md", "ok\n"],
            clone, sandbox, "", 20,
        )
        self.assertEqual(committed.returncode, 0, committed.stderr + committed.stdout)
        self.assertTrue((clone / "reports" / "TASK-R7-HOME-RO.md").is_file())
        self.assertEqual(sha256(existing.read_bytes()).hexdigest(), before_sha)
        self.assertFalse(created.exists())
        self.assertFalse(child_target.exists())
        self.assertNotIn("canary-secret-value-do-not-log", (self.state / "home_write_probe.py").read_text(encoding="utf-8"))
        self.assertNotIn("canary-secret-value-do-not-log", committed.stdout)
        self.assertNotIn("canary-secret-value-do-not-log", completed.stdout)

    def test_missing_credential_store_hits_fake_keychain_marker(self):
        occupancy = self.pool.allocate("TASK-R7-KC-OLD", self.head)
        clone = Path(occupancy["path"])
        marker = clone / "keychain.marker"
        script = self.state / "fake_cursor_old.py"
        script.write_text(FAKE_KEYCHAIN_CURSOR, encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(script), str(marker)],
            capture_output=True, text=True, cwd=str(clone),
            env={"PATH": os.environ.get("PATH", "/usr/bin"), "HOME": str(clone / ".sandbox-home")},
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        body = json.loads(completed.stdout)
        self.assertEqual(body["store"], "missing")
        self.assertTrue(body["keychain"])
        self.assertTrue(marker.is_file())

    def test_sandbox_pins_file_and_clears_auth_json(self):
        occupancy = self.pool.allocate("TASK-R7-KC-FILE", self.head)
        clone = Path(occupancy["path"])
        parent_before = os.environ.get(CREDENTIAL_STORE_KEY)
        marker = clone / "keychain.marker"
        script = self.state / "fake_cursor_file.py"
        script.write_text(FAKE_KEYCHAIN_CURSOR, encoding="utf-8")
        source_env = {
            "PATH": os.environ.get("PATH", "/usr/bin"),
            "HOME": str(self.base / "host-home"),
            "USER": os.environ.get("USER", "pojian"),
            "CURSOR_API_KEY": "canary-secret-value-do-not-log",
            CREDENTIAL_STORE_KEY: "memory",
        }
        env = sandbox_environment(clone, source_env)
        self.assertEqual(env[CREDENTIAL_STORE_KEY], "file")
        sandbox = prepare_executor_sandbox(
            "TASK-R7-KC-FILE", clone, self.runtime, self.project, self.pool_root, self.state,
            source_env=source_env,
        )
        completed = launch_sandboxed_executor(
            [sys.executable, str(script), str(marker)],
            clone, sandbox, "", 20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        body = json.loads(completed.stdout)
        self.assertEqual(body["store"], "file")
        self.assertTrue(body["authExists"])
        self.assertFalse(body["keychain"])
        auth = Path(env["HOME"]) / ".cursor" / "auth.json"
        self.assertFalse(auth.exists())
        self.assertFalse(marker.exists())
        self.assertEqual(os.environ.get(CREDENTIAL_STORE_KEY), parent_before)
        profile = Path(sandbox["profilePath"]).read_text(encoding="utf-8")
        self.assertEqual(sum(1 for line in profile.splitlines() if line.strip().startswith("(allow file-write")), 2)
        self.assertNotIn("canary-secret-value-do-not-log", completed.stdout)
        self.assertNotIn("canary-secret-value-do-not-log", completed.stderr)
        for host_value in ("memory", "default", "keychain", "FILE", "file\n"):
            pinned = sandbox_environment(clone, {CREDENTIAL_STORE_KEY: host_value, "PATH": "/usr/bin"})
            self.assertEqual(pinned[CREDENTIAL_STORE_KEY], "file")
        tracked = subprocess.check_output(
            ["git", "-C", str(clone), "ls-files", ".sandbox-home"], text=True,
        ).strip()
        self.assertEqual(tracked, "")

    def test_sandbox_clears_auth_json_on_nonzero_and_timeout(self):
        occupancy = self.pool.allocate("TASK-R7-KC-CLEAN", self.head)
        clone = Path(occupancy["path"])
        script = self.state / "fake_file_store.py"
        script.write_text(FAKE_FILE_STORE, encoding="utf-8")
        sandbox = prepare_executor_sandbox(
            "TASK-R7-KC-CLEAN", clone, self.runtime, self.project, self.pool_root, self.state,
        )
        home = Path(str(sandbox["environment"]["HOME"]))
        auth = home / ".cursor" / "auth.json"
        failed = launch_sandboxed_executor(
            [sys.executable, str(script), "fail"],
            clone, sandbox, "", 20,
        )
        self.assertEqual(failed.returncode, 2)
        body = json.loads(failed.stdout)
        self.assertEqual(body["store"], "file")
        self.assertTrue(body["authExists"])
        self.assertFalse(auth.exists())
        with self.assertRaises(subprocess.TimeoutExpired):
            launch_sandboxed_executor(
                [sys.executable, str(script), "sleep"],
                clone, sandbox, "", 1,
            )
        self.assertFalse(auth.exists())

    def test_auth_json_symlink_is_fail_closed(self):
        occupancy = self.pool.allocate("TASK-R7-KC-LINK", self.head)
        clone = Path(occupancy["path"])
        sandbox = prepare_executor_sandbox(
            "TASK-R7-KC-LINK", clone, self.runtime, self.project, self.pool_root, self.state,
        )
        home = Path(str(sandbox["environment"]["HOME"]))
        host_secret = self.base / "host-secret.json"
        host_secret.write_text("keep\n", encoding="utf-8")
        cursor_dir = home / ".cursor"
        cursor_dir.mkdir(parents=True)
        auth = cursor_dir / "auth.json"
        auth.symlink_to(host_secret)
        with self.assertRaises(ExecutorSandboxError):
            launch_sandboxed_executor(
                [sys.executable, "-c", "print(0)"],
                clone, sandbox, "", 10,
            )
        self.assertTrue(auth.is_symlink())
        self.assertEqual(host_secret.read_text(encoding="utf-8"), "keep\n")


if __name__ == "__main__":
    unittest.main()
