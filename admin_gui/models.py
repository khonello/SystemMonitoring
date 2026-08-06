"""Qt data models exposed to QML.

PHASE 1 SCAFFOLD. The model is real enough for QML to bind against, but is
only ever populated by hand until Phase 3 wires it to the Engine.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Slot

logger = logging.getLogger(__name__)


class ClientListModel(QAbstractListModel):
    """The connected Client Agents, for the client list view."""

    ClientIdRole = Qt.ItemDataRole.UserRole + 1
    HostnameRole = Qt.ItemDataRole.UserRole + 2
    AddressRole = Qt.ItemDataRole.UserRole + 3
    StatusRole = Qt.ItemDataRole.UserRole + 4
    LastSeenRole = Qt.ItemDataRole.UserRole + 5

    _ROLE_KEYS = {
        ClientIdRole: "client_id",
        HostnameRole: "hostname",
        AddressRole: "address",
        StatusRole: "status",
        LastSeenRole: "last_seen",
    }

    def __init__(self, parent: QAbstractListModel | None = None) -> None:
        super().__init__(parent)
        self._clients: list[dict[str, Any]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._clients)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._clients):
            return None

        key = self._ROLE_KEYS.get(role)
        if key is None:
            return None

        return self._clients[index.row()].get(key)

    def roleNames(self) -> dict[int, bytes]:
        return {role: key.encode() for role, key in self._ROLE_KEYS.items()}

    @Slot(list)
    def setClients(self, clients: list[dict[str, Any]]) -> None:
        """Replace the roster wholesale.

        Fine at this scale: the design ceiling is 50 clients, so a full reset
        costs less than diffing would.
        """
        self.beginResetModel()
        self._clients = list(clients)
        self.endResetModel()

    @Slot()
    def clear(self) -> None:
        self.setClients([])
