"""Windows key-name tests. Stdlib only, and they run on any platform.

The hook and SendInput need Windows and cannot be tested here. The name
tables can, and they are where the mistakes live: a keymap that parses on
Linux must resolve on Windows, and nothing else in the suite would catch a
chord the backend cannot name.
"""
import unittest
from pathlib import Path

from metamorse.core.dispatch import parse_chord
from metamorse.core.keymap import Action, load
from metamorse.inputs.key import windows


class TestResolveKey(unittest.TestCase):
    def test_default_key_resolves(self):
        self.assertEqual(windows.resolve_key(windows.DEFAULT_KEY), 0x5B)

    def test_aliases_agree_with_targets(self):
        for alias, target in windows.ALIASES.items():
            self.assertEqual(windows.resolve_key(alias),
                             windows.resolve_key(target), alias)

    def test_case_and_space_insensitive(self):
        self.assertEqual(windows.resolve_key("  LWin "), 0x5B)

    def test_letters_and_digits(self):
        self.assertEqual(windows.resolve_key("c"), ord("C"))
        self.assertEqual(windows.resolve_key("7"), ord("7"))

    def test_function_keys_span_the_range(self):
        self.assertEqual(windows.resolve_key("f1"), 0x70)
        self.assertEqual(windows.resolve_key("f24"), 0x87)

    def test_unknown_key_is_rejected(self):
        with self.assertRaises(SystemExit):
            windows.resolve_key("nosuchkey")


class TestExtended(unittest.TestCase):
    """Keys that need KEYEVENTF_EXTENDEDKEY to register at all."""

    def test_win_keys_are_extended(self):
        for name in ("lwin", "rwin"):
            self.assertIn(windows.resolve_key(name), windows.EXTENDED, name)

    def test_arrows_are_extended(self):
        for name in ("left", "right", "up", "down"):
            self.assertIn(windows.resolve_key(name), windows.EXTENDED, name)

    def test_plain_letters_are_not(self):
        self.assertNotIn(windows.resolve_key("a"), windows.EXTENDED)


class TestChordInterop(unittest.TestCase):
    """`parse_chord` is platform-independent; what it yields must resolve."""

    def test_parsed_chord_resolves(self):
        mods, key = parse_chord("ctrl+shift+t")
        for name in (*mods, key):
            windows.resolve_key(name)

    def test_super_chord_resolves(self):
        """'super+c' is the portable spelling of a Windows-key chord."""
        mods, key = parse_chord("super+c")
        self.assertEqual([windows.resolve_key(m) for m in mods], [0x5B])
        self.assertEqual(windows.resolve_key(key), ord("C"))

    def test_shipped_keymap_chords_resolve(self):
        """Every `key` action in the default keymap must be nameable here,
        or the shipped map is Linux-only in a way nothing else reports."""
        share = Path(__file__).resolve().parent.parent / "share" / "keymap.toml"

        def walk(node):
            for child in node.children.values():
                if isinstance(child, Action):
                    if child.kind == "key":
                        mods, key = parse_chord(child.arg)
                        for name in (*mods, key):
                            windows.resolve_key(name)
                else:
                    walk(child)

        walk(load(share))


if __name__ == "__main__":
    unittest.main()
