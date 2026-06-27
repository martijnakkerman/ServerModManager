"""Main application window: toolbar, mod table, detail panel."""

from __future__ import annotations

import logging
from html import escape
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.config import COMMON_MC_VERSIONS, LOADERS, Config, load_config, save_config
from app.models import LatestVersion, ModMatch, Status
from app.providers.curseforge import CurseForgeProvider
from app.providers.modrinth import ModrinthProvider
from app.services.dependency import check_dependencies
from app.services.matcher import apply_pins
from app.services.side_detector import find_client_only
from app.ui.dialogs.client_only_dialog import ClientOnlyDialog
from app.ui.dialogs.restore_dialog import RestoreDialog
from app.ui.dialogs.search_dialog import SearchDialog
from app.ui.dialogs.settings_dialog import SettingsDialog
from app.ui.mod_table import (
    COL_CHECK,
    COL_STATUS,
    MATCH_ROLE,
    ModFilterProxy,
    ModTableModel,
    StatusPillDelegate,
)
from app.ui.workers import (
    InstallVersionWorker,
    ScanWorker,
    UpdateWorker,
    VersionsWorker,
)

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MC Mod Manager")
        self.resize(1080, 680)
        self.cfg: Config = load_config()
        self.matches: list[ModMatch] = []
        self._scan_worker: ScanWorker | None = None
        self._update_worker: UpdateWorker | None = None
        self._versions_worker: VersionsWorker | None = None
        self._install_worker: InstallVersionWorker | None = None
        self._current: ModMatch | None = None
        self._current_versions: list[LatestVersion] = []
        self._build_providers()
        self._build_ui()
        if self.cfg.server_mods_path:
            self.path_label.setText(self.cfg.server_mods_path)

    # ------------------------------------------------------------------ #
    def _build_providers(self):
        self.modrinth = ModrinthProvider()
        self.curseforge = CurseForgeProvider(self.cfg.curseforge_api_key)
        self.providers = [self.modrinth, self.curseforge]

    # ------------------------------------------------------------------ #
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_toolbar())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 12, 14, 12)

        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("Filter by name or status…")
        self.filter_box.textChanged.connect(lambda t: self.proxy.set_text(t))
        body_layout.addWidget(self.filter_box)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_detail())
        splitter.setSizes([700, 360])
        body_layout.addWidget(splitter, 1)
        outer.addWidget(body, 1)

        # Status bar with progress.
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage("Choose your server's mods folder to begin.")

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Toolbar")
        v = QVBoxLayout(bar)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)

        # Row 1: folder + version selectors + scan
        row1 = QHBoxLayout()
        choose = QPushButton("Choose mods folder…")
        choose.clicked.connect(self._choose_folder)
        self.path_label = QLabel("No folder selected")
        self.path_label.setObjectName("PathLabel")

        self.loader_combo = QComboBox()
        self.loader_combo.addItems(LOADERS)
        self.loader_combo.setCurrentText(self.cfg.loader)
        self.loader_combo.currentTextChanged.connect(self._on_loader_changed)

        self.mc_combo = QComboBox()
        self.mc_combo.setEditable(True)
        self.mc_combo.addItems(COMMON_MC_VERSIONS)
        if self.cfg.mc_version not in COMMON_MC_VERSIONS:
            self.mc_combo.insertItem(0, self.cfg.mc_version)
        self.mc_combo.setCurrentText(self.cfg.mc_version)
        self.mc_combo.currentTextChanged.connect(self._on_mc_changed)

        self.scan_btn = QPushButton("Scan && check updates")
        self.scan_btn.setObjectName("Primary")
        self.scan_btn.clicked.connect(self._scan)

        row1.addWidget(choose)
        row1.addWidget(self.path_label, 1)
        row1.addWidget(QLabel("Loader:"))
        row1.addWidget(self.loader_combo)
        row1.addWidget(QLabel("MC:"))
        row1.addWidget(self.mc_combo)
        row1.addWidget(self.scan_btn)
        v.addLayout(row1)

        # Row 2: actions
        row2 = QHBoxLayout()
        self.update_sel_btn = QPushButton("Update selected")
        self.update_sel_btn.clicked.connect(self._update_selected)
        self.update_all_btn = QPushButton("Update all available")
        self.update_all_btn.setObjectName("Primary")
        self.update_all_btn.clicked.connect(self._update_all)
        self.browse_btn = QPushButton("Browse & install…")
        self.browse_btn.clicked.connect(self._browse)
        self.client_btn = QPushButton("Find client-only")
        self.client_btn.clicked.connect(self._find_client_only)
        self.deps_btn = QPushButton("Check dependencies")
        self.deps_btn.clicked.connect(self._check_deps)
        self.restore_btn = QPushButton("Restore removed…")
        self.restore_btn.clicked.connect(self._restore)
        settings_btn = QPushButton("Settings…")
        settings_btn.clicked.connect(self._settings)

        for b in (self.update_sel_btn, self.update_all_btn, self.browse_btn,
                  self.client_btn, self.deps_btn, self.restore_btn):
            row2.addWidget(b)
        row2.addStretch(1)
        row2.addWidget(settings_btn)
        v.addLayout(row2)

        self._set_actions_enabled(False)
        return bar

    def _build_table(self) -> QWidget:
        self.model = ModTableModel()
        self.proxy = ModFilterProxy()
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setItemDelegateForColumn(COL_STATUS, StatusPillDelegate(self.table))
        self.table.selectionModel().selectionChanged.connect(self._on_select)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(COL_CHECK, 34)
        return self.table

    def _build_detail(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)

        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(True)
        self.detail.setHtml("<p style='color:#9aa0ac'>Select a mod to see details.</p>")
        v.addWidget(self.detail, 1)

        # Version picker row.
        self.version_box = QWidget()
        vb = QVBoxLayout(self.version_box)
        vb.setContentsMargins(0, 8, 0, 0)
        vb.addWidget(QLabel("Version"))
        row = QHBoxLayout()
        self.version_combo = QComboBox()
        self.version_combo.setMinimumWidth(180)
        self.install_version_btn = QPushButton("Install")
        self.install_version_btn.clicked.connect(self._install_selected_version)
        self.unpin_btn = QPushButton("Unpin")
        self.unpin_btn.clicked.connect(self._unpin_current)
        row.addWidget(self.version_combo, 1)
        row.addWidget(self.install_version_btn)
        row.addWidget(self.unpin_btn)
        vb.addLayout(row)
        self.version_box.setVisible(False)
        v.addWidget(self.version_box)
        return panel

    # ------------------------------------------------------------------ #
    # Settings / selectors
    # ------------------------------------------------------------------ #
    def _on_loader_changed(self, text):
        self.cfg.loader = text
        save_config(self.cfg)

    def _on_mc_changed(self, text):
        self.cfg.mc_version = text.strip()
        save_config(self.cfg)

    def _settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            self.cfg = dlg.updated_config()
            save_config(self.cfg)
            self._build_providers()
            self.statusBar().showMessage("Settings saved.", 4000)

    def _set_actions_enabled(self, on: bool):
        for b in (self.update_sel_btn, self.update_all_btn, self.client_btn,
                  self.deps_btn):
            b.setEnabled(on)

    # ------------------------------------------------------------------ #
    # Folder + scan
    # ------------------------------------------------------------------ #
    def _choose_folder(self):
        start = self.cfg.server_mods_path or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Select mods folder", start)
        if folder:
            self.cfg.server_mods_path = folder
            save_config(self.cfg)
            self.path_label.setText(folder)
            self.statusBar().showMessage("Folder set. Click Scan to check updates.", 5000)

    def _scan(self):
        if not self.cfg.server_mods_path:
            QMessageBox.information(self, "Scan", "Choose a mods folder first.")
            return
        self.scan_btn.setEnabled(False)
        self._set_actions_enabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.statusBar().showMessage("Scanning…")
        self._scan_worker = ScanWorker(
            self.cfg.server_mods_path, self.providers,
            self.loader_combo.currentText(), self.mc_combo.currentText().strip(),
            self.cfg.accept_same_minor,
        )
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished_with.connect(self._on_scan_done)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.start()

    def _on_scan_progress(self, done, total, name):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.statusBar().showMessage(f"Checking {name} ({done}/{total})")

    def _on_scan_done(self, matches: list[ModMatch]):
        apply_pins(matches, self.cfg.pins)
        self.matches = matches
        self.model.set_matches(matches)
        self.proxy.sort(COL_STATUS, Qt.SortOrder.AscendingOrder)
        self.progress.setVisible(False)
        self.scan_btn.setEnabled(True)
        self._set_actions_enabled(True)
        updates = sum(1 for m in matches if m.has_update)
        unknown = sum(1 for m in matches if m.status == Status.UNKNOWN)
        self.statusBar().showMessage(
            f"{len(matches)} mods · {updates} update(s) available · {unknown} unidentified"
        )

    def _on_scan_error(self, msg):
        self.progress.setVisible(False)
        self.scan_btn.setEnabled(True)
        QMessageBox.critical(self, "Scan failed", msg)
        self.statusBar().showMessage("Scan failed.", 5000)

    # ------------------------------------------------------------------ #
    # Detail panel
    # ------------------------------------------------------------------ #
    def _on_select(self):
        idxs = self.table.selectionModel().selectedRows()
        if not idxs:
            return
        m = idxs[0].data(MATCH_ROLE)
        if not isinstance(m, ModMatch):
            return
        self._current = m
        self.detail.setHtml(self._detail_html(m))
        self._load_versions(m)

    def _detail_html(self, m: ModMatch) -> str:
        c = m.pill_color
        rows = [
            ("Status", f"<span style='color:{c}'>{escape(m.pill_label)}</span>"),
            ("Installed", escape(m.current_version)),
            ("Latest", escape(m.latest_version) if m.has_update else "—"),
            ("Source", escape(m.source or "unidentified")),
            ("File", escape(m.mod.jar_path.name)),
            ("Mod id", escape(m.mod.mod_id)),
            ("Authors", escape(m.mod.authors or "—")),
        ]
        table = "".join(
            f"<tr><td style='color:#9aa0ac;padding:2px 12px 2px 0'>{k}</td>"
            f"<td>{v}</td></tr>" for k, v in rows
        )
        link = (f"<p><a style='color:#5b8cff' href='{escape(m.project_url)}'>Open project page</a></p>"
                if m.project_url else "")
        desc = f"<p>{escape(m.mod.description)}</p>" if m.mod.description else ""
        changelog = ""
        if m.has_update and m.latest and m.latest.changelog:
            cl = escape(m.latest.changelog[:1500])
            changelog = f"<h4>Changelog ({escape(m.latest_version)})</h4><pre style='white-space:pre-wrap'>{cl}</pre>"
        return (
            f"<h2 style='margin-bottom:2px'>{escape(m.display_name)}</h2>"
            f"<table>{table}</table>{link}{desc}{changelog}"
        )

    # ------------------------------------------------------------------ #
    # Per-mod version picker
    # ------------------------------------------------------------------ #
    def _load_versions(self, m: ModMatch):
        self._current_versions = []
        self.version_combo.clear()
        if not m.source or not m.project_id:
            self.version_box.setVisible(False)
            return
        self.version_box.setVisible(True)
        self.unpin_btn.setVisible(m.pinned)
        self.version_combo.setEnabled(False)
        self.install_version_btn.setEnabled(False)
        self.version_combo.addItem("Loading versions…")
        provider = self.providers and {p.name: p for p in self.providers}.get(m.source)
        if not provider:
            return
        self._versions_worker = VersionsWorker(
            m, provider, self.loader_combo.currentText(),
            self.mc_combo.currentText().strip(), self.cfg.accept_same_minor,
        )
        self._versions_worker.done.connect(self._on_versions_loaded)
        self._versions_worker.error.connect(lambda mm, e: self._on_versions_loaded(mm, []))
        self._versions_worker.start()

    def _on_versions_loaded(self, m: ModMatch, versions: list[LatestVersion]):
        if m is not self._current:
            return  # selection changed while loading
        self._current_versions = versions
        self.version_combo.clear()
        if not versions:
            self.version_combo.addItem("No compatible versions")
            self.version_combo.setEnabled(False)
            self.install_version_btn.setEnabled(False)
            return
        installed_id = m.installed.version_id if m.installed else None
        latest_id = versions[0].version_id
        select_row = 0
        for i, v in enumerate(versions):
            tags = []
            if v.version_id == latest_id:
                tags.append("latest")
            if installed_id and v.version_id == installed_id:
                tags.append("installed")
                select_row = i
            if m.pinned and v.version_id == m.pinned_version_id:
                tags.append("pinned")
                select_row = i
            suffix = f"  ({', '.join(tags)})" if tags else ""
            self.version_combo.addItem(f"{v.version_number}{suffix}", v)
        self.version_combo.setCurrentIndex(select_row)
        self.version_combo.setEnabled(True)
        self.install_version_btn.setEnabled(True)

    def _install_selected_version(self):
        m = self._current
        target = self.version_combo.currentData()
        if not m or not isinstance(target, LatestVersion):
            return
        provider = {p.name: p for p in self.providers}.get(m.source)
        if not provider:
            return
        self.install_version_btn.setEnabled(False)
        self.version_combo.setEnabled(False)
        self.statusBar().showMessage(f"Installing {m.display_name} {target.version_number}…")
        self._install_worker = InstallVersionWorker(m, provider, target)
        self._install_worker.done.connect(lambda mm, t=target: self._on_version_installed(mm, t))
        self._install_worker.failed.connect(self._on_version_install_failed)
        self._install_worker.start()

    def _on_version_installed(self, m: ModMatch, target: LatestVersion):
        # Pin to the chosen version (a manual choice locks it).
        self.cfg.pins[m.project_id] = target.version_id
        save_config(self.cfg)
        apply_pins([m], self.cfg.pins)
        self.model.refresh_row(m)
        if m is self._current:
            self.detail.setHtml(self._detail_html(m))
            self._load_versions(m)
        self.statusBar().showMessage(
            f"Installed & pinned {m.display_name} {target.version_number}.", 5000
        )

    def _on_version_install_failed(self, m: ModMatch, msg: str):
        self.install_version_btn.setEnabled(True)
        self.version_combo.setEnabled(True)
        QMessageBox.warning(self, "Install failed", f"{m.display_name}: {msg}")
        self.statusBar().showMessage("Install failed.", 5000)

    def _unpin_current(self):
        m = self._current
        if not m or not m.project_id:
            return
        self.cfg.pins.pop(m.project_id, None)
        save_config(self.cfg)
        apply_pins([m], self.cfg.pins)
        self.model.refresh_row(m)
        self.unpin_btn.setVisible(False)
        self.detail.setHtml(self._detail_html(m))
        self.statusBar().showMessage(f"Unpinned {m.display_name}.", 4000)

    # ------------------------------------------------------------------ #
    # Updates
    # ------------------------------------------------------------------ #
    def _update_selected(self):
        self._run_updates(self.model.checked_matches())

    def _update_all(self):
        self.model.check_all_updates()
        self._run_updates([m for m in self.matches if m.updatable])

    def _run_updates(self, targets: list[ModMatch]):
        targets = [m for m in targets if m.updatable and m.latest and m.latest.download_url]
        if not targets:
            QMessageBox.information(self, "Update", "No updatable mods selected.")
            return
        self.scan_btn.setEnabled(False)
        self._set_actions_enabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(targets))
        self._update_worker = UpdateWorker(targets, self.providers)
        self._update_worker.progress.connect(self._on_update_progress)
        self._update_worker.mod_updated.connect(self._on_mod_updated)
        self._update_worker.mod_failed.connect(self._on_mod_failed)
        self._update_worker.all_done.connect(self._on_updates_done)
        self._failed: list[str] = []
        self._update_worker.start()

    def _on_update_progress(self, done, total, name):
        self.progress.setValue(done)
        self.statusBar().showMessage(f"Updating {name} ({done}/{total})")

    def _on_mod_updated(self, match: ModMatch):
        self.model.refresh_row(match)

    def _on_mod_failed(self, match: ModMatch, msg: str):
        self._failed.append(f"{match.display_name}: {msg}")

    def _on_updates_done(self):
        self.progress.setVisible(False)
        self.scan_btn.setEnabled(True)
        self._set_actions_enabled(True)
        if self._failed:
            QMessageBox.warning(self, "Some updates failed", "\n".join(self._failed))
        self.statusBar().showMessage("Updates complete.", 5000)

    # ------------------------------------------------------------------ #
    # Other actions
    # ------------------------------------------------------------------ #
    def _browse(self):
        if not self.cfg.server_mods_path:
            QMessageBox.information(self, "Browse", "Choose a mods folder first.")
            return
        SearchDialog(
            self.providers, self.loader_combo.currentText(),
            self.mc_combo.currentText().strip(), Path(self.cfg.server_mods_path),
            self.cfg.accept_same_minor, self,
        ).exec()

    def _find_client_only(self):
        findings = find_client_only(self.matches)
        if not findings:
            QMessageBox.information(self, "Client-only", "No client-only mods detected.")
            return
        dlg = ClientOnlyDialog(findings, Path(self.cfg.server_mods_path), self)
        if dlg.exec() and dlg.removed_count:
            self.statusBar().showMessage(f"Removed {dlg.removed_count} mod(s). Re-scanning…", 4000)
            self._scan()

    def _check_deps(self):
        issues = check_dependencies(self.matches)
        if not issues:
            QMessageBox.information(self, "Dependencies", "No dependency problems found.")
            return
        QMessageBox.warning(self, "Dependency issues", "\n".join(i.detail for i in issues))

    def _restore(self):
        if not self.cfg.server_mods_path:
            QMessageBox.information(self, "Restore", "Choose a mods folder first.")
            return
        dlg = RestoreDialog(Path(self.cfg.server_mods_path), self)
        if dlg.exec() and dlg.restored_count:
            self.statusBar().showMessage(f"Restored {dlg.restored_count} mod(s). Re-scanning…", 4000)
            self._scan()
