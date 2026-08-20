#!/usr/bin/env python3
"""Single-task Control Plane Cursor daemon. PYTHONPATH must include src."""

import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from control_plane.config import load_settings
from control_plane.services.cursor_daemon import CursorDaemon
from control_plane.services.cursor_runner import CursorRunner, redact_secrets
from control_plane.services.dispatcher import LeaseDispatcher
from control_plane.storage import Repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the injected CursorRunner as a single-task idle loop")
    parser.add_argument("--config", required=True, help="Absolute Control Plane project config")
    parser.add_argument("--executor-id", required=True)
    parser.add_argument("--executor-command", required=True, nargs="+")
    parser.add_argument("--project", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--idle-seconds", type=int, default=30)
    parser.add_argument("--log-file", required=True, help="Absolute rotating log path")
    parser.add_argument("--max-cycles", type=int, default=0)
    return parser


def configure_log(path: str):
    log_path = Path(path).expanduser()
    if not log_path.is_absolute():
        raise SystemExit("log file path must be absolute")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(message)s")

    def emit(message: str) -> None:
        logging.info(redact_secrets(message))

    return emit


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
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
    CursorDaemon(runner, args.project, args.idle_seconds, log=emit).run(args.max_cycles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
