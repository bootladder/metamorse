"""Morse primitives and the timing that classifies them."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Symbol(Enum):
    """A resolved Morse element or the silence that terminates one."""
    DIT = "."
    DAH = "-"
    CHAR_GAP = " "
    WORD_GAP = "/"


@dataclass(frozen=True, slots=True)
class Edge:
    """A key transition. `down` is the new state; `t` is monotonic seconds."""
    down: bool
    t: float


@dataclass(frozen=True, slots=True)
class Timing:
    """Morse durations derived from one unit. Dit=1u, dah=3u, gaps 1/3/7u."""
    unit: float = 0.09

    @property
    def dah_min(self) -> float:
        return 2 * self.unit          # midpoint of dit(1u) and dah(3u)

    @property
    def char_gap_min(self) -> float:
        return 2 * self.unit

    @property
    def word_gap_min(self) -> float:
        return 5 * self.unit          # midpoint of char(3u) and word(7u)

    def mark(self, held: float) -> Symbol:
        return Symbol.DAH if held >= self.dah_min else Symbol.DIT

    def space(self, idle: float) -> Symbol | None:
        if idle >= self.word_gap_min:
            return Symbol.WORD_GAP
        return Symbol.CHAR_GAP if idle >= self.char_gap_min else None
