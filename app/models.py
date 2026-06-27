"""Core data model.

Everything the rest of the app passes around lives here. The types are kept
deliberately plain (dataclasses + an enum) so the matching engine in
``services/resolver.py`` can be tested with no network and no mocking — just
construct these objects directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class Status(str, Enum):
    """Update status of a single installed mod.

    Decided by identity (version id / file hash), never by parsing version
    strings — see ``services/resolver.py``.
    """

    UNKNOWN = "unknown"
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    CHECK = "check"  # matched a project but couldn't pin the installed version

    @property
    def label(self) -> str:
        return {
            Status.UNKNOWN: "Unknown",
            Status.UP_TO_DATE: "Up to date",
            Status.UPDATE_AVAILABLE: "Update available",
            Status.CHECK: "Check manually",
        }[self]

    @property
    def color(self) -> str:
        """Hex color for the status pill."""
        return {
            Status.UNKNOWN: "#6b7280",          # grey
            Status.UP_TO_DATE: "#22c55e",       # green
            Status.UPDATE_AVAILABLE: "#f59e0b",  # amber
            Status.CHECK: "#eab308",            # yellow
        }[self]


@dataclass
class VersionIdentity:
    """The exact version of a file as a provider identifies it.

    Produced by a hash/fingerprint lookup of the *installed* JAR, so it is the
    authoritative answer to "which release do I actually have?".
    """

    version_id: str
    version_number: str = ""
    date_published: Optional[datetime] = None


@dataclass
class LatestVersion:
    """The newest version of a project compatible with the selected loader + MC."""

    version_id: str
    version_number: str = ""
    date_published: Optional[datetime] = None
    download_url: Optional[str] = None
    # sha1 hashes of the files in this version — used to confirm "up to date"
    # when the installed version itself couldn't be pinned by the provider.
    file_hashes: set[str] = field(default_factory=set)
    changelog: str = ""
    dependencies: list[dict] = field(default_factory=list)
    game_versions: list[str] = field(default_factory=list)
    loaders: list[str] = field(default_factory=list)


@dataclass
class InstalledMod:
    """A mod JAR found on disk."""

    jar_path: Path
    mod_id: str
    display_name: str
    version: str  # from the JAR's mods.toml — display only, never used for compare
    authors: str = ""
    description: str = ""
    sha1: str = ""
    sha512: str = ""
    murmur2: int = 0
    # Side declared in the JAR's own toml: client_only | server_only | both | unknown
    toml_side: str = "unknown"


@dataclass
class ModMatch:
    """An installed mod enriched with provider data and a decided status.

    This is the object the UI renders. ``installed`` and ``latest`` are the two
    inputs the resolver compares; ``status`` is the verdict.
    """

    mod: InstalledMod
    source: str = ""  # "modrinth" | "curseforge" | ""  (empty = unmatched)
    project_id: Optional[str] = None
    project_title: str = ""
    project_slug: str = ""
    project_url: str = ""
    # Provider's declared sides (for client-only detection)
    client_side: str = "unknown"
    server_side: str = "unknown"
    installed: Optional[VersionIdentity] = None
    latest: Optional[LatestVersion] = None
    status: Status = Status.UNKNOWN
    error: str = ""
    # Pinning: a manually chosen version is locked and skipped by bulk updates.
    pinned: bool = False
    pinned_version_id: Optional[str] = None

    PIN_COLOR = "#a78bfa"  # purple

    @property
    def display_name(self) -> str:
        return self.project_title or self.mod.display_name

    @property
    def current_version(self) -> str:
        """Best label for what's installed: provider's version number if known,
        otherwise the JAR's own toml version."""
        if self.installed and self.installed.version_number:
            return self.installed.version_number
        return self.mod.version

    @property
    def latest_version(self) -> str:
        return self.latest.version_number if self.latest else ""

    @property
    def has_update(self) -> bool:
        return self.status == Status.UPDATE_AVAILABLE

    @property
    def updatable(self) -> bool:
        """Eligible for bulk update / the row checkbox: has an update and not pinned."""
        return self.has_update and not self.pinned

    @property
    def pill_label(self) -> str:
        return "Pinned" if self.pinned else self.status.label

    @property
    def pill_color(self) -> str:
        return self.PIN_COLOR if self.pinned else self.status.color
