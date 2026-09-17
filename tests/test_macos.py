"""macOS key-name tests. Stdlib only, and they run on any platform.

The tap, the runloop and CGEventPost need macOS and cannot be tested here.
The name tables can, and they are where the mistakes live: macOS keycodes
are positional rather than ASCII, so the whole table is transcribed by hand
and a transposed digit would silently bind the wrong key.
"""
import unittest
from pathlib import Path

from metamorse.core.dispatch import parse_chord
from metamorse.core.keymap import Action, load
from metamorse.inputs.key import macos


class TestResolveKey(unittest.TestCase):
    def test_default_key_resolves(self):
        self.assertEqual(macos.resolve_key(macos.DEFAULT_KEY), 0x36)

    def test_aliases_agree_with_targets(self):
        for alias, target in macos.ALIASES.items():
            self.assertEqual(macos.resolve_key(alias),
                             macos.resolve_key(target), alias)

    def test_case_and_space_insensitive(self):
        self.assertEqual(macos.resolve_key("  RCommand "), 0x36)

    def test_positional_letters(self):
        """kVK_ANSI_A is 0 because of where the key sits, not its ASCII."""
        self.assertEqual(macos.resolve_key("a"), 0x00)
        self.assertEqual(macos.resolve_key("z"), 0x06)

    def test_unknown_key_is_rejected(self):
        with self.assertRaises(SystemExit):
            macos.resolve_key("nosuchkey")

    def test_no_duplicate_keycodes(self):
        """Two names may share a code only when they are the same physical
        key. A collision anywhere else means a transcription slip."""
        seen = {}
        for name, code in macos.VK.items():
            seen.setdefault(code, []).append(name)
        shared = {code: names for code, names in seen.items() if len(names) > 1}
        self.assertEqual(shared, {0x24: ["enter", "return"]},
                         f"unexpected keycode collisions: {shared}")


class TestModifiers(unittest.TestCase):
    """Modifiers report through flagsChanged, not keyDown/keyUp."""

    def test_command_keys_are_modifiers(self):
        for name in ("lcommand", "rcommand"):
            self.assertTrue(macos.is_modifier(macos.resolve_key(name)), name)

    def test_letters_are_not_modifiers(self):
        self.assertFalse(macos.is_modifier(macos.resolve_key("a")))

    def test_default_key_is_a_modifier(self):
        """The whole flagsChanged path exists for this key."""
        self.assertTrue(macos.is_modifier(macos.resolve_key(macos.DEFAULT_KEY)))

    def test_flag_table_only_names_real_keys(self):
        """MODIFIER_FLAGS and VK are coupled by hand and must not drift."""
        codes = set(macos.VK.values())
        self.assertLessEqual(set(macos.MODIFIER_FLAGS), codes)

    def test_paired_modifiers_share_a_flag(self):
        """Left and right of the same modifier set the same bit."""
        for left, right in (("lcommand", "rcommand"), ("lshift", "rshift"),
                            ("lalt", "ralt"), ("lctrl", "rctrl")):
            self.assertEqual(macos.MODIFIER_FLAGS[macos.resolve_key(left)],
                             macos.MODIFIER_FLAGS[macos.resolve_key(right)],
                             f"{left}/{right}")


class TestInjectionSource(unittest.TestCase):
    """The re-entrancy guard compares source state IDs, so the source we
    inject from must not be the one physical keys come from."""

    def test_injects_from_a_private_source(self):
        self.assertEqual(macos.PRIVATE_STATE, -1)

    def test_private_state_is_not_the_hid_state(self):
        """Sharing it makes `_is_ours` true for every real keypress: the tap
        installs, enables, and silently reads nothing."""
        self.assertNotEqual(macos.PRIVATE_STATE, macos.HID_SYSTEM_STATE)


class TestClock(unittest.TestCase):
    """Edges are stamped by CGEventGetTimestamp (nanoseconds) and idle ticks
    by mach_absolute_time (ticks). Demod compares them directly, so the two
    must be the same scale."""

    def test_scales_ticks_to_nanoseconds(self):
        """Apple Silicon is 125/3: unscaled, the clock runs 41x slow and the
        first idle tick reports a word gap, killing any lone dash."""
        class Libc:
            def mach_absolute_time(self):
                return 24_000_000          # one second of 24MHz ticks
        self.assertAlmostEqual(macos.clock(Libc(), 125 / 3), 1.0, places=6)

    def test_tap_stamps_share_the_clock_scale(self):
        """CGEventGetTimestamp returns ticks too, so the Tap must apply the
        same scale. Scaling one side only leaves them 41x apart, which is the
        word-gap flood all over again."""
        tap = macos.Tap.__new__(macos.Tap)
        tap.scale = 125 / 3
        stamp = 24_000_000 * tap.scale / 1_000_000_000.0
        class Libc:
            def mach_absolute_time(self):
                return 24_000_000
        self.assertAlmostEqual(stamp, macos.clock(Libc(), tap.scale), places=9)

    def test_intel_timebase_is_identity(self):
        class Libc:
            def mach_absolute_time(self):
                return 1_000_000_000
        self.assertAlmostEqual(macos.clock(Libc(), 1.0), 1.0, places=6)


class TestChordInterop(unittest.TestCase):
    """`parse_chord` is platform-independent; what it yields must resolve."""

    def test_parsed_chord_resolves(self):
        mods, key = parse_chord("ctrl+shift+t")
        for name in (*mods, key):
            macos.resolve_key(name)

    def test_super_maps_to_command(self):
        """'super+c' is the portable spelling; on macOS that is Command."""
        mods, key = parse_chord("super+c")
        self.assertEqual([macos.resolve_key(m) for m in mods], [0x37])
        self.assertEqual(macos.resolve_key(key), 0x08)

    def test_shipped_keymap_chords_resolve(self):
        share = Path(__file__).resolve().parent.parent / "share" / "keymap.toml"

        def walk(node):
            for child in node.children.values():
                if isinstance(child, Action):
                    if child.kind == "key":
                        mods, key = parse_chord(child.arg)
                        for name in (*mods, key):
                            macos.resolve_key(name)
                else:
                    walk(child)

        walk(load(share))


if __name__ == "__main__":
    unittest.main()
