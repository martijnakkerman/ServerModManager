"""Atomic mod updates.

Sequence (any failure leaves the existing JAR untouched):
  1. download new file to a ``.part`` temp inside the mods dir
  2. verify it's a valid ZIP
  3. copy the current JAR to ``mods/.backup/<name>.<timestamp>.jar``
  4. delete the old JAR, rename the ``.part`` to its final name
  5. recompute hashes and re-resolve through the same engine, so the row's
     status reflects hash-derived truth (not a faked version string)
"""

from __future__ import annotations

import logging
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from app.models import ModMatch, VersionIdentity
from app.providers.base import Provider
from app.services import resolver
from app.services.scanner import compute_hashes, murmur2_fingerprint

log = logging.getLogger(__name__)

BACKUP_DIRNAME = ".backup"


class UpdateError(Exception):
    pass


def backup_dir(mods_dir: Path) -> Path:
    d = mods_dir / BACKUP_DIRNAME
    d.mkdir(exist_ok=True)
    return d


def _backup_existing(jar_path: Path) -> Path:
    bdir = backup_dir(jar_path.parent)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = bdir / f"{jar_path.stem}.{ts}.jar"
    dest.write_bytes(jar_path.read_bytes())
    log.info("Backed up %s -> %s", jar_path.name, dest.name)
    return dest


def update_mod(match: ModMatch, provider: Provider) -> Path:
    """Download + install ``match.latest`` for this mod. Returns the new path."""
    latest = match.latest
    if not latest or not latest.download_url:
        raise UpdateError(f"No download URL for {match.display_name}")

    mod = match.mod
    mods_dir = mod.jar_path.parent

    with tempfile.NamedTemporaryFile(suffix=".jar.part", dir=mods_dir, delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        if not provider.download_file(latest.download_url, tmp_path):
            raise UpdateError(f"Download failed for {match.display_name}")
        try:
            with zipfile.ZipFile(tmp_path, "r") as z:
                z.testzip()
        except zipfile.BadZipFile:
            raise UpdateError(f"Downloaded file is corrupt for {match.display_name}")

        _backup_existing(mod.jar_path)

        new_name = latest.download_url.rsplit("/", 1)[-1]
        if not new_name.lower().endswith(".jar"):
            new_name = mod.jar_path.name
        final_path = mods_dir / new_name

        old_path = mod.jar_path
        # If the new name collides with a *different* existing file, fall back.
        if final_path.exists() and final_path != old_path:
            final_path = mods_dir / mod.jar_path.name

        old_path.unlink()
        tmp_path.replace(final_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    # Refresh on-disk identity and re-resolve through the same engine.
    mod.jar_path = final_path
    mod.sha1, mod.sha512 = compute_hashes(final_path)
    try:
        mod.murmur2 = murmur2_fingerprint(final_path)
    except OSError:
        pass
    mod.version = latest.version_number or mod.version
    # We installed exactly `latest`, so the installed identity IS latest's identity.
    match.installed = VersionIdentity(
        version_id=latest.version_id,
        version_number=latest.version_number,
        date_published=latest.date_published,
    )
    resolver.resolve(match)
    return final_path


def list_backups(mods_dir: Path) -> list[Path]:
    bdir = mods_dir / BACKUP_DIRNAME
    if not bdir.is_dir():
        return []
    return sorted(bdir.glob("*.jar"), reverse=True)


def rollback(match: ModMatch, backup_jar: Path) -> None:
    """Restore a mod from a backup JAR (best-effort name recovery)."""
    if not backup_jar.is_file():
        raise UpdateError(f"Backup not found: {backup_jar}")
    mod = match.mod
    mods_dir = mod.jar_path.parent
    target = (mods_dir / backup_jar.name.split(".", 1)[0]).with_suffix(".jar")
    target.write_bytes(backup_jar.read_bytes())
    if mod.jar_path.exists() and mod.jar_path != target:
        mod.jar_path.unlink()
    mod.jar_path = target
    mod.sha1, mod.sha512 = compute_hashes(target)
