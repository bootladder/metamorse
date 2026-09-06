"""Passthrough policy: when the physical Meta reaches the rest of X11.

Meta-down is emitted immediately so chords stay zero-latency. Meta-up is
withheld until the letter resolves, since a held modifier is inert while a
released one may trigger menu/overlay bindings.
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
    owed: bool = False              # an up is pending, awaiting resolution

    def on_edge(self, down: bool) -> tuple[Passthrough, tuple[Emit, ...]]:
        if down == self.held:
            return self, ()
        if down:
            return replace(self, held=True), (Emit.DOWN,)
        if self.immediate:
            return replace(self, held=False), (Emit.UP,)
        return replace(self, held=False, owed=True), ()

    def on_resolve(self, consumed: bool) -> tuple[Passthrough, tuple[Emit, ...]]:
        """A letter resolved. `consumed` means metamorse acted on it, so the
        pending Meta-up is dropped rather than replayed."""
        if not self.owed:
            return self, ()
        state = replace(self, owed=False)
        return (state, ()) if consumed else (state, (Emit.UP,))
