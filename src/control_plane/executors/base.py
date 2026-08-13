import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Status returned by a precise targeted claim when the requested task is not
# present or not in a claimable state. Crucially this is NOT an error and MUST
# NOT trigger a fallback to `dispatcher.next()` to grab another READY task.
TARGET_NOT_READY = "TARGET_NOT_READY"


class WorktreeVerificationError(Exception):
    """Raised when the execution git worktree fails a baseline/isolation check."""


class ScopeViolationError(Exception):
    """Raised when a proposed change lands outside the authorized workspace roots."""


def in_scope(path: str, roots: List[str]) -> bool:
    normalized = os.path.normpath(path)
    for root in roots:
        normalized_root = os.path.normpath(root)
        if normalized == normalized_root or normalized.startswith(normalized_root.rstrip(os.sep) + os.sep):
            return True
    return False


@dataclass
class TargetedClaimResult:
    status: str  # "CLAIMED" or TARGET_NOT_READY
    task_id: str
    task: Optional[Dict[str, Any]] = None
    lease: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


@dataclass
class ExecutionResult:
    task_id: str
    success: bool
    status: str = "UNKNOWN"  # CLAIMED | REVIEW | FAILED | TARGET_NOT_READY
    lease_id: Optional[str] = None
    run_id: Optional[str] = None
    report_id: Optional[str] = None
    task_version: Optional[int] = None
    error: Optional[str] = None
    target_not_ready_reason: Optional[str] = None


class ExecutorAdapter(ABC):
    """Protocol for an external execution backend (Cursor + Grok, WorkBuddy Hy3, ...).

    Implementations must never move a task past REVIEW on their own; the existing
    ReviewGate (run by a separate Reviewer) is the only path to DONE.
    """

    executor_id: str = "unknown"

    @abstractmethod
    def execute(self, task_id: str, worktree_path: Path, expected_common_dir: str,
                baseline_ref: str, request_id_prefix: str = "cg",
                ttl_seconds: int = 900, trigger: str = "external-scheduler") -> ExecutionResult:
        ...


class GitWorktreeVerifier:
    """Fail-closed checks that execution happens in the right isolated git worktree.

    Verifies three things before any change is applied:
      1. Git common directory matches the registered project repo (it really is a
         worktree of the authorized repo, not a detached copy).
      2. Worktree HEAD equals the registered baseline (no baseline drift).
      3. The worktree is clean before execution (so our diff is the only diff).
    """

    def __init__(self, git_runner=None):
        self._git = git_runner or self._default_git

    @staticmethod
    def _default_git(worktree: Path, *args: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(worktree), *args],
                check=True, capture_output=True, text=True, timeout=15,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as error:
            raise WorktreeVerificationError(
                "git {} failed: {}".format(" ".join(args), error.stderr.strip()[:200])
            )
        except (subprocess.SubprocessError, OSError) as error:
            raise WorktreeVerificationError("git {} failed: {}".format(" ".join(args), str(error)[:200]))

    def verify(self, worktree_path: Path, expected_common_dir: str,
               expected_baseline: str) -> Dict[str, Any]:
        worktree_path = Path(worktree_path)
        # Raises if not inside a work tree.
        self._git(worktree_path, "rev-parse", "--is-inside-work-tree")
        actual_common = os.path.normpath(os.path.abspath(
            self._git(worktree_path, "rev-parse", "--git-common-dir")
        ))
        expected_common = os.path.normpath(os.path.abspath(str(expected_common_dir)))
        if actual_common != expected_common:
            raise WorktreeVerificationError(
                "worktree common dir '{}' does not match registered repo common dir '{}'".format(
                    actual_common, expected_common
                )
            )
        head = self._git(worktree_path, "rev-parse", "HEAD").lower()
        if not (head == expected_baseline.lower() or head.startswith(expected_baseline.lower())):
            raise WorktreeVerificationError(
                "worktree HEAD '{}' does not match baseline '{}' (baseline drift)".format(
                    head, expected_baseline
                )
            )
        porcelain = self._git(worktree_path, "status", "--porcelain")
        if porcelain:
            raise WorktreeVerificationError(
                "worktree is not clean before execution: {}".format(porcelain[:200])
            )
        return {"common_dir_ok": True, "baseline_ok": True, "clean": True, "head": head}
