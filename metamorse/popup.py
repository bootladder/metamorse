"""Observer that drives the OSD subprocess.

Spawned lazily -- no popup process exists until a branch is entered, so the
idle daemon costs nothing.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field

from .keymap import Branch, Node
from .render import rows


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

    def _open(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self.process = subprocess.Popen(
            [sys.executable, "-m", "metamorse.osd"],
            stdin=subprocess.PIPE, text=True)

    def _show(self, branch: Branch, path: str, keyed: str = "") -> None:
        self._open()
        self.path, self.branch = path, branch
        self._send({"path": path, "keyed": keyed,
                    "rows": [[r.letter, r.code, r.label, r.is_branch]
                             for r in rows(branch)]})

    def close(self) -> None:
        self._send({"close": True})
        self.path, self.branch = "", None

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

    def on_reset(self, reason: str) -> None:
        self.close()
