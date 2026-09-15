"""The keyboard input, one backend per platform.

Registered once under the name `key`; which module actually opens it is a
platform decision made here and nowhere else. Everything downstream --
`pump`, `Session`, the keymap -- is identical across all three.

Key *names* are the one thing that cannot be shared. Linux resolves them
through evdev (`KEY_LEFTMETA`), Windows through virtual key codes (`VK_LWIN`),
macOS through positional keycodes (`kVK_Command`), so each backend owns its
own vocabulary and its own default. `settings.key` overrides that default
when set; leaving it unset is what asks for the platform's own answer.
"""
from __future__ import annotations

import sys

from .. import Input, register

BACKENDS = {"linux": "linux", "win32": "windows", "darwin": "macos"}


def _backend():
    """Import the module for this platform, or explain why there isn't one."""
    name = BACKENDS.get(sys.platform)
    if name is None:
        raise SystemExit(
            f"no keyboard backend for {sys.platform!r}.\n"
            f"supported: {', '.join(sorted(set(BACKENDS.values())))}"
        )
    module = __import__(f"{__name__}.{name}", fromlist=["open_input"])
    return module


def open_input(settings, **options) -> Input:
    return _backend().open_input(settings, **options)


register("key", open_input)
