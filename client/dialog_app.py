#!/usr/bin/env python3
"""Warning dialog — bundled as its own executable, spawned on demand.

    python -m client.dialog_app --message "Shutting down in 60 seconds" --timeout 60

Used for graceful shutdown warnings and lockout grace periods. Deliberately a
real executable rather than MessageBoxW through ctypes: the agent spawns it the
same way it spawns scripts, so it never blocks the event loop, and the user's
answer comes back through the same exit-code channel everything else uses.

Exit codes are the interface:
    0  OK / acknowledged
    1  Cancelled
    2  Timed out with no answer
    3  Bad arguments or the UI failed to start
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from PySide6.QtCore import Property, QTimer, Signal, Slot

from client.ui_host import HEADLESS_ENV, BaseBridge, build_engine, create_app

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_CANCELLED = 1
EXIT_TIMEOUT = 2
EXIT_BAD_ARGS = 3


class DialogBridge(BaseBridge):
    """State and answers for Dialog.qml."""

    finished = Signal(int)
    titleChanged = Signal()
    allowCancelChanged = Signal()
    totalSecondsChanged = Signal()
    remainingSecondsChanged = Signal()

    def __init__(self, title: str, message: str, timeout: int,
                 allow_cancel: bool, show_windows: bool) -> None:
        super().__init__(message, show_windows)
        self._title = title
        self._timeout = max(0, timeout)
        self._remaining = self._timeout
        self._allow_cancel = allow_cancel
        self.result = EXIT_TIMEOUT

    def _get_title(self) -> str:
        return self._title

    title = Property(str, _get_title, notify=titleChanged)

    def _get_allow_cancel(self) -> bool:
        return self._allow_cancel

    allowCancel = Property(bool, _get_allow_cancel, notify=allowCancelChanged)

    def _get_total(self) -> int:
        return self._timeout

    totalSeconds = Property(int, _get_total, notify=totalSecondsChanged)

    def _get_remaining(self) -> int:
        return self._remaining

    remainingSeconds = Property(int, _get_remaining, notify=remainingSecondsChanged)

    @Slot()
    def accept(self) -> None:
        self._finish(EXIT_OK)

    @Slot()
    def cancel(self) -> None:
        # Ignored when cancelling was not offered: a warning that must be
        # acknowledged should not be dismissible.
        if self._allow_cancel:
            self._finish(EXIT_CANCELLED)

    def tick(self) -> None:
        self._remaining -= 1
        self.remainingSecondsChanged.emit()
        if self._remaining <= 0:
            self._finish(EXIT_TIMEOUT)

    def _finish(self, code: int) -> None:
        self.result = code
        self.finished.emit(code)


def _show(app, bridge: DialogBridge, timeout: int, headless: bool) -> int:
    """Own the QML engine for exactly as long as the window is up.

    The engine lives and dies inside this frame, while `app` and `bridge` are
    held by the caller. That ordering is the whole point: if the bridge is
    collected first, the still-live QML bindings re-evaluate against a dead
    object and the process spews "Cannot read property of null" on every exit.
    """
    try:
        engine = build_engine(app, bridge, "Dialog.qml")
    except RuntimeError:
        logger.exception("Dialog UI failed to start")
        return EXIT_BAD_ARGS

    bridge.finished.connect(lambda _code: app.quit())

    countdown = QTimer()
    countdown.setInterval(1000)
    countdown.timeout.connect(bridge.tick)
    if timeout > 0:
        countdown.start()

    if headless:
        # Loaded and validated; nothing to show.
        QTimer.singleShot(0, app.quit)

    app.exec()
    countdown.stop()

    return EXIT_OK if headless else bridge.result


def run_dialog(title: str, message: str, timeout: int, allow_cancel: bool) -> int:
    headless = os.environ.get(HEADLESS_ENV) == "1"

    app = create_app("Lab Monitor Notice")
    bridge = DialogBridge(title, message, timeout, allow_cancel, not headless)

    return _show(app, bridge, timeout, headless)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Client warning dialog")
    parser.add_argument("--message", required=True)
    parser.add_argument("--title", default="Lab Monitor")
    parser.add_argument(
        "--timeout", type=int, default=60,
        help="Seconds before auto-closing with EXIT_TIMEOUT; 0 waits forever",
    )
    parser.add_argument("--allow-cancel", action="store_true")

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse raises SystemExit(0) for --help and SystemExit(2) for a bad
        # argument. Mapping both to EXIT_BAD_ARGS would make --help report
        # failure, and this program's exit code is its answer channel.
        return EXIT_BAD_ARGS if exc.code else EXIT_OK

    logging.basicConfig(level="INFO", format="%(asctime)s - %(levelname)s - %(message)s")

    return run_dialog(args.title, args.message, args.timeout, args.allow_cancel)


if __name__ == "__main__":
    sys.exit(main())
