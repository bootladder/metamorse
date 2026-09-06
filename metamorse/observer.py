"""Feedback seam. The OSD implements this; nothing else changes when it lands."""
from __future__ import annotations

from typing import Protocol

from .keymap import Node
from .symbols import Symbol


class Observer(Protocol):
    def on_symbol(self, marks: tuple[Symbol, ...]) -> None: ...
    def on_branch(self, path: str, node: Node) -> None: ...
    def on_dispatch(self, path: str, node: Node) -> None: ...
    def on_stray(self, letter: str, node: Node) -> None: ...
    def on_reset(self, reason: str) -> None: ...


class NullObserver:
    def on_symbol(self, marks: tuple[Symbol, ...]) -> None: pass
    def on_branch(self, path: str, node: Node) -> None: pass
    def on_dispatch(self, path: str, node: Node) -> None: pass
    def on_stray(self, letter: str, node: Node) -> None: pass
    def on_reset(self, reason: str) -> None: pass
