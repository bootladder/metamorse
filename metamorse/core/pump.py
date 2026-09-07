"""Drive a session from an edge stream. Pure control flow: the caller supplies
the impure edges, sink and clock."""
from __future__ import annotations

from typing import Callable

from .keymap import Action
from .policy import Emit
from .session import Session


def pump(session: Session, stream, sink, key: int,
         run: Callable[[Action], None], clock) -> None:
    """Drive the session. Emits go to the sink; actions go to `run`."""
    for edge in stream:
        if edge is None:
            session, emits, action = session.tick(clock())
        else:
            session, emits, action = session.step(edge)
        for emit in emits:
            sink.emit(key, emit is Emit.DOWN)
        if action:
            run(action)
