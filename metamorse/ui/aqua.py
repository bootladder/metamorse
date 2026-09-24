"""Pin the OSD above everything on macOS.

Tk's -topmost on Aqua is kCGUtilityWindowLevel only, on the Space it was
created in, and owned by a process that is never the active app -- so other
apps' windows, full-screen Spaces and the Dock can all cover it. This sets
the NSWindow directly. ctypes over the objc runtime, not pyobjc, for the
reason given in inputs/key/macos.py.
"""
from __future__ import annotations

import ctypes
import ctypes.util
from functools import partial

POPUP_MENU_LEVEL = 101          # NSPopUpMenuWindowLevel: above Dock, status
BEHAVIOR = (1 << 0              # canJoinAllSpaces
            | 1 << 4            # stationary
            | 1 << 6            # ignoresCycle
            | 1 << 8)           # fullScreenAuxiliary


def _runtime():
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc") or "libobjc.dylib")
    for name in ("objc_getClass", "sel_registerName"):
        fn = getattr(objc, name)
        fn.restype, fn.argtypes = ctypes.c_void_p, (ctypes.c_char_p,)
    return objc


def _sender(objc):
    """send(restype, obj, "selector:", *(ctype, value)). objc_msgSend must be
    cast per signature: arm64 does not pass variadic args in registers."""
    def send(restype, obj, selector, *args):
        proto = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p,
                                 *(t for t, _ in args))
        fn = proto(("objc_msgSend", objc))
        return fn(obj, objc.sel_registerName(selector.encode()),
                  *(v for _, v in args))
    return send


def _visible_windows(send, objc):
    app = send(ctypes.c_void_p, objc.objc_getClass(b"NSApplication"),
               "sharedApplication")
    windows = send(ctypes.c_void_p, app, "windows")
    at = partial(send, ctypes.c_void_p, windows, "objectAtIndex:")
    return filter(lambda w: send(ctypes.c_bool, w, "isVisible"),
                  (at((ctypes.c_ulong, i))
                   for i in range(send(ctypes.c_ulong, windows, "count"))))


def _pin(send, window) -> None:
    send(None, window, "setLevel:", (ctypes.c_long, POPUP_MENU_LEVEL))
    send(None, window, "setCollectionBehavior:", (ctypes.c_ulong, BEHAVIOR))
    send(None, window, "setHidesOnDeactivate:", (ctypes.c_bool, False))
    send(None, window, "orderFrontRegardless")


def pinner():
    """A callable that re-pins every visible Tk window. Main thread only.
    Cheap enough to call on every show; Tk may reassert its own level."""
    objc = _runtime()
    send = _sender(objc)

    def pin() -> None:
        for window in _visible_windows(send, objc):
            _pin(send, window)
    return pin
