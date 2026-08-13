"""Qt data models exposed to QML."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QModelIndex,
    Qt,
    Signal,
    Slot,
)

logger = logging.getLogger(__name__)


class _DictListModel(QAbstractListModel):
    """List model over a list of dicts, with roles named after dict keys.

    Every model in this GUI shows rows that arrive as JSON payload dicts, so
    the mapping from role to key is mechanical — only the key set differs.
    """

    KEYS: tuple[str, ...] = ()

    def __init__(self, parent: QAbstractListModel | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        base = Qt.ItemDataRole.UserRole + 1
        self._roles = {base + index: key for index, key in enumerate(self.KEYS)}

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        key = self._roles.get(role)
        return None if key is None else self._rows[index.row()].get(key)

    def roleNames(self) -> dict[int, bytes]:
        return {role: key.encode() for role, key in self._roles.items()}

    # QML bindings cannot watch rowCount(): it is a plain method with no change
    # signal, so `text: model.rowCount()` is evaluated once and then never
    # again. That is why the old tab read "Applications (0)" while rows were
    # arriving. `count` is a real property with a notify signal, so anything
    # bound to it updates — and any binding that also wants a total should
    # mention `count` so it re-evaluates on the same signal.
    countChanged = Signal()

    def _count(self) -> int:
        return len(self._rows)

    count = Property(int, _count, notify=countChanged)

    @Slot(str, result=float)
    def total(self, key: str) -> float:
        """Sum one numeric column across every row.

        Summed here rather than in QML because QML cannot read a model's roles
        by index without a delegate, and because a loop in a binding would run
        on every repaint rather than on every change.
        """
        running = 0.0
        for row in self._rows:
            value = row.get(key)
            if isinstance(value, (int, float)):
                running += float(value)
        return running

    @Slot(list)
    def setRows(self, rows: list[dict[str, Any]]) -> None:
        """Replace every row.

        A full reset rather than a diff: the design ceiling is 50 clients and a
        few hundred rows, where resetting costs less than computing a diff.
        """
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()
        self.countChanged.emit()

    @Slot()
    def clear(self) -> None:
        self.setRows([])

    @property
    def rows(self) -> list[dict[str, Any]]:
        return list(self._rows)


class ClientListModel(_DictListModel):
    """Connected and previously-seen Client Agents."""

    KEYS = ("client_id", "hostname", "address", "ip_address", "os_type",
            "status", "last_seen", "connected", "paused", "pause_until")


class ApplicationModel(_DictListModel):
    """Live application data for the selected client."""

    KEYS = ("process_name", "pid", "window_title", "cpu_percent", "memory_mb", "start_time")


class UsbEventModel(_DictListModel):
    """USB events for the selected client."""

    KEYS = ("event", "device_name", "device_id", "timestamp", "event_type")


class NetworkSampleModel(_DictListModel):
    """Recent network samples for the selected client."""

    KEYS = ("timestamp", "bytes_sent", "bytes_received", "active_connections")


class ReportModel(_DictListModel):
    """Rows of whichever report was last requested.

    Deliberately schema-less: the columns differ per report kind, so QML reads
    `display` and `detail`, which the backend fills in when it flattens a
    report payload.
    """

    KEYS = ("label", "detail", "value")
