"""Review detected client-only mods and quarantine the ones you choose."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.services.quarantine import quarantine
from app.services.side_detector import SideFinding


class ClientOnlyDialog(QDialog):
    def __init__(self, findings: list[SideFinding], mods_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Client-only mods")
        self.resize(680, 460)
        self.findings = findings
        self.mods_dir = Path(mods_dir)
        self.removed_count = 0

        root = QVBoxLayout(self)
        intro = QLabel(
            "These mods look client-only and probably don't belong on a server. "
            "Nothing is deleted — selected mods move to <code>.removed/</code> and "
            "can be restored later."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.table = QTableWidget(len(findings), 4)
        self.table.setHorizontalHeaderLabels(["Remove", "Mod", "Confidence", "Why"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        for r, f in enumerate(findings):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked if f.safe_to_remove else Qt.CheckState.Unchecked)
            self.table.setItem(r, 0, chk)
            self.table.setItem(r, 1, QTableWidgetItem(f.match.display_name))
            badge = f.confidence + (" ⚠" if f.conflict else "")
            self.table.setItem(r, 2, QTableWidgetItem(badge))
            self.table.setItem(r, 3, QTableWidgetItem("; ".join(f.reasons)))
        self.table.resizeColumnsToContents()
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Close")
        cancel.clicked.connect(self.reject)
        remove = QPushButton("Remove selected")
        remove.setObjectName("Primary")
        remove.clicked.connect(self._remove)
        actions.addWidget(cancel)
        actions.addWidget(remove)
        root.addLayout(actions)

    def _remove(self):
        to_remove = [
            self.findings[r].match.mod.jar_path
            for r in range(self.table.rowCount())
            if self.table.item(r, 0).checkState() == Qt.CheckState.Checked
        ]
        if to_remove:
            quarantine(to_remove, self.mods_dir)
            self.removed_count = len(to_remove)
        self.accept()
