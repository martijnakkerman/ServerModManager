"""QThread workers so network/API work never freezes the UI."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from app.models import LatestVersion, ModMatch
from app.providers.base import Provider
from app.services.matcher import match_and_resolve
from app.services.scanner import scan_mods_folder
from app.services.updater import UpdateError, install_version, update_mod

log = logging.getLogger(__name__)


class ScanWorker(QThread):
    progress = pyqtSignal(int, int, str)   # done, total, name
    finished_with = pyqtSignal(list)       # list[ModMatch]
    error = pyqtSignal(str)

    def __init__(self, mods_dir, providers, loader, mc_version, accept_same_minor):
        super().__init__()
        self.mods_dir = Path(mods_dir)
        self.providers = providers
        self.loader = loader
        self.mc_version = mc_version
        self.accept_same_minor = accept_same_minor

    def run(self):
        try:
            mods = scan_mods_folder(self.mods_dir)
            if not mods:
                self.finished_with.emit([])
                return
            matches = match_and_resolve(
                mods,
                self.providers,
                loader=self.loader,
                mc_version=self.mc_version,
                accept_same_minor=self.accept_same_minor,
                progress_cb=lambda d, t, n: self.progress.emit(d, t, n),
            )
            self.finished_with.emit(matches)
        except Exception as e:  # noqa: BLE001
            log.exception("Scan failed")
            self.error.emit(str(e))


class UpdateWorker(QThread):
    progress = pyqtSignal(int, int, str)
    mod_updated = pyqtSignal(object)       # ModMatch
    mod_failed = pyqtSignal(object, str)   # ModMatch, error
    all_done = pyqtSignal()

    def __init__(self, matches: list[ModMatch], providers: list[Provider]):
        super().__init__()
        self.matches = matches
        self.by_name = {p.name: p for p in providers}

    def run(self):
        total = len(self.matches)
        for i, match in enumerate(self.matches, 1):
            self.progress.emit(i, total, match.display_name)
            provider = self.by_name.get(match.source)
            if not provider:
                self.mod_failed.emit(match, "No provider for this mod")
                continue
            try:
                update_mod(match, provider)
                self.mod_updated.emit(match)
            except UpdateError as e:
                self.mod_failed.emit(match, str(e))
            except Exception as e:  # noqa: BLE001
                log.exception("Update failed")
                self.mod_failed.emit(match, f"Unexpected: {e}")
        self.all_done.emit()


class VersionsWorker(QThread):
    """Lazily fetch all compatible versions for one mod (for the picker)."""

    done = pyqtSignal(object, list)   # ModMatch, list[LatestVersion]
    error = pyqtSignal(object, str)

    def __init__(self, match: ModMatch, provider: Provider, loader, mc_version, accept_same_minor):
        super().__init__()
        self.match = match
        self.provider = provider
        self.loader = loader
        self.mc_version = mc_version
        self.accept_same_minor = accept_same_minor

    def run(self):
        try:
            versions = self.provider.list_versions(
                self.match.project_id, self.loader, self.mc_version, self.accept_same_minor
            )
            self.done.emit(self.match, versions)
        except Exception as e:  # noqa: BLE001
            log.exception("Version list failed")
            self.error.emit(self.match, str(e))


class InstallVersionWorker(QThread):
    """Install one specific chosen version of a single mod."""

    done = pyqtSignal(object)          # ModMatch
    failed = pyqtSignal(object, str)   # ModMatch, error

    def __init__(self, match: ModMatch, provider: Provider, target: LatestVersion):
        super().__init__()
        self.match = match
        self.provider = provider
        self.target = target

    def run(self):
        try:
            install_version(self.match, self.provider, self.target)
            self.done.emit(self.match)
        except UpdateError as e:
            self.failed.emit(self.match, str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("Install version failed")
            self.failed.emit(self.match, f"Unexpected: {e}")
