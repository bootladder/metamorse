"""Action execution. The only module that runs foreign code."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable

from .keymap import Action


@dataclass(frozen=True, slots=True)
class Dispatcher:
    """Runs resolved actions. `spawn` and `synth` are injected so tests and
    `tap` mode can observe without side effects."""
    spawn: Callable[[str], None]
    synth: Callable[[str], None]

    def __call__(self, action: Action) -> None:
        if action.kind == "sh":
            self.spawn(action.arg)
        elif action.kind == "key":
            self.synth(action.arg)


def shell(command: str) -> None:
    """Detached so a slow command never stalls the event loop."""
    subprocess.Popen(command, shell=True, start_new_session=True,
                     stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def parse_chord(chord: str) -> tuple[list[str], str]:
    """'ctrl+shift+t' -> (['ctrl','shift'], 't')."""
    *mods, key = [part.strip().lower() for part in chord.split("+") if part.strip()]
    if not key:
        raise ValueError(f"empty chord: {chord!r}")
    return mods, key
