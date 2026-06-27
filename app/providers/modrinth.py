"""Modrinth provider — the primary mod source.

Docs: https://docs.modrinth.com/api/

No API key needed for reads, but Modrinth asks for a descriptive User-Agent and
rate-limits at 300 req/min; we send the UA and back off on HTTP 429.

The key behaviour for correct update detection: the batch hash lookup returns the
*exact version object for each installed file*, so we record the installed
version's id + publish date as a :class:`VersionIdentity`. That identity — not a
version string — is what the resolver compares.
"""

from __future__ import annotations

import json
import logging
import time
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

BASE_URL = "https://api.modrinth.com/v2"
USER_AGENT = "mc-mod-manager/2.0 (github.com/mc-mod-manager)"
SITE_URL = "https://modrinth.com/mod/"


class ModrinthProvider:
    name = "modrinth"

    def __init__(self, user_agent: str = USER_AGENT, timeout: int = 20):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return True  # always available, no key required

    # ------------------------------------------------------------------ #
    # HTTP with 429 backoff
    # ------------------------------------------------------------------ #
    def _request(self, method: str, path: str, **kwargs):
        url = f"{BASE_URL}{path}"
        for attempt in range(3):
            try:
                r = self.session.request(method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as e:
                log.warning("Modrinth %s %s network error: %s", method, path, e)
                return None
            if r.status_code == 429 and attempt < 2:
                wait = float(r.headers.get("Retry-After", "2"))
                log.info("Modrinth rate-limited; waiting %.1fs", wait)
                time.sleep(min(wait, 10))
                continue
            if r.status_code == 404:
                return None
            if not r.ok:
                log.warning("Modrinth %s -> %s: %s", path, r.status_code, r.text[:200])
                return None
            try:
                return r.json()
            except ValueError:
                return None
        return None

    def _get(self, path: str, params: Optional[dict] = None):
        return self._request("GET", path, params=params)

    # ------------------------------------------------------------------ #
    # Matching
    # ------------------------------------------------------------------ #
    def match(self, mods: list[InstalledMod]) -> dict[str, ProviderMatch]:
        sha1s = [m.sha1 for m in mods if m.sha1]
        if not sha1s:
            return {}
        data = self._request(
            "POST", "/version_files", json={"hashes": sha1s, "algorithm": "sha1"}
        )
        if not isinstance(data, dict):
            return {}

        out: dict[str, ProviderMatch] = {}
        for sha1, version_obj in data.items():
            if not isinstance(version_obj, dict):
                continue
            project_id = version_obj.get("project_id")
            if not project_id:
                continue
            out[sha1] = ProviderMatch(
                source=self.name,
                project_id=project_id,
                installed=VersionIdentity(
                    version_id=version_obj.get("id", ""),
                    version_number=version_obj.get("version_number", ""),
                    date_published=parse_iso(version_obj.get("date_published")),
                ),
            )

        # Enrich with project metadata (title, slug, sides) in one batch call.
        self._attach_project_meta(out)
        return out

    def _attach_project_meta(self, matches: dict[str, ProviderMatch]) -> None:
        ids = sorted({pm.project_id for pm in matches.values()})
        if not ids:
            return
        data = self._get("/projects", params={"ids": json.dumps(ids)})
        if not isinstance(data, list):
            return
        by_id = {p.get("id"): p for p in data if isinstance(p, dict)}
        for pm in matches.values():
            proj = by_id.get(pm.project_id)
            if not proj:
                continue
            pm.project_title = proj.get("title", "")
            pm.project_slug = proj.get("slug", "")
            pm.project_url = SITE_URL + proj.get("slug", "") if proj.get("slug") else ""
            pm.client_side = proj.get("client_side", "unknown")
            pm.server_side = proj.get("server_side", "unknown")

    # ------------------------------------------------------------------ #
    # Latest version
    # ------------------------------------------------------------------ #
    def latest_version(
        self,
        project_id: str,
        loader: str,
        mc_version: str,
        accept_same_minor: bool = True,
    ) -> Optional[LatestVersion]:
        # Filter by loader server-side; filter MC compatibility client-side so we
        # can honor the same-minor rule without facet-exactness surprises.
        versions = self._get(
            f"/project/{project_id}/version",
            params={"loaders": json.dumps([loader])},
        )
        if not isinstance(versions, list):
            return None

        compatible = [
            v
            for v in versions
            if isinstance(v, dict)
            and is_mc_compatible(v.get("game_versions", []), mc_version, accept_same_minor)
        ]
        if not compatible:
            return None

        # Newest by publish date (Modrinth returns newest-first, but be explicit).
        compatible.sort(key=lambda v: v.get("date_published", ""), reverse=True)
        return self._to_latest(compatible[0])

    @staticmethod
    def _to_latest(v: dict) -> LatestVersion:
        files = v.get("files", [])
        primary = next((f for f in files if f.get("primary")), files[0] if files else None)
        file_hashes = {
            f.get("hashes", {}).get("sha1")
            for f in files
            if f.get("hashes", {}).get("sha1")
        }
        return LatestVersion(
            version_id=v.get("id", ""),
            version_number=v.get("version_number", ""),
            date_published=parse_iso(v.get("date_published")),
            download_url=primary.get("url") if primary else None,
            file_hashes=file_hashes,
            changelog=v.get("changelog", "") or "",
            dependencies=v.get("dependencies", []) or [],
            game_versions=v.get("game_versions", []) or [],
            loaders=v.get("loaders", []) or [],
        )

    # ------------------------------------------------------------------ #
    # Search + download
    # ------------------------------------------------------------------ #
    def search(
        self, query: str, loader: str, mc_version: str, limit: int = 20
    ) -> list[SearchHit]:
        facets = json.dumps(
            [[f"categories:{loader}"], [f"versions:{mc_version}"], ["project_type:mod"]]
        )
        data = self._get("/search", params={"query": query, "facets": facets, "limit": limit})
        if not isinstance(data, dict):
            return []
        hits = []
        for h in data.get("hits", []):
            hits.append(
                SearchHit(
                    source=self.name,
                    project_id=h.get("project_id", ""),
                    title=h.get("title", ""),
                    description=h.get("description", ""),
                    author=h.get("author", ""),
                    downloads=h.get("downloads", 0),
                    slug=h.get("slug", ""),
                    icon_url=h.get("icon_url", ""),
                )
            )
        return hits

    def latest_for_install(
        self, project_id: str, loader: str, mc_version: str, accept_same_minor: bool = True
    ) -> Optional[LatestVersion]:
        """Alias used by the install flow; identical to :meth:`latest_version`."""
        return self.latest_version(project_id, loader, mc_version, accept_same_minor)

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
            log.error("Modrinth download failed %s: %s", url, e)
            return False
