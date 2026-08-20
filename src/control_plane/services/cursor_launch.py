import argparse
import json
import os
import plistlib
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .cursor_runner import CursorAdapterError, redact_secrets


CLI_ENV_ALLOWLIST = (
    "HOME", "USER", "LOGNAME", "PATH", "SHELL",
    "TMPDIR", "TMP", "TEMP",
    "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "LC_TIME", "TZ",
    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR",
    "CURSOR_API_KEY", "CURSOR_API_ENDPOINT",
)


class CursorLaunchError(CursorAdapterError):
    pass


def filter_cli_env(source: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    environment = source if source is not None else os.environ
    filtered: Dict[str, str] = {}
    for key in CLI_ENV_ALLOWLIST:
        value = environment.get(key)
        if value is None or value == "":
            continue
        filtered[key] = str(value)
    return filtered


def parse_executor_command(raw: str) -> List[str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CursorLaunchError("executor command must be a JSON array of arguments") from error
    if not isinstance(payload, list) or not payload:
        raise CursorLaunchError("executor command must be a non-empty JSON array")
    command = [str(part) for part in payload]
    if any(not part.strip() for part in command):
        raise CursorLaunchError("executor command must not contain empty arguments")
    if "/" not in command[0] or not Path(command[0]).is_absolute():
        raise CursorLaunchError("executor command[0] must be an absolute path")
    return command


def build_runner_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the injected CursorRunner as a single-task idle loop")
    parser.add_argument("--config", required=True, help="Absolute Control Plane project config")
    parser.add_argument("--executor-id", required=True)
    parser.add_argument(
        "--executor-command", required=True,
        help="JSON array of absolute argv for the injected wrapper",
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--idle-seconds", type=int, default=30)
    parser.add_argument("--log-file", required=True, help="Absolute rotating log path")
    parser.add_argument("--halt-file", required=True, help="Absolute halt file written on circuit-breaker")
    parser.add_argument("--reject-limit", type=int, default=3)
    parser.add_argument("--max-cycles", type=int, default=0)
    parser.add_argument("--inbox-dir", default=None, help="Optional absolute Chief inbox for status receipts")
    return parser


def parse_runner_argv(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    args = build_runner_parser().parse_args(None if argv is None else list(argv))
    args.executor_command = parse_executor_command(args.executor_command)
    if args.reject_limit < 1:
        raise CursorLaunchError("reject-limit must be >= 1")
    if args.idle_seconds < 0:
        raise CursorLaunchError("idle-seconds must be >= 0")
    for path_arg in (args.config, args.log_file, args.halt_file):
        if not Path(path_arg).is_absolute():
            raise CursorLaunchError("config, log-file and halt-file must be absolute paths")
    if args.inbox_dir:
        inbox = Path(args.inbox_dir)
        if not inbox.is_absolute():
            raise CursorLaunchError("inbox-dir must be an absolute path")
        if inbox.exists() and (inbox.is_symlink() or not inbox.is_dir()):
            raise CursorLaunchError("inbox-dir must be a directory")
        args.inbox_dir = str(inbox)
    else:
        args.inbox_dir = None
    return args


def plist_program_arguments(path: Path) -> List[str]:
    with path.open("rb") as handle:
        payload = plistlib.load(handle)
    arguments = payload.get("ProgramArguments")
    if not isinstance(arguments, list) or not arguments:
        raise CursorLaunchError("plist ProgramArguments must be a non-empty array")
    return [str(part) for part in arguments]


def plist_keepalive_is_limited(path: Path) -> bool:
    with path.open("rb") as handle:
        payload = plistlib.load(handle)
    keepalive = payload.get("KeepAlive")
    if keepalive is True:
        return False
    if isinstance(keepalive, dict) and keepalive.get("SuccessfulExit") is False:
        return True
    return False


def write_halt_file(path: Path, reason: str, fingerprint: str, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "status": "halted",
        "reason": redact_secrets(reason),
        "fingerprint": redact_secrets(fingerprint),
        "rejectCount": count,
        "waitingFor": "Chief",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_halt_file(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "halted", "reason": "halt file is unreadable", "waitingFor": "Chief"}
    if not isinstance(payload, dict):
        return {"status": "halted", "reason": "halt file is invalid", "waitingFor": "Chief"}
    payload["reason"] = redact_secrets(str(payload.get("reason") or "halted"))
    payload["status"] = "halted"
    payload["waitingFor"] = "Chief"
    return payload
