"""The version-matching engine.

This module answers one question per mod: *is there an update?* — and it does so
**deterministically by identity**, never by parsing version strings.

The whole reason the previous app got this wrong was that it compared the JAR's
self-reported version string against Modrinth's version-number string. Those come
from different places and rarely share a format, so the comparison was unreliable
and "just updated" mods kept showing as out of date.

Here, the provider's hash lookup tells us the *exact* version we have installed
(its version id + publish date). We compare that identity against the latest
compatible version's identity. No string parsing, so a fresh scan and the
post-update view can never disagree.

The function is pure: it takes already-fetched data and returns a ``Status``. That
keeps it fully unit-testable with no network and no mocks.
"""

from __future__ import annotations

from typing import Optional

from app.models import LatestVersion, ModMatch, Status, VersionIdentity


def decide_status(
    installed: Optional[VersionIdentity],
    latest: Optional[LatestVersion],
    installed_sha1: str = "",
) -> Status:
    """Decide the update status for one mod.

    Args:
        installed: the version the provider matched the *installed* JAR to, or
            ``None`` if the hash/fingerprint lookup couldn't pin it.
        latest: the newest version compatible with the chosen loader + MC
            version, or ``None`` if no comparison is possible (e.g. the mod was
            never matched to a project, or has no compatible release).
        installed_sha1: sha1 of the installed JAR — used as a fallback identity
            check when the provider didn't return an installed version object.
    """
    # Nothing to compare against -> we simply don't know.
    if latest is None:
        return Status.UNKNOWN

    # We know the latest, but the provider didn't pin our installed version.
    # Fall back to file identity: if our JAR's hash is one of the latest
    # version's files, we already have the latest. Otherwise flag for review
    # rather than risk a false "update available".
    if installed is None:
        if installed_sha1 and installed_sha1 in latest.file_hashes:
            return Status.UP_TO_DATE
        return Status.CHECK

    # Authoritative: same version id means same release, full stop.
    if installed.version_id == latest.version_id:
        return Status.UP_TO_DATE

    # Different ids — order by publish date when both are known.
    if installed.date_published and latest.date_published:
        if latest.date_published > installed.date_published:
            return Status.UPDATE_AVAILABLE
        # Installed is the same age or newer than the newest compatible release
        # (e.g. a beta ahead of the latest stable) -> treat as current.
        return Status.UP_TO_DATE

    # Ids differ and we can't order by date. Last resort: file-hash identity.
    if installed_sha1 and installed_sha1 in latest.file_hashes:
        return Status.UP_TO_DATE
    return Status.CHECK


def resolve(match: ModMatch) -> ModMatch:
    """Set ``match.status`` in place using :func:`decide_status` and return it."""
    match.status = decide_status(
        installed=match.installed,
        latest=match.latest,
        installed_sha1=match.mod.sha1,
    )
    return match
