"""The correctness surface: pure, and testable without X11, audio or root.

Nothing here imports from `inputs` or `ui`. Edges go in, actions come out; the
impure work of producing edges and executing actions belongs to the callers.
"""
from .decode import code_for, decode, extensions, viable
from .demod import Demod
from .dispatch import Dispatcher, parse_chord, shell
from .keymap import DISMISS, HELP, Action, Branch, Node, load
from .observer import NullObserver, Observer
from .policy import Emit, Passthrough
from .pump import pump
from .session import Session
from .symbols import Edge, Symbol, Timing

__all__ = ["code_for", "decode", "extensions", "viable", "Demod", "Dispatcher",
           "parse_chord", "shell", "DISMISS", "HELP", "Action", "Branch",
           "Node", "load", "NullObserver", "Observer", "Emit", "Passthrough",
           "pump", "Session", "Edge", "Symbol", "Timing"]
