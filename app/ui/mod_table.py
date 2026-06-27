"""Table model, status-pill delegate, and filter proxy for the mod list."""

from __future__ import annotations

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QRect,
    QSortFilterProxyModel,
    Qt,
)
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QStyledItemDelegate

from app.models import ModMatch, Status

COL_CHECK, COL_NAME, COL_INSTALLED, COL_LATEST, COL_STATUS, COL_SOURCE = range(6)
HEADERS = ["", "Mod", "Installed", "Latest", "Status", "Source"]

# Role carrying the ModMatch for delegates/filtering.
MATCH_ROLE = int(Qt.ItemDataRole.UserRole) + 1
STATUS_ORDER = {
    Status.UPDATE_AVAILABLE: 0,
    Status.CHECK: 1,
    Status.UNKNOWN: 2,
    Status.UP_TO_DATE: 3,
}


class ModTableModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._matches: list[ModMatch] = []
        self._checked: set[int] = set()  # indices into _matches

    # -- population --
    def set_matches(self, matches: list[ModMatch]):
        self.beginResetModel()
        self._matches = list(matches)
        self._checked.clear()
        self.endResetModel()

    def match_at(self, row: int) -> ModMatch | None:
        return self._matches[row] if 0 <= row < len(self._matches) else None

    def refresh_row(self, match: ModMatch):
        try:
            row = self._matches.index(match)
        except ValueError:
            return
        self._checked.discard(row)
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(HEADERS) - 1))

    def checked_matches(self) -> list[ModMatch]:
        return [self._matches[i] for i in sorted(self._checked) if i < len(self._matches)]

    def check_all_updates(self):
        self._checked = {i for i, m in enumerate(self._matches) if m.has_update}
        self._emit_all()

    def clear_checks(self):
        self._checked.clear()
        self._emit_all()

    def _emit_all(self):
        if self._matches:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._matches) - 1, 0))

    # -- Qt model interface --
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._matches)

    def columnCount(self, parent=QModelIndex()):
        return len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        return None

    def flags(self, index):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_CHECK and self._matches[index.row()].has_update:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        m = self._matches[index.row()]
        col = index.column()

        if role == MATCH_ROLE:
            return m

        if role == Qt.ItemDataRole.CheckStateRole and col == COL_CHECK:
            if not m.has_update:
                return None
            return (
                Qt.CheckState.Checked
                if index.row() in self._checked
                else Qt.CheckState.Unchecked
            )

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NAME:
                return m.display_name
            if col == COL_INSTALLED:
                return m.current_version
            if col == COL_LATEST:
                return m.latest_version if m.has_update else ""
            if col == COL_STATUS:
                return m.status.label
            if col == COL_SOURCE:
                return m.source or "—"

        if role == Qt.ItemDataRole.ToolTipRole and col == COL_NAME:
            return m.mod.jar_path.name

        if role == Qt.ItemDataRole.FontRole and col == COL_NAME:
            f = QFont()
            f.setBold(m.has_update)
            return f

        # For sorting the status column meaningfully.
        if role == Qt.ItemDataRole.UserRole and col == COL_STATUS:
            return STATUS_ORDER.get(m.status, 9)
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == COL_CHECK:
            row = index.row()
            if value == Qt.CheckState.Checked.value or value == Qt.CheckState.Checked:
                self._checked.add(row)
            else:
                self._checked.discard(row)
            self.dataChanged.emit(index, index)
            return True
        return False


class ModFilterProxy(QSortFilterProxyModel):
    """Filters by free text over name + status, and supports a status-only filter."""

    def __init__(self):
        super().__init__()
        self._text = ""
        self.setSortRole(Qt.ItemDataRole.DisplayRole)

    def set_text(self, text: str):
        self._text = text.lower().strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self._text:
            return True
        model = self.sourceModel()
        m = model.match_at(source_row)
        if not m:
            return True
        haystack = f"{m.display_name} {m.status.label} {m.source} {m.mod.jar_path.name}".lower()
        return self._text in haystack

    def lessThan(self, left, right):
        # Status column sorts by severity, not alphabetically.
        if left.column() == COL_STATUS:
            lo = self.sourceModel().data(left, Qt.ItemDataRole.UserRole) or 9
            ro = self.sourceModel().data(right, Qt.ItemDataRole.UserRole) or 9
            return lo < ro
        return super().lessThan(left, right)


class StatusPillDelegate(QStyledItemDelegate):
    """Paints the status column as a colored rounded pill."""

    def paint(self, painter: QPainter, option, index):
        m = index.data(MATCH_ROLE)
        if m is None:
            return super().paint(painter, option, index)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(m.status.color)

        text = m.status.label
        metrics = option.fontMetrics
        tw = metrics.horizontalAdvance(text)
        pad_x, pill_h = 11, 22
        rect = option.rect
        pill = QRect(
            rect.left() + 8,
            rect.center().y() - pill_h // 2,
            min(tw + pad_x * 2, rect.width() - 16),
            pill_h,
        )
        bg = QColor(color)
        bg.setAlpha(48)
        painter.setBrush(bg)
        painter.setPen(color)
        painter.drawRoundedRect(pill, 11, 11)
        painter.setPen(color)
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()
