"""Entry point for `python -m metamorse` and for the frozen exe."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
