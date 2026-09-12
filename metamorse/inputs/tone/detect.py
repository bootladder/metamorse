"""Audio blocks to key edges. Pure: no I/O, no clock of its own.

The question this module answers is not "which note is playing" but "is a
string sounding at all" -- any guitar note keys the same as any other. That
makes it a two-part decision, and the two parts are kept apart on purpose:

  Harmonicity  is this pitched, and in guitar range?   (spectral, stateless)
  Gate         is the note on right now?                (temporal, stateful)

Splitting them matters because a plucked string decays. Harmonicity says
"yes, a string" for as long as the ring is above the floor; Gate decides when
that ring has faded far enough to call the mark over. Only Gate carries state,
and it never learns what an FFT is -- it sees a bool and a timestamp, so the
same hysteresis serves any on/off source.

Timestamps come from the caller's sample clock. See `listen.py`: a block
boundary at sample N is the exact instant N/samplerate, which is immune to
scheduler jitter in a way `time.time()` is not.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable

import numpy as np

from ...core.symbols import Edge

# A 6-string guitar in standard tuning: low E fundamental is 82.4 Hz, and the
# high E at the 12th fret reaches ~1319 Hz. The window is opened slightly at
# both ends for down-tuning and for capos, but no further -- its whole value
# is rejecting what falls outside it (mains hum below, sibilance above).
F0_MIN = 75.0
F0_MAX = 1400.0

HARMONICS = (2, 3)      # partials that must accompany f0 for "pitched"

# Frequency resolution and timing precision pull in opposite directions, so
# the analysis window is decoupled from the rate it advances. At 44.1kHz a
# 4096-sample window resolves 10.8Hz -- enough to separate semitones down at
# low E, where a coarser window smears the whole low register into two bins.
# That window spans 93ms, which is longer than a 90ms dit, so waiting for a
# fresh one each time would quantise every edge into uselessness. Advancing
# 512 samples at a time instead puts an edge within 11.6ms of the truth while
# still analysing 4096 samples of context.
WINDOW = 4096
HOP = 512

# Mains hum is pitched and its partials reach into the guitar window, so no
# in-window test can exclude it -- and a notch cannot either, because a 100Hz
# partial leaks into the bins on both sides of 100Hz and a notch wide enough
# to catch that leakage is also wide enough to swallow a semitone.
#
# What separates them is where the fundamental lies. Hum is rooted below the
# guitar's range and reaches up; a real low E is rooted at 82Hz with little
# below it. So the test is comparative: if the sub-range holds more energy
# than the peak we found inside the range, we are looking at the harmonics of
# something we do not want.
SUBSONIC_RATIO = 0.8    # sub-range energy this close to the peak means hum


@dataclass(frozen=True, slots=True)
class Spectrum:
    """One block's magnitude spectrum. Knows FFT; knows no Morse."""
    mag: np.ndarray
    freqs: np.ndarray

    @classmethod
    def of(cls, block: np.ndarray, samplerate: int) -> Spectrum:
        """Hann-windowed rFFT. The window suppresses the spectral leakage that
        would otherwise smear a strong fundamental across neighbouring bins and
        fake the harmonics we are about to go looking for."""
        windowed = block * np.hanning(len(block))
        return cls(np.abs(np.fft.rfft(windowed)),
                   np.fft.rfftfreq(len(block), 1 / samplerate))

    def peak(self, lo: float, hi: float) -> tuple[float, float]:
        """(frequency, magnitude) of the strongest bin within [lo, hi]."""
        band = (self.freqs >= lo) & (self.freqs <= hi)
        if not band.any():
            return 0.0, 0.0
        index = np.argmax(np.where(band, self.mag, 0.0))
        return float(self.freqs[index]), float(self.mag[index])

    def below(self, freq: float) -> float:
        """Strongest magnitude beneath `freq`, ignoring the DC bin."""
        band = (self.freqs > 0) & (self.freqs < freq)
        return float(np.where(band, self.mag, 0.0).max()) if band.any() else 0.0

    def at(self, freq: float) -> float:
        """Magnitude near `freq`, taking the best of the closest three bins.
        A partial is never exactly on a bin centre, and a slightly sharp or
        flat string would otherwise read as a missing harmonic."""
        if freq > self.freqs[-1]:
            return 0.0
        index = int(np.argmin(np.abs(self.freqs - freq)))
        lo, hi = max(0, index - 1), min(len(self.mag), index + 2)
        return float(self.mag[lo:hi].max())

    @property
    def noise(self) -> float:
        """Median magnitude -- a robust floor. The median is chosen over the
        mean because a handful of loud harmonic bins must not raise the very
        floor they are being measured against."""
        return float(np.median(self.mag)) or 1e-12


@dataclass(frozen=True, slots=True)
class Note:
    """What one block sounded like: a pitch, its strength, its partials.

    Exists so the detector can report *what* it heard, not merely how loud it
    was. `Gate` still sees only `power`, so the hysteresis stays ignorant of
    frequency; the extra fields serve the meter and the pitch-stability test.

    A silent or rejected block is `Note.silent()`: f0 of zero, power of zero.
    Callers distinguish the two cases with `sounding`, never by comparing
    floats.
    """
    f0: float = 0.0
    power: float = 0.0
    partials: int = 0

    @classmethod
    def silent(cls) -> Note:
        return cls()

    @property
    def sounding(self) -> bool:
        return self.power > 0.0


