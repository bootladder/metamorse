"""Dispatch, config, and keymap-shipping tests. Stdlib only."""
import tempfile
import unittest
from pathlib import Path

from metamorse import config
from metamorse.core.dispatch import Dispatcher, parse_chord
from metamorse.core.keymap import Action, load


class TestParseChord(unittest.TestCase):
    def test_splits_mods_and_key(self):
        self.assertEqual(parse_chord("ctrl+shift+t"), (["ctrl", "shift"], "t"))

    def test_bare_key(self):
        self.assertEqual(parse_chord("f5"), ([], "f5"))

    def test_normalises_case_and_space(self):
        self.assertEqual(parse_chord(" Super + C "), (["super"], "c"))

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            parse_chord("+")


class TestDispatcher(unittest.TestCase):
    def setUp(self):
        self.ran, self.synthed = [], []
        self.dispatch = Dispatcher(self.ran.append, self.synthed.append)

    def test_routes_sh(self):
        self.dispatch(Action("sh", "echo hi"))
        self.assertEqual((self.ran, self.synthed), (["echo hi"], []))

    def test_routes_key(self):
        self.dispatch(Action("key", "super+c"))
        self.assertEqual((self.ran, self.synthed), ([], ["super+c"]))

    def test_ignores_unknown_kind(self):
        self.dispatch(Action("nop", ""))
        self.assertEqual((self.ran, self.synthed), ([], []))


class TestShippedDefaults(unittest.TestCase):
    """What `install` lays down on a fresh machine. The release binary is the
    product, so these files must work with no editing."""

    SHARE = Path(__file__).resolve().parent.parent / "share"
    PLATFORMS = ("", "-darwin", "-win32")      # "" is the generic/Linux pair

    def test_every_shipped_keymap_leaves_e_unbound(self):
        for suffix in self.PLATFORMS:
            with self.subTest(suffix or "generic"):
                trie = load(self.SHARE / f"keymap{suffix}.toml")
                self.assertNotIn("e", trie.children)

    def test_every_shipped_settings_file_is_pure_defaults(self):
        """They ship fully commented out, so loading one must give exactly
        the built-in defaults."""
        baseline = config.Settings.load(Path("/nonexistent"))
        for suffix in self.PLATFORMS:
            with self.subTest(suffix or "generic"):
                path = self.SHARE / f"metamorse{suffix}.toml"
                self.assertTrue(path.exists(), path)
                self.assertEqual(config.Settings.load(path), baseline)

    def test_install_ships_a_pair_for_every_platform(self):
        """A keymap without its settings file, or vice versa, means `install`
        writes a half-configured machine."""
        for suffix in self.PLATFORMS:
            with self.subTest(suffix or "generic"):
                self.assertTrue((self.SHARE / f"keymap{suffix}.toml").exists())
                self.assertTrue((self.SHARE / f"metamorse{suffix}.toml").exists())


class TestShippedKeymap(unittest.TestCase):
    """The default keymap must parse and must not bind 'e'."""

    def setUp(self):
        share = Path(__file__).resolve().parent.parent / "share" / "keymap.toml"
        self.trie = load(share)

    def test_parses(self):
        self.assertIn("g", self.trie.children)

    def test_e_is_unbound(self):
        self.assertNotIn("e", self.trie.children)

    def test_every_action_is_valid(self):
        def walk(node):
            for child in node.children.values():
                if isinstance(child, Action):
                    self.assertIn(child.kind, ("sh", "key", "nop"))
                    self.assertTrue(child.arg)
                else:
                    walk(child)
        walk(self.trie)

    def test_chords_parse(self):
        def walk(node):
            for child in node.children.values():
                if isinstance(child, Action) and child.kind == "key":
                    parse_chord(child.arg)
                elif not isinstance(child, Action):
                    walk(child)
        walk(self.trie)


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_defaults_when_absent(self):
        """`key` stays unset: which key, and by what name, is the backend's
        call. Asserting 'leftmeta' here would put evdev vocabulary in the
        platform-independent config layer."""
        settings = config.Settings.load(Path(self.tmp.name) / "nope.toml")
        self.assertIsNone(settings.key)
        self.assertAlmostEqual(settings.timing.unit, 0.09)

    def test_overrides(self):
        path = Path(self.tmp.name) / "s.toml"
        path.write_text('key = "capslock"\nunit = 0.12\nimmediate = true\n')
        settings = config.Settings.load(path)
        self.assertEqual(settings.key, "capslock")
        self.assertAlmostEqual(settings.timing.unit, 0.12)
        self.assertTrue(settings.immediate)

    def test_partial_override_keeps_defaults(self):
        path = Path(self.tmp.name) / "s.toml"
        path.write_text('unit = 0.15\n')
        settings = config.Settings.load(path)
        self.assertIsNone(settings.key)
        self.assertAlmostEqual(settings.timing.unit, 0.15)


if __name__ == "__main__":
    unittest.main()
