"""Orchestrates providers + the resolver to turn scanned JARs into ``ModMatch``es.

Flow:
  1. Ask each provider (in order: Modrinth, then CurseForge fallback) to recognize
     the still-unmatched JARs by hash/fingerprint.
  2. For every matched mod, fetch the latest compatible version from the provider
     that matched it.
  3. Run the resolver to decide the status by identity — no string parsing.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from app.models import InstalledMod, ModMatch
from app.providers.base import Provider
from app.services import resolver

log = logging.getLogger(__name__)

ProgressCb = Optional[Callable[[int, int, str], None]]


def match_and_resolve(
    mods: list[InstalledMod],
    providers: list[Provider],
    loader: str,
    mc_version: str,
    accept_same_minor: bool = True,
    progress_cb: ProgressCb = None,
) -> list[ModMatch]:
    matches = {m.sha1: ModMatch(mod=m) for m in mods}
    by_name = {p.name: p for p in providers}

    # ---- Step 1: recognize JARs, providers in priority order ----
    remaining = [m for m in mods if m.sha1]
    for provider in providers:
        if not provider.enabled or not remaining:
            continue
        try:
            found = provider.match(remaining)
        except Exception as e:  # never let one provider abort the scan
            log.warning("Provider %s match failed: %s", provider.name, e)
            found = {}
        for sha1, pm in found.items():
            mm = matches.get(sha1)
            if not mm:
                continue
            mm.source = pm.source
            mm.project_id = pm.project_id
            mm.project_title = pm.project_title
            mm.project_slug = pm.project_slug
            mm.project_url = pm.project_url
            mm.client_side = pm.client_side
            mm.server_side = pm.server_side
            mm.installed = pm.installed
        remaining = [m for m in remaining if m.sha1 not in found]

    # ---- Step 2 + 3: fetch latest, then resolve ----
    ordered = list(matches.values())
    total = len(ordered)
    for i, mm in enumerate(ordered, 1):
        if progress_cb:
            progress_cb(i, total, mm.display_name)
        provider = by_name.get(mm.source)
        if provider and mm.project_id:
            try:
                mm.latest = provider.latest_version(
                    mm.project_id, loader, mc_version, accept_same_minor
                )
            except Exception as e:
                log.warning("latest_version failed for %s: %s", mm.display_name, e)
                mm.error = str(e)
        resolver.resolve(mm)

    # Preserve the scan order of the input list.
    return [matches[m.sha1] for m in mods]
