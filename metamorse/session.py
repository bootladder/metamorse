"""Composition root for the pure pipeline: edges in, actions out."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .decode import decode, extensions, viable
from .demod import Demod
from .keymap import HELP, Action, Branch, Node
from .observer import NullObserver, Observer
from .policy import Emit, Passthrough
from .symbols import Edge, Symbol, Timing


@dataclass(frozen=True, slots=True)
class Session:
    """Walks the keymap trie as letters resolve. Immutable; step returns a
    successor plus whatever the caller must emit or run."""
    keymap: Branch
    timing: Timing = Timing()
    observer: Observer = field(default_factory=NullObserver)
    demod: Demod = field(default_factory=Demod)
    passthrough: Passthrough = field(default_factory=Passthrough)
    marks: tuple[Symbol, ...] = ()
    node: Branch | None = None      # current trie position; None = at root
    entered: str = ""               # the letter that opened `node`

    def step(self, edge: Edge) -> tuple[Session, tuple[Emit, ...], Action | None]:
        pt, emits = self.passthrough.on_edge(edge.down)
        demod, symbols = self.demod.step(edge)
        state = replace(self, demod=demod, passthrough=pt)
        for symbol in symbols:
            state, more, action = state._absorb(symbol)
            emits += more
            if action:
                return state, emits, action
        return state, emits, None

    def tick(self, now: float) -> tuple[Session, tuple[Emit, ...], Action | None]:
        if self._expired(now):
            return self._reset("sequence timed out")
        demod, symbols = self.demod.tick(now)
        state = replace(self, demod=demod)
        emits: tuple[Emit, ...] = ()
        for symbol in symbols:
            state, more, action = state._absorb(symbol)
            emits += more
            if action:
                return state, emits, action
        return state, emits, None

    def _expired(self, now: float) -> bool:
        """A branch we have been sitting on for longer than `hold`."""
        return (self.node is not None and not self.marks
                and self.demod.since is not None
                and now - self.demod.since >= self.timing.hold)

    def _absorb(self, symbol: Symbol) -> tuple[Session, tuple[Emit, ...], Action | None]:
        if symbol is Symbol.WORD_GAP:
            if not self.marks and self.node is None:
                return self, (), None          # idle silence, nothing to abandon
            if self.node is not None and not self.marks:
                return self, (), None          # mid-sequence: `hold` governs, not this
            return self._reset("word gap")
        if symbol is not Symbol.CHAR_GAP:
            return self._mark(symbol)
        letter = decode(self.marks)
        return self._advance(letter) if letter else self._reset("no such code")

    def _mark(self, symbol: Symbol) -> tuple[Session, tuple[Emit, ...], Action | None]:
        marks = self.marks + (symbol,)
        if not viable(marks):
            return self._reset("not a prefix")
        self.observer.on_symbol(marks)
        state = replace(self, marks=marks)
        return state._settled() or (state, (), None)

    def _settled(self):
        """Open a menu without waiting for the character gap, when waiting
        cannot change the outcome: the marks spell exactly one letter and that
        letter is a branch. Actions still wait -- firing a command early on a
        code the user meant to extend is unrecoverable; a menu is not."""
        if extensions(self.marks):
            return None
        letter = decode(self.marks)
        if letter is None:
            return None
        node = (self.node or self.keymap).children.get(letter)
        if not isinstance(node, Branch):
            return None
        return self._advance(letter)

    def _advance(self, letter: str) -> tuple[Session, tuple[Emit, ...], Action | None]:
        # Re-keying the help letter dismisses help. Scoped to help on purpose:
        # a general "repeat backs out" rule would shadow bindings like `m m`.
        if self.node is not None and letter == HELP == self.entered:
            return self._reset("toggled shut")
        node = (self.node or self.keymap).children.get(letter)
        if node is None:
            return self._reset(f"unbound '{letter}'")
        if isinstance(node, Branch):
            self.observer.on_branch(letter, node)
            return replace(self, marks=(), node=node, entered=letter), (), None
        self.observer.on_dispatch(letter, node)
        state, emits = self.passthrough.on_resolve()
        return replace(self, marks=(), node=None, entered="",
                       passthrough=state), emits, node

    def _reset(self, reason: str) -> tuple[Session, tuple[Emit, ...], Action | None]:
        self.observer.on_reset(reason)
        pt, emits = self.passthrough.on_resolve()
        return replace(self, marks=(), node=None, entered="",
                       passthrough=pt), emits, None