@dataclass(frozen=True, slots=True)
class Harmonicity:
    """Is this block a pitched string in guitar range? Stateless predicate.

    A guitar string puts energy at f0, 2f0, 3f0...; speech, handclaps and room
    noise do not, in that specific way. Requiring the partials is what keeps a
    cough from dispatching a shell command.
    """
    f0_min: float = F0_MIN
    f0_max: float = F0_MAX
    snr: float = 6.0            # peak must beat the noise floor by this factor
    partial: float = 0.10       # partial counts if >= this fraction of f0

    def hear(self, spectrum: Spectrum) -> Note:
        """The Note this block holds, or `Note.silent()` if none does.

        Reporting strength rather than a bool is what lets Gate apply
        hysteresis; reporting f0 alongside it is what lets the meter show the
        player which string the detector thinks it heard.
        """
        f0, mag = spectrum.peak(self.f0_min, self.f0_max)
        if not f0 or mag < self.snr * spectrum.noise:
            return Note.silent()
        if spectrum.below(self.f0_min) >= SUBSONIC_RATIO * mag:
            return Note.silent()        # rooted below the guitar: hum, rumble
        floor = self.partial * mag
        present = sum(spectrum.at(f0 * n) >= floor for n in HARMONICS)
        return Note(f0, mag, present) if present else Note.silent()


@dataclass(frozen=True, slots=True)
class Gate:
    """Hysteresis plus hangover over a decaying signal. Immutable.

    Two thresholds, not one: a note must be plucked hard to open the gate but
    may fade much further before it closes. A single threshold sits exactly
    where a decaying string crosses it, so the gate chatters and one dah
    arrives as a string of dits.

    `hangover` then requires the signal to stay low for a stretch before the
    mark is called over, which covers the amplitude dip between two strums of
    the same sustained note.
    """
    on: float = 0.0             # 0.0 until calibrated; see `calibrate`
    off_ratio: float = 0.25     # close at a quarter of the opening threshold
    hangover: float = 0.040     # seconds of quiet before releasing
    down: bool = False
    quiet_since: float | None = None    # when the signal first fell below off

    @property
    def off(self) -> float:
        return self.on * self.off_ratio

    def step(self, power: float, t: float) -> tuple[Gate, Edge | None]:
        """Fold one block's strength in. Returns a successor and an Edge only
        on a transition, matching Demod.step's shape."""
        if not self.down:
            if power < self.on:
                return self, None
            return replace(self, down=True, quiet_since=None), Edge(True, t)
        if power >= self.off:
            return (self, None) if self.quiet_since is None else (
                replace(self, quiet_since=None), None)
        if self.quiet_since is None:
            return replace(self, quiet_since=t), None
        if t - self.quiet_since < self.hangover:
            return self, None
        # The mark ended when the signal fell, not when the hangover expired;
        # dating the edge to `quiet_since` keeps dit/dah lengths honest.
        return replace(self, down=False, quiet_since=None), Edge(False, self.quiet_since)


@dataclass(frozen=True, slots=True)
class Window:
    """The last WINDOW samples, advanced HOP at a time.

    Holds the analysis window steady while letting the detector run at the hop
    rate, which is what buys frequency resolution without paying for it in
    edge timing.
    """
    samples: np.ndarray

    @classmethod
    def empty(cls, size: int = WINDOW) -> Window:
        return cls(np.zeros(size, dtype=np.float32))

    def push(self, hop: np.ndarray) -> Window:
        return Window(np.concatenate((self.samples[len(hop):], hop)))


@dataclass(frozen=True, slots=True)
class Detector:
    """Window -> Spectrum -> Harmonicity -> Gate. Immutable; <=1 Edge out.

    Fed one HOP of samples at a time; `t` is the timestamp of the *end* of
    that hop, since that is the instant the newest evidence describes.
    """
    samplerate: int
    harmonicity: Harmonicity = Harmonicity()
    gate: Gate = Gate()
    window: Window = field(default_factory=Window.empty)

    def step(self, hop: np.ndarray, t: float) -> tuple[Detector, Edge | None, Note]:
        """Advance one hop. The Note is returned whether or not it moved the
        gate, because the meter reports every block while edges are rare."""
        window = self.window.push(hop)
        note = self._hear(window)
        gate, edge = self.gate.step(note.power, t)
        return replace(self, window=window, gate=gate), edge, note

    def observe(self, hop: np.ndarray) -> tuple[Detector, Note]:
        """Advance the window and report what was heard, without gating. For
        `tune`, which measures thresholds rather than keying on them."""
        window = self.window.push(hop)
        return replace(self, window=window), self._hear(window)

    def _hear(self, window: Window) -> Note:
        return self.harmonicity.hear(Spectrum.of(window.samples, self.samplerate))

    def tuned(self, on: float) -> Detector:
        return replace(self, gate=replace(self.gate, on=on))


def calibrate(powers: Iterable[float], fraction: float = 0.35) -> float:
    """Pick a gate threshold from the strengths measured while the user plays.

    A fraction of the median *sounding* block, not of the loudest: one
    hard pluck must not raise the bar above every normal note. Blocks that
    Harmonicity already rejected are dropped, so silence between notes does
    not drag the estimate down.
    """
    sounding = [p for p in powers if p > 0.0]
    if not sounding:
        return 0.0
    return fraction * float(np.median(sounding))
