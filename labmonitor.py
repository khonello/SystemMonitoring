#!/usr/bin/env python3
"""Development launcher — one command for all three systems and their helpers.

    python labmonitor.py <system> [flags]
    python labmonitor.py client --help

A convenience for a machine that has all three checked out. In production each
unit runs from its own package (`python -m engine`, `python -m client`,
`python -m admin`) and this file is not deployed at all — which is why every
flag lives in the components' own cli.py modules rather than here. This only
dispatches.

Each subcommand imports its component **inside** the branch that needs it, on
purpose. A top-level `from admin.cli import run` would drag PySide6 into
`labmonitor.py engine`, and the Engine is meant to import nothing but the
standard library.

Unrecognised flags are passed straight through to the chosen component, so
`--help` after a system name gives that system's own help rather than this one.
"""

from __future__ import annotations

import sys

SYSTEMS = {
    "engine": "The central hub. Linux only in production; runs under WSL here.",
    "client": "The Client Agent. Windows only.",
    "admin": "The Administrator client.",
}

HELPERS = {
    "overlay": "Lockout overlay window - TAKES OVER THE SCREEN.",
    "dialog": "Warning dialog window.",
    "certs": "Generate the Engine's self-signed TLS certificate.",
    "initdb": "Create the Engine's SQLite schema.",
}

USAGE = f"""\
usage: python labmonitor.py <command> [flags]

Systems (each also runs standalone as `python -m <name>`):
{chr(10).join(f"  {name:9} {text}" for name, text in SYSTEMS.items())}

Helpers:
{chr(10).join(f"  {name:9} {text}" for name, text in HELPERS.items())}

Quick checks that need nothing else running:
  python labmonitor.py engine --check       resolved config, prepares the database
  python labmonitor.py client --once        one real collection cycle, printed
  python labmonitor.py admin  --check-qml   loads every QML file offscreen

`<command> --help` shows that command's own flags.\
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(USAGE)
        return 0

    command, rest = argv[0], argv[1:]

    if command == "engine":
        from engine.cli import run
        return run(rest)

    if command == "client":
        from client.cli import run
        return run(rest)

    if command == "admin":
        from admin.cli import run
        return run(rest)

    if command == "overlay":
        # Deliberately noisy. This covers the whole screen, disables Task
        # Manager and re-asserts topmost twice a second; it is not something to
        # start by accident on a machine someone is using.
        print(
            "WARNING: the overlay takes over the primary display and disables "
            "Task Manager.\n         It closes at its --until time and always "
            "restores the policy on exit.",
            file=sys.stderr,
        )
        from client.overlay_app import main as overlay_main
        return overlay_main(rest)

    if command == "dialog":
        from client.dialog_app import main as dialog_main
        return dialog_main(rest)

    if command == "certs":
        from scripts.generate_cert import main as certs_main
        return certs_main(rest)

    if command == "initdb":
        from engine.setup_db import main as initdb_main
        return initdb_main(rest)

    print(f"Unknown command {command!r}\n", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
