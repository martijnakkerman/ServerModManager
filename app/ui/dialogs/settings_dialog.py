"""Settings dialog: CurseForge key, version-match behavior, backup cap."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from app.config import Config


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(440)
        self._cfg = cfg

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.cf_key = QLineEdit(cfg.curseforge_api_key)
        self.cf_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.cf_key.setPlaceholderText("Optional — enables CurseForge fallback")
        form.addRow("CurseForge API key", self.cf_key)

        self.same_minor = QCheckBox("Accept files from the same minor line (e.g. 1.21 for 1.21.1)")
        self.same_minor.setChecked(cfg.accept_same_minor)
        form.addRow("Version matching", self.same_minor)

        self.keep = QSpinBox()
        self.keep.setRange(0, 100)
        self.keep.setValue(cfg.keep_backups)
        form.addRow("Backups to keep", self.keep)

        layout.addLayout(form)
        hint = QLabel("Get a free key at console.curseforge.com. Without one, the app "
                      "works fully on Modrinth alone.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#9aa0ac;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def updated_config(self) -> Config:
        self._cfg.curseforge_api_key = self.cf_key.text().strip()
        self._cfg.accept_same_minor = self.same_minor.isChecked()
        self._cfg.keep_backups = self.keep.value()
        return self._cfg
