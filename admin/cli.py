"""Command-line entry for the Administrator client.

    python -m admin --help

Why this is a separate module from main.py: admin.config reads every value from
os.environ into module-level Final constants at import time, so a flag has to
reach the environment *before* the component is imported. See engine.cli for
the longer version — the same reasoning applies to all three units.

`--check-qml` is the one to reach for after touching a .qml file. It loads every
QML file on the offscreen platform, reports whatever the engine complains about,
and exits — no window, no Engine connection, nothing to close.
"""

from __future__ import annotations

import argparse
import os
import sys


# Unlike the Client Agent, this package ships no companion executables — the
# console is one program. Listed anyway, and honestly, so the absence is a
# stated fact rather than something to go looking for.
PROGRAMS: tuple[tuple[str, str], ...] = (
    ("python -m admin", "the console itself - the only program in this package"),
    ("python -m scripts.generate_cert", "generate the self-signed TLS certificate (shared)"),
)


def _programs_text() -> str:
    lines = "\n".join(f"  {invocation}\n      {text}" for invocation, text in PROGRAMS)
    return (
        f"Programs in this package:\n{lines}\n\n"
        "The lockout overlay and warning dialog belong to the Client Agent and run\n"
        "on the lab machine, not here: see `python -m client --help`."
    )


def build_parser() -> argparse.ArgumentParser:
    """Flags for the Administrator client. Every one maps onto an env var."""
    parser = argparse.ArgumentParser(
        prog="python -m admin",
        description="Lab Monitor Administrator - Qt 6 + QML over a Python backend.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "The address is also remembered in QSettings once a connection "
            "succeeds; --engine overrides what the window is prefilled with.\n\n"
            + _programs_text()
        ),
    )

    parser.add_argument(
        "--engine", metavar="HOST",
        help="Engine address to prefill (env ENGINE_HOST, default 127.0.0.1)",
    )
    parser.add_argument(
        "--port", type=int, metavar="N",
        help="Engine port to prefill (env ENGINE_PORT, default 5000)",
    )
    parser.add_argument(
        "--id", metavar="NAME", dest="admin_id",
        help="Identify as NAME rather than admin-<hostname> (env ADMIN_ID). "
             "This is what lands in command_log.admin_id for every command sent",
    )
    parser.add_argument(
        "--no-tls", action="store_true",
        help="Connect in plaintext even if the Engine certificate is present "
             "(env ADMIN_TLS=0)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Log at DEBUG (env ADMIN_LOG_LEVEL)",
    )

    diagnostics = parser.add_argument_group("diagnostics (no Engine, no window)")
    diagnostics.add_argument(
        "--check", action="store_true",
        help="Report resolved configuration and exit",
    )
    diagnostics.add_argument(
        "--check-qml", action="store_true",
        help="Load every QML file offscreen, report errors and warnings, and "
             "exit. Renders nothing",
    )

    return parser


def _env_from(args: argparse.Namespace) -> dict[str, str]:
    """Translate parsed flags into the environment variables config reads."""
    env: dict[str, str] = {}

    if args.engine is not None:
        env["ENGINE_HOST"] = args.engine
    if args.port is not None:
        env["ENGINE_PORT"] = str(args.port)
    if args.admin_id is not None:
        env["ADMIN_ID"] = args.admin_id
    if args.no_tls:
        env["ADMIN_TLS"] = "0"
    if args.verbose:
        env["ADMIN_LOG_LEVEL"] = "DEBUG"

    return env


def _check() -> int:
    """Report what the Administrator client resolved."""
    from admin import config

    print("Administrator configuration")
    print(f"  admin id         {config.ADMIN_ID}")
    print(f"  engine           {config.DEFAULT_HOST}:{config.DEFAULT_PORT}")
    print(f"  log level        {config.LOG_LEVEL}")
    print(f"  qml              {config.QML_DIR}")
    print(f"  live sample cap  {config.MAX_LIVE_SAMPLES} per client")

    if config.TLS_ENABLED:
        print(f"  transport        TLS, pinned to {config.TLS_CERT_PATH}")
        if not config.TLS_CERT_PATH.exists():
            print("    ERROR: that certificate does not exist; this client will "
                  "refuse to connect")
    else:
        print("  transport        PLAINTEXT")

    runtime = config.BUNDLED_PYTHON_PATH
    state = "bundled runtime" if runtime.exists() else (
        "MISSING - script validation falls back to this interpreter"
    )
    print(f"\n  script validator {state}")
    print(f"                   {runtime}")

    print()
    print(_programs_text())

    return 0


def _check_qml() -> int:
    """Load the whole QML tree offscreen and report anything Qt objects to.

    The offscreen platform is set before Qt is imported, since the platform
    plugin is chosen at QGuiApplication construction and cannot be changed
    afterwards.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine

    from admin.backend import Backend
    from admin.config import QML_DIR
    from admin.style import apply_style

    app = QGuiApplication(sys.argv[:1])

    # The same style the console runs under. Without this the check would load
    # a different tree of controls than the one that ships, and main.qml's
    # Material attached properties would warn here while working in the window.
    apply_style()
    backend = Backend()

    qml_engine = QQmlApplicationEngine()
    context = qml_engine.rootContext()

    # The same context properties admin/main.py sets. A missing one shows up as
    # a QML warning rather than a crash, which is exactly what this is for.
    context.setContextProperty("backend", backend)
    context.setContextProperty("clientModel", backend.clients)
    context.setContextProperty("applicationModel", backend.applications)
    context.setContextProperty("usbModel", backend.usbEvents)
    context.setContextProperty("networkModel", backend.networkSamples)
    context.setContextProperty("reportModel", backend.report)
    context.setContextProperty("defaultHost", "127.0.0.1")
    context.setContextProperty("defaultPort", 5000)

    complaints: list[str] = []
    qml_engine.warnings.connect(
        lambda errors: complaints.extend(error.toString() for error in errors)
    )

    qml_engine.load(QUrl.fromLocalFile(str(QML_DIR / "main.qml")))

    loaded = bool(qml_engine.rootObjects())
    files = sorted(path.name for path in QML_DIR.glob("*.qml"))

    if not loaded:
        print(f"FAILED to load QML from {QML_DIR}")
        for line in complaints:
            print(f"  {line}")
        return 1

    if complaints:
        print(f"Loaded {len(files)} QML files with {len(complaints)} warning(s):")
        for line in complaints:
            print(f"  {line}")
        _exit_without_teardown(1)

    print(f"OK - {len(files)} QML files loaded with no errors or warnings")
    print(f"     {', '.join(files)}")
    _exit_without_teardown(0)

    return 0  # unreachable, kept for the type checker


def _exit_without_teardown(code: int) -> None:
    """Exit before Python collects the Backend out from under live QML bindings.

    Ordinary interpreter shutdown frees the Backend while the QML engine still
    holds bindings to it, which produces null-model errors that look like panel
    faults but are an artefact of shutting down. Leaving that noise in would
    make this check untrustworthy for the thing it exists to detect.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def run(argv: list[str] | None = None) -> int:
    """Parse flags, apply them to the environment, then start the GUI."""
    args = build_parser().parse_args(argv)
    os.environ.update(_env_from(args))

    # Imported here, after the environment is set - see the module docstring.
    if args.check:
        return _check()

    if args.check_qml:
        return _check_qml()

    from admin.main import main

    return main()


if __name__ == "__main__":
    sys.exit(run())
