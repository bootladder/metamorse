"""The impure edge: evdev capture, uinput injection, event loop.

evdev is imported lazily so the pure core and `doctor` work without it.
"""
from __future__ import annotations

import select
from dataclasses import dataclass
from typing import Callable, Iterator

from .keymap import Action
from .policy import Emit
from .session import Session
from .symbols import Edge

TICK = 0.005         # resolution of the trailing-gap check


def require_evdev():
    try:
        import evdev
        return evdev
    except ImportError as exc:
        raise SystemExit(
            "python-evdev is not installed.\n"
            "  Debian/Ubuntu: sudo apt install python3-evdev\n"
            "  Fedora:        sudo dnf install python3-evdev\n"
            "  Arch:          sudo pacman -S python-evdev"
        ) from exc


def find_keyboards(evdev) -> list:
    """Devices advertising the alphabet -- real keyboards, not mice or lids."""
    probe = {evdev.ecodes.KEY_A, evdev.ecodes.KEY_Z, evdev.ecodes.KEY_SPACE}
    found = []
    for path in evdev.list_devices():
        device = evdev.InputDevice(path)
        keys = set(device.capabilities().get(evdev.ecodes.EV_KEY, []))
        found.append(device) if probe <= keys else device.close()
    return found


def resolve_key(evdev, name: str) -> int:
    code = evdev.ecodes.ecodes.get(f"KEY_{name.upper().removeprefix('KEY_')}")
    if code is None:
        raise SystemExit(f"unknown key: {name!r}")
    return code


@dataclass(frozen=True, slots=True)
class Sink:
    """uinput device that replays the modifier and synthesizes chords."""
    device: object
    evdev: object

    def emit(self, code: int, down: bool) -> None:
        self.device.write(self.evdev.ecodes.EV_KEY, code, int(down))
        self.device.syn()

    def chord(self, mods: list[str], key: str) -> None:
        codes = [resolve_key(self.evdev, m) for m in mods]
        target = resolve_key(self.evdev, key)
        for code in codes:
            self.emit(code, True)
        self.emit(target, True)
        self.emit(target, False)
        for code in reversed(codes):
            self.emit(code, False)


def open_sink(evdev):
    from evdev import UInput
    try:
        return Sink(UInput(name="metamorse"), evdev)
    except (PermissionError, OSError) as exc:
        raise SystemExit(
            f"cannot open /dev/uinput ({exc}).\n"
            "Run `metamorse doctor` for the udev rule that fixes this."
        ) from exc


def events(evdev, devices: list, key: int, timeout: float) -> Iterator[Edge | None]:
    """Yield Edges for the target key; yield None on idle so gaps can resolve."""
    fds = {device.fd: device for device in devices}
    while True:
        ready, _, _ = select.select(fds, [], [], timeout)
        if not ready:
            yield None
            continue
        for fd in ready:
            for event in fds[fd].read():
                if event.type == evdev.ecodes.EV_KEY and event.code == key:
                    if event.value != 2:            # ignore autorepeat
                        yield Edge(bool(event.value), event.timestamp())


def pump(session: Session, stream, sink: Sink, key: int,
         run: Callable[[Action], None], clock) -> None:
    """Drive the session. Emits go to the sink; actions go to `run`."""
    for edge in stream:
        if edge is None:
            session, emits, action = session.tick(clock())
        else:
            session, emits, action = session.step(edge)
        for emit in emits:
            sink.emit(key, emit is Emit.DOWN)
        if action:
            run(action)
