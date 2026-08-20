import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..domain.models import ApprovalClass, ready_requires_owner_approval
from .cursor_runner import CursorAdapterError, redact_secrets


REQUIRED_FIELDS = (
    "taskId", "projectId", "title", "objective", "scope", "acceptance",
    "workspaceRoots", "approvalClass", "ownerApprovalRef", "leaseId",
    "taskVersion", "baselineRef",
)
FORBIDDEN_CONFIG_KEYS = {
    "apiKey", "api_key", "token", "secret", "password", "CURSOR_API_KEY",
    "FEISHU_APP_SECRET", "appSecret", "app_secret",
}
HEADLESS_FLAGS = (
    "--print", "--output-format", "json", "--force", "--trust",
    "--sandbox", "enabled",
)


class CursorCliWrapperError(CursorAdapterError):
    pass


def load_runner_config(path: str) -> Dict[str, Any]:
    config_path = Path(path).expanduser()
    if not config_path.is_absolute():
        raise CursorCliWrapperError("runner config path must be absolute")
    if not config_path.is_file():
        raise CursorCliWrapperError("runner config is missing")
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CursorCliWrapperError("runner config is not valid JSON") from error
    if not isinstance(payload, dict):
        raise CursorCliWrapperError("runner config must be a JSON object")
    forbidden = sorted(set(payload) & FORBIDDEN_CONFIG_KEYS)
    if forbidden:
        raise CursorCliWrapperError("runner config must not contain secrets: {}".format(", ".join(forbidden)))
    cli_path = str(payload.get("cliPath") or "").strip()
    if not cli_path or "/" not in cli_path:
        raise CursorCliWrapperError("cliPath must be an explicit absolute executable path")
    resolved = Path(cli_path).expanduser()
    if not resolved.is_absolute() or not resolved.is_file():
        raise CursorCliWrapperError("cliPath must exist as an absolute file")
    if not os.access(resolved, os.X_OK):
        raise CursorCliWrapperError("cliPath is not executable")
    allowlist = payload.get("projectAllowlist")
    if not isinstance(allowlist, list) or not allowlist or any(not str(item).strip() for item in allowlist):
        raise CursorCliWrapperError("projectAllowlist must be a non-empty list")
    timeout = int(payload.get("timeoutSeconds") or 300)
    if timeout <= 0:
        raise CursorCliWrapperError("timeoutSeconds must be positive")
    return {
        "cliPath": str(resolved),
        "projectAllowlist": [str(item).strip() for item in allowlist],
        "timeoutSeconds": timeout,
        "idleSeconds": int(payload.get("idleSeconds") or 30),
        "logPath": payload.get("logPath"),
    }


def parse_task_payload(raw: str) -> Dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CursorCliWrapperError("stdin must be R0 JSON") from error
    if not isinstance(payload, dict):
        raise CursorCliWrapperError("stdin JSON must be an object")
    missing = [key for key in REQUIRED_FIELDS if key not in payload]
    if missing:
        raise CursorCliWrapperError("stdin JSON missing fields: {}".format(", ".join(missing)))
    extra = sorted(set(payload) - set(REQUIRED_FIELDS))
    if extra:
        raise CursorCliWrapperError("stdin JSON has unknown fields: {}".format(", ".join(extra)))
    for key in ("taskId", "projectId", "title", "objective", "leaseId", "baselineRef"):
        if not str(payload.get(key) or "").strip():
            raise CursorCliWrapperError("{} must be a non-empty string".format(key))
    if not isinstance(payload["taskVersion"], int) or payload["taskVersion"] < 1:
        raise CursorCliWrapperError("taskVersion must be a positive integer")
    for key in ("scope", "acceptance", "workspaceRoots"):
        value = payload.get(key)
        if not isinstance(value, list) or not value or any(not str(item).strip() for item in value):
            raise CursorCliWrapperError("{} must be a non-empty string list".format(key))
    try:
        ApprovalClass(payload["approvalClass"])
    except ValueError as error:
        raise CursorCliWrapperError("approvalClass is not allowed") from error
    if ready_requires_owner_approval(payload["approvalClass"], payload.get("ownerApprovalRef")):
        raise CursorCliWrapperError("ownerApprovalRef is required for this approvalClass")
    return payload


