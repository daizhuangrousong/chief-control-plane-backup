from .base import (
    ExecutionResult, ExecutorAdapter, GitWorktreeVerifier, ScopeViolationError,
    TARGET_NOT_READY, TargetedClaimResult, WorktreeVerificationError, in_scope,
)
from .dispatcher_gateway import DispatcherGateway
from .grok_client import FakeGrokClient, GrokClient, GrokPrompt, GrokResult, PlannedChange
from .cursor_grok import CursorGrokExecutor


def build_cursor_grok_executor(repository, executor_id: str = "cursor-grok",
                               grok: GrokClient = None, git_runner=None) -> CursorGrokExecutor:
    """Construct a CursorGrokExecutor wired to the existing Chief dispatch primitives.

    ``grok`` defaults to the offline ``FakeGrokClient`` so no paid API or secret is
    ever touched during validation or a low-risk Shadow run.
    """
    from ..services.dispatcher import LeaseDispatcher

    dispatcher = LeaseDispatcher(repository)
    gateway = DispatcherGateway(dispatcher, repository)
    verifier = GitWorktreeVerifier(git_runner=git_runner)
    return CursorGrokExecutor(
        gateway=gateway, grok=grok or FakeGrokClient(), verifier=verifier,
        repository=repository, executor_id=executor_id,
    )


__all__ = [
    "ExecutionResult", "ExecutorAdapter", "GitWorktreeVerifier", "ScopeViolationError",
    "TARGET_NOT_READY", "TargetedClaimResult", "WorktreeVerificationError",
    "DispatcherGateway", "FakeGrokClient", "GrokClient", "GrokPrompt", "GrokResult",
    "PlannedChange", "CursorGrokExecutor", "build_cursor_grok_executor",
]
