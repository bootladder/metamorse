"""The version. A frozen build has no checkout to ask, so the release
workflow stamps the tag in before PyInstaller runs:

    python -m metamorse.version v0.1.9

Unstamped, it is whatever `git describe` says about the checkout.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

STAMP = Path(__file__).with_name("_stamp.py")     # generated, gitignored


def _stamped() -> str | None:
    try:
        from ._stamp import VERSION
    except ImportError:
        return None
    return VERSION


def _described() -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(STAMP.parent), "describe",
                              "--tags", "--dirty", "--always"],
                             capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def version() -> str:
    return _stamped() or _described() or "unknown"


def stamp(tag: str) -> None:
    STAMP.write_text(f"VERSION = {tag!r}\n")


if __name__ == "__main__":
    stamp(sys.argv[1])
