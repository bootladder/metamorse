"""Observer that drives the OSD subprocess.

Spawned lazily -- no popup process exists until a branch is entered, so the
idle daemon costs nothing.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field

from ..core.keymap import Branch, Node
from .render import rows

OSD_FLAG = "--osd"
"""Argv marker that runs the OSD instead of the CLI.

A frozen build has no interpreter to hand `-m metamorse.ui.osd` to:
sys.executable is metamorse.exe itself, which ignores -m. So the exe
re-invokes itself with this flag and `cli.main` routes on it before argparse
ever runs. Unfrozen, the old `-m` spawn is still the honest thing to do.
"""


def _osd_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, OSD_FLAG]
    return [sys.executable, "-m", "metamorse.ui.osd"]


@dataclass
class PopupObserver:
    """Shows the branch you just entered; hides on dispatch or reset."""
    root: Branch
    process: subprocess.Popen | None = field(default=None, init=False)
    path: str = field(default="", init=False)
    branch: Branch | None = field(default=None, init=False)

    def _send(self, message: dict) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, ValueError):
            self.process = None

    def start(self) -> None:
        """Spawn the popup process up front and leave it hidden. Paying
        interpreter startup once at boot keeps the first menu as fast as the
        hundredth."""
        if self.process is not None and self.process.poll() is None:
            return
        self.process = subprocess.Popen(
            _osd_command(), stdin=subprocess.PIPE, text=True)

    def _open(self) -> None:
        self.start()                     # no-op once running

    def _show(self, branch: Branch, path: str, keyed: str = "",
              stray: str = "") -> None:
        self._open()
        self.path, self.branch = path, branch
        self._send({"path": path, "keyed": keyed, "stray": stray,
                    "rows": [[r.letter, r.code, r.label, r.is_branch]
                             for r in rows(branch)]})

    def close(self) -> None:
        self._send({"hide": True})       # hide, never destroy
        self.path, self.branch = "", None

    def stop(self) -> None:
        self._send({"close": True})

    # Observer protocol ---------------------------------------------------
    def on_symbol(self, marks) -> None:
        """Live feedback: highlight rows still reachable from what is keyed."""
        if self.branch is None:
            return
        self._show(self.branch, self.path,
                   "".join(symbol.value for symbol in marks))

    def on_branch(self, path: str, node: Node) -> None:
        self._show(node, f"{self.path} {path}".strip())

    def on_dispatch(self, path: str, node: Node) -> None:
        self.close()

    def on_stray(self, letter: str, node: Node) -> None:
        """Wrong letter for this menu. Redraw it, say so, stay open."""
        if self.branch is None:
            return
        self._show(self.branch, self.path, stray=letter)

    def on_reset(self, reason: str) -> None:
        self.close()
