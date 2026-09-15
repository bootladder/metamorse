"""Preflight checks. Every failure prints the exact fix.

Split by platform, because the failures are: Linux users need evdev, group
membership and a udev rule; Windows users need none of those and would only
be confused by them. Shared checks come first, then whatever this platform
can actually go wrong at.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator

from . import config

UDEV_RULE = 'KERNEL=="uinput", GROUP="input", MODE="0660"'
UDEV_PATH = "/etc/udev/rules.d/99-metamorse.rules"


def _check(label: str, ok: bool, fix: str) -> tuple[bool, str]:
    mark = "\033[32m OK \033[0m" if ok else "\033[31mFAIL\033[0m"
    line = f" [{mark}] {label}"
    return ok, line if ok else f"{line}\n        {fix}"


def _username() -> str:
    """os.getlogin() needs a controlling terminal and raises under a service
    manager, which is exactly where doctor gets run from."""
    return os.environ.get("USER") or os.environ.get("USERNAME") or "$USER"


def _shared() -> Iterator[tuple[bool, str]]:
    yield _check(f"python {sys.version_info.major}.{sys.version_info.minor} >= 3.11",
                 sys.version_info >= (3, 11), "install python 3.11 or newer")
    yield _check("keymap present", config.KEYMAP.exists(),
                 f"metamorse install   (writes {config.KEYMAP})")


def _linux() -> Iterator[tuple[bool, str]]:
    import grp

    try:
        import evdev                                    # noqa: F401
        has_evdev = True
    except ImportError:
        has_evdev = False
    yield _check("python-evdev installed", has_evdev,
                 "sudo apt install python3-evdev  (or dnf/pacman equivalent)")

    user = _username()
    in_input = "input" in {g.gr_name for g in grp.getgrall()
                           if user in g.gr_mem} or os.geteuid() == 0
    yield _check("member of 'input' group", in_input,
                 f"sudo usermod -aG input {user}   then log out and back in")

    uinput = Path("/dev/uinput")
    yield _check("/dev/uinput exists", uinput.exists(),
                 "sudo modprobe uinput")
    yield _check("/dev/uinput writable", os.access(uinput, os.W_OK),
                 f"echo '{UDEV_RULE}' | sudo tee {UDEV_PATH}\n"
                 "        sudo udevadm control --reload-rules && sudo udevadm trigger")

    session = os.environ.get("XDG_SESSION_TYPE", "unknown")
    yield _check(f"session type: {session}", session in ("x11", "wayland", "tty"),
                 "no graphical session detected; chords may not reach a compositor")


def _windows() -> Iterator[tuple[bool, str]]:
    import ctypes

    yield _check("ctypes can reach user32", hasattr(ctypes, "WinDLL"),
                 "this python cannot load Windows DLLs -- use the official "
                 "python.org build, or the metamorse.exe release")

    try:
        elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        elevated = False
    # Reported, never failed: metamorse works unelevated everywhere except
    # against windows running as admin, and demanding admin for everyone to
    # fix that minority is the worse trade.
    yield _check(f"running elevated: {'yes' if elevated else 'no'}", True, "")


def _macos() -> Iterator[tuple[bool, str]]:
    import ctypes
    import ctypes.util

    frameworks = all(ctypes.util.find_library(name) is not None
                     for name in ("CoreGraphics", "CoreFoundation"))
    yield _check("CoreGraphics reachable", frameworks,
                 "this does not look like macOS, or the frameworks are missing")

    from .inputs.key.macos import _trusted
    yield _check("Accessibility permission granted", _trusted(),
                 "System Settings > Privacy & Security > Accessibility:\n"
                 "        add this program and switch it on. An untrusted tap\n"
                 "        installs and then reads nothing at all.")


PLATFORMS = {"linux": _linux, "win32": _windows, "darwin": _macos}


def checks() -> Iterator[tuple[bool, str]]:
    yield from _shared()
    platform = PLATFORMS.get(sys.platform)
    if platform is None:
        yield _check(f"platform {sys.platform} supported", False,
                     f"no backend for {sys.platform}; supported: linux, windows")
        return
    yield from platform()


def report() -> int:
    print("metamorse doctor\n")
    results = list(checks())
    print("\n".join(line for _, line in results))
    failed = sum(not ok for ok, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0
