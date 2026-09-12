"""Naming and rendering what the detector heard. Pure: formatting only.

Kept apart from `detect` because none of it is detection: a note's name has no
bearing on whether the gate opens, and the meter is a human affordance that the
keying path never consults. `detect` decides; this describes.
"""
from __future__ import annotations

from .detect import Note

# Equal temperament, A4 = 440Hz. The guitar's low E is 82.4Hz, so nothing here
# needs to reach below E2 -- but the formula is general and costs nothing.
A4 = 440.0
A4_MIDI = 69
NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

BAR_WIDTH = 20


def midi(f0: float) -> float:
    """Fractional MIDI number for a frequency. Fractional on purpose: the
    distance to the nearest whole number is how far out of tune the note is."""
    from math import log2
    return A4_MIDI + 12 * log2(f0 / A4)


def name(f0: float) -> str:
    """Nearest note name with octave, e.g. 110Hz -> 'A2'. Empty for silence."""
    if f0 <= 0.0:
        return ""
    nearest = round(midi(f0))
    return f"{NAMES[nearest % 12]}{nearest // 12 - 1}"


def cents(f0: float) -> int:
    """Signed distance to the nearest named note, in cents. Tells the player
    whether the string is in tune or whether the detector is reading a partial
    rather than the fundamental."""
    if f0 <= 0.0:
        return 0
    value = midi(f0)
    return round(100 * (value - round(value)))


def bar(power: float, threshold: float, width: int = BAR_WIDTH) -> str:
    """Power drawn against the gate threshold, which sits at mid-scale. A note
    that keys reliably fills past the halfway mark; one that hovers at it is
    the reason a dit sometimes goes missing."""
    if threshold <= 0.0:
        return ""
    filled = min(width, round(width * power / (2 * threshold)))
    middle = width // 2
    cells = ["█" if i < filled else "░" for i in range(width)]
    if filled != middle and middle < width:
        cells[middle] = "┃" if filled <= middle else "█"
    return "".join(cells)


def meter(t: float, note: Note, threshold: float, down: bool) -> str:
    """One line of the `listen --notes` display.

    Silence still prints, because a gap that should have closed the gate and
    did not is exactly the fault worth seeing.
    """
    state = "●" if down else "·"
    if not note.sounding:
        return f"  {t:6.2f}s  {state}  {'—':>9}      {'':>4}  {0.0:8.0f}"
    tuning = f"{cents(note.f0):+d}¢"
    return (f"  {t:6.2f}s  {state}  {note.f0:7.1f}Hz  {name(note.f0):>4} "
            f"{tuning:>5}  {note.power:8.0f}  {bar(note.power, threshold)}")


HEADER = ("    time   on        f0  note  cents     power\n"
          "  " + "-" * 56)
