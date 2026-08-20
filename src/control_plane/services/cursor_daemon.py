import time
from typing import Any, Callable, Dict, Optional

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
    ):
        if not project_id or project_id in ISOLATED_PROJECT_IDS:
            raise CursorDaemonError("project is not allowed for the Cursor daemon")
        if idle_seconds < 0:
            raise CursorDaemonError("idle_seconds must be >= 0")
        self.runner = runner
        self.project_id = project_id
        self.idle_seconds = idle_seconds
        self._log = log or (lambda _message: None)
        self._sleep = sleep or time.sleep

    def run(self, max_cycles: int = 0) -> Dict[str, Any]:
        cycles = 0
        last: Dict[str, Any] = {"status": "idle", "reason": "not started"}
        while True:
            try:
                last = self.runner.run_next(self.project_id)
            except CursorAdapterError as error:
                self._log(redact_secrets("rejected: {}".format(error)))
                last = {"status": "rejected", "error": str(error)}
            status = last.get("status") or "unknown"
            if status == "idle":
                self._log(redact_secrets("idle: no eligible READY task"))
            else:
                self._log(redact_secrets("cycle status={} task_state={}".format(
                    status, last.get("task_state") or last.get("error") or "",
                )))
            cycles += 1
            last = dict(last)
            last["cycles"] = cycles
            if max_cycles and cycles >= max_cycles:
                return last
            self._sleep(self.idle_seconds)
