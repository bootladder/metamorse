"""Passthrough policy: when the physical Meta reaches the rest of X11.

Meta-down is emitted on the first mark of a letter so chords stay zero-latency;
later marks are covered by that still-unreleased modifier. Meta-up is withheld
until the letter resolves, since a held modifier is inert while a released one
may trigger menu/overlay bindings.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, auto


class Emit(Enum):
    DOWN = auto()
    UP = auto()


@dataclass(frozen=True, slots=True)
class Passthrough:
    """`immediate` releases Meta-up as it happens, for WMs with overlay keys."""
    immediate: bool = False
    held: bool = False
    owed: bool = False              # downstream believes Meta is still down

    def on_edge(self, down: bool) -> tuple[Passthrough, tuple[Emit, ...]]:
        if down == self.held:
            return self, ()
        if down:
            state = replace(self, held=True, owed=True)
            return state, () if self.owed else (Emit.DOWN,)
        if self.immediate:
            return replace(self, held=False, owed=False), (Emit.UP,)
        return replace(self, held=False), ()

    def on_resolve(self) -> tuple[Passthrough, tuple[Emit, ...]]:
        """A letter resolved. The outstanding Meta-up is always released --
        stranding a held modifier would wedge every later keystroke. Dispatch
        having already fired is what stops it reading as a bare tap."""
        if not self.owed or self.held:
            return self, ()
        return replace(self, owed=False), (Emit.UP,)
