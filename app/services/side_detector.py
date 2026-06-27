"""Identify client-only mods that shouldn't live on a server.

Three signals are combined:
  1. TOML/JSON ``side`` declared in the JAR itself (strongest when it says CLIENT)
  2. Modrinth's ``server_side`` flag (``unsupported`` is a strong signal)
  3. A curated heuristic list of well-known client-only mod ids

Confidence:
  * HIGH   — two+ signals agree, or the JAR explicitly declares CLIENT
  * MEDIUM — one strong signal (Modrinth unsupported, or JAR-only client)
  * LOW    — only the heuristic matched (review manually)

Contradictions (JAR says CLIENT but Modrinth says server_side required) are
surfaced with ``conflict=True`` and never marked safe-to-remove.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import ModMatch

# Well-known client-only mod ids (loader-agnostic). Extend freely.
KNOWN_CLIENT_ONLY = {
    "iris", "oculus", "sodium", "rubidium", "embeddium", "xaerominimap",
    "xaeroworldmap", "journeymap", "jei_but_client", "controlling", "jade",
    "appleskin_client", "betterf3", "dynamiclights", "entityculling",
    "ferritecore_client", "modmenu", "reeses_sodium_options", "sodiumextra",
    "zoomify", "okzoomer", "shouldersurfing", "mousetweaks", "itemzoom",
}


@dataclass
class SideFinding:
    match: ModMatch
    confidence: str       # HIGH | MEDIUM | LOW
    reasons: list[str]
    conflict: bool
    safe_to_remove: bool


def _classify(match: ModMatch) -> SideFinding | None:
    mod = match.mod
    reasons: list[str] = []
    conflict = False

    toml_client = mod.toml_side == "client_only"
    toml_server = mod.toml_side == "server_only"
    mr_unsupported = match.server_side == "unsupported"
    mr_required = match.server_side == "required"
    heuristic = mod.mod_id.lower() in KNOWN_CLIENT_ONLY

    if toml_client:
        reasons.append("JAR declares side=CLIENT")
    if mr_unsupported:
        reasons.append("Modrinth: server_side unsupported")
    if heuristic:
        reasons.append("Known client-only mod")

    # Contradictions
    if toml_client and mr_required:
        conflict = True
        reasons.append("⚠ conflict: Modrinth says server required")
    if toml_server:
        return None  # explicitly server-side, not a candidate

    signals = sum([toml_client, mr_unsupported, heuristic])
    if signals == 0:
        return None

    if toml_client or signals >= 2:
        confidence = "HIGH"
    elif mr_unsupported:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    safe = not conflict and confidence in ("HIGH", "MEDIUM")
    return SideFinding(match, confidence, reasons, conflict, safe)


def find_client_only(matches: list[ModMatch]) -> list[SideFinding]:
    findings = [_classify(m) for m in matches]
    return [f for f in findings if f is not None]
