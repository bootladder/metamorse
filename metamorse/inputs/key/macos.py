"""The impure edge on macOS: CGEventTap capture, CGEventPost injection.

ctypes only, like the Windows backend and for the same reason: pyobjc would
work, but it drags pyobjc-core and a large bridge into a binary whose whole
selling point is that there is no runtime to install. The cost is declaring
the CoreGraphics signatures by hand, which is the trade windows.py already
makes -- keeping both backends the same shape is worth more than the
convenience in one of them.

Four things differ from the other backends, all forced by the platform:

MODIFIERS ARE NOT KEYS.  Command, Option, Control, Shift and Caps Lock do
not emit keyDown/keyUp at all -- they arrive as kCGEventFlagsChanged, and
whether it was a press or a release has to be read out of the flags word.
The key metamorse watches *is* a modifier, so this is the main path here,
not a special case. Ordinary keys still come through as keyDown/keyUp for
the benefit of anyone who sets `key = "f13"`.

SUPPRESSION.  Like Windows and unlike Linux, there is no second device to
replay through: a tap swallows an event by returning NULL. So Emit.DOWN /
Emit.UP mean "swallow the real key, synthesize one", and policy.py is
untouched.

RE-ENTRANCY.  Events from CGEventPost come back through our own tap. They
are tagged with a source state ID, and ours are skipped unread -- the
counterpart of LLKHF_INJECTED on Windows. That only distinguishes anything
if the source is a *private* one: the HID source shares its state ID with
every physical keypress, so injecting from it makes the guard true for the
whole keyboard and the tap reads nothing at all.

TIMEBASE.  CGEventGetTimestamp is nanoseconds, and Demod requires edges and
idle ticks on one clock, so that is the clock. mach_absolute_time is the
cheap way to read it for idle ticks, but its ticks are NOT nanoseconds --
scale by mach_timebase_info or the clock runs 41x slow on Apple Silicon and
every idle tick reports a word gap.

ACCESSIBILITY.  A tap that is not trusted installs and then silently
delivers nothing, so `open_input` checks first and says so rather than
appearing to work.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import queue
import threading
from dataclasses import dataclass
from typing import Iterator

from ...core.symbols import Edge
from .. import Input

TICK = 0.005         # resolution of the trailing-gap check, as elsewhere

DEFAULT_KEY = "rcommand"
"""The right Command key.

