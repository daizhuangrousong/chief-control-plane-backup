#!/usr/bin/env python3
"""Single-task Control Plane Cursor daemon. PYTHONPATH must include src."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from control_plane.config import load_settings
from control_plane.services.chief_task_ingress import ChiefTaskReporter
from control_plane.services.cursor_daemon import CursorDaemon
from control_plane.services.cursor_keychain import (
    CursorKeychainError, executor_environment, load_cursor_api_key,
)
from control_plane.services.cursor_launch import CursorLaunchError, parse_runner_argv
from control_plane.services.cursor_runner import CursorAdapterError, CursorRunner, redact_secrets
from control_plane.services.dispatcher import ExecutorUnauthorizedError, LeaseDispatcher
from control_plane.services.production_runtime import ProductionRuntimeError, load_production_runtime
from control_plane.services.task_worktree import TaskWorktreeError
from control_plane.storage import Repository


def configure_log(path: str):
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(message)s")

    def emit(message: str) -> None:
        logging.info(redact_secrets(message))

    return emit


def main(argv=None) -> int:
    try:
        args = parse_runner_argv(argv)
        settings = load_settings(args.config)
        registered = next((item for item in settings.projects if item.id == args.project), None)
        if registered is None:
            raise ProductionRuntimeError("project is not registered: {}".format(args.project))
        runtime = load_production_runtime(args.lifecycle_config, registered.root)
        api_key = load_cursor_api_key(args.cursor_keychain_service, args.cursor_keychain_account)
        source_env = executor_environment(api_key)
        api_key = None
        repository = Repository(settings.database)
        repository.migrate()
        with repository.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        for project in settings.projects:
            repository.upsert_project(project)
        emit = configure_log(args.log_file)
        dispatcher = LeaseDispatcher(repository)
        runner = CursorRunner(
            dispatcher,
            executor_id=args.executor_id,
            executor_command=args.executor_command,
            timeout_seconds=args.timeout,
            log=emit,
            worktree_pool=runtime["pool"],
            execution_report_dir=runtime["execution_report_dir"],
            source_env=source_env,
        )
        if runner.worktree_pool is None:
            raise ProductionRuntimeError("production runner refused to start without a worktree pool")
        reporter = None
        if args.inbox_dir:
            reporter = ChiefTaskReporter(repository, Path(args.inbox_dir), dispatcher=dispatcher).report_cycle
        result = CursorDaemon(
            runner, args.project, args.idle_seconds, log=emit,
            halt_file=Path(args.halt_file), reject_limit=args.reject_limit,
            reporter=reporter,
        ).run(args.max_cycles)
    except (CursorLaunchError, ProductionRuntimeError, TaskWorktreeError, CursorAdapterError, ExecutorUnauthorizedError, CursorKeychainError) as error:
        message = redact_secrets(str(error))
        logging.error(message)
        sys.stderr.write(message + "\n")
        return 2
    if result.get("status") == "halted":
        emit(redact_secrets("halted waiting for Chief: {}".format(result.get("reason"))))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
