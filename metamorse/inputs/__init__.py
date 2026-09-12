"""Keying sources. One protocol, one registry, one line to add an input.

An input is whatever can produce key edges: the meta key today, a guitar
string if the optional tone extra is installed. The core cannot tell them
apart, and must not -- everything downstream of `stream` is identical.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

from ..core import Edge, Timing


@dataclass(frozen=True, slots=True)
class Input:
    """An opened keying source, ready to pump.

    The clock travels with the stream because each source owns its timebase --
    evdev stamps CLOCK_REALTIME, audio counts samples -- and Demod requires
    edges and idle ticks to share one. Letting a caller pair the wrong clock
    with a stream is the bug this bundling prevents.
    """
    stream: Iterator[Edge | None]
    sink: object
    key: int
    clock: Callable[[], float]
    timing: Timing
    banner: str


OPENERS: dict[str, Callable[..., Input]] = {}


def register(name: str, opener: Callable[..., Input]) -> None:
    OPENERS[name] = opener


def open_input(name: str, settings, **options) -> Input:
    """Open a source by name, importing its module only if asked for.

    The import is deliberately lazy: `tone` needs numpy and sounddevice, and
    running on the meta key must not require either to be installed.

    `options` carries source-specific switches straight through to the opener
    that understands them. They are keyword-only and each opener names the ones
    it accepts, so a flag meant for audio never silently changes the key path.
    """
    if name not in OPENERS:
        __import__(f"{__name__}.{name}")
    if name not in OPENERS:
        raise SystemExit(f"unknown input: {name!r}")
    return OPENERS[name](settings, **options)