Left Command is the busiest modifier on the platform -- copy, paste,
switcher, every menu shortcut -- so keying Morse on it would fight the whole
system. Right Command is the same key to the OS, reachable by the same
thumb, and almost nothing binds it on its own. `key = "capslock"` in
metamorse.toml is the other good answer.
"""

# CGEventType
KEY_DOWN, KEY_UP, FLAGS_CHANGED = 10, 11, 12
TAP_DISABLED_BY_TIMEOUT = 0xFFFFFFFE
TAP_DISABLED_BY_USER_INPUT = 0xFFFFFFFF

# CGEventField
KEYCODE_FIELD = 9              # kCGKeyboardEventKeycode
SOURCE_STATE_ID = 45           # kCGEventSourceStateID

# CGEventTapLocation / options / masks
HID_EVENT_TAP = 0              # kCGHIDEventTapLocation
HEAD_INSERT = 0                # kCGHeadInsertEventTap
DEFAULT_TAP = 0                # active tap: it may alter or swallow events
EVENT_MASK = (1 << KEY_DOWN) | (1 << KEY_UP) | (1 << FLAGS_CHANGED)

HID_SYSTEM_STATE = 1           # kCGEventSourceStateHIDSystemState
PRIVATE_STATE = -1             # kCGEventSourceStatePrivate

# Injection uses a *private* source so its state ID is unique. The HID source
# shares state ID 1 with every physical keypress, so tagging our own events
# with it makes `_is_ours` true for the whole keyboard and the tap silently
# drops everything it was installed to read.

# Virtual keycodes. Positional, not ASCII -- kVK_ANSI_A is 0 because of where
# the key sits, so unlike Windows there is no ord() shortcut and the whole
# table has to be spelled out.
VK = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C,
    "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11, "o": 0x1F,
    "u": 0x20, "i": 0x22, "p": 0x23, "l": 0x25, "j": 0x26, "k": 0x28,
    "n": 0x2D, "m": 0x2E,
    "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "5": 0x17, "6": 0x16,
    "7": 0x1A, "8": 0x1C, "9": 0x19, "0": 0x1D,
    "enter": 0x24, "return": 0x24, "tab": 0x30, "space": 0x31,
    "backspace": 0x33, "escape": 0x35, "delete": 0x75,
    "left": 0x7B, "right": 0x7C, "down": 0x7D, "up": 0x7E,
    "home": 0x73, "end": 0x77, "pageup": 0x74, "pagedown": 0x79,
    "lcommand": 0x37, "rcommand": 0x36,
    "lshift": 0x38, "rshift": 0x3C,
    "lalt": 0x3A, "ralt": 0x3D,
    "lctrl": 0x3B, "rctrl": 0x3E,
    "capslock": 0x39, "fn": 0x3F,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60,
    "f6": 0x61, "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D,
    "f11": 0x67, "f12": 0x6F, "f13": 0x69, "f14": 0x6B, "f15": 0x71,
    "f16": 0x6A, "f17": 0x40, "f18": 0x4F, "f19": 0x50, "f20": 0x5A,
}

ALIASES = {"cmd": "lcommand", "command": "lcommand", "super": "lcommand",
           "meta": "lcommand", "win": "lcommand",
           "rcmd": "rcommand", "lcmd": "lcommand",
           "ctrl": "lctrl", "control": "lctrl",
           "shift": "lshift", "alt": "lalt", "option": "lalt", "opt": "lalt",
           "esc": "escape", "ret": "enter"}

# Modifier keycode -> the flag bit that says it is held. These keys never
# emit keyDown/keyUp, so the flags word is the only way to read their state.
MODIFIER_FLAGS = {
    0x37: 0x00100000, 0x36: 0x00100000,     # command
    0x38: 0x00020000, 0x3C: 0x00020000,     # shift
    0x3A: 0x00080000, 0x3D: 0x00080000,     # option
    0x3B: 0x00040000, 0x3E: 0x00040000,     # control
    0x39: 0x00010000,                       # caps lock
    0x3F: 0x00800000,                       # fn
}


def resolve_key(name: str) -> int:
    """Name to macOS virtual keycode. The counterpart of evdev's KEY_* and
    the Windows VK_* tables."""
    key = name.strip().lower()
    key = ALIASES.get(key, key)
    code = VK.get(key)
    if code is None:
        raise SystemExit(f"unknown key: {name!r}\n"
                         f"known: {', '.join(sorted(VK))}")
    return code


def is_modifier(code: int) -> bool:
    """Whether this key reports through flagsChanged instead of keyDown."""
    return code in MODIFIER_FLAGS


def _framework(name: str) -> ctypes.CDLL:
    path = ctypes.util.find_library(name)
    if path is None:
        raise SystemExit(f"cannot find the {name} framework -- is this macOS?")
    return ctypes.cdll.LoadLibrary(path)


TAPPROC = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                           ctypes.c_void_p, ctypes.c_void_p)


def _quartz():
    """CoreGraphics and CoreFoundation with signatures declared.

    Every pointer is c_void_p rather than a real type: ctypes defaults
    return values to int, which truncates a 64-bit pointer and crashes at
    the first deref. Declaring them is not optional here.
    """
    cg = _framework("CoreGraphics")
    cf = _framework("CoreFoundation")

    cg.CGEventTapCreate.restype = ctypes.c_void_p
    cg.CGEventTapCreate.argtypes = (ctypes.c_uint32, ctypes.c_uint32,
                                    ctypes.c_uint32, ctypes.c_uint64,
                                    TAPPROC, ctypes.c_void_p)
    cg.CGEventTapEnable.argtypes = (ctypes.c_void_p, ctypes.c_bool)
    cg.CGEventGetIntegerValueField.restype = ctypes.c_int64
    cg.CGEventGetIntegerValueField.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    cg.CGEventGetFlags.restype = ctypes.c_uint64
    cg.CGEventGetFlags.argtypes = (ctypes.c_void_p,)
    cg.CGEventGetTimestamp.restype = ctypes.c_uint64
    cg.CGEventGetTimestamp.argtypes = (ctypes.c_void_p,)
    cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    cg.CGEventCreateKeyboardEvent.argtypes = (ctypes.c_void_p, ctypes.c_uint16,
                                              ctypes.c_bool)
    cg.CGEventSetFlags.argtypes = (ctypes.c_void_p, ctypes.c_uint64)
    cg.CGEventPost.argtypes = (ctypes.c_uint32, ctypes.c_void_p)
    cg.CGEventSourceCreate.restype = ctypes.c_void_p
    cg.CGEventSourceCreate.argtypes = (ctypes.c_int32,)
    cg.CGEventSourceGetSourceStateID.restype = ctypes.c_int32
    cg.CGEventSourceGetSourceStateID.argtypes = (ctypes.c_void_p,)

    cf.CFMachPortCreateRunLoopSource.restype = ctypes.c_void_p
    cf.CFMachPortCreateRunLoopSource.argtypes = (ctypes.c_void_p,
                                                 ctypes.c_void_p,
                                                 ctypes.c_long)
    cf.CFRunLoopGetCurrent.restype = ctypes.c_void_p
    cf.CFRunLoopAddSource.argtypes = (ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_void_p)
    cf.CFRelease.argtypes = (ctypes.c_void_p,)
    cf.CFRunLoopRun.argtypes = ()
    return cg, cf


def _common_modes(cf: ctypes.CDLL) -> ctypes.c_void_p:
    """The kCFRunLoopCommonModes constant.

    It is an exported CFStringRef, so the value wanted is the pointer stored
    in the variable, not its address -- `in_dll` on c_void_p reads exactly
    that. Passing the wrong one attaches the source to no mode at all, and a
    tap on no mode is installed, enabled and never called.
    """
    try:
        return ctypes.c_void_p.in_dll(cf, "kCFRunLoopCommonModes")
    except ValueError as exc:
        raise OSError(f"kCFRunLoopCommonModes is not exported: {exc}") from exc


def _trusted() -> bool:
    """Whether this process may install an event tap.

    An untrusted tap is created successfully and then delivers nothing at
    all, so asking up front is the difference between a clear error and a
    program that looks fine and ignores the keyboard.
    """
    try:
        hi = _framework("ApplicationServices")
        hi.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(hi.AXIsProcessTrusted())
    except (SystemExit, AttributeError):
        return False


@dataclass(frozen=True, slots=True)
class Sink:
    """CGEventPost injection. Same interface as the other sinks.

    Carries CoreFoundation as well as CoreGraphics: CGEventCreate* returns a
    +1 retained object and CFRelease lives in CoreFoundation, so releasing it
    needs both handles. A chord posts six events, so leaking one per keystroke
    is not something a long-running daemon can absorb.
    """
    cg: ctypes.CDLL
    cf: ctypes.CDLL
    source: int

    def emit(self, code: int, down: bool) -> None:
        event = self.cg.CGEventCreateKeyboardEvent(self.source, code, down)
        if not event:
            return
        self.cg.CGEventPost(HID_EVENT_TAP, event)
        self.cf.CFRelease(event)

    def chord(self, mods: list[str], key: str) -> None:
        codes = [resolve_key(mod) for mod in mods]
        target = resolve_key(key)
        for code in codes:
            self.emit(code, True)
        self.emit(target, True)
        self.emit(target, False)
        for code in reversed(codes):
            self.emit(code, False)


class Tap:
    """The event tap, pumped on its own CFRunLoop thread.

    The callback runs on the runloop thread and must return promptly: macOS
    disables a tap that overruns its timeout, exactly as Windows unhooks a
    slow hook. So it decides, pushes an Edge onto a queue, and returns --
    decoding and dispatch happen on the consumer thread where stalling is
    free. A tap disabled anyway is re-enabled from the callback, which is
    the documented recovery and the reason that branch exists.
    """

    def __init__(self, key: int) -> None:
        self.key = key
        self.modifier_flag = MODIFIER_FLAGS.get(key)
        self.edges: queue.Queue[Edge] = queue.Queue()
        self.cg, self.cf = _quartz()
        self._proc = TAPPROC(self._callback)      # kept alive deliberately
        self._ready = threading.Event()
        self._tap = None
        self._failure: Exception | None = None
        self.source = self.cg.CGEventSourceCreate(PRIVATE_STATE)
        self._our_state = self.cg.CGEventSourceGetSourceStateID(self.source)

    def _callback(self, proxy, kind, event, refcon):
        if kind in (TAP_DISABLED_BY_TIMEOUT, TAP_DISABLED_BY_USER_INPUT):
            self.cg.CGEventTapEnable(self._tap, True)
            return event
        if self._is_ours(event):
            return event
        code = self.cg.CGEventGetIntegerValueField(event, KEYCODE_FIELD)
        if code != self.key:
            return event
        down = self._down(kind, event)
        if down is None:
            return event
        stamp = self.cg.CGEventGetTimestamp(event) / 1_000_000_000.0
        self.edges.put(Edge(down, stamp))
        return None                               # swallow: we replay it

    def _is_ours(self, event) -> bool:
        """Skip what we posted, or the first replayed key feeds itself."""
        state = self.cg.CGEventGetIntegerValueField(event, SOURCE_STATE_ID)
        return state == self._our_state

    def _down(self, kind: int, event) -> bool | None:
        """Press or release, however this key reports it.

        Modifiers never emit keyDown/keyUp: flagsChanged fires for both, and
        the flags word is what says which it was.
        """
        if kind == KEY_DOWN:
            return True
        if kind == KEY_UP:
            return False
        if kind == FLAGS_CHANGED and self.modifier_flag is not None:
            flags = self.cg.CGEventGetFlags(event)
            return bool(flags & self.modifier_flag)
        return None

    def _attach(self) -> None:
        """Create the tap and wire it to this thread's runloop.

        Every step is load-bearing and any of them can fail, so this runs to
        completion before `start` is released -- a half-attached tap is the
        failure that looks exactly like working software.
        """
        self._tap = self.cg.CGEventTapCreate(HID_EVENT_TAP, HEAD_INSERT,
                                             DEFAULT_TAP, EVENT_MASK,
                                             self._proc, None)
        if not self._tap:
            raise OSError("CGEventTapCreate returned NULL")
        source = self.cf.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        if not source:
            raise OSError("CFMachPortCreateRunLoopSource returned NULL")
        self.cf.CFRunLoopAddSource(self.cf.CFRunLoopGetCurrent(), source,
                                   _common_modes(self.cf))
        self.cf.CFRelease(source)
        self.cg.CGEventTapEnable(self._tap, True)

    def _pump(self) -> None:
        try:
            self._attach()
        except Exception as exc:                  # reported by `start`
            self._failure = exc
            return
        finally:
            self._ready.set()
        self.cf.CFRunLoopRun()

    def start(self) -> Tap:
        threading.Thread(target=self._pump, daemon=True).start()
        if not self._ready.wait(timeout=5.0):
            raise SystemExit("the event tap thread did not start.")
        if self._failure is not None:
            raise SystemExit(
                f"could not install the event tap: {self._failure}\n"
                "Grant Accessibility to this program: System Settings > "
                "Privacy & Security > Accessibility."
            )
        return self


class _Timebase(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


def _mach() -> tuple[ctypes.CDLL, float]:
    """mach_absolute_time ticks are not nanoseconds. numer/denom converts;
    it is 1/1 on Intel but 125/3 on Apple Silicon, where dividing by 1e9
    runs the clock 41x slow."""
    libc = _framework("System")
    libc.mach_absolute_time.restype = ctypes.c_uint64
    libc.mach_absolute_time.argtypes = ()
    info = _Timebase()
    libc.mach_timebase_info(ctypes.byref(info))
    return libc, info.numer / info.denom


def clock(libc, scale: float) -> float:
    """Stream time in seconds, on the same timebase CGEventGetTimestamp
    stamps events with (which really is nanoseconds). Never time.time()."""
    return libc.mach_absolute_time() * scale / 1_000_000_000.0


def events(tap: Tap, tick: float) -> Iterator[Edge | None]:
    """Yield Edges from the tap queue; yield None on idle so trailing gaps
    resolve. Mirrors the Linux and Windows `events` and the audio `edges` --
    `pump` cannot tell any of them apart."""
    while True:
        try:
            yield tap.edges.get(timeout=tick)
        except queue.Empty:
            yield None


def open_input(settings, **_) -> Input:
    """The meta key itself: an event tap in, CGEventPost out.

    Ignores source-specific options, as the other key backends do.
    """
    if not _trusted():
        raise SystemExit(
            "metamorse needs Accessibility permission to read the keyboard.\n"
            "  System Settings > Privacy & Security > Accessibility\n"
            "  add this program, switch it on, then run it again.\n"
            "An untrusted tap installs and then silently reads nothing, so "
            "this is checked up front rather than left to look like a bug."
        )
    name = settings.key or DEFAULT_KEY
    key = resolve_key(name)
    tap = Tap(key).start()
    libc, scale = _mach()
    return Input(events(tap, TICK), Sink(tap.cg, tap.cf, tap.source), key,
                 lambda: clock(libc, scale),
                 settings.timing,
                 f"metamorse: {name} tapped, "
                 f"unit={settings.timing.unit*1000:.0f}ms")
