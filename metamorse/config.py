"""Where things live, and how the daemon is configured."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .core.symbols import Timing

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_DIR = CONFIG_HOME / "metamorse"
KEYMAP = CONFIG_DIR / "keymap.toml"
SETTINGS = CONFIG_DIR / "metamorse.toml"

DEFAULTS = {"key": "leftmeta", "unit": 0.09, "hold": 10.0, "immediate": False,
            "input": "key"}


@dataclass(frozen=True, slots=True)
class Settings:
    key: str = DEFAULTS["key"]
    timing: Timing = Timing()
    immediate: bool = False
    input: str = DEFAULTS["input"]

    @classmethod
    def load(cls, path: Path = SETTINGS) -> Settings:
        raw = tomllib.loads(path.read_text()) if path.exists() else {}
        merged = {**DEFAULTS, **raw}
        return cls(str(merged["key"]),
                   Timing(float(merged["unit"]), float(merged["hold"])),
                   bool(merged["immediate"]),
                   str(merged["input"]))
