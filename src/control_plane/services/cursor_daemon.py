import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .cursor_launch import read_halt_file, write_halt_file
from .cursor_runner import CursorAdapterError, CursorRunner, redact_secrets
from .project_isolation import ISOLATED_PROJECT_IDS


class CursorDaemonError(RuntimeError):
    pass


class CursorDaemon:
    """Single-task idle loop around CursorRunner. Empty queues never start Cursor."""

    def __init__(
        self,
        runner: CursorRunner,
        project_id: str,
        idle_seconds: int = 30,
        log: Optional[Callable[[str], None]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        halt_file: Optional[Path] = None,
        reject_limit: int = 3,
        reporter: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        if not project_id or project_id in ISOLATED_PROJECT_IDS:
            raise CursorDaemonError("project is not allowed for the Cursor daemon")
        if idle_seconds < 0:
            raise CursorDaemonError("idle_seconds must be >= 0")
        if reject_limit < 1:
            raise CursorDaemonError("reject_limit must be >= 1")
        self.runner = runner
        self.project_id = project_id
        self.idle_seconds = idle_seconds
        self.halt_file = Path(halt_file) if halt_file else None
        self.reject_limit = reject_limit
        self._reporter = reporter
        self._log = log or (lambda _message: None)
        self._sleep = sleep or time.sleep
        self._reject_fingerprint = None
        self._reject_count = 0

    def run(self, max_cycles: int = 0) -> Dict[str, Any]:
        if self.halt_file:
            existing = read_halt_file(self.halt_file)
            if existing:
                self._log(redact_secrets("halted: {}".format(existing.get("reason"))))
                return {"status": "halted", "reason": existing.get("reason"), "cycles": 0, "waitingFor": "Chief"}
        cycles = 0
        last: Dict[str, Any] = {"status": "idle", "reason": "not started"}
        while True:
            try:
                last = self.runner.run_next(self.project_id)
            except CursorAdapterError as error:
                self._log(redact_secrets("rejected: {}".format(error)))
                last = {"status": "rejected", "error": str(error), "task_id": getattr(error, "task_id", None)}
            status = last.get("status") or "unknown"
            if status == "idle":
                self._reject_fingerprint = None
                self._reject_count = 0
                self._log(redact_secrets("idle: no eligible READY task"))
            else:
                self._log(redact_secrets("cycle status={} task_state={}".format(
                    status, last.get("task_state") or last.get("error") or "",
                )))
                halted = self._note_rejection(last)
                if halted is not None:
                    halted["cycles"] = cycles + 1
                    if last.get("task_id"):
                        halted["task_id"] = last["task_id"]
                    if self._reporter:
                        self._reporter(halted)
                    return halted
            if self._reporter:
                self._reporter(last)
            cycles += 1
            last = dict(last)
            last["cycles"] = cycles
            if max_cycles and cycles >= max_cycles:
                return last
            self._sleep(self.idle_seconds)

    def _note_rejection(self, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if result.get("status") != "rejected":
            self._reject_fingerprint = None
            self._reject_count = 0
            return None
        fingerprint = redact_secrets("rejected:{}".format(result.get("error") or "unknown"))
        if fingerprint == self._reject_fingerprint:
            self._reject_count += 1
        else:
            self._reject_fingerprint = fingerprint
            self._reject_count = 1
        if self._reject_count < self.reject_limit:
            return None
        reason = redact_secrets(
            "circuit breaker stopped after {} identical rejections: {}".format(
                self._reject_count, result.get("error") or "unknown",
            )
        )
        if self.halt_file:
            write_halt_file(self.halt_file, reason, fingerprint, self._reject_count)
        self._log(reason)
        return {
            "status": "halted",
            "reason": reason,
            "error": result.get("error"),
            "waitingFor": "Chief",
        }
