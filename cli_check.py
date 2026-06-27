"""Headless smoke test for the scan + match + resolve pipeline.

Usage:
    python cli_check.py <mods_folder> [--loader neoforge] [--mc 1.21.1]
                        [--cf-key KEY] [--exact]

Prints each mod with its resolved status — handy for confirming the
identity-based matching is correct without launching the GUI.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.providers.curseforge import CurseForgeProvider
from app.providers.modrinth import ModrinthProvider
from app.services.matcher import match_and_resolve
from app.services.scanner import scan_mods_folder

STATUS_MARK = {
    "up_to_date": "OK ",
    "update_available": "UPD",
    "unknown": "?? ",
    "check": "CHK",
}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scan a mods folder and check updates.")
    parser.add_argument("mods_folder", type=Path)
    parser.add_argument("--loader", default="neoforge")
    parser.add_argument("--mc", default="1.21.1")
    parser.add_argument("--cf-key", default="")
    parser.add_argument("--exact", action="store_true", help="exact MC version only")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    try:
        mods = scan_mods_folder(args.mods_folder)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 2
    if not mods:
        print("No mods found.")
        return 0

    print(f"Scanned {len(mods)} mods. Checking against {args.loader} {args.mc}...\n")
    providers = [ModrinthProvider(), CurseForgeProvider(args.cf_key)]
    matches = match_and_resolve(
        mods, providers, loader=args.loader, mc_version=args.mc,
        accept_same_minor=not args.exact,
    )

    matches.sort(key=lambda m: (m.status.value, m.display_name.lower()))
    for m in matches:
        mark = STATUS_MARK.get(m.status.value, "   ")
        latest = f"  ->  {m.latest_version}" if m.has_update else ""
        src = f"[{m.source}]" if m.source else "[unidentified]"
        print(f"  {mark}  {m.display_name:<34} {m.current_version:<22}{latest}  {src}")

    updates = sum(1 for m in matches if m.has_update)
    unknown = sum(1 for m in matches if m.status.value == "unknown")
    print(f"\n{updates} update(s) available - {unknown} unidentified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
