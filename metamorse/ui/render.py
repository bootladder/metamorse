"""Keymap -> displayable rows. Pure: no toolkit, no I/O."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.decode import code_for
from ..core.keymap import Action, Branch, Node


@dataclass(frozen=True, slots=True)
class Row:
    letter: str
    code: str
    label: str
    is_branch: bool

    @property
    def arrow(self) -> str:
        return "…" if self.is_branch else "→"    # ellipsis / arrow


def describe(node: Node) -> str:
    if isinstance(node, Branch):
        return node.hint or f"{len(node.children)} bindings"
    return node.hint or f"{node.kind}: {node.arg}"


def rows(branch: Branch) -> list[Row]:
    """One row per child, cheapest Morse code first -- the order you learn in."""
    made = [Row(letter, code_for(letter), describe(child), isinstance(child, Branch))
            for letter, child in branch.children.items()]
    return sorted(made, key=lambda r: (len(r.code), r.code))
