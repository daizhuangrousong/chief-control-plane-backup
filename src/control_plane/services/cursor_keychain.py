"""Load the Cursor API key from macOS Keychain into process memory only."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, Mapping, Optional

from .cursor_launch import filter_cli_env
from .cursor_runner import CursorAdapterError


SECURITY = Path("/usr/bin/security")
KEYCHAIN_TIMEOUT_SECONDS = 10


class CursorKeychainError(CursorAdapterError):
    pass


class ExecutorEnvironment(dict):
    """Allowlisted child env. Never include CURSOR_API_KEY in repr/str."""

    def __repr__(self) -> str:
        parts = []
        for key, value in self.items():
            if key == "CURSOR_API_KEY":
                parts.append("{0!r}: [REDACTED]".format(key))
            else:
                parts.append("{0!r}: {1!r}".format(key, value))
        return "{{{0}}}".format(", ".join(parts))

    __str__ = __repr__


def _identity_token(raw: object, label: str) -> str:
    text = str(raw or "").strip()
    if not text or len(text) > 128:
        raise CursorKeychainError("{} is invalid".format(label))
    if any(character.isspace() for character in text):
        raise CursorKeychainError("{} is invalid".format(label))
    forbidden = set("\"'`$;&|<>\\")
    if any(character in forbidden for character in text):
        raise CursorKeychainError("{} is invalid".format(label))
    return text


def require_security_binary(executable: Path = SECURITY) -> Path:
    executable = Path(executable)
    if executable.is_symlink() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise CursorKeychainError("security binary is unavailable; refusing to start")
    if not executable.is_absolute():
        raise CursorKeychainError("security binary must be an absolute path")
    if executable == SECURITY:
        try:
            resolved = executable.resolve()
            expected = SECURITY.resolve()
        except OSError as error:
            raise CursorKeychainError("security binary is unreadable") from error
        if resolved != expected:
            raise CursorKeychainError("security path escaped the system binary")
        return resolved
    return executable


def load_cursor_api_key(
    service: str,
    account: str,
    security_binary: Path = SECURITY,
) -> str:
    service = _identity_token(service, "keychain service")
    account = _identity_token(account, "keychain account")
    executable = require_security_binary(security_binary)
    argv = [
        str(executable),
        "find-generic-password",
        "-w",
        "-s",
        service,
        "-a",
        account,
    ]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=KEYCHAIN_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        raise CursorKeychainError("cursor API key is unavailable; refusing to start") from error
    except OSError as error:
        raise CursorKeychainError("cursor API key is unavailable; refusing to start") from error
    if completed.returncode != 0:
        raise CursorKeychainError("cursor API key is unavailable; refusing to start")
    value = (completed.stdout or "").strip("\r\n")
    if not value or "\n" in value or "\r" in value:
        raise CursorKeychainError("cursor API key is empty; refusing to start")
    return value


def executor_environment(
    api_key: str,
    source: Optional[Mapping[str, str]] = None,
) -> ExecutorEnvironment:
    if not str(api_key or "").strip("\r\n"):
        raise CursorKeychainError("cursor API key is empty; refusing to start")
    filtered = filter_cli_env(source)
    filtered.pop("CURSOR_API_KEY", None)
    environment = ExecutorEnvironment(filtered)
    environment["CURSOR_API_KEY"] = str(api_key)
    return environment
