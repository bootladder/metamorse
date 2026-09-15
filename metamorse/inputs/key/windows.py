"""The impure edge on Windows: WH_KEYBOARD_LL capture, SendInput injection.

ctypes only -- no third-party package, which is what lets the frozen .exe be
a single file with no runtime to install.

Three things here differ from the Linux backend, and all three are forced by
the platform rather than chosen:

SUPPRESSION.  Linux reads the real key and replays it through a *separate*
uinput device, so both exist and the original is harmless. Windows has no
such split: a low-level hook either passes a key on or swallows it by
returning non-zero. So `Emit.DOWN`/`Emit.UP` mean "swallow the physical key,
then synthesize one" here. `policy.py` is untouched -- only the mechanism
under it changes.

RE-ENTRANCY.  Keys we synthesize come straight back through our own hook. The
flags word carries LLKHF_INJECTED to say so, and injected events are passed
through without being looked at. Without that the first replayed Meta would
feed itself forever.

TIMEBASE.  The hook stamps every event with GetTickCount milliseconds, and
`Demod` requires edges and idle ticks to share one clock. So the clock here
is GetTickCount, never time.time() -- the same rule the audio input follows
for its sample clock, and the same bug if it is broken.
"""
from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterator

from ...core.symbols import Edge
from .. import Input

TICK = 0.005         # resolution of the trailing-gap check, as on Linux

DEFAULT_KEY = "lwin"
"""The left Windows key.

Windows itself binds this: a bare tap opens the Start menu, and Win+L and
Win+G are reserved outright. metamorse swallows the physical key and replays
a tap only when the gesture decodes to a bare `e`, which keeps the tap
working -- but the reserved chords still belong to the shell. Users who want
none of that argument can set `key = "capslock"` in metamorse.toml.
"""

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
WM_KEYUP, WM_SYSKEYUP = 0x0101, 0x0105

DOWN_MESSAGES = frozenset((WM_KEYDOWN, WM_SYSKEYDOWN))
UP_MESSAGES = frozenset((WM_KEYUP, WM_SYSKEYUP))

LLKHF_INJECTED = 0x10

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001

# Virtual key codes. Only the names a keymap can mention: the key metamorse
# watches, plus the modifiers and letters `parse_chord` produces.
VK = {
    "lwin": 0x5B, "rwin": 0x5C, "capslock": 0x14,
    "lctrl": 0xA2, "rctrl": 0xA3, "ctrl": 0x11,
    "lshift": 0xA0, "rshift": 0xA1, "shift": 0x10,
    "lalt": 0xA4, "ralt": 0xA5, "alt": 0x12,
    "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "space": 0x20,
    "enter": 0x0D, "return": 0x0D, "backspace": 0x08, "delete": 0x2E,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    **{f"f{n}": 0x6F + n for n in range(1, 25)},
    **{c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz"},
    **{d: ord(d) for d in "0123456789"},
}

# Keys that must carry KEYEVENTF_EXTENDEDKEY to be recognised.
EXTENDED = frozenset((0x5B, 0x5C, 0xA3, 0xA5, 0x25, 0x26, 0x27, 0x28,
                      0x2E, 0x24, 0x23, 0x21, 0x22))

ALIASES = {"super": "lwin", "win": "lwin", "meta": "lwin",
           "control": "ctrl", "return": "enter", "esc": "escape"}


def resolve_key(name: str) -> int:
    """Name to virtual key code. The Windows counterpart to evdev's KEY_*."""
    key = name.strip().lower()
    key = ALIASES.get(key, key)
    code = VK.get(key)
    if code is None:
        raise SystemExit(f"unknown key: {name!r}\n"
                         f"known: {', '.join(sorted(VK))}")
    return code


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class INPUT(ctypes.Structure):
    class _UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_ubyte * 32)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]


def _hookproc():
    """The callback signature, built on demand.

    ctypes.WINFUNCTYPE exists only on Windows, and a module-level call would
    make this file unimportable anywhere else. Deferring it keeps the name
    tables and `resolve_key` testable on any platform -- which is the only
    part of this backend that *can* be tested off Windows.
    """
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int,
                              wintypes.WPARAM, wintypes.LPARAM)


