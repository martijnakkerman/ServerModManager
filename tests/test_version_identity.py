"""Tests for the pure helpers behind compatibility + date handling."""

from __future__ import annotations

from datetime import timezone

from app.providers.base import is_mc_compatible, minor_line, parse_iso


def test_minor_line():
    assert minor_line("1.21.1") == "1.21"
    assert minor_line("1.21") == "1.21"
    assert minor_line("1.20.4") == "1.20"


def test_exact_compatibility():
    assert is_mc_compatible(["1.21.1"], "1.21.1", accept_same_minor=False)
    assert not is_mc_compatible(["1.21"], "1.21.1", accept_same_minor=False)


def test_same_minor_compatibility():
    # A file tagged only "1.21" is accepted for "1.21.1" when same-minor is on.
    assert is_mc_compatible(["1.21"], "1.21.1", accept_same_minor=True)
    # But a different minor line is never accepted.
    assert not is_mc_compatible(["1.20.1"], "1.21.1", accept_same_minor=True)


def test_parse_iso_handles_z_suffix():
    dt = parse_iso("2024-01-15T12:00:00Z")
    assert dt is not None and dt.tzinfo is not None
    assert dt.astimezone(timezone.utc).year == 2024


def test_parse_iso_none_and_bad():
    assert parse_iso(None) is None
    assert parse_iso("not-a-date") is None
