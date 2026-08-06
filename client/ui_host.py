"""Shared PySide6/QML plumbing for the client-side helper windows.

Both helper windows are QML for the same two reasons: the project already
commits to Qt 6 + QML for its UI, and frameless translucent windows with eased
motion are what QML does well.

Note the separation this preserves — the helper UI and the script-execution
runtime are independent. Scripts run under a plain interpreter; these windows
ship as a self-contained frozen executable carrying their own Qt. Choosing one
does not constrain the other.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Property, QUrl, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

UI_DIR = Path(__file__).resolve().parent / "ui"

# Set by the self-test so QML can be loaded and validated without anything
# appearing on screen.
HEADLESS_ENV = "LABMONITOR_UI_HEADLESS"


class BaseBridge(QObject):
    """Common state QML binds to.

    Every exposed property carries its own notify signal. A single shared
    `changed` signal does work, but Qt then reports each binding as depending
    on non-bindable properties, which buries real QML errors in warnings.
    """

    messageChanged = Signal()
    showWindowsChanged = Signal()

    def __init__(self, message: str, show_windows: bool = True) -> None:
        super().__init__()
        self._message = message
        self._show = show_windows

    def _get_message(self) -> str:
        return self._message

    message = Property(str, _get_message, notify=messageChanged)

    def _get_show(self) -> bool:
        return self._show

    showWindows = Property(bool, _get_show, notify=showWindowsChanged)


def build_engine(app: QGuiApplication, bridge: QObject, qml_file: str) -> QQmlApplicationEngine:
    """Load a QML window with `bridge` exposed to it.

    Theme.qml and ActionButton.qml need no registration: QML resolves any
    .qml file as a type of the same name for its siblings in the same
    directory. An earlier attempt registered Theme as a module singleton via a
    qmldir, which competed with the context properties installed here and left
    `bridge` null inside QML.

    Raises:
        RuntimeError: If the QML failed to load, rather than leaving a process
            running with no window — a lockout that silently fails to appear is
            worse than one that fails loudly.
    """
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("bridge", bridge)

    engine.load(QUrl.fromLocalFile(str(UI_DIR / qml_file)))

    if not engine.rootObjects():
        raise RuntimeError(f"QML failed to load: {qml_file}")

    return engine


def create_app(name: str) -> QGuiApplication:
    app = QGuiApplication(sys.argv)
    app.setApplicationName(name)
    app.setOrganizationName("SystemMonitoring")
    return app


def primary_screen_geometry(app: QGuiApplication) -> tuple[int, int, int, int]:
    """Geometry of the primary display as (x, y, width, height).

    Single-monitor by design: covering every screen means enumerating displays
    and managing a window each, which the README explicitly trades away.
    """
    screen = app.primaryScreen()
    if screen is None:
        return 0, 0, 1920, 1080

    geometry = screen.geometry()
    return geometry.x(), geometry.y(), geometry.width(), geometry.height()


def force_topmost(window) -> None:
    """Re-assert topmost at both the Qt and Win32 level.

    Qt's raise() alone loses to a window that also sets topmost, so the Win32
    call is what actually makes this stick.
    """
    try:
        window.raise_()
        window.requestActivate()
    except Exception:
        return

    if not IS_WINDOWS:
        return

    try:
        hwnd = int(window.winId())
        HWND_TOPMOST, SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = -1, 0x0002, 0x0001, 0x0010
        ctypes.windll.user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    except Exception:
        logger.debug("SetWindowPos failed", exc_info=True)
