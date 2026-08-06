#!/usr/bin/env python3
"""Administrator GUI entry point.

    python -m admin_gui.main

PHASE 1 SCAFFOLD — the window opens and the panels lay out, but nothing is
connected to an Engine.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from admin_gui.backend import Backend
from admin_gui.models import ClientListModel

logger = logging.getLogger(__name__)

QML_DIR = Path(__file__).resolve().parent / "qml"

LOG_LEVEL = os.environ.get("ADMIN_LOG_LEVEL", "INFO")


def main() -> int:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    app = QGuiApplication(sys.argv)
    app.setApplicationName("Lab Monitor - Administrator")
    app.setOrganizationName("SystemMonitoring")

    qml_engine = QQmlApplicationEngine()

    # Held on the Python side: QML does not own these, and letting them fall
    # out of scope would take the bindings down with them.
    backend = Backend()
    client_model = ClientListModel()

    context = qml_engine.rootContext()
    context.setContextProperty("backend", backend)
    context.setContextProperty("clientModel", client_model)

    qml_engine.load(QUrl.fromLocalFile(str(QML_DIR / "main.qml")))

    if not qml_engine.rootObjects():
        logger.error("Failed to load QML from %s", QML_DIR)
        return 1

    logger.info("Administrator GUI started")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
