"""CurseForge provider — optional fallback for mods not on Modrinth.

Needs a free API key (https://console.curseforge.com/). Without one the provider
reports ``enabled == False`` and the matcher skips it, so the app stays fully
functional Modrinth-only.

Installed JARs are recognized by Murmur2 fingerprint (computed during the scan).
The fingerprint lookup returns the exact file object, giving us the installed
file id + date as a :class:`VersionIdentity` — the same identity-based approach
used for Modrinth.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import requests

from app.models import InstalledMod, LatestVersion, VersionIdentity
from app.providers.base import (
    ProviderMatch,
    SearchHit,
    is_mc_compatible,
    parse_iso,
)

log = logging.getLogger(__name__)

BASE_URL = "https://api.curseforge.com/v1"
MINECRAFT_GAME_ID = 432
MOD_CLASS_ID = 6
SITE_URL = "https://www.curseforge.com/minecraft/mc-mods/"

# CurseForge mod-loader type ids.
LOADER_TYPES = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
# CurseForge file hash algo ids.
_SHA1_ALGO = 1


class CurseForgeProvider:
    name = "curseforge"

    def __init__(self, api_key: Optional[str] = None, timeout: int = 20):
        self.api_key = api_key or ""
        self.timeout = timeout
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update(
                {"x-api-key": self.api_key, "Accept": "application/json"}
            )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------ #
    def _request(self, method: str, path: str, **kwargs):
        if not self.enabled:
            return None
        try:
            r = self.session.request(
                method, f"{BASE_URL}{path}", timeout=self.timeout, **kwargs
            )
        except requests.RequestException as e:
            log.warning("CurseForge %s %s error: %s", method, path, e)
            return None
        if r.status_code == 404:
            return None
        if not r.ok:
            log.warning("CurseForge %s -> %s", path, r.status_code)
            return None
        try:
            return r.json()
        except ValueError:
            return None

    # ------------------------------------------------------------------ #
    # Matching
    # ------------------------------------------------------------------ #
    def match(self, mods: list[InstalledMod]) -> dict[str, ProviderMatch]:
        if not self.enabled:
            return {}
        fp_to_sha1 = {m.murmur2: m.sha1 for m in mods if m.murmur2 and m.sha1}
        if not fp_to_sha1:
            return {}
        data = self._request(
            "POST", "/fingerprints", json={"fingerprints": list(fp_to_sha1.keys())}
        )
        if not isinstance(data, dict):
            return {}

        out: dict[str, ProviderMatch] = {}
        for m in data.get("data", {}).get("exactMatches", []):
            file_obj = m.get("file", {})
            fp = file_obj.get("fileFingerprint")
            sha1 = fp_to_sha1.get(fp)
            mod_id = file_obj.get("modId")
            if not sha1 or not mod_id:
                continue
            out[sha1] = ProviderMatch(
                source=self.name,
                project_id=str(mod_id),
                installed=VersionIdentity(
                    version_id=str(file_obj.get("id", "")),
                    version_number=file_obj.get("displayName") or file_obj.get("fileName", ""),
                    date_published=parse_iso(file_obj.get("fileDate")),
                ),
            )
        self._attach_project_meta(out)
        return out

    def _attach_project_meta(self, matches: dict[str, ProviderMatch]) -> None:
        ids = sorted({int(pm.project_id) for pm in matches.values() if pm.project_id.isdigit()})
        if not ids:
            return
        data = self._request("POST", "/mods", json={"modIds": ids})
        if not isinstance(data, dict):
            return
        by_id = {str(p.get("id")): p for p in data.get("data", []) if isinstance(p, dict)}
        for pm in matches.values():
            proj = by_id.get(pm.project_id)
            if not proj:
                continue
            pm.project_title = proj.get("name", "")
            pm.project_slug = proj.get("slug", "")
            links = proj.get("links", {}) or {}
            pm.project_url = links.get("websiteUrl") or (
                SITE_URL + proj.get("slug", "") if proj.get("slug") else ""
            )

    # ------------------------------------------------------------------ #
    # Latest version
    # ------------------------------------------------------------------ #
    def list_versions(
        self,
        project_id: str,
        loader: str,
        mc_version: str,
        accept_same_minor: bool = True,
    ) -> list[LatestVersion]:
        """All compatible files for this loader + MC, newest-first."""
        params = {
            "gameVersion": mc_version,
            "pageSize": 50,
            "index": 0,
        }
        loader_type = LOADER_TYPES.get(loader)
        if loader_type:
            params["modLoaderType"] = loader_type
        data = self._request("GET", f"/mods/{project_id}/files", params=params)
        if not isinstance(data, dict):
            return []
        files = [f for f in data.get("data", []) if isinstance(f, dict)]
        compatible = [
            f
            for f in files
            if is_mc_compatible(f.get("gameVersions", []), mc_version, accept_same_minor)
        ]
        compatible.sort(key=lambda f: f.get("fileDate", ""), reverse=True)
        return [self._to_latest(f) for f in compatible]

    def latest_version(
        self,
        project_id: str,
        loader: str,
        mc_version: str,
        accept_same_minor: bool = True,
    ) -> Optional[LatestVersion]:
        versions = self.list_versions(project_id, loader, mc_version, accept_same_minor)
        return versions[0] if versions else None

    @staticmethod
    def _to_latest(f: dict) -> LatestVersion:
        sha1s = {
            h.get("value")
            for h in f.get("hashes", [])
            if h.get("algo") == _SHA1_ALGO and h.get("value")
        }
        return LatestVersion(
            version_id=str(f.get("id", "")),
            version_number=f.get("displayName") or f.get("fileName", ""),
            date_published=parse_iso(f.get("fileDate")),
            download_url=f.get("downloadUrl"),
            file_hashes=sha1s,
            changelog="",
            dependencies=[
                {
                    "project_id": str(d.get("modId")),
                    "dependency_type": _CF_DEP_TYPE.get(d.get("relationType"), "unknown"),
                }
                for d in f.get("dependencies", [])
            ],
            game_versions=f.get("gameVersions", []) or [],
        )

    # ------------------------------------------------------------------ #
    def search(
        self, query: str, loader: str, mc_version: str, limit: int = 20
    ) -> list[SearchHit]:
        params = {
            "gameId": MINECRAFT_GAME_ID,
            "classId": MOD_CLASS_ID,
            "searchFilter": query,
            "gameVersion": mc_version,
            "pageSize": limit,
        }
        loader_type = LOADER_TYPES.get(loader)
        if loader_type:
            params["modLoaderType"] = loader_type
        data = self._request("GET", "/mods/search", params=params)
        if not isinstance(data, dict):
            return []
        hits = []
        for p in data.get("data", []):
            authors = p.get("authors", []) or []
            hits.append(
                SearchHit(
                    source=self.name,
                    project_id=str(p.get("id", "")),
                    title=p.get("name", ""),
                    description=p.get("summary", ""),
                    author=authors[0].get("name", "") if authors else "",
                    downloads=int(p.get("downloadCount", 0)),
                    slug=p.get("slug", ""),
                    icon_url=(p.get("logo") or {}).get("thumbnailUrl", ""),
                )
            )
        return hits

    def download_file(self, url: str, dest_path: Path) -> bool:
        try:
            with self.session.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(dest_path, "wb") as f:
                    for chunk in r.iter_content(65536):
                        if chunk:
                            f.write(chunk)
            return True
        except (requests.RequestException, OSError) as e:
            log.error("CurseForge download failed %s: %s", url, e)
            return False


_CF_DEP_TYPE = {1: "embedded", 2: "optional", 3: "required", 4: "tool", 5: "incompatible", 6: "include"}
