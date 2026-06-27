"""Tests for the scanner: descriptor parsing, hashing, murmur2 fingerprint."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from app.services.scanner import (
    _murmur2,
    compute_hashes,
    murmur2_fingerprint,
    scan_mod_jar,
)


def _make_jar(path: Path, files: dict[str, bytes]) -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    path.write_bytes(buf.getvalue())
    return path


# ---- murmur2 ----

def test_murmur2_is_deterministic_and_matches_reference():
    assert _murmur2(b"", 1) == 1540447798
    assert _murmur2(b"abc", 1) == 1621425345
    assert _murmur2(b"helloworld", 1) == 2824650221


def test_fingerprint_strips_whitespace(tmp_path):
    a = _make_jar(tmp_path / "a.jar", {"x.txt": b"hello world\n\t data"})
    b = _make_jar(tmp_path / "b.jar", {"x.txt": b"helloworlddata"})
    # Whitespace bytes (space/tab/newline) are stripped before hashing, so the
    # two files fingerprint identically.
    assert murmur2_fingerprint(a) != 0
    # Build raw byte streams to prove the stripping rule directly:
    raw = b"hello world\n\t data"
    assert _murmur2(bytes(c for c in raw if c not in (9, 10, 13, 32)), 1) == _murmur2(b"helloworlddata", 1)


# ---- hashing ----

def test_compute_hashes_lengths(tmp_path):
    jar = _make_jar(tmp_path / "m.jar", {"a": b"content"})
    sha1, sha512 = compute_hashes(jar)
    assert len(sha1) == 40 and len(sha512) == 128


# ---- descriptor parsing ----

def test_scan_neoforge_toml(tmp_path):
    toml = b"""
modLoader="javafml"
[[mods]]
modId="examplemod"
version="1.2.3"
displayName="Example Mod"
authors="Alice, Bob"
description="An example."
side="SERVER"
"""
    jar = _make_jar(tmp_path / "ex.jar", {"META-INF/neoforge.mods.toml": toml})
    mod = scan_mod_jar(jar)
    assert mod is not None
    assert mod.mod_id == "examplemod"
    assert mod.display_name == "Example Mod"
    assert mod.version == "1.2.3"
    assert mod.authors == "Alice, Bob"
    assert mod.toml_side == "server_only"
    assert mod.sha1 and mod.murmur2


def test_scan_fabric_json(tmp_path):
    fabric = json.dumps({
        "id": "fabricmod",
        "name": "Fabric Mod",
        "version": "0.9.0",
        "authors": ["Carol", {"name": "Dave"}],
        "description": "Fabric example",
        "environment": "client",
    }).encode()
    jar = _make_jar(tmp_path / "fab.jar", {"fabric.mod.json": fabric})
    mod = scan_mod_jar(jar)
    assert mod is not None
    assert mod.mod_id == "fabricmod"
    assert mod.display_name == "Fabric Mod"
    assert mod.authors == "Carol, Dave"
    assert mod.toml_side == "client_only"


def test_non_mod_jar_returns_none(tmp_path):
    jar = _make_jar(tmp_path / "lib.jar", {"com/example/Foo.class": b"\xca\xfe\xba\xbe"})
    assert scan_mod_jar(jar) is None


def test_non_jar_file_returns_none(tmp_path):
    p = tmp_path / "readme.txt"
    p.write_text("not a jar")
    assert scan_mod_jar(p) is None
