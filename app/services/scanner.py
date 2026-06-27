"""Scan a Minecraft ``mods/`` folder and extract metadata + hashes per JAR.

Metadata is read from whichever descriptor the JAR carries:
  * ``META-INF/neoforge.mods.toml`` / ``META-INF/mods.toml``  (NeoForge / Forge)
  * ``fabric.mod.json``                                       (Fabric)
  * ``quilt.mod.json``                                        (Quilt)

Metadata is only for display + side detection — matching itself is done purely by
file hash, so a JAR whose descriptor we can't parse is still hashed and matched.

Three hashes are computed:
  * SHA-1   — Modrinth's primary lookup key
  * SHA-512 — recorded for completeness / future use
  * Murmur2 — CurseForge's fingerprint
"""

from __future__ import annotations

import hashlib
import json
import logging
import tomllib
import zipfile
from pathlib import Path
from typing import Optional

from app.models import InstalledMod

log = logging.getLogger(__name__)

# Descriptor files we know how to read, in priority order.
_TOML_DESCRIPTORS = ("META-INF/neoforge.mods.toml", "META-INF/mods.toml")
_FABRIC_DESCRIPTOR = "fabric.mod.json"
_QUILT_DESCRIPTOR = "quilt.mod.json"


# --------------------------------------------------------------------------- #
# Hashing
# --------------------------------------------------------------------------- #
def compute_hashes(jar_path: Path) -> tuple[str, str]:
    """Return (sha1_hex, sha512_hex)."""
    sha1 = hashlib.sha1()
    sha512 = hashlib.sha512()
    with jar_path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha1.update(chunk)
            sha512.update(chunk)
    return sha1.hexdigest(), sha512.hexdigest()


def murmur2_fingerprint(jar_path: Path) -> int:
    """CurseForge fingerprint: Murmur2 (seed=1) over the file with whitespace
    bytes (9, 10, 13, 32) stripped."""
    data = jar_path.read_bytes()
    filtered = bytes(b for b in data if b not in (9, 10, 13, 32))
    return _murmur2(filtered, seed=1)


def _murmur2(data: bytes, seed: int = 1) -> int:
    m = 0x5BD1E995
    r = 24
    length = len(data)
    h = (seed ^ length) & 0xFFFFFFFF
    i = 0
    while length >= 4:
        k = (
            data[i]
            | (data[i + 1] << 8)
            | (data[i + 2] << 16)
            | (data[i + 3] << 24)
        ) & 0xFFFFFFFF
        k = (k * m) & 0xFFFFFFFF
        k ^= (k >> r) & 0xFFFFFFFF
        k = (k * m) & 0xFFFFFFFF
        h = (h * m) & 0xFFFFFFFF
        h ^= k
        i += 4
        length -= 4
    if length >= 3:
        h ^= data[i + 2] << 16
    if length >= 2:
        h ^= data[i + 1] << 8
    if length >= 1:
        h ^= data[i]
        h = (h * m) & 0xFFFFFFFF
    h ^= (h >> 13) & 0xFFFFFFFF
    h = (h * m) & 0xFFFFFFFF
    h ^= (h >> 15) & 0xFFFFFFFF
    return h & 0xFFFFFFFF


# --------------------------------------------------------------------------- #
# Descriptor parsing
# --------------------------------------------------------------------------- #
def _norm_side(raw: str) -> str:
    """Normalize a loader's side declaration to client_only/server_only/both."""
    raw = raw.upper().strip()
    return {
        "CLIENT": "client_only",
        "SERVER": "server_only",
        "BOTH": "both",
        "*": "both",
        "": "unknown",
    }.get(raw, "unknown")


