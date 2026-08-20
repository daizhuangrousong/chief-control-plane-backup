#!/usr/bin/env python3
"""Chief outbox importer + identity reporter. Limited KeepAlive; do not put secrets in the plist."""

import argparse
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from control_plane.config import load_settings
from control_plane.services.chief_task_ingress import (
    MAX_IDLE_SECONDS, ChiefTaskImporter, ChiefTaskIngressError, load_ingress_config,
)
from control_plane.services.cursor_launch import read_halt_file, write_halt_file
from control_plane.services.cursor_runner import redact_secrets
from control_plane.services.dispatcher import LeaseDispatcher
from control_plane.storage import Repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest Chief task envelopes and publish identity receipts")
    parser.add_argument("--config", required=True, help="Absolute Control Plane project config")
    parser.add_argument("--ingress-config", required=True, help="Absolute ingress path config")
    parser.add_argument("--idle-seconds", type=int, default=5)
    parser.add_argument("--max-cycles", type=int, default=0)
    parser.add_argument("--log-file", required=True, help="Absolute rotating log path")
    parser.add_argument("--halt-file", required=True, help="Absolute halt file written on repeated failures")
    parser.add_argument("--reject-limit", type=int, default=3)
    return parser


def configure_log(path: str):
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(message)s")

    def emit(message: str) -> None:
        logging.info(redact_secrets(message))

    return emit


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.idle_seconds < 0 or args.idle_seconds > MAX_IDLE_SECONDS:
        raise SystemExit("idle-seconds must be between 0 and {}".format(MAX_IDLE_SECONDS))
    if args.reject_limit < 1:
        raise SystemExit("reject-limit must be >= 1")
    halt_file = Path(args.halt_file)
    existing = read_halt_file(halt_file)
    emit = configure_log(args.log_file)
    if existing:
        emit(redact_secrets("halted: {}".format(existing.get("reason"))))
        return 0
    settings = load_settings(args.config)
    ingress_cfg = load_ingress_config(args.ingress_config)
    repository = Repository(settings.database)
    repository.migrate()
    with repository.connect() as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    for project in settings.projects:
        repository.upsert_project(project)
    dispatcher = LeaseDispatcher(repository)
    importer = ChiefTaskImporter(
        repository,
        Path(ingress_cfg["outboxDir"]),
        Path(ingress_cfg["inboxDir"]),
        settings.projects,
        allowed_projects=tuple(ingress_cfg["allowedProjects"]),
        max_bytes=int(ingress_cfg["maxBytes"]),
        dispatcher=dispatcher,
    )
    failures = 0
    fingerprint = None
    cycles = 0
    while True:
        try:
            result = importer.cycle()
            ingest_count = len(result["ingested"])
            publish_count = len(result["published"])
            if ingest_count or publish_count:
                emit("cycle ingested={} published={}".format(ingest_count, publish_count))
            else:
                emit("idle: no outbox change and no identity state change")
            failures = 0
            fingerprint = None
        except (ChiefTaskIngressError, OSError) as error:
            reason = redact_secrets(str(error))
            emit("rejected: {}".format(reason))
            if reason == fingerprint:
                failures += 1
            else:
                fingerprint = reason
                failures = 1
            if failures >= args.reject_limit:
                write_halt_file(halt_file, "circuit breaker stopped after {} identical failures: {}".format(
                    failures, reason,
                ), reason, failures)
                emit("halted waiting for Chief")
                return 0
        cycles += 1
        if args.max_cycles and cycles >= args.max_cycles:
            return 0
        time.sleep(max(args.idle_seconds, 0))


if __name__ == "__main__":
    raise SystemExit(main())