def _user32(hookproc):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.SetWindowsHookExW.argtypes = (ctypes.c_int, hookproc,
                                         wintypes.HINSTANCE, wintypes.DWORD)
    user32.CallNextHookEx.restype = ctypes.c_long
    user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int,
                                      wintypes.WPARAM, wintypes.LPARAM)
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT),
                                 ctypes.c_int)
    user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),
                                   wintypes.HWND, wintypes.UINT, wintypes.UINT)
    user32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
    user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
    return user32


@dataclass(frozen=True, slots=True)
class Sink:
    """SendInput injection. Same interface as the Linux uinput sink."""
    user32: ctypes.CDLL

    def emit(self, code: int, down: bool) -> None:
        flags = 0 if down else KEYEVENTF_KEYUP
        if code in EXTENDED:
            flags |= KEYEVENTF_EXTENDEDKEY
        event = INPUT(type=INPUT_KEYBOARD,
                      ki=KEYBDINPUT(wVk=code, wScan=0, dwFlags=flags, time=0,
                                    dwExtraInfo=None))
        self.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))

    def chord(self, mods: list[str], key: str) -> None:
        codes = [resolve_key(mod) for mod in mods]
        target = resolve_key(key)
        for code in codes:
            self.emit(code, True)
        self.emit(target, True)
        self.emit(target, False)
        for code in reversed(codes):
            self.emit(code, False)


class Hook:
    """The low-level keyboard hook, pumped on its own thread.

    The callback runs on whatever thread owns the pump and must return
    promptly -- Windows silently unhooks a callback that overruns
    LowLevelHooksTimeout. So it does the least possible work: decide, push an
    Edge onto a queue, return. Everything slow (decoding, dispatch, the OSD)
    happens on the consumer thread, where stalling costs nothing.
    """

    def __init__(self, key: int) -> None:
        self.key = key
        self.edges: queue.Queue[Edge] = queue.Queue()
        hookproc = _hookproc()
        self.user32 = _user32(hookproc)
        self._proc = hookproc(self._callback)     # kept alive deliberately
        self._ready = threading.Event()
        self._handle = None

    def _callback(self, code: int, wparam: int, lparam: int) -> int:
        if code < 0:
            return self.user32.CallNextHookEx(None, code, wparam, lparam)
        event = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        if event.vkCode != self.key or event.flags & LLKHF_INJECTED:
            return self.user32.CallNextHookEx(None, code, wparam, lparam)
        down = wparam in DOWN_MESSAGES
        if down or wparam in UP_MESSAGES:
            self.edges.put(Edge(down, event.time / 1000.0))
        return 1                                   # swallow: we replay it

    def _pump(self) -> None:
        self._handle = self.user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc, None, 0)
        self._ready.set()
        if not self._handle:
            return
        message = wintypes.MSG()
        while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            self.user32.TranslateMessage(ctypes.byref(message))
            self.user32.DispatchMessageW(ctypes.byref(message))

    def start(self) -> Hook:
        threading.Thread(target=self._pump, daemon=True).start()
        self._ready.wait(timeout=5.0)
        if not self._handle:
            raise SystemExit(
                f"could not install the keyboard hook "
                f"(error {ctypes.get_last_error()}).\n"
                "Another program may already hold it, or metamorse needs to "
                "run at the same privilege level as the window you are in."
            )
        return self


def clock(kernel32) -> float:
    """Stream time in seconds, on the same GetTickCount base the hook stamps
    its events with. Never time.time(): see the module docstring."""
    return kernel32.GetTickCount() / 1000.0


def events(hook: Hook, tick: float) -> Iterator[Edge | None]:
    """Yield Edges from the hook queue; yield None on idle so trailing gaps
    resolve. Mirrors the Linux `events` and the audio `edges` -- `pump`
    cannot tell any of the three apart."""
    while True:
        try:
            yield hook.edges.get(timeout=tick)
        except queue.Empty:
            yield None


def open_input(settings, **_) -> Input:
    """The meta key itself: a low-level hook in, SendInput out.

    Ignores source-specific options, exactly as the Linux backend does.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    name = settings.key or DEFAULT_KEY
    key = resolve_key(name)
    hook = Hook(key).start()
    return Input(events(hook, TICK), Sink(hook.user32), key,
                 lambda: clock(kernel32),
                 settings.timing,
                 f"metamorse: {name} hooked, "
                 f"unit={settings.timing.unit*1000:.0f}ms")
