"""Tests for the version-matching engine — the heart of the rewrite.

These are deliberately network-free: the resolver compares plain dataclasses,
so every row of the status decision matrix is exercised with constructed inputs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import LatestVersion, Status, VersionIdentity
from app.services.resolver import decide_status


def _dt(day: int) -> datetime:
    return datetime(2024, 1, day, tzinfo=timezone.utc)


def _latest(version_id="V_LATEST", day=10, hashes=None):
    return LatestVersion(
        version_id=version_id,
        version_number="2.0.0",
        date_published=_dt(day),
        file_hashes=set(hashes or ["sha_latest"]),
    )


def _installed(version_id="V_OLD", day=1):
    return VersionIdentity(version_id=version_id, version_number="1.0.0", date_published=_dt(day))


# ---- no comparison possible ----

def test_no_latest_is_unknown():
    assert decide_status(installed=_installed(), latest=None, installed_sha1="x") == Status.UNKNOWN


def test_no_match_at_all_is_unknown():
    assert decide_status(installed=None, latest=None, installed_sha1="") == Status.UNKNOWN


# ---- identity match: the bug we're fixing ----

def test_same_version_id_is_up_to_date_even_if_dates_differ():
    # The installed file resolves to the exact same version id as latest.
    installed = VersionIdentity(version_id="V123", date_published=_dt(1))
    latest = _latest(version_id="V123", day=9)  # later date, but SAME id
    assert decide_status(installed, latest, "sha_latest") == Status.UP_TO_DATE


def test_just_updated_mod_reports_up_to_date():
    # Regression for the original complaint: after updating, the installed
    # version id equals latest -> must NOT show update available.
    v = _latest(version_id="V_NEW", day=10)
    installed = VersionIdentity(version_id="V_NEW", version_number="2.0.0", date_published=_dt(10))
    assert decide_status(installed, v, "sha_latest") == Status.UP_TO_DATE


# ---- ordering by publish date ----

def test_newer_latest_is_update_available():
    assert decide_status(_installed(day=1), _latest(day=10), "sha_x") == Status.UPDATE_AVAILABLE


def test_installed_ahead_of_latest_is_up_to_date():
    # Installed a beta newer than the newest "compatible" release.
    installed = VersionIdentity(version_id="V_BETA", date_published=_dt(20))
    latest = _latest(version_id="V_REL", day=10)
    assert decide_status(installed, latest, "sha_beta") == Status.UP_TO_DATE


def test_equal_dates_different_ids_is_up_to_date():
    installed = VersionIdentity(version_id="A", date_published=_dt(10))
    latest = _latest(version_id="B", day=10)
    assert decide_status(installed, latest, "sha") == Status.UP_TO_DATE


# ---- installed version not pinned by provider ----

def test_unpinned_but_file_is_latest_is_up_to_date():
    # Hash lookup didn't return an installed version object, but our file's
    # sha1 is one of the latest version's files -> we are current.
    latest = _latest(hashes=["sha_a", "sha_b"])
    assert decide_status(installed=None, latest=latest, installed_sha1="sha_b") == Status.UP_TO_DATE


def test_unpinned_and_file_not_latest_is_check():
    latest = _latest(hashes=["sha_a"])
    assert decide_status(installed=None, latest=latest, installed_sha1="sha_other") == Status.CHECK


# ---- ids differ but dates missing ----

def test_ids_differ_no_dates_falls_back_to_hash():
    installed = VersionIdentity(version_id="A", date_published=None)
    latest = _latest(version_id="B", day=10, hashes=["sha_match"])
    latest.date_published = None
    assert decide_status(installed, latest, "sha_match") == Status.UP_TO_DATE


def test_ids_differ_no_dates_no_hash_is_check():
    installed = VersionIdentity(version_id="A", date_published=None)
    latest = _latest(version_id="B", day=10, hashes=["sha_x"])
    latest.date_published = None
    assert decide_status(installed, latest, "sha_other") == Status.CHECK
