"""Config to dispatch trie."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

ACTIONS = ("sh", "key", "nop")

HELP = "t"          # a single dash: the cheapest gesture, so the safest one
HELP_HINT = "help -- all bindings"

DISMISS = "e"       # a bare tap: already reserved, so it collides with nothing


@dataclass(frozen=True, slots=True)
class Action:
    kind: str
    arg: str
    hint: str = ""


@dataclass(frozen=True, slots=True)
class Branch:
    hint: str = ""
    children: dict[str, "Node"] = field(default_factory=dict)


Node = Union[Action, Branch]


def _action(spec: dict, where: str) -> Action | None:
    kinds = [k for k in ACTIONS if k in spec]
    if not kinds:
        return None
    if len(kinds) > 1:
        raise ValueError(f"{where}: conflicting actions {kinds}")
    return Action(kinds[0], str(spec[kinds[0]]), spec.get("hint", ""))


def _descend(root: dict[str, Node], stem: list[str], where: str) -> dict[str, Node]:
    node = root
    for step in stem:
        child = node.setdefault(step, Branch())
        if not isinstance(child, Branch):
            raise ValueError(f"{where}: '{step}' is bound to an action")
        node = child.children
    return node


def load(path: Path) -> Branch:
    """Parse keymap TOML. Keys are space-separated letter paths; a spec with a
    hint and no action labels a branch."""
    raw = tomllib.loads(path.read_text())
    root: dict[str, Node] = {}
    for seq, spec in sorted(raw.items(), key=lambda kv: kv[0].count(" ")):
        *stem, last = seq.split()
        level = _descend(root, stem, seq)
        action = _action(spec, seq)
        if action is None:
            existing = level.get(last, Branch())
            if not isinstance(existing, Branch):
                raise ValueError(f"{seq}: cannot label an action")
            level[last] = Branch(spec.get("hint", ""), existing.children)
        elif isinstance(level.get(last), Action):
            raise ValueError(f"{seq}: duplicate binding")
        else:
            level[last] = action
    return Branch("", with_help(root))


def with_help(root: dict[str, Node]) -> dict[str, Node]:
    """Bind `t` to a branch listing everything, unless the user bound it.

    `t` is one dash -- the gesture you hit by accident. Pointing it at a menu
    makes an accidental trigger free: it shows, then times out, doing nothing.
    """
    if HELP in root:
        return root
    return {**root, HELP: Branch(HELP_HINT, root)}
