"""Action execution. The only module that runs foreign code."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

from .keymap import Action

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


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


def _detach() -> dict:
    """How to outlive the daemon, in this platform's terms.

    POSIX detaches by leaving the session; Windows has no sessions and takes
    creation flags instead. `start_new_session` is accepted and silently
    ignored there -- the spawned program would stay tied to our console and
    die with it -- so the flags are not cosmetic.
    """
    if sys.platform == "win32":
        return {"creationflags": DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def shell(command: str) -> None:
    """Detached so a slow command never stalls the event loop."""
    subprocess.Popen(command, shell=True,
                     stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     **_detach())


def parse_chord(chord: str) -> tuple[list[str], str]:
    """'ctrl+shift+t' -> (['ctrl','shift'], 't')."""
    *mods, key = [part.strip().lower() for part in chord.split("+") if part.strip()]
    if not key:
        raise ValueError(f"empty chord: {chord!r}")
    return mods, key
