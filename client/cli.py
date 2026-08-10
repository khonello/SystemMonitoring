"""Command-line entry for the Client Agent.

    python -m client --help

Why this is a separate module from main.py: client.config reads every value
from os.environ into module-level Final constants at import time, so a flag has
to reach the environment *before* the component is imported. See engine.cli for
the longer version — the same reasoning applies to all three units.

`--once` is the flag that matters for bringing up a new machine. It runs a
single collection cycle with no Engine involved and prints what it gathered, so
"does psutil see processes here", "does the window-title call work" and "is the
agent looking at the right paths" can each be answered on their own, before any
networking is in the picture.
"""

from __future__ import annotations

import argparse
import os
import sys
import time


# The other programs in this package. The agent is the long-running one; these
# are spawned on demand or run by the installer's Scheduled Task, and each has
# its own argparse. Listed in --help and --check so the shape of the package is
# discoverable without reading the source.
PROGRAMS: tuple[tuple[str, str], ...] = (
    ("python -m client", "the agent itself - connects, monitors, executes commands"),
    ("python -m client.watchdog --id NAME",
     "one-shot lockout check; the installer runs this every 5 min as SYSTEM"),
    ("python -m client.overlay_app --until ISO",
     "fullscreen lockout overlay - TAKES OVER THE SCREEN"),
    ("python -m client.dialog_app --message TEXT", "warning dialog; answer is the exit code"),
    ("python -m client.install_service", "service, ACLs and watchdog task; needs elevation"),
)


def _programs_text() -> str:
    lines = "\n".join(f"  {invocation}\n      {text}" for invocation, text in PROGRAMS)
    return f"Programs in this package:\n{lines}"


def build_parser() -> argparse.ArgumentParser:
    """Flags for the Client Agent. Every one maps onto an existing env var."""
    parser = argparse.ArgumentParser(
        prog="python -m client",
        description="Lab Monitor Client Agent - Windows only. Headless in production.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Every connection flag has an environment-variable equivalent, which "
            "is what the flag sets. Flags win over an already-set variable.\n\n"
            + _programs_text()
        ),
    )

    parser.add_argument(
        "--engine", metavar="HOST",
        help="Engine address (env ENGINE_HOST, default 127.0.0.1)",
    )
    parser.add_argument(
        "--port", type=int, metavar="N",
        help="Engine port (env ENGINE_PORT, default 5000)",
    )
    parser.add_argument(
        "--id", metavar="NAME", dest="client_id",
        help="Identify as NAME instead of hostname-platform (env CLIENT_ID). "
             "Local state is per client, so several agents can run on one box "
             "without overwriting each other's schedule - but they still share "
             "one screen, so lockout enforcement cannot be simulated that way "
             "(issues.md B21)",
    )
    parser.add_argument(
        "--no-tls", action="store_true",
        help="Connect in plaintext even if the Engine certificate is present "
             "(env CLIENT_TLS=0)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Log at DEBUG (env CLIENT_LOG_LEVEL)",
    )

    diagnostics = parser.add_argument_group("diagnostics (no Engine needed)")
    diagnostics.add_argument(
        "--check", action="store_true",
        help="Report resolved configuration, local state and which bundled "
             "components are missing, then exit",
    )
    diagnostics.add_argument(
        "--once", action="store_true",
        help="Run one collection cycle, print what was gathered, and exit "
             "without connecting to anything",
    )
    diagnostics.add_argument(
        "--top", type=int, default=10, metavar="N",
        help="How many processes --once prints, busiest first (default 10)",
    )

    return parser


def _env_from(args: argparse.Namespace) -> dict[str, str]:
    """Translate parsed flags into the environment variables config reads."""
    env: dict[str, str] = {}

    if args.engine is not None:
        env["ENGINE_HOST"] = args.engine
    if args.port is not None:
        env["ENGINE_PORT"] = str(args.port)
    if args.client_id is not None:
        env["CLIENT_ID"] = args.client_id
    if args.no_tls:
        env["CLIENT_TLS"] = "0"
    if args.verbose:
        env["CLIENT_LOG_LEVEL"] = "DEBUG"

    return env


