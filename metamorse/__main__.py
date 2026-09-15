"""Entry point for `python -m metamorse` and for the frozen exe.

The import is absolute, not relative. PyInstaller runs this as a top-level
script rather than as part of the package, so there is no parent for `.cli`
to be relative to and a frozen build dies on import. `python -m metamorse`
establishes the package context either way, so absolute works in both.
"""
import sys

from metamorse.cli import main

if __name__ == "__main__":
    sys.exit(main())
