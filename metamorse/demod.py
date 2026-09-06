"""Edges to symbols. Pure: no I/O, no clock of its own."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Iterator

from .symbols import Edge, Symbol, Timing


@dataclass(frozen=True, slots=True)
class Demod:
    """Immutable demodulator state. Each step returns (state, symbols)."""
    timing: Timing = Timing()
    since: float | None = None      # timestamp of the last transition
    down: bool = False

    def step(self, edge: Edge) -> tuple[Demod, tuple[Symbol, ...]]:
        if edge.down == self.down:
            return self, ()
        elapsed = 0.0 if self.since is None else edge.t - self.since
        state = replace(self, since=edge.t, down=edge.down)
        if edge.down:
            gap = self.timing.space(elapsed) if self.since is not None else None
            return state, (gap,) if gap else ()
        return state, (self.timing.mark(elapsed),)

    def tick(self, now: float) -> tuple[Demod, tuple[Symbol, ...]]:
        """Resolve a trailing gap once silence has run long enough."""
        if self.down or self.since is None:
            return self, ()
        gap = self.timing.space(now - self.since)
        return (replace(self, since=None), (gap,)) if gap else (self, ())


def run(edges: Iterable[Edge], timing: Timing = Timing()) -> Iterator[Symbol]:
    """Fold a finite edge stream into symbols. For tests and replay."""
    state = Demod(timing)
    for edge in edges:
        state, out = state.step(edge)
        yield from out
