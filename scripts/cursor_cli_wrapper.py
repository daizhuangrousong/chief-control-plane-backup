#!/usr/bin/env python3
"""Injected Cursor CLI wrapper entry. PYTHONPATH must include src."""

from control_plane.services.cursor_cli_wrapper import main


if __name__ == "__main__":
    raise SystemExit(main())
