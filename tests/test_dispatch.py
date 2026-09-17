"""Dispatch, config, and keymap-shipping tests. Stdlib only."""
import tempfile
import unittest
from pathlib import Path

import shipped
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


class TestShippedKeymaps(unittest.TestCase):
    """Every platform's shipped keymap, checked the same way. These are what
    `install` copies, so a broken one ships."""

    def test_parses(self):
        for platform in shipped.PLATFORMS:
            with self.subTest(platform):
                self.assertTrue(shipped.keymap(platform).children)

    def test_e_is_unbound(self):
        """The `e` contract: a bare tap must pass through."""
        for platform in shipped.PLATFORMS:
            with self.subTest(platform):
                self.assertNotIn("e", shipped.keymap(platform).children)

    def test_every_action_is_valid(self):
        for platform in shipped.PLATFORMS:
            for action in shipped.actions(shipped.keymap(platform)):
                with self.subTest(platform, arg=action.arg):
                    self.assertIn(action.kind, ("sh", "key", "nop"))
                    self.assertTrue(action.arg)

    def test_chords_parse(self):
        for platform in shipped.PLATFORMS:
            for chord in shipped.chords(shipped.keymap(platform)):
                with self.subTest(platform, chord=chord):
                    parse_chord(chord)


class TestShippedSettings(unittest.TestCase):
    """Each metamorse.toml ships fully commented out, so loading one must
    give exactly the built-in defaults -- otherwise the file is lying about
    what it says it is."""

    def test_matches_defaults(self):
        baseline = config.Settings.load(Path("/nonexistent"))
        for platform in shipped.PLATFORMS:
            path = shipped.SHARE / f"metamorse-{platform}.toml"
            with self.subTest(platform):
                self.assertTrue(path.exists(), path)
                self.assertEqual(config.Settings.load(path), baseline)

    def test_names_the_backend_default_key(self):
        """The commented `key =` must name that backend's own default, or it
        documents a key metamorse does not actually use."""
        expected = {"linux": "leftmeta", "windows": "lwin", "macos": "rcommand"}
        for platform, key in expected.items():
            path = shipped.SHARE / f"metamorse-{platform}.toml"
            with self.subTest(platform):
                self.assertIn(f'#key = "{key}"', path.read_text())


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
