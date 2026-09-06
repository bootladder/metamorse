"""Edges to symbols. Pure: no I/O, no clock of its own."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Iterator

from .symbols import Edge, Symbol, Timing


@dataclass(frozen=True, slots=True)
class Demod:
    """Immutable demodulator state. Each step returns (state, symbols).

    Timestamps must all come from one clock. The evdev source uses
    `event.timestamp()` (CLOCK_REALTIME), so idle ticks must pass
    `time.time()` -- never `time.monotonic()`.
    """
    timing: Timing = Timing()
    since: float | None = None      # timestamp of the last transition
    down: bool = False
    gap: Symbol | None = None       # strongest gap already reported for `since`

    def step(self, edge: Edge) -> tuple[Demod, tuple[Symbol, ...]]:
        if edge.down == self.down:
            return self, ()
        elapsed = 0.0 if self.since is None else edge.t - self.since
        state = replace(self, since=edge.t, down=edge.down, gap=None)
        if not edge.down:
            return state, (self.timing.mark(elapsed),)
        if self.since is None:
            return state, ()
        gap = self.timing.space(elapsed)
        return state, (gap,) if gap and gap is not self.gap else ()

    def tick(self, now: float) -> tuple[Demod, tuple[Symbol, ...]]:
        """Resolve a trailing gap once silence has run long enough. Reports
        each gap once, but still escalates CHAR_GAP -> WORD_GAP as idle grows.
        `since` is retained so the next gap is measured from the same edge."""
        if self.down or self.since is None:
            return self, ()
        gap = self.timing.space(now - self.since)
        if gap is None or gap is self.gap:
            return self, ()
        return replace(self, gap=gap), (gap,)


def run(edges: Iterable[Edge], timing: Timing = Timing()) -> Iterator[Symbol]:
    """Fold a finite edge stream into symbols. For tests and replay."""
    state = Demod(timing)
    for edge in edges:
        state, out = state.step(edge)
        yield from out
