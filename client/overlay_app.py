#!/usr/bin/env python3
"""Lockout overlay — bundled as its own executable, spawned on demand.

    python -m client.overlay_app --until 2026-08-06T12:00:00Z

A translucent scrim over the primary display with a centred panel, rather than
an opaque takeover — the README's stated intent is "the impression of a locked
screen with a single dialog". Covering every monitor would mean enumerating
displays and managing a window per screen; single-monitor is the deliberate
trade.

Soft-defeat resistance only, which is the right level here:

- The window re-asserts topmost every 500ms, so anything a user Alt-Tabs
  forward is pushed back almost immediately.
- The scrim swallows every mouse event, so nothing underneath is clickable.
- Task Manager is disabled by policy while this is up, and restored when it
  exits — including on a crash.
- A determined user with physical access (safe mode, a live USB, pulling the
  disk) still wins. That is true of all client-side enforcement and is out of
  scope to solve here.

The overlay also closes itself at its end time. That is a convenience, not the
guarantee: the agent and a Scheduled Task both watch from outside, precisely
because this process might hang.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from PySide6.QtCore import Property, QTimer, Signal

from client.ui_host import (
    HEADLESS_ENV,
    BaseBridge,
    build_engine,
    create_app,
    force_topmost,
    primary_screen_geometry,
)
from common.constants import OVERLAY_MODE_PAUSE, OVERLAY_MODE_SCHEDULED

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

TOPMOST_INTERVAL_MS = 500
TICK_INTERVAL_MS = 1000

_TASKMGR_POLICY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
_TASKMGR_POLICY_VALUE = "DisableTaskMgr"

DEFAULT_MESSAGE = (
    "This computer is unavailable during the scheduled restriction period. "
    "Your work has not been affected and will still be here afterwards."
)


def parse_until(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Task Manager policy
# ---------------------------------------------------------------------------


def set_task_manager_disabled(disabled: bool) -> None:
    """Toggle the standard Task Manager policy.

    Per-user (HKCU) so it needs no elevation. Failures are logged and ignored:
    losing this hardening should never stop the lockout itself from showing.
    """
    if not IS_WINDOWS:
        return

    try:
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, _TASKMGR_POLICY_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if disabled:
                winreg.SetValueEx(key, _TASKMGR_POLICY_VALUE, 0, winreg.REG_DWORD, 1)
            else:
                try:
                    winreg.DeleteValue(key, _TASKMGR_POLICY_VALUE)
                except FileNotFoundError:
                    pass
    except PermissionError:
        # Anticipated: the policy key is often locked down by group policy on a
        # managed machine. One line, no traceback — the lockout still shows,
        # just without this bit of hardening.
        logger.warning(
            "Task Manager policy not applied (access denied); overlay continues"
        )
    except OSError:
        logger.warning("Could not change the Task Manager policy", exc_info=True)


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class OverlayBridge(BaseBridge):
    """State for Overlay.qml.

    `mode` decides what the student is told. A scheduled block shows a
    countdown, because there is a known end to count to. A pause shows none —
    it has no stated end, and displaying the internal one-hour fail-safe would
    turn an admin safety net into a promise to the user.
    """

    expired = Signal()
    geometryChanged = Signal()
    countdownChanged = Signal()
    progressChanged = Signal()
    modeChanged = Signal()

    def __init__(self, until: datetime, message: str,
                 geometry: tuple[int, int, int, int], show_windows: bool,
                 mode: str = OVERLAY_MODE_SCHEDULED) -> None:
        super().__init__(message, show_windows)
        self._until = until
        self._mode = mode
        self._started = datetime.now(timezone.utc)
        self._x, self._y, self._width, self._height = geometry
        self._countdown = "--:--:--"
        self._progress = 1.0
        self.refresh()

    def _get_mode(self) -> str:
        return self._mode

    mode = Property(str, _get_mode, notify=modeChanged)

    def _is_paused(self) -> bool:
        return self._mode == OVERLAY_MODE_PAUSE

    paused = Property(bool, _is_paused, notify=modeChanged)

    def _get_x(self) -> int:
        return self._x

    def _get_y(self) -> int:
        return self._y

    def _get_width(self) -> int:
        return self._width

    def _get_height(self) -> int:
        return self._height

    screenX = Property(int, _get_x, notify=geometryChanged)
    screenY = Property(int, _get_y, notify=geometryChanged)
    screenWidth = Property(int, _get_width, notify=geometryChanged)
    screenHeight = Property(int, _get_height, notify=geometryChanged)

    def _get_countdown(self) -> str:
        return self._countdown

    countdown = Property(str, _get_countdown, notify=countdownChanged)

    def _get_progress(self) -> float:
        return self._progress

    progress = Property(float, _get_progress, notify=progressChanged)

    def refresh(self) -> None:
        remaining = (self._until - datetime.now(timezone.utc)).total_seconds()

        if remaining <= 0:
            self._countdown = "00:00:00"
            self._progress = 0.0
            self.countdownChanged.emit()
            self.progressChanged.emit()
            self.expired.emit()
            return

        hours, rest = divmod(int(remaining), 3600)
        minutes, seconds = divmod(rest, 60)
        self._countdown = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        total = (self._until - self._started).total_seconds()
        self._progress = max(0.0, min(1.0, remaining / total)) if total > 0 else 0.0

        self.countdownChanged.emit()
        self.progressChanged.emit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


PAUSE_MESSAGE = (
    "Your screen has been paused by a lab supervisor. Your work is untouched "
    "and will still be here when the pause is lifted."
)


def _show(app, bridge: OverlayBridge, headless: bool) -> int:
    """Own the QML engine for exactly as long as the overlay is up.

    The engine lives and dies inside this frame while `app` and `bridge` are
    held by the caller — see dialog_app._show for why that ordering matters.
    """
    try:
        engine = build_engine(app, bridge, "Overlay.qml")
    except RuntimeError:
        logger.exception("Overlay UI failed to start")
        return 1

    bridge.expired.connect(app.quit)

    ticker = QTimer()
    ticker.setInterval(TICK_INTERVAL_MS)
    ticker.timeout.connect(bridge.refresh)
    ticker.start()

    topmost: QTimer | None = None

    if headless:
        QTimer.singleShot(0, app.quit)
    else:
        window = engine.rootObjects()[0]

        # Re-assert topmost on a timer: anything the user brings forward is
        # pushed back within half a second.
        topmost = QTimer()
        topmost.setInterval(TOPMOST_INTERVAL_MS)
        topmost.timeout.connect(lambda: force_topmost(window))
        topmost.start()

    app.exec()

    ticker.stop()
    if topmost is not None:
        topmost.stop()

    return 0


def run_overlay(until: datetime, message: str, mode: str) -> int:
    headless = os.environ.get(HEADLESS_ENV) == "1"

    app = create_app("Lab Monitor Lockout")
    bridge = OverlayBridge(
        until, message, primary_screen_geometry(app), not headless, mode
    )

    return _show(app, bridge, headless)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lab lockout overlay")
    parser.add_argument("--until", required=True, help="ISO-8601 end time (UTC)")
    parser.add_argument(
        "--mode",
        default=OVERLAY_MODE_SCHEDULED,
        choices=[OVERLAY_MODE_SCHEDULED, OVERLAY_MODE_PAUSE],
        help="scheduled shows a countdown; pause deliberately shows none",
    )
    parser.add_argument("--message", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level="INFO", format="%(asctime)s - %(levelname)s - %(message)s")

    try:
        until = parse_until(args.until)
    except ValueError:
        logger.error("Unparseable --until value: %r", args.until)
        return 2

    if until <= datetime.now(timezone.utc):
        logger.info("End time has already passed; nothing to show")
        return 0

    message = args.message or (
        PAUSE_MESSAGE if args.mode == OVERLAY_MODE_PAUSE else DEFAULT_MESSAGE
    )

    set_task_manager_disabled(True)
    try:
        return run_overlay(until, message, args.mode)
    finally:
        # Always restore, including on a crash — leaving Task Manager disabled
        # after the block expired would be a lasting side effect.
        set_task_manager_disabled(False)


if __name__ == "__main__":
    sys.exit(main())
