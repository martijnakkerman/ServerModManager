"""Tests for client-only side detection and dependency checking."""

from __future__ import annotations

from pathlib import Path

from app.models import InstalledMod, LatestVersion, ModMatch
from app.services.dependency import check_dependencies
from app.services.side_detector import find_client_only


def _match(mod_id, toml_side="unknown", server_side="unknown", project_id=None, deps=None):
    mod = InstalledMod(jar_path=Path(f"{mod_id}.jar"), mod_id=mod_id, display_name=mod_id,
                       version="1", sha1=mod_id, toml_side=toml_side)
    mm = ModMatch(mod=mod, project_id=project_id, server_side=server_side)
    if deps is not None:
        mm.latest = LatestVersion("v", "1", dependencies=deps)
    return mm


def test_toml_client_is_high_confidence():
    f = find_client_only([_match("foo", toml_side="client_only")])
    assert len(f) == 1 and f[0].confidence == "HIGH" and f[0].safe_to_remove


def test_conflict_not_safe():
    f = find_client_only([_match("foo", toml_side="client_only", server_side="required")])
    assert f[0].conflict and not f[0].safe_to_remove


def test_modrinth_unsupported_is_medium():
    f = find_client_only([_match("bar", server_side="unsupported")])
    assert f[0].confidence == "MEDIUM"


def test_heuristic_only_is_low():
    f = find_client_only([_match("sodium")])
    assert f[0].confidence == "LOW" and not f[0].safe_to_remove


def test_server_side_mod_ignored():
    assert find_client_only([_match("srv", toml_side="server_only")]) == []


def test_missing_required_dependency():
    a = _match("a", project_id="pA", deps=[{"project_id": "pMISSING", "dependency_type": "required"}])
    issues = check_dependencies([a])
    assert len(issues) == 1 and issues[0].kind == "missing_required"


def test_incompatible_dependency():
    a = _match("a", project_id="pA", deps=[{"project_id": "pB", "dependency_type": "incompatible"}])
    b = _match("b", project_id="pB")
    issues = check_dependencies([a, b])
    assert len(issues) == 1 and issues[0].kind == "incompatible"


def test_satisfied_required_dependency_ok():
    a = _match("a", project_id="pA", deps=[{"project_id": "pB", "dependency_type": "required"}])
    b = _match("b", project_id="pB")
    assert check_dependencies([a, b]) == []
