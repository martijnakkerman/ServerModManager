# MC Mod Manager v2 — Design

Date: 2026-06-27

## Problem

The existing app's version matching is inconsistent: mods that have just been
updated still show "update available". Root cause: `has_update` compares two
strings from different sources — the JAR's `mods.toml` `version` vs Modrinth's
`version_number` — using fragile normalization. The reliable signal (the exact
Modrinth version object returned by the hash lookup) is discarded.

## Goal

Full rewrite. Correct, deterministic version matching driven by hash/ID
identity, not string parsing. Modrinth primary, CurseForge fallback. Selectable
loader and Minecraft version. PyQt6 UI with a modern dark theme.

## The version-matching engine (core fix)

Each installed JAR resolves to a **version identity** via its provider, using the
hash the provider already indexes:

- **Modrinth:** SHA-1 -> exact version object -> `{version_id, date_published, version_number}`
- **CurseForge:** Murmur2 fingerprint -> exact file object -> `{file_id, file_date}`

Fetch the **latest compatible** version for `(loader, mc_version)`, then decide
status deterministically:

| Condition | Status |
|---|---|
| No hash/fingerprint match | `UNKNOWN` |
| installed `version_id` == latest `version_id` | `UP_TO_DATE` |
| latest `date_published` > installed `date_published` | `UPDATE_AVAILABLE` |
| installed newer than newest compatible | `UP_TO_DATE` (ahead) |
| project known, installed version not indexed | compare installed SHA-1 to latest file hashes -> equal = `UP_TO_DATE`, else `CHECK` (amber) |

No version-string parsing anywhere. Identity by ID; ordering by publish date.

## After-update verification

`update_mod` does not fake `version = latest_version`. After the swap it
re-resolves the new JAR through the same engine (recompute hash -> re-lookup), so
the displayed status and a fresh rescan can never disagree.

## Architecture

```
app/
  main.py                  # entry
  models.py                # InstalledMod, VersionIdentity, ModMatch, Status enum
  config.py                # settings (path, loader, mc_version, cf key, backups)
  providers/
    base.py                # Provider protocol: match_hashes/latest_version/download
    modrinth.py
    curseforge.py
  services/
    scanner.py             # scan jars, parse toml, hashes
    resolver.py            # THE engine: identity + latest + status decision
    updater.py             # download/backup/swap/re-resolve
    side_detector.py
    dependency.py
  ui/
    theme.qss / theme.py   # modern dark theme
    main_window.py
    mod_table.py           # table model + status-pill delegate
    workers.py
    dialogs/ (search, settings, client_only, restore)
cli_check.py
tests/
```

A `Provider` protocol makes Modrinth and CurseForge interchangeable; the resolver
is provider-agnostic. Loader + MC version flow from config/UI into every query.

## UI

- Toolbar: folder picker, loader dropdown, MC-version dropdown, Scan, Update
  selected, Update all.
- Mod table: colored status pill, current -> latest version, source icon,
  filter box, sortable columns.
- Detail panel: description, latest changelog, dependencies, side info.
- Dialogs: Search & install, Settings, Client-only review, Restore backup.
- App-wide modern dark QSS theme.

## Version compatibility ("exact + compatible")

Query latest by the exact MC version facet (matches any file listing that
version). Plus an opt-in "accept same minor line" toggle (default on) so a file
tagged only `1.21` is not a false "no update" when on `1.21.1`.

## Error handling & testing

- Per-mod graceful degradation; one mod failing never aborts a scan.
- Modrinth client sends User-Agent and backs off on HTTP 429.
- Atomic updates: temp file -> verify zip -> backup -> swap; failure leaves the
  old JAR untouched.
- pytest unit tests for the resolver status decision (mocked providers), scanner
  TOML parsing, murmur2, and version-identity comparison. Resolver is pure and
  network-free, so fully unit-testable.
