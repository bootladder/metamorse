"""Symbols to letters."""
from __future__ import annotations

from .symbols import Symbol

_CODE = {
    "a": ".-",    "b": "-...",  "c": "-.-.",  "d": "-..",   "e": ".",
    "f": "..-.",  "g": "--.",   "h": "....",  "i": "..",    "j": ".---",
    "k": "-.-",   "l": ".-..",  "m": "--",    "n": "-.",    "o": "---",
    "p": ".--.",  "q": "--.-",  "r": ".-.",   "s": "...",   "t": "-",
    "u": "..-",   "v": "...-",  "w": ".--",   "x": "-..-",  "y": "-.--",
    "z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
}

LETTERS = {code: letter for letter, code in _CODE.items()}
PREFIXES = frozenset(code[:n] for code in LETTERS for n in range(len(code) + 1))


def decode(marks: tuple[Symbol, ...]) -> str | None:
    """Resolve accumulated marks to a letter, or None if no such code."""
    return LETTERS.get("".join(m.value for m in marks))


def code_for(letter: str) -> str:
    """The Morse code for a letter, for display."""
    return _CODE.get(letter, "?")


def viable(marks: tuple[Symbol, ...]) -> bool:
    """Whether these marks can still grow into a valid code."""
    return "".join(m.value for m in marks) in PREFIXES
