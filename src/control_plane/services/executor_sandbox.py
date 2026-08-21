"""macOS sandbox-exec write isolation. Fail closed; never fall back to path checks."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence

from .cursor_launch import (
    CLI_ENV_ALLOWLIST,
    CREDENTIAL_STORE_KEY,
    PRODUCTION_CREDENTIAL_STORE,
    filter_cli_env,
)
from .task_registry import TaskValidationError
from .task_worktree import path_within, paths_equal, resolve_existing_dir


SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
PROFILE_VERSION_LINE = "(version 1)"
DENY_WRITES_LINE = "(deny file-write*)"
ALLOW_DEV_NULL_LINE = '(allow file-write* (literal "/dev/null"))'
AUTH_JSON_DIRNAME = ".cursor"
AUTH_JSON_FILENAME = "auth.json"


class ExecutorSandboxError(TaskValidationError):
    pass


def _seatbelt_quote(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def _allow_clone_line(clone: Path) -> str:
    return '(allow file-write* (subpath "{}"))'.format(_seatbelt_quote(clone))


def require_sandbox_exec(executable: Path = SANDBOX_EXEC) -> Path:
    if sys.platform != "darwin":
        raise ExecutorSandboxError("executor sandbox is unsupported on this platform")
    executable = Path(executable)
    if executable.is_symlink() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ExecutorSandboxError("sandbox-exec is unavailable; refusing to start executor")
    try:
        resolved = executable.resolve()
        expected = SANDBOX_EXEC.resolve()
    except OSError as error:
        raise ExecutorSandboxError("sandbox-exec is unreadable") from error
    if executable == SANDBOX_EXEC and resolved != expected:
        raise ExecutorSandboxError("sandbox-exec path escaped the system binary")
    if executable != SANDBOX_EXEC and resolved == expected:
        return resolved
    if executable != SANDBOX_EXEC:
        raise ExecutorSandboxError("refusing to use a non-system sandbox-exec")
    return resolved


def assert_fail_closed_profile(text: str, clone: Path) -> None:
    clone = Path(clone).resolve()
    allowed = {ALLOW_DEV_NULL_LINE, _allow_clone_line(clone)}
    if PROFILE_VERSION_LINE not in text.splitlines()[:1] and not text.startswith(PROFILE_VERSION_LINE):
        raise ExecutorSandboxError("sandbox profile is missing version 1")
    if DENY_WRITES_LINE not in text:
        raise ExecutorSandboxError("sandbox profile is not fail-closed for writes")
    write_allows = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("(allow file-write"):
            continue
        write_allows += 1
        if line not in allowed:
            raise ExecutorSandboxError("sandbox profile allows writes outside the task clone")
    if write_allows != 2:
        raise ExecutorSandboxError("sandbox profile write allowlist is invalid")
    if _allow_clone_line(Path("/")) in text or '(subpath "/")' in text:
        raise ExecutorSandboxError("sandbox profile write root is too broad")


def sandbox_environment(clone: Path, source: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    clone = Path(clone).resolve()
    filtered = filter_cli_env(source)
    home = clone / ".sandbox-home"
    tmp = clone / ".sandbox-tmp"
    xdg = clone / ".sandbox-xdg"
    overlay = {
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "TMP": str(tmp),
        "TEMP": str(tmp),
        "XDG_CONFIG_HOME": str(xdg / "config"),
        "XDG_CACHE_HOME": str(xdg / "cache"),
        "XDG_DATA_HOME": str(xdg / "data"),
        "XDG_RUNTIME_DIR": str(xdg / "runtime"),
        "PYTHONDONTWRITEBYTECODE": "1",
        CREDENTIAL_STORE_KEY: PRODUCTION_CREDENTIAL_STORE,
    }
    environment = {key: value for key, value in filtered.items() if key in CLI_ENV_ALLOWLIST}
    environment.update(overlay)
    return environment


def _prepare_sandbox_dirs(clone: Path) -> None:
    clone = Path(clone).resolve()
    for path in (
        clone / ".sandbox-home",
        clone / ".sandbox-tmp",
        clone / ".sandbox-xdg" / "config",
        clone / ".sandbox-xdg" / "cache",
        clone / ".sandbox-xdg" / "data",
        clone / ".sandbox-xdg" / "runtime",
    ):
        path.mkdir(parents=True, exist_ok=True)


def _assert_isolated_paths(
    clone: Path,
    runtime_root: Path,
    project_root: Path,
    pool_root: Path,
    state_root: Path,
    profile_path: Path,
) -> Path:
    clone = Path(clone)
    if clone.is_symlink():
        raise ExecutorSandboxError("task clone path must not be a symlink")
    clone = resolve_existing_dir(clone, "task clone")
    runtime_root = Path(runtime_root).resolve()
    project_root = Path(project_root).resolve()
    pool_root = Path(pool_root).resolve()
    state_root = Path(state_root).resolve()
    profile_path = Path(profile_path)
    if profile_path.is_symlink():
        raise ExecutorSandboxError("sandbox profile must not be a symlink")
    if not path_within(clone, pool_root) or paths_equal(clone, pool_root):
        raise ExecutorSandboxError("sandbox clone escaped the pool")
    if paths_equal(clone, runtime_root) or path_within(clone, runtime_root) or path_within(runtime_root, clone):
        raise ExecutorSandboxError("sandbox clone overlaps the runtime checkout")
    if paths_equal(clone, state_root) or path_within(clone, state_root) or path_within(state_root, clone):
        raise ExecutorSandboxError("sandbox clone overlaps the state root")
    if paths_equal(clone, project_root):
        raise ExecutorSandboxError("sandbox clone must not be the project root")
    project_git = (project_root / ".git").resolve() if (project_root / ".git").exists() else project_root
    if path_within(project_git, clone) or paths_equal(project_git, clone):
        raise ExecutorSandboxError("sandbox clone overlaps the project git directory")
    if not path_within(profile_path, state_root):
        raise ExecutorSandboxError("sandbox profile must sit inside the state root")
    if path_within(profile_path, clone) or path_within(profile_path, runtime_root) or path_within(profile_path, project_root):
        raise ExecutorSandboxError("sandbox profile escaped the state root")
    return clone


def render_write_profile(clone: Path) -> str:
    clone = Path(clone).resolve()
    text = "\n".join(
        [
            PROFILE_VERSION_LINE,
            "(allow default)",
            DENY_WRITES_LINE,
            ALLOW_DEV_NULL_LINE,
            _allow_clone_line(clone),
            "",
        ]
    )
    assert_fail_closed_profile(text, clone)
    return text


def write_sandbox_profile(
    state_root: Path,
    task_id: str,
    clone: Path,
    runtime_root: Path,
    project_root: Path,
    pool_root: Path,
) -> Path:
    if not str(task_id or "").strip():
        raise ExecutorSandboxError("sandbox profile task id is required")
    state_root = Path(state_root).resolve()
    directory = state_root / "executor-sandbox"
    directory.mkdir(parents=True, exist_ok=True)
    profile_path = directory / "{}.sb".format(task_id)
    clone = _assert_isolated_paths(clone, runtime_root, project_root, pool_root, state_root, profile_path)
    if profile_path.exists() and (profile_path.is_symlink() or not profile_path.is_file()):
        raise ExecutorSandboxError("sandbox profile path is not a regular file")
    text = render_write_profile(clone)
    profile_path.write_text(text, encoding="utf-8")
    if profile_path.is_symlink():
        raise ExecutorSandboxError("sandbox profile must not be a symlink")
    loaded = profile_path.read_text(encoding="utf-8")
    assert_fail_closed_profile(loaded, clone)
    return profile_path


def probe_sandbox(profile_path: Path, environment: Mapping[str, str], cwd: Path) -> None:
    sandbox_exec = require_sandbox_exec()
    profile_path = Path(profile_path)
    if profile_path.is_symlink() or not profile_path.is_file():
        raise ExecutorSandboxError("sandbox profile is missing")
    completed = subprocess.run(
        [str(sandbox_exec), "-f", str(profile_path), "/usr/bin/true"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        shell=False,
        cwd=str(cwd),
        env=dict(environment),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "sandbox-exec failed").strip()
        raise ExecutorSandboxError("sandbox profile failed to load: {}".format(detail))


def prepare_executor_sandbox(
    task_id: str,
    clone: Path,
    runtime_root: Path,
    project_root: Path,
    pool_root: Path,
    state_root: Path,
    source_env: Optional[Mapping[str, str]] = None,
) -> Dict[str, object]:
    require_sandbox_exec()
    clone = Path(clone).resolve()
    environment = sandbox_environment(clone, source_env)
    profile_path = write_sandbox_profile(
        state_root, task_id, clone, runtime_root, project_root, pool_root,
    )
    _prepare_sandbox_dirs(clone)
    probe_sandbox(profile_path, environment, clone)
    return {
        "profilePath": str(profile_path),
        "environment": environment,
        "sandboxExec": str(SANDBOX_EXEC),
        "clone": str(clone),
    }


def _lexists(path: Path) -> bool:
    try:
        os.lstat(str(path))
        return True
    except FileNotFoundError:
        return False
    except OSError as error:
        raise ExecutorSandboxError("sandbox auth path is unreadable") from error


def _is_regular_file(path: Path) -> bool:
    try:
        mode = os.lstat(str(path)).st_mode
    except OSError as error:
        raise ExecutorSandboxError("sandbox auth path is unreadable") from error
    return stat.S_ISREG(mode)


def sandbox_auth_json_path(home: Path) -> Path:
    return Path(home) / AUTH_JSON_DIRNAME / AUTH_JSON_FILENAME


def clear_sandbox_auth_json(home: Path, clone: Path) -> None:
    clone = Path(clone).resolve()
    home = Path(home)
    if not str(home):
        raise ExecutorSandboxError("sandbox HOME is missing")
    if home.is_symlink():
        raise ExecutorSandboxError("sandbox HOME must not be a symlink")
    if not home.exists() or not home.is_dir():
        raise ExecutorSandboxError("sandbox HOME must be a directory")
    if not path_within(home, clone):
        raise ExecutorSandboxError("sandbox HOME escaped the clone")
    cursor_dir = home / AUTH_JSON_DIRNAME
    auth = sandbox_auth_json_path(home)
    if auth.parent != cursor_dir or cursor_dir.parent != home:
        raise ExecutorSandboxError("sandbox auth path escaped the clone HOME")
    if auth.name != AUTH_JSON_FILENAME or cursor_dir.name != AUTH_JSON_DIRNAME:
        raise ExecutorSandboxError("sandbox auth path is invalid")
    if not _lexists(cursor_dir) and not _lexists(auth):
        return
    if _lexists(cursor_dir):
        if cursor_dir.is_symlink():
            raise ExecutorSandboxError("refusing to follow .cursor symlink")
        if not cursor_dir.is_dir():
            raise ExecutorSandboxError("sandbox auth parent is not a directory")
    elif _lexists(auth):
        raise ExecutorSandboxError("sandbox auth parent is missing")
    if not _lexists(auth):
        return
    if auth.is_symlink():
        raise ExecutorSandboxError("refusing to follow auth.json symlink")
    if not _is_regular_file(auth):
        raise ExecutorSandboxError("auth.json is not a regular file")
    os.unlink(str(auth))
    if _lexists(auth):
        raise ExecutorSandboxError("auth.json still exists after cleanup")


def launch_sandboxed_executor(
    argv: Sequence[str],
    workspace: Path,
    sandbox: Mapping[str, object],
    input_text: str,
    timeout_seconds: int,
) -> subprocess.CompletedProcess:
    require_sandbox_exec()
    if not argv:
        raise ExecutorSandboxError("executor command is empty")
    workspace = Path(workspace).resolve()
    profile_path = Path(str(sandbox.get("profilePath") or ""))
    if profile_path.is_symlink() or not profile_path.is_file():
        raise ExecutorSandboxError("sandbox profile is missing")
    expected_clone = Path(str(sandbox.get("clone") or "")).resolve()
    if expected_clone != workspace:
        raise ExecutorSandboxError("sandbox clone does not match the leased workspace")
    text = profile_path.read_text(encoding="utf-8")
    assert_fail_closed_profile(text, workspace)
    environment = dict(sandbox.get("environment") or {})
    if not environment:
        raise ExecutorSandboxError("sandbox environment is missing")
    home = Path(str(environment.get("HOME") or ""))
    if not home or not path_within(home, workspace):
        raise ExecutorSandboxError("HOME must sit inside the task clone")
    tmp = Path(str(environment.get("TMPDIR") or ""))
    if not tmp or not path_within(tmp, workspace):
        raise ExecutorSandboxError("TMPDIR must sit inside the task clone")
    sandbox_exec = Path(str(sandbox.get("sandboxExec") or SANDBOX_EXEC))
    if sandbox_exec.resolve() != SANDBOX_EXEC.resolve():
        raise ExecutorSandboxError("refusing to use a non-system sandbox-exec")
    try:
        return subprocess.run(
            [str(SANDBOX_EXEC), "-f", str(profile_path), *[str(part) for part in argv]],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(workspace),
            env=environment,
            check=False,
            shell=False,
        )
    finally:
        clear_sandbox_auth_json(home, workspace)