def assert_workspace(payload: Dict[str, Any]) -> Path:
    workspace = Path(str(payload["workspaceRoots"][0])).expanduser().resolve()
    if not workspace.is_dir():
        raise CursorCliWrapperError("workspace root does not exist")
    return workspace


def cli_is_authenticated(cli_path: str, env: Optional[Mapping[str, str]] = None) -> bool:
    environment = env if env is not None else os.environ
    if str(environment.get("CURSOR_API_KEY") or "").strip():
        return True
    try:
        completed = subprocess.run(
            [cli_path, "status", "--format", "json"],
            capture_output=True, text=True, timeout=30, check=False, shell=False,
            env=dict(environment),
        )
    except OSError:
        return False
    if completed.returncode != 0:
        return False
    try:
        data = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return False
    return bool(isinstance(data, dict) and data.get("isAuthenticated"))


def build_cli_command(cli_path: str, workspace: Path, payload: Dict[str, Any]) -> List[str]:
    prompt = json.dumps({
        "constraints": [
            "Do not access the network or fetch external documents.",
            "Do not modify source code, tests, git metadata, or credentials.",
            "Do not run git commit, push, merge, or deploy.",
            "Follow the leased task payload exactly.",
        ],
        "task": payload,
    }, ensure_ascii=False)
    return [
        cli_path, *HEADLESS_FLAGS, "--workspace", str(workspace), prompt,
    ]


def invoke_cursor_cli(
    payload: Dict[str, Any],
    config: Dict[str, Any],
    env: Optional[Mapping[str, str]] = None,
) -> subprocess.CompletedProcess:
    if payload["projectId"] not in config["projectAllowlist"]:
        raise CursorCliWrapperError("project is not in the runner allowlist")
    workspace = assert_workspace(payload)
    environment = env if env is not None else os.environ
    if not cli_is_authenticated(config["cliPath"], environment):
        raise CursorCliWrapperError("Cursor CLI is not authenticated; refusing to start")
    command = build_cli_command(config["cliPath"], workspace, payload)
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=config["timeoutSeconds"],
        cwd=str(workspace),
        check=False,
        shell=False,
        env=dict(environment),
    )


def _print_process(completed: subprocess.CompletedProcess) -> int:
    if completed.stdout:
        sys.stdout.write(redact_secrets(completed.stdout))
    if completed.stderr:
        sys.stderr.write(redact_secrets(completed.stderr))
    return 0 if completed.returncode == 0 else 1


def main(argv: Optional[Sequence[str]] = None, stdin=None, env: Optional[Mapping[str, str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Injected Cursor CLI wrapper. Reads R0 JSON on stdin.")
    parser.add_argument("--runner-config", required=True, help="Absolute gitignored runner config path")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        config = load_runner_config(args.runner_config)
        raw = (stdin or sys.stdin).read()
        payload = parse_task_payload(raw)
        completed = invoke_cursor_cli(payload, config, env)
    except CursorCliWrapperError as error:
        sys.stderr.write(redact_secrets(str(error)) + "\n")
        return 2
    except subprocess.TimeoutExpired as error:
        sys.stderr.write(redact_secrets("cursor CLI timed out") + "\n")
        if error.stdout:
            sys.stdout.write(redact_secrets(error.stdout if isinstance(error.stdout, str) else error.stdout.decode("utf-8", "replace")))
        if error.stderr:
            sys.stderr.write(redact_secrets(error.stderr if isinstance(error.stderr, str) else error.stderr.decode("utf-8", "replace")))
        return 1
    return _print_process(completed)