def _check() -> int:
    """Report configuration, local state, and what packaging has not built yet."""
    from client import config, lockout, policy

    print("Client Agent configuration")
    print(f"  client id        {config.CLIENT_ID}")
    print(f"  engine           {config.ENGINE_HOST}:{config.ENGINE_PORT}")
    print(f"  log level        {config.LOG_LEVEL}")
    print(f"  intervals        apps {config.MONITOR_INTERVAL}s, "
          f"network {config.NETWORK_INTERVAL}s, heartbeat {config.HEARTBEAT_SECONDS}s")

    if config.TLS_ENABLED:
        print(f"  transport        TLS, pinned to {config.TLS_CERT_PATH}")
        if not config.TLS_CERT_PATH.exists():
            print("    ERROR: that certificate does not exist; the agent will "
                  "refuse to connect")
    else:
        print("  transport        PLAINTEXT")

    print("\nBundled components (absent until the packaging phase)")
    for label, path in (
        ("python runtime", config.BUNDLED_PYTHON_PATH),
        ("dialog exe", config.DIALOG_EXE_PATH),
        ("overlay exe", config.OVERLAY_EXE_PATH),
    ):
        state = "present" if path.exists() else "MISSING - falls back to this interpreter"
        print(f"  {label:16} {state}")

    # Per client, not per machine — several agents on one box would otherwise
    # share one lockout schedule and overwrite each other.
    print(f"\nLocal state       {config.STATE_DIR}")
    print(f"  root             {config.STATE_ROOT}")
    print(f"  writable         {os.access(config.STATE_ROOT.parent, os.W_OK)}")

    # Enforcement state is read through the same fail-closed helpers the agent
    # uses, so a tampered file shows up here as a live block rather than as
    # something reassuring.
    print(f"  lockout active   {lockout.is_blocked_now()}")
    print(f"  paused           {lockout.is_paused()}")

    # Answered by taking the guard's own lock and dropping it again, so this
    # reports the same thing the agent would decide rather than a second
    # opinion. It holds the lock for microseconds; an agent starting in that
    # window would be refused, which is acceptable for a manual diagnostic.
    from client import single_instance

    running = not single_instance.acquire()
    single_instance.release()
    print(f"  agent running    {running}")

    try:
        blacklist = policy.load_cached_policy().get("app_blacklist", [])
        print(f"  app blacklist    {len(blacklist)} entries")
    except Exception as exc:  # noqa: BLE001 - a diagnostic, never fatal
        print(f"  app blacklist    unreadable ({exc})")

    print()
    print(_programs_text())

    return 0


def _once(top: int) -> int:
    """Run one collection cycle and print it. No Engine, no sockets."""
    from client.config import CLIENT_ID
    from client.monitors.network_monitor import collect_network_data
    from client.monitors.process_monitor import collect_process_data, prime_cpu_percent
    from client.monitors.usb_monitor import get_idle_time, is_screen_locked, poll_usb_events

    print(f"Collecting one cycle as {CLIENT_ID}\n")

    # psutil measures CPU *between* calls, so priming and then sampling
    # immediately would report zeroes for everything. The pause is what makes
    # the numbers below real.
    prime_cpu_percent()
    time.sleep(1.0)

    processes = collect_process_data()
    print(f"Processes: {len(processes)}")
    for entry in sorted(processes, key=lambda p: p.get("cpu_percent") or 0, reverse=True)[:top]:
        print(
            f"  {entry.get('process_name', '?'):28.28} "
            f"pid {str(entry.get('pid', '?')):>7} "
            f"cpu {entry.get('cpu_percent') or 0:5.1f}% "
            f"mem {entry.get('memory_mb') or 0:8.1f}MB  "
            f"{(entry.get('window_title') or '')[:40]}"
        )

    titled = sum(1 for entry in processes if entry.get("window_title"))
    print(f"  ({titled} of them have a window title)")

    network = collect_network_data()
    print("\nNetwork (counters are cumulative since boot, differenced by the Engine)")
    for key, value in network.items():
        print(f"  {key:20} {value}")

    events = poll_usb_events()
    print(f"\nUSB events: {len(events)}")
    for event in events:
        print(f"  {event}")
    if not events:
        print("  (none - the first poll establishes a baseline, so drives already "
              "mounted are not reported as insertions. Run again after plugging "
              "one in.)")

    print(f"\nIdle time:    {get_idle_time()}s")
    print(f"Screen locked: {is_screen_locked()}")

    return 0


def run(argv: list[str] | None = None) -> int:
    """Parse flags, apply them to the environment, then start the agent."""
    args = build_parser().parse_args(argv)
    os.environ.update(_env_from(args))

    # Imported here, after the environment is set - see the module docstring.
    if args.check:
        return _check()

    if args.once:
        return _once(args.top)

    from client.main import main

    return main()


if __name__ == "__main__":
    sys.exit(run())