def _authors_to_str(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        names = []
        for a in value:
            if isinstance(a, str):
                names.append(a)
            elif isinstance(a, dict) and a.get("name"):
                names.append(str(a["name"]))
        return ", ".join(names)
    return ""


def _parse_toml(raw: bytes) -> Optional[dict]:
    try:
        data = tomllib.loads(raw.decode("utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, ValueError) as e:
        log.warning("Failed to parse mods.toml: %s", e)
        return None
    mods = data.get("mods")
    if not mods:
        return None
    mod = mods[0]
    return {
        "mod_id": mod.get("modId", "unknown"),
        "display_name": mod.get("displayName", mod.get("modId", "unknown")),
        "version": str(mod.get("version", "0.0.0")),
        "authors": _authors_to_str(mod.get("authors", "")),
        "description": str(mod.get("description", "")).strip(),
        "side": _norm_side(str(mod.get("side", ""))),
    }


def _parse_fabric_json(raw: bytes) -> Optional[dict]:
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("Failed to parse fabric.mod.json: %s", e)
        return None
    return {
        "mod_id": data.get("id", "unknown"),
        "display_name": data.get("name", data.get("id", "unknown")),
        "version": str(data.get("version", "0.0.0")),
        "authors": _authors_to_str(data.get("authors", "")),
        "description": str(data.get("description", "")).strip(),
        "side": _norm_side(str(data.get("environment", "*"))),
    }


def _read_descriptor(z: zipfile.ZipFile) -> Optional[dict]:
    names = set(z.namelist())
    for toml_name in _TOML_DESCRIPTORS:
        if toml_name in names:
            return _parse_toml(z.read(toml_name))
    if _FABRIC_DESCRIPTOR in names:
        return _parse_fabric_json(z.read(_FABRIC_DESCRIPTOR))
    if _QUILT_DESCRIPTOR in names:
        # Quilt nests mod info under "quilt_loader".
        try:
            data = json.loads(z.read(_QUILT_DESCRIPTOR).decode("utf-8", errors="replace"))
            ql = data.get("quilt_loader", {})
            meta = ql.get("metadata", {})
            return {
                "mod_id": ql.get("id", "unknown"),
                "display_name": meta.get("name", ql.get("id", "unknown")),
                "version": str(ql.get("version", "0.0.0")),
                "authors": _authors_to_str(meta.get("contributors", "")),
                "description": str(meta.get("description", "")).strip(),
                "side": "unknown",
            }
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("Failed to parse quilt.mod.json: %s", e)
            return None
    return None


# --------------------------------------------------------------------------- #
# Scanning
# --------------------------------------------------------------------------- #
def scan_mod_jar(jar_path: Path) -> Optional[InstalledMod]:
    """Extract an :class:`InstalledMod` from one JAR, or ``None`` if it isn't a mod."""
    if not jar_path.is_file() or jar_path.suffix.lower() != ".jar":
        return None
    try:
        with zipfile.ZipFile(jar_path, "r") as z:
            meta = _read_descriptor(z)
    except (zipfile.BadZipFile, OSError) as e:
        log.warning("Bad/unreadable JAR %s: %s", jar_path.name, e)
        return None
    if not meta:
        log.debug("No recognizable mod descriptor in %s", jar_path.name)
        return None

    sha1, sha512 = compute_hashes(jar_path)
    try:
        murmur2 = murmur2_fingerprint(jar_path)
    except OSError:
        murmur2 = 0
    return InstalledMod(
        jar_path=jar_path,
        mod_id=meta["mod_id"],
        display_name=meta["display_name"],
        version=meta["version"],
        authors=meta["authors"],
        description=meta["description"],
        sha1=sha1,
        sha512=sha512,
        murmur2=murmur2,
        toml_side=meta["side"],
    )


def scan_mods_folder(mods_dir: Path) -> list[InstalledMod]:
    """Scan every JAR in a folder. Dotfolders (``.backup`` etc.) are skipped."""
    mods_dir = Path(mods_dir)
    if not mods_dir.is_dir():
        raise FileNotFoundError(f"Mods directory not found: {mods_dir}")
    results: list[InstalledMod] = []
    for entry in sorted(mods_dir.iterdir()):
        if entry.name.startswith("."):
            continue
        mod = scan_mod_jar(entry)
        if mod:
            results.append(mod)
    return results
