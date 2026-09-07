"""Keying with a guitar instead of a finger.

Optional: needs numpy and sounddevice. Nothing in the core imports this, and
`metamorse run` never touches it.

Settings live in their own file rather than under an [audio] block in the
daemon's. Owning the whole file is what lets `tune` rewrite it wholesale --
patching one float inside a file belonging to something else was the only
reason a hand-rolled TOML writer ever existed here.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from ...config import CONFIG_DIR
from ...core import Timing
from .. import Input, register

SETTINGS = CONFIG_DIR / "tone.toml"

DEFAULTS = {"device": "", "samplerate": 44100, "threshold": 0.0,
            "unit": 0.12, "hangover": 0.040}


@dataclass(frozen=True, slots=True)
class Tone:
    """`unit` is separate from the key `unit` because a plucked string is a
    coarser instrument than a finger: comfortable Morse on a guitar runs
    slower than on a key.

    `threshold` is 0.0 until `metamorse tune` measures it -- it depends on the
    guitar, the mic and the gain, so there is no useful default.
    """
    device: str = ""
    samplerate: int = DEFAULTS["samplerate"]
    threshold: float = 0.0
    unit: float = DEFAULTS["unit"]
    hangover: float = DEFAULTS["hangover"]

    @property
    def name(self) -> str | None:
        return self.device or None

    def timing(self, hold: float) -> Timing:
        """Morse timing for tone, borrowing `hold` from the daemon: how long a
        half-typed sequence waits is a UI decision, not an input one."""
        return Timing(self.unit, hold)

    @classmethod
    def load(cls, path: Path = SETTINGS) -> Tone:
        raw = tomllib.loads(path.read_text()) if path.exists() else {}
        merged = {**DEFAULTS, **raw}
        return cls(str(merged["device"]), int(merged["samplerate"]),
                   float(merged["threshold"]), float(merged["unit"]),
                   float(merged["hangover"]))

    def save(self, path: Path = SETTINGS) -> None:
        """Rewrite the file whole. Every key here is ours, so there is nothing
        to preserve and no parser to round-trip."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# metamorse tone input. Written by `metamorse tune`.\n"
            f'device = "{self.device}"\n'
            f"samplerate = {self.samplerate}\n"
            f"threshold = {self.threshold:.6g}\n"
            f"unit = {self.unit}\n"
            f"hangover = {self.hangover}\n")


def open_input(settings) -> Input:
    """Audio in, same sink out: a tone resolves to a letter and dispatches
    exactly as a keyed one does, and chord actions still need a real Meta to
    press, so the uinput sink is unchanged."""
    from ..key import TICK, open_sink, require_evdev, resolve_key
    from .capture import Clock, edges, find_input, open_stream, require_audio
    from .detect import Detector, Gate, Harmonicity

    tone = Tone.load()
    if tone.threshold <= 0.0:
        raise SystemExit("audio threshold is not calibrated.\n"
                         "Run `metamorse tune` first (it plays nothing; you play).")
    sd = require_audio()
    evdev = require_evdev()
    key = resolve_key(evdev, settings.key)
    sink = open_sink(evdev)
    stream = open_stream(sd, find_input(sd, tone.name), tone.samplerate)
    detector = Detector(tone.samplerate, Harmonicity(),
                        Gate(tone.threshold, hangover=tone.hangover))
    clock = Clock()
    timing = tone.timing(settings.timing.hold)
    return Input(edges(stream, detector, TICK, clock), sink, key, clock, timing,
                 f"metamorse: listening, unit={timing.unit*1000:.0f}ms, "
                 f"threshold={tone.threshold:.4g}")


register("tone", open_input)
