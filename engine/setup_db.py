#!/usr/bin/env python3
"""Create the Engine's SQLite database and schema.

    python -m engine.setup_db [path]

Idempotent — safe to re-run against an existing database.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from engine.config import DATABASE_PATH, LOG_LEVEL
from engine.database import init_database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialise the Engine database")
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=DATABASE_PATH,
        help=f"SQLite file to create (default: {DATABASE_PATH})",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=LOG_LEVEL, format="%(levelname)s - %(message)s")

    try:
        init_database(args.path)
    except Exception as exc:  # noqa: BLE001 - top-level CLI boundary
        logging.error("Failed to initialise database: %s", exc)
        return 1

    print(f"Database initialised at {args.path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
