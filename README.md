# Minecraft Mod Manager

A Prism-Launcher-style GUI for managing Minecraft mods. Scans your `mods/` folder,
matches each JAR to its Modrinth (and optionally CurseForge) project **by file
hash**, shows which mods have updates, and updates them with one click — always
backing up the old JAR first.

Built for any loader and Minecraft version: pick **neoforge / fabric / forge /
quilt** and the MC version right in the toolbar.

## What makes update detection reliable

The previous version sometimes showed "update available" for a mod that was
already up to date. That happened because it compared two version *strings* from
different sources (the JAR's `mods.toml` vs Modrinth's version number), which
rarely share a format.

v2 decides status by **identity, never by parsing version strings**:

1. The JAR's SHA-1 (Modrinth) or Murmur2 fingerprint (CurseForge) is looked up,
   which returns the **exact version of the installed file** — its version id and
   publish date.
2. The latest compatible version for your loader + MC is fetched.
3. Status is decided by comparing **version ids** (same id ⇒ up to date) and
   **publish dates** (newer ⇒ update available). After an update the new file
   re-resolves to the version we just installed, so a fresh rescan and the
   on-screen status can never disagree.

See [app/services/resolver.py](app/services/resolver.py) — it's pure and fully
unit-tested in [tests/test_resolver.py](tests/test_resolver.py).

## Features

- **Auto-identify** installed mods by hash (works even if a JAR was renamed).
- **Selectable loader + MC version** with an "accept same minor line" option
  (e.g. a file tagged `1.21` counts for `1.21.1`).
- **Deterministic update detection** — no false positives.
- **Per-mod version selector** — pick any compatible version from the detail
  panel (incl. downgrades). A manually chosen version is **pinned** and skipped
  by "Update all available" until you unpin it.
- **One-click update** with timestamped backups in `mods/.backup/`.
- **Client-only detection** — flags mods that shouldn't be on a server and
  quarantines them to `mods/.removed/<timestamp>/` (restore any batch later).
- **Dependency check** — missing required deps and incompatibilities.
- **Browse & install** new mods from Modrinth/CurseForge.
- **Filter & sort**; modern dark theme.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

Requires Python 3.11+ (`tomllib` is stdlib). Tested on 3.14.

## Usage

### GUI

```bash
python main.py
```

1. **Choose mods folder…** — point it at your server's `mods/` directory.
2. Pick the **loader** and **MC version**.
3. **Scan && check updates**.
4. Tick mods to update, then **Update selected** (or **Update all available**).

### CLI smoke test

```bash
python cli_check.py /path/to/mods --loader neoforge --mc 1.21.1
python cli_check.py /path/to/mods --cf-key YOUR_KEY      # enable CurseForge
python cli_check.py /path/to/mods --exact                # exact MC version only
```

## Architecture

```
app/
  main.py                  # entry
  models.py                # Status enum, VersionIdentity, LatestVersion, InstalledMod, ModMatch
  config.py                # ~/.mc_mod_manager/config.json
  providers/
    base.py                # Provider protocol + shared helpers (date parse, compat)
    modrinth.py            # SHA-1 lookup, version list, search
    curseforge.py          # Murmur2 fingerprint lookup, files, search
  services/
    scanner.py             # parse descriptors (neoforge/forge/fabric/quilt), hashes
    matcher.py             # orchestrate providers -> ModMatch list
    resolver.py            # the identity-based status engine (pure)
    updater.py             # atomic download/verify/backup/swap/re-resolve
    side_detector.py       # client-only detection
    dependency.py          # dependency checker
    quarantine.py          # move-to-.removed + restore
  ui/
    theme.py               # modern dark theme
    main_window.py         # toolbar + table + detail panel
    mod_table.py           # table model, filter proxy, status-pill delegate
    workers.py             # scan/update QThreads
    dialogs/               # search, settings, client-only, restore
cli_check.py
tests/                     # pytest — resolver matrix, scanner, matcher, updater, detection
```

## Tests

```bash
python -m pytest -q
```

The critical logic (the status decision) is covered exhaustively and runs with no
network access.

## CurseForge API key (optional)

Some mods aren't on Modrinth. To enable the fallback, get a free key at
<https://console.curseforge.com/>, then **Settings… → CurseForge API key**.
Without a key the app is fully functional on Modrinth alone.

## Notes

- No SFTP/SSH transport — assumes the mods folder is on this machine.
- The app never touches your server process; restart it yourself after updating.

## License

MIT.
