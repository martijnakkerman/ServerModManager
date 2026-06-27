"""The provider interface the matcher relies on.

A provider knows how to (a) recognize installed JARs by hash, (b) fetch the
latest compatible version of a project, (c) download a file, and (d) search.
Modrinth and CurseForge both implement this, so the matcher and updater never
care which source a given mod came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from app.models import InstalledMod, LatestVersion, VersionIdentity


@dataclass
class ProviderMatch:
    """Result of recognizing one installed JAR against a provider."""

    source: str
    project_id: str
    installed: Optional[VersionIdentity] = None
    project_title: str = ""
    project_slug: str = ""
    project_url: str = ""
    client_side: str = "unknown"
    server_side: str = "unknown"


@dataclass
class SearchHit:
    """A project returned from a search, for the browse-and-install dialog."""

    source: str
    project_id: str
    title: str
    description: str = ""
    author: str = ""
    downloads: int = 0
    slug: str = ""
    icon_url: str = ""


@runtime_checkable
class Provider(Protocol):
    name: str

    @property
    def enabled(self) -> bool:
        ...

    def match(self, mods: list[InstalledMod]) -> dict[str, ProviderMatch]:
        """Recognize installed JARs. Returns ``{mod.sha1: ProviderMatch}`` for the
        subset this provider can identify."""
        ...

    def latest_version(
        self,
        project_id: str,
        loader: str,
        mc_version: str,
        accept_same_minor: bool = True,
    ) -> Optional[LatestVersion]:
        ...

    def download_file(self, url: str, dest_path: Path) -> bool:
        ...

    def search(
        self, query: str, loader: str, mc_version: str, limit: int = 20
    ) -> list[SearchHit]:
        ...


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (Modrinth/CurseForge style) to aware UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def minor_line(mc_version: str) -> str:
    """'1.21.1' -> '1.21';  '1.21' -> '1.21'.  Used for same-minor compatibility."""
    parts = mc_version.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else mc_version


def is_mc_compatible(
    version_game_versions: list[str], mc_version: str, accept_same_minor: bool
) -> bool:
    """Does a version's declared game-versions cover the selected MC version?"""
    if mc_version in version_game_versions:
        return True
    if accept_same_minor:
        target = minor_line(mc_version)
        return any(minor_line(gv) == target for gv in version_game_versions)
    return False
