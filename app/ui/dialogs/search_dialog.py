"""Browse Modrinth/CurseForge and install a new mod into the folder."""

from __future__ import annotations

import logging
import tempfile
import zipfile
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.providers.base import Provider, SearchHit

log = logging.getLogger(__name__)


class _SearchThread(QThread):
    done = pyqtSignal(list)

    def __init__(self, providers, query, loader, mc_version):
        super().__init__()
        self.providers, self.query = providers, query
        self.loader, self.mc_version = loader, mc_version

    def run(self):
        hits: list[SearchHit] = []
        for p in self.providers:
            if not p.enabled:
                continue
            try:
                hits.extend(p.search(self.query, self.loader, self.mc_version, limit=25))
            except Exception as e:  # noqa: BLE001
                log.warning("search via %s failed: %s", p.name, e)
        self.done.emit(hits)


class SearchDialog(QDialog):
    def __init__(self, providers: list[Provider], loader, mc_version, mods_dir: Path,
                 accept_same_minor: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Browse & install mods")
        self.resize(640, 520)
        self.providers = providers
        self.by_name = {p.name: p for p in providers}
        self.loader, self.mc_version = loader, mc_version
        self.mods_dir = Path(mods_dir)
        self.accept_same_minor = accept_same_minor
        self._thread: _SearchThread | None = None

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search mods…")
        self.query.returnPressed.connect(self._search)
        self.source_combo = QComboBox()
        self.source_combo.addItems(["all"] + [p.name for p in providers if p.enabled])
        btn = QPushButton("Search")
        btn.setObjectName("Primary")
        btn.clicked.connect(self._search)
        bar.addWidget(self.query, 1)
        bar.addWidget(self.source_combo)
        bar.addWidget(btn)
        root.addLayout(bar)

        self.results = QListWidget()
        self.results.itemSelectionChanged.connect(self._update_install_btn)
        root.addWidget(self.results, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#9aa0ac;")
        root.addWidget(self.status)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.install_btn = QPushButton("Install selected")
        self.install_btn.setObjectName("Primary")
        self.install_btn.setEnabled(False)
        self.install_btn.clicked.connect(self._install)
        actions.addWidget(self.install_btn)
        root.addLayout(actions)

    def _search(self):
        q = self.query.text().strip()
        if not q:
            return
        self.status.setText("Searching…")
        self.results.clear()
        chosen = self.source_combo.currentText()
        providers = self.providers if chosen == "all" else [self.by_name[chosen]]
        self._thread = _SearchThread(providers, q, self.loader, self.mc_version)
        self._thread.done.connect(self._show_results)
        self._thread.start()

    def _show_results(self, hits: list[SearchHit]):
        self.results.clear()
        for h in hits:
            label = f"{h.title}   ·   {h.source}   ·   {h.downloads:,} downloads\n{h.description}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, h)
            self.results.addItem(item)
        self.status.setText(f"{len(hits)} result(s)") if hits else self.status.setText("No results")

    def _update_install_btn(self):
        self.install_btn.setEnabled(bool(self.results.selectedItems()))

    def _install(self):
        items = self.results.selectedItems()
        if not items:
            return
        hit: SearchHit = items[0].data(Qt.ItemDataRole.UserRole)
        provider = self.by_name.get(hit.source)
        if not provider:
            return
        self.status.setText(f"Resolving {hit.title}…")
        latest = provider.latest_version(
            hit.project_id, self.loader, self.mc_version, self.accept_same_minor
        )
        if not latest or not latest.download_url:
            QMessageBox.warning(self, "Install", f"No compatible file for {hit.title}.")
            self.status.setText("")
            return
        if self._download(provider, latest.download_url):
            QMessageBox.information(self, "Install", f"Installed {hit.title}.")
            self.status.setText(f"Installed {hit.title}")
        else:
            QMessageBox.warning(self, "Install", f"Download failed for {hit.title}.")
            self.status.setText("")

    def _download(self, provider: Provider, url: str) -> bool:
        with tempfile.NamedTemporaryFile(suffix=".jar.part", dir=self.mods_dir, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            if not provider.download_file(url, tmp_path):
                return False
            with zipfile.ZipFile(tmp_path, "r") as z:
                z.testzip()
            name = url.rsplit("/", 1)[-1]
            if not name.lower().endswith(".jar"):
                name = tmp_path.stem + ".jar"
            tmp_path.replace(self.mods_dir / name)
            return True
        except (zipfile.BadZipFile, OSError) as e:
            log.warning("install download failed: %s", e)
            tmp_path.unlink(missing_ok=True)
            return False
