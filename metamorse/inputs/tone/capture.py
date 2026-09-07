"""The impure audio edge: sounddevice capture on a sample clock.

sounddevice and numpy are imported lazily so the pure core, `doctor` and the
key-driven daemon all work without them installed.

TIMEBASE -- the one thing not to get wrong here. Demod requires that edges and
idle ticks share a clock, and audio offers a better one than the wall: the Nth
sample captured is exactly N/samplerate seconds into the stream, with no
scheduler jitter. `listen` therefore times everything off the sample count and
never calls time.time(). Mixing the two would resurrect the bug that
"one clock for edges and ticks" fixed for the evdev path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from ...core.symbols import Edge
from .detect import HOP, WINDOW, Detector, calibrate

BLOCKSIZE = HOP        # capture one hop at a time; the window is kept in Detector
CHANNELS = 1


def require_audio():
    try:
        import numpy                     # noqa: F401
        import sounddevice
        return sounddevice
    except ImportError as exc:
        raise SystemExit(
            f"audio input needs numpy and sounddevice ({exc.name} is missing).\n"
            "  Debian/Ubuntu: sudo apt install python3-numpy python3-sounddevice\n"
            "  Fedora:        sudo dnf install python3-numpy python3-sounddevice\n"
            "  pip:           pip install numpy sounddevice\n"
            "sounddevice also needs libportaudio2."
        ) from exc


def find_input(sd, name: str | None):
    """Resolve a device by substring, or fall back to the system default."""
    if name is None:
        return None                      # sounddevice's own default
    matches = [i for i, d in enumerate(sd.query_devices())
               if d["max_input_channels"] > 0 and name.lower() in d["name"].lower()]
    if not matches:
        raise SystemExit(f"no input device matching {name!r}.  "
                         "Run `metamorse devices` to list them.")
    return matches[0]


def devices(sd) -> list[tuple[int, str, float]]:
    return [(i, d["name"], d["default_samplerate"])
            for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0]


@dataclass(frozen=True, slots=True)
class Stream:
    """An open capture stream that yields (hop, timestamp) on a sample clock."""
    stream: object
    samplerate: int

    def hops(self) -> Iterator[tuple[object, float]]:
        """Blocking reads. `t` is the instant the hop's last sample was
        captured -- the newest evidence the window has."""
        elapsed = 0
        while True:
            block, overflowed = self.stream.read(BLOCKSIZE)
            elapsed += len(block)
            yield block[:, 0], elapsed / self.samplerate


def open_stream(sd, device, samplerate: int) -> Stream:
    try:
        stream = sd.InputStream(device=device, channels=CHANNELS,
                                samplerate=samplerate, blocksize=BLOCKSIZE,
                                dtype="float32")
        stream.start()
    except Exception as exc:             # portaudio raises a family of these
        raise SystemExit(f"cannot open audio input ({exc}).\n"
                         "Run `metamorse devices` to see what is available.")
    return Stream(stream, samplerate)


class Clock:
    """Stream time, readable as a callable. Advanced by `edges` as hops
    arrive so `pump`'s idle ticks land on the same timebase as the edges --
    the invariant Demod depends on."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def edges(stream: Stream, detector: Detector, tick: float,
          clock: Clock) -> Iterator[Edge | None]:
    """Yield Edges from the tone gate; yield None between them so trailing
    gaps resolve. Mirrors `source.events` so `pump` cannot tell them apart.

    A None is emitted whenever `tick` seconds of stream time have passed with
    no edge, which is the audio equivalent of select() timing out.
    """
    last = 0.0
    for hop, t in stream.hops():
        clock.t = t
        detector, edge = detector.step(hop, t)
        if edge is not None:
            last = t
            yield edge
            continue
        if t - last >= tick:
            last = t
            yield None


def measure(stream: Stream, detector: Detector, seconds: float,
            report=None) -> float:
    """Listen for `seconds` of stream time and derive a gate threshold from
    whatever was played. Returns the suggested `on` value."""
    powers = []
    for hop, t in stream.hops():
        detector, power = detector.observe(hop)
        powers.append(power)
        if report:
            report(t, power)
        if t >= seconds:
            break
    return calibrate(powers)
