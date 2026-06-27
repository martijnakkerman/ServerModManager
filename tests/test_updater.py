"""Updater tests: atomic swap, backup, and the post-update status fix."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.models import InstalledMod, LatestVersion, ModMatch, Status, VersionIdentity
from app.services import resolver
from app.services.updater import UpdateError, list_backups, update_mod


def _valid_jar_bytes(marker: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("META-INF/MANIFEST.MF", f"Manifest-Version: 1.0\n{marker}\n")
    return buf.getvalue()


class FakeDownloadProvider:
    name = "modrinth"
    enabled = True

    def __init__(self, payload: bytes):
        self.payload = payload

    def download_file(self, url, dest_path):
        Path(dest_path).write_bytes(self.payload)
        return True


def _dt(day):
    return datetime(2024, 1, day, tzinfo=timezone.utc)


def test_update_swaps_backs_up_and_marks_up_to_date(tmp_path):
    # Existing (old) jar on disk.
    old = tmp_path / "mod-1.0.jar"
    old.write_bytes(_valid_jar_bytes("old"))

    new_bytes = _valid_jar_bytes("new")
    import hashlib
    new_sha1 = hashlib.sha1(new_bytes).hexdigest()

    mod = InstalledMod(jar_path=old, mod_id="m", display_name="M", version="1.0", sha1="oldsha")
    match = ModMatch(
        mod=mod,
        source="modrinth",
        project_id="p",
        installed=VersionIdentity("vOld", "1.0", _dt(1)),
        latest=LatestVersion(
            version_id="vNew",
            version_number="2.0",
            date_published=_dt(9),
            download_url="https://x/mod-2.0.jar",
            file_hashes={new_sha1},
        ),
    )
    resolver.resolve(match)
    assert match.status == Status.UPDATE_AVAILABLE  # precondition

    provider = FakeDownloadProvider(new_bytes)
    new_path = update_mod(match, provider)

    # New file installed, old backed up, old jar gone.
    assert new_path.exists() and new_path.name == "mod-2.0.jar"
    assert not old.exists()
    assert len(list_backups(tmp_path)) == 1

    # The fix: status is now up to date...
    assert match.status == Status.UP_TO_DATE
    assert mod.sha1 == new_sha1

    # ...and re-resolving (as a fresh scan would) keeps it up to date.
    resolver.resolve(match)
    assert match.status == Status.UP_TO_DATE


def test_update_without_url_raises(tmp_path):
    old = tmp_path / "mod.jar"
    old.write_bytes(_valid_jar_bytes("old"))
    mod = InstalledMod(jar_path=old, mod_id="m", display_name="M", version="1.0")
    match = ModMatch(mod=mod, source="modrinth", latest=LatestVersion("v", "2.0"))
    try:
        update_mod(match, FakeDownloadProvider(b""))
        assert False, "expected UpdateError"
    except UpdateError:
        pass
    assert old.exists()  # untouched
