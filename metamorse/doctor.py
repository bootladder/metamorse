"""Preflight checks. Every failure prints the exact fix."""
from __future__ import annotations

import grp
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


def checks() -> Iterator[tuple[bool, str]]:
    yield _check(f"python {sys.version_info.major}.{sys.version_info.minor} >= 3.11",
                 sys.version_info >= (3, 11), "install python 3.11 or newer")

    try:
        import evdev                                    # noqa: F401
        has_evdev = True
    except ImportError:
        has_evdev = False
    yield _check("python-evdev installed", has_evdev,
                 "sudo apt install python3-evdev  (or dnf/pacman equivalent)")

    in_input = "input" in {g.gr_name for g in grp.getgrall()
                           if os.getlogin() in g.gr_mem} or os.geteuid() == 0
    yield _check("member of 'input' group", in_input,
                 f"sudo usermod -aG input {os.getlogin()}   then log out and back in")

    uinput = Path("/dev/uinput")
    yield _check("/dev/uinput exists", uinput.exists(),
                 "sudo modprobe uinput")
    yield _check("/dev/uinput writable", os.access(uinput, os.W_OK),
                 f"echo '{UDEV_RULE}' | sudo tee {UDEV_PATH}\n"
                 "        sudo udevadm control --reload-rules && sudo udevadm trigger")

    yield _check("keymap present", config.KEYMAP.exists(),
                 f"metamorse install   (writes {config.KEYMAP})")

    session = os.environ.get("XDG_SESSION_TYPE", "unknown")
    yield _check(f"session type: {session}", session in ("x11", "wayland", "tty"),
                 "no graphical session detected; chords may not reach a compositor")


def report() -> int:
    print("metamorse doctor\n")
    results = list(checks())
    print("\n".join(line for _, line in results))
    failed = sum(not ok for ok, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0
