"""Matcher orchestration tests using fake in-memory providers (no network)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.models import InstalledMod, LatestVersion, Status, VersionIdentity
from app.providers.base import ProviderMatch
from app.models import ModMatch
from app.services.matcher import apply_pins, match_and_resolve


def _mod(sha1: str, name: str) -> InstalledMod:
    return InstalledMod(
        jar_path=Path(f"{name}.jar"), mod_id=name, display_name=name, version="1", sha1=sha1
    )


class FakeProvider:
    def __init__(self, name, known: dict, latest: dict, enabled=True):
        self.name = name
        self._known = known      # {sha1: ProviderMatch}
        self._latest = latest    # {project_id: LatestVersion}
        self._enabled = enabled

    @property
    def enabled(self):
        return self._enabled

    def match(self, mods):
        return {m.sha1: self._known[m.sha1] for m in mods if m.sha1 in self._known}

    def latest_version(self, project_id, loader, mc_version, accept_same_minor=True):
        return self._latest.get(project_id)

    def download_file(self, url, dest_path):
        return True

    def search(self, query, loader, mc_version, limit=20):
        return []


def _dt(day):
    return datetime(2024, 1, day, tzinfo=timezone.utc)


def test_primary_then_fallback_and_status():
    a, b, c = _mod("sha_a", "A"), _mod("sha_b", "B"), _mod("sha_c", "C")

    modrinth = FakeProvider(
        "modrinth",
        known={
            "sha_a": ProviderMatch("modrinth", "projA", VersionIdentity("vA1", date_published=_dt(1))),
            "sha_b": ProviderMatch("modrinth", "projB", VersionIdentity("vB9", date_published=_dt(9))),
        },
        latest={
            "projA": LatestVersion("vA9", "9.0", _dt(9)),   # newer -> update
            "projB": LatestVersion("vB9", "9.0", _dt(9)),   # same id -> up to date
        },
    )
    curseforge = FakeProvider(
        "curseforge",
        known={"sha_c": ProviderMatch("curseforge", "cfC", VersionIdentity("fC1", date_published=_dt(2)))},
        latest={"cfC": LatestVersion("fC1", "x", _dt(2))},  # same id -> up to date
    )

    results = match_and_resolve(
        [a, b, c], [modrinth, curseforge], loader="neoforge", mc_version="1.21.1"
    )

    by_name = {r.mod.mod_id: r for r in results}
    assert by_name["A"].source == "modrinth" and by_name["A"].status == Status.UPDATE_AVAILABLE
    assert by_name["B"].status == Status.UP_TO_DATE
    assert by_name["C"].source == "curseforge" and by_name["C"].status == Status.UP_TO_DATE
    # Output order matches input order.
    assert [r.mod.mod_id for r in results] == ["A", "B", "C"]


def test_unmatched_mod_is_unknown():
    a = _mod("sha_a", "A")
    modrinth = FakeProvider("modrinth", known={}, latest={})
    results = match_and_resolve([a], [modrinth], loader="neoforge", mc_version="1.21.1")
    assert results[0].source == "" and results[0].status == Status.UNKNOWN


def test_disabled_provider_skipped():
    a = _mod("sha_a", "A")
    cf = FakeProvider("curseforge", known={"sha_a": ProviderMatch("curseforge", "x")}, latest={}, enabled=False)
    results = match_and_resolve([a], [cf], loader="neoforge", mc_version="1.21.1")
    assert results[0].source == ""


def test_apply_pins_marks_and_clears():
    m1 = ModMatch(mod=_mod("s1", "A"), project_id="pA")
    m2 = ModMatch(mod=_mod("s2", "B"), project_id="pB")
    apply_pins([m1, m2], {"pA": "ver123"})
    assert m1.pinned and m1.pinned_version_id == "ver123"
    assert not m2.pinned
    # Re-applying with an empty pin set clears it.
    apply_pins([m1], {})
    assert not m1.pinned and m1.pinned_version_id is None


def test_pinned_mod_not_updatable():
    from app.models import LatestVersion as LV, Status as St
    m = ModMatch(mod=_mod("s", "A"), project_id="p", status=St.UPDATE_AVAILABLE)
    assert m.updatable
    apply_pins([m], {"p": "v1"})
    assert m.has_update and not m.updatable  # still has an update, but locked
    assert m.pill_label == "Pinned"
