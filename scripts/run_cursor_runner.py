#!/usr/bin/env python3
"""Single-task Control Plane Cursor daemon. PYTHONPATH must include src."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from control_plane.config import load_settings
from control_plane.services.cursor_daemon import CursorDaemon
from control_plane.services.cursor_launch import parse_runner_argv
from control_plane.services.cursor_runner import CursorRunner, redact_secrets
from control_plane.services.dispatcher import LeaseDispatcher
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
    args = parse_runner_argv(argv)
    settings = load_settings(args.config)
    repository = Repository(settings.database)
    repository.migrate()
    for project in settings.projects:
        repository.upsert_project(project)
    emit = configure_log(args.log_file)
    runner = CursorRunner(
        LeaseDispatcher(repository),
        executor_id=args.executor_id,
        executor_command=args.executor_command,
        timeout_seconds=args.timeout,
        log=emit,
    )
    result = CursorDaemon(
        runner, args.project, args.idle_seconds, log=emit,
        halt_file=Path(args.halt_file), reject_limit=args.reject_limit,
    ).run(args.max_cycles)
    if result.get("status") == "halted":
        emit(redact_secrets("halted waiting for Chief: {}".format(result.get("reason"))))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
