"""Restore a previously removed (quarantined) batch of mods."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.services.quarantine import list_batches, restore_batch


class RestoreDialog(QDialog):
    def __init__(self, mods_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Restore removed mods")
        self.resize(520, 400)
        self.mods_dir = Path(mods_dir)
        self.restored_count = 0
        self.batches = list_batches(self.mods_dir)

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Pick a removed batch to put back into the mods folder:"))

        self.list = QListWidget()
        for b in self.batches:
            names = ", ".join(j.name for j in b.jars) or "(empty)"
            item = QListWidgetItem(f"{b.timestamp}  —  {len(b.jars)} mod(s)\n{names}")
            item.setData(Qt.ItemDataRole.UserRole, b)
            self.list.addItem(item)
        if not self.batches:
            self.list.addItem("No removed batches.")
            self.list.setEnabled(False)
        root.addWidget(self.list, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        restore = QPushButton("Restore selected")
        restore.setObjectName("Primary")
        restore.clicked.connect(self._restore)
        actions.addWidget(close)
        actions.addWidget(restore)
        root.addLayout(actions)

    def _restore(self):
        items = self.list.selectedItems()
        if not items:
            return
        batch = items[0].data(Qt.ItemDataRole.UserRole)
        if not batch:
            return
        restored = restore_batch(batch, self.mods_dir)
        self.restored_count = len(restored)
        QMessageBox.information(self, "Restore", f"Restored {len(restored)} mod(s).")
        self.accept()
