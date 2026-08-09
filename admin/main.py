#!/usr/bin/env python3
"""Administrator GUI entry point.

    python -m admin.main

qasync runs the asyncio loop on top of Qt's, so the GUI and the Engine socket
share one thread. Everything below is ordinary Qt startup apart from that.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import qasync
from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from admin.backend import Backend
from admin.config import (
    APPLICATION,
    DEFAULT_HOST,
    DEFAULT_PORT,
    LOG_LEVEL,
    ORGANISATION,
    QML_DIR,
    SETTINGS_HOST,
    SETTINGS_PORT,
)

logger = logging.getLogger(__name__)


def load_settings() -> tuple[str, int]:
    """Last-used Engine address, or the defaults."""
    settings = QSettings(ORGANISATION, APPLICATION)
    host = str(settings.value(SETTINGS_HOST, DEFAULT_HOST))
    try:
        port = int(settings.value(SETTINGS_PORT, DEFAULT_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    return host, port


def save_settings(host: str, port: int) -> None:
    settings = QSettings(ORGANISATION, APPLICATION)
    settings.setValue(SETTINGS_HOST, host)
    settings.setValue(SETTINGS_PORT, port)


def main() -> int:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    app = QGuiApplication(sys.argv)
    app.setApplicationName("Lab Monitor - Administrator")
    app.setOrganizationName(ORGANISATION)

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    backend = Backend()
    host, port = load_settings()

    qml_engine = QQmlApplicationEngine()
    context = qml_engine.rootContext()

    # Held on the Python side: QML does not take ownership, and letting these
    # fall out of scope would take the bindings down with them.
    context.setContextProperty("backend", backend)
    context.setContextProperty("clientModel", backend.clients)
    context.setContextProperty("applicationModel", backend.applications)
    context.setContextProperty("usbModel", backend.usbEvents)
    context.setContextProperty("networkModel", backend.networkSamples)
    context.setContextProperty("reportModel", backend.report)
    context.setContextProperty("defaultHost", host)
    context.setContextProperty("defaultPort", port)

    qml_engine.load(QUrl.fromLocalFile(str(QML_DIR / "main.qml")))

    if not qml_engine.rootObjects():
        logger.error("Failed to load QML from %s", QML_DIR)
        return 1

    def remember_address(connected: bool) -> None:
        """Persist the address that actually worked, not the prefilled one."""
        if connected and backend.engine_host:
            save_settings(backend.engine_host, backend.engine_port)

    backend.connectionStateChanged.connect(remember_address)

    logger.info("Administrator GUI started (admin id from ADMIN_ID or hostname)")

    with loop:
        loop.run_forever()

    return 0


if __name__ == "__main__":
    sys.exit(main())
