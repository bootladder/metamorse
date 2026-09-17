"""Which shipped defaults belong to this platform.

Keymaps differ because the programs do; settings files differ because key
names are platform vocabulary (`leftmeta` / `lwin` / `rcommand`).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from . import config

PLATFORMS = {"linux": "linux", "win32": "windows", "darwin": "macos"}


@dataclass(frozen=True, slots=True)
class Default:
    """One shipped file and where it installs to."""
    source: str
    target: Path

    @property
    def label(self) -> str:
        return self.target.name


def _platform() -> str:
    name = PLATFORMS.get(sys.platform)
    if name is None:
        raise SystemExit(
            f"no defaults for {sys.platform!r}.\n"
            f"supported: {', '.join(sorted(set(PLATFORMS.values())))}"
        )
    return name


def defaults() -> tuple[Default, ...]:
    """The keymap and the settings file. The settings file ships entirely
    commented out: it exists to write the key names down."""
    name = _platform()
    return (Default(f"keymap-{name}.toml", config.KEYMAP),
            Default(f"metamorse-{name}.toml", config.SETTINGS))
