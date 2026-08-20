#!/usr/bin/env python3
"""One-shot or idle-loop Chief task outbox importer. Do not install as a LaunchAgent in R2."""

import argparse
import time
from pathlib import Path

from control_plane.config import load_settings
from control_plane.services.chief_task_ingress import ChiefTaskImporter, load_ingress_config
from control_plane.storage import Repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest Chief task envelopes from a local outbox")
    parser.add_argument("--config", required=True, help="Absolute Control Plane project config")
    parser.add_argument("--ingress-config", required=True, help="Absolute ingress path config")
    parser.add_argument("--idle-seconds", type=int, default=30)
    parser.add_argument("--max-cycles", type=int, default=1)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings(args.config)
    ingress_cfg = load_ingress_config(args.ingress_config)
    repository = Repository(settings.database)
    repository.migrate()
    for project in settings.projects:
        repository.upsert_project(project)
    importer = ChiefTaskImporter(
        repository,
        Path(ingress_cfg["outboxDir"]),
        Path(ingress_cfg["inboxDir"]),
        settings.projects,
        allowed_projects=tuple(ingress_cfg.get("allowedProjects") or ["control-panel"]),
        max_bytes=int(ingress_cfg.get("maxBytes") or 262144),
    )
    cycles = 0
    while True:
        importer.ingest_once()
        cycles += 1
        if args.max_cycles and cycles >= args.max_cycles:
            return 0
        time.sleep(max(args.idle_seconds, 0))


if __name__ == "__main__":
    raise SystemExit(main())
