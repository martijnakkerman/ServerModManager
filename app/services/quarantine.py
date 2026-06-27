"""Quarantine + restore of removed (client-only) mods.

Nothing is ever deleted. Removed JARs are moved to ``mods/.removed/<timestamp>/``
as a batch, and any batch can be restored with one call.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

REMOVED_DIRNAME = ".removed"


@dataclass
class RemovedBatch:
    path: Path
    timestamp: str
    jars: list[Path]


def quarantine(jar_paths: list[Path], mods_dir: Path) -> Path:
    """Move the given JARs into a fresh timestamped batch under ``.removed/``."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    batch = mods_dir / REMOVED_DIRNAME / ts
    batch.mkdir(parents=True, exist_ok=True)
    for jar in jar_paths:
        if jar.is_file():
            shutil.move(str(jar), str(batch / jar.name))
            log.info("Quarantined %s", jar.name)
    return batch


def list_batches(mods_dir: Path) -> list[RemovedBatch]:
    root = mods_dir / REMOVED_DIRNAME
    if not root.is_dir():
        return []
    batches = []
    for d in sorted(root.iterdir(), reverse=True):
        if d.is_dir():
            batches.append(
                RemovedBatch(path=d, timestamp=d.name, jars=sorted(d.glob("*.jar")))
            )
    return batches


def restore_batch(batch: RemovedBatch, mods_dir: Path) -> list[Path]:
    """Move a batch's JARs back into the mods folder. Removes the empty batch dir."""
    restored = []
    for jar in batch.jars:
        dest = mods_dir / jar.name
        shutil.move(str(jar), str(dest))
        restored.append(dest)
        log.info("Restored %s", jar.name)
    try:
        batch.path.rmdir()
    except OSError:
        pass
    return restored
