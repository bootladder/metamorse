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

DEFAULTS = {"key": None, "unit": 0.09, "hold": 10.0, "immediate": False,
            "input": "key"}


@dataclass(frozen=True, slots=True)
class Settings:
    """`key` is None until the user names one. Key names are platform
    vocabulary -- evdev's `leftmeta` means nothing to Windows -- so the
    default belongs to the backend that resolves it, not here."""
    key: str | None = DEFAULTS["key"]
    timing: Timing = Timing()
    immediate: bool = False
    input: str = DEFAULTS["input"]

    @classmethod
    def load(cls, path: Path = SETTINGS) -> Settings:
        raw = tomllib.loads(path.read_text()) if path.exists() else {}
        merged = {**DEFAULTS, **raw}
        return cls(None if merged["key"] is None else str(merged["key"]),
                   Timing(float(merged["unit"]), float(merged["hold"])),
                   bool(merged["immediate"]),
                   str(merged["input"]))
