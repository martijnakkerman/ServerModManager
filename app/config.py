"""User settings, persisted to ``~/.mc_mod_manager/config.json``."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".mc_mod_manager"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Offered in the UI dropdowns.
LOADERS = ["neoforge", "fabric", "forge", "quilt"]
COMMON_MC_VERSIONS = [
    "1.21.4", "1.21.3", "1.21.1", "1.21",
    "1.20.6", "1.20.4", "1.20.1", "1.19.2",
]


@dataclass
class Config:
    server_mods_path: str = ""
    loader: str = "neoforge"
    mc_version: str = "1.21.1"
    curseforge_api_key: str = ""
    accept_same_minor: bool = True
    keep_backups: int = 10
    # Pinned versions: project_id -> version_id (locked, skipped by bulk updates).
    pins: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


def load_config() -> Config:
    if not CONFIG_PATH.is_file():
        return Config()
    try:
        data = json.loads(CONFIG_PATH.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Could not read config (%s); using defaults", e)
        return Config()
    cfg = Config()
    for k, v in data.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    return cfg


def save_config(cfg: Config) -> None:
    CONFIG_DIR.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(cfg), indent=2), "utf-8")
