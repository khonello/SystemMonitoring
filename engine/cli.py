"""Command-line entry for the Engine.

    python -m engine --help

Why this is a separate module from main.py
------------------------------------------
engine.config reads every value from os.environ into module-level Final
constants **at import time**, and main.py imports those constants at module
level. So a flag cannot be applied by setting an attribute on config after the
fact — consumers have already bound the value. tests/conftest.py documents the
same trap from the other direction.

The order that does work is: parse argv, write into os.environ, and only then
import the component. That is why `main` is imported inside run() rather than
at the top of this file, and why main.py itself needed no changes — running
`python -m engine.main` with no flags still works exactly as before.

Standard library only, like the rest of the Engine: a Linux install pulls
nothing, and that must stay true of its entry point too.
"""

from __future__ import annotations

import argparse
import os
import sys


# The other programs that ship with the Engine. Listed in --help and --check so
# the shape of the package is discoverable without reading the source.
PROGRAMS: tuple[tuple[str, str], ...] = (
    ("python -m engine", "the hub itself - accepts peers, routes, stores"),
    ("python -m engine.setup_db [PATH]", "create the SQLite schema without serving"),
    ("python -m scripts.generate_cert", "generate the self-signed TLS certificate (shared)"),
    ("python -m scripts.bench_database", "measure SQLite write cost (shared)"),
)


def _programs_text() -> str:
    lines = "\n".join(f"  {invocation}\n      {text}" for invocation, text in PROGRAMS)
    return f"Programs in this package:\n{lines}"


def build_parser() -> argparse.ArgumentParser:
    """Flags for the Engine. Every one maps onto an existing env var."""
    parser = argparse.ArgumentParser(
        prog="python -m engine",
        description="Lab Monitor Engine - the central hub. Linux only in production.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Every flag has an environment-variable equivalent, which is what the "
            "flag sets. Flags win over an already-set variable.\n\n"
            + _programs_text()
        ),
    )

    parser.add_argument(
        "--host", metavar="ADDR",
        help="Address to bind (env ENGINE_HOST, default 0.0.0.0)",
    )
    parser.add_argument(
        "--port", type=int, metavar="N",
        help="Port to listen on (env ENGINE_PORT, default 5000)",
    )
    parser.add_argument(
        "--db", metavar="PATH",
        help="SQLite database file (env ENGINE_DB, default monitoring.db)",
    )
    parser.add_argument(
        "--retention-days", type=int, metavar="N",
        help="Delete monitoring data older than N days; 0 disables pruning "
             "(env ENGINE_RETENTION_DAYS, default 30)",
    )
    parser.add_argument(
        "--no-tls", action="store_true",
        help="Serve plaintext even if certificates exist (env ENGINE_TLS=0). "
             "TLS is otherwise enabled by the presence of certs/engine-cert.pem",
    )
    parser.add_argument(
        "--dev-bypass-auth", action="store_true",
        help="Skip the registration handshake ENTIRELY - no nonce is sent. "
             "Development only; the Engine logs a warning for every peer",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Log at DEBUG, which surfaces heartbeats (env ENGINE_LOG_LEVEL)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Report the resolved configuration and prepare the database, then "
             "exit without binding a port",
    )

    return parser


def _env_from(args: argparse.Namespace) -> dict[str, str]:
    """Translate parsed flags into the environment variables config reads."""
    env: dict[str, str] = {}

    if args.host is not None:
        env["ENGINE_HOST"] = args.host
    if args.port is not None:
        env["ENGINE_PORT"] = str(args.port)
    if args.db is not None:
        env["ENGINE_DB"] = args.db
    if args.retention_days is not None:
        env["ENGINE_RETENTION_DAYS"] = str(args.retention_days)
    if args.no_tls:
        env["ENGINE_TLS"] = "0"
    if args.dev_bypass_auth:
        env["DEV_BYPASS_AUTH"] = "1"
    if args.verbose:
        env["ENGINE_LOG_LEVEL"] = "DEBUG"

    return env


def _check() -> int:
    """Print what the Engine resolved, and prove the database is writable.

    Deliberately does not bind the port: the point is to answer "is this box
    configured the way I think" without taking the address, so it can be run
    while an Engine is already serving.
    """
    from engine import config, database

    print("Engine configuration")
    print(f"  listen           {config.SERVER_HOST}:{config.SERVER_PORT}")
    print(f"  database         {config.DATABASE_PATH.resolve()}")
    print(f"  max clients      {config.MAX_CLIENTS}")
    print(f"  max admins       {config.MAX_ADMINS}")
    print(f"  heartbeat timeout {config.CLIENT_HEARTBEAT_TIMEOUT}s")
    print(f"  log level        {config.LOG_LEVEL}")

    if config.RETENTION_DAYS > 0:
        print(f"  retention        {config.RETENTION_DAYS} days, "
              f"sweeping every {config.PRUNE_INTERVAL}s")
    else:
        print("  retention        DISABLED - monitoring data will grow unbounded")

    print(f"  outbox TTL       {config.OUTBOX_TTL}s")

    if config.TLS_ENABLED:
        print(f"  transport        TLS, certificate {config.TLS_CERT_PATH}")
        if not config.TLS_CERT_PATH.exists():
            print("    ERROR: that certificate does not exist; the Engine will "
                  "refuse to start")
            return 1
    else:
        print("  transport        PLAINTEXT - anyone on the network can read traffic")

    if config.DEV_BYPASS_AUTH:
        print("  authentication   BYPASSED - the handshake is skipped entirely")
    else:
        print("  authentication   handshake runs (verification is a stub until "
              "Phase 7)")

    try:
        database.init_database()
    except Exception as exc:  # noqa: BLE001 - reported as a check failure
        print(f"\nDatabase could not be prepared: {exc}")
        return 1
    finally:
        database.close_database()

    print("\nDatabase ready. Configuration looks serviceable.\n")
    print(_programs_text())
    return 0


def run(argv: list[str] | None = None) -> int:
    """Parse flags, apply them to the environment, then start the Engine."""
    args = build_parser().parse_args(argv)
    os.environ.update(_env_from(args))

    # Imported here, after the environment is set - see the module docstring.
    if args.check:
        return _check()

    from engine.main import main

    return main()


if __name__ == "__main__":
    sys.exit(run())
