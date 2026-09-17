"""Helpers for testing the shipped defaults. Stdlib only, any platform."""
from pathlib import Path

from metamorse.core.keymap import Action, load

SHARE = Path(__file__).resolve().parent.parent / "share"
PLATFORMS = ("linux", "macos", "windows")


def keymap(platform: str):
    return load(SHARE / f"keymap-{platform}.toml")


def actions(node):
    """Every Action in a keymap, depth first."""
    for child in node.children.values():
        if isinstance(child, Action):
            yield child
        else:
            yield from actions(child)


def chords(node):
    """Every `key` action's chord string."""
    return (a.arg for a in actions(node) if a.kind == "key")
