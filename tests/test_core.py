"""Core pipeline tests. Stdlib only: python3 -m unittest discover tests"""
import tempfile
import unittest
from pathlib import Path

from metamorse.decode import decode, viable
from metamorse.demod import run
from metamorse.keymap import Action, load
from metamorse.policy import Emit, Passthrough
from metamorse.session import Session
from metamorse.symbols import Edge, Symbol, Timing

U = Timing().unit


def edges(pattern, start=0.0):
    """Render Morse as key edges with 1u intra-element gaps. Returns
    (edges, end_time) so callers can space letters correctly."""
    out, t = [], start
    for i, mark in enumerate(pattern):
        if i:
            t += U
        out.append(Edge(True, t))
        t += U * (3 if mark == "-" else 1)
        out.append(Edge(False, t))
    return out, t


class TestDemod(unittest.TestCase):
    def test_classifies_marks(self):
        stream, _ = edges(".-.")
        self.assertEqual(tuple(run(stream)), (Symbol.DIT, Symbol.DAH, Symbol.DIT))

    def test_emits_char_gap(self):
        first, end = edges(".-")
        second, _ = edges("-", start=end + 3 * U)
        self.assertIn(Symbol.CHAR_GAP, tuple(run(first + second)))

    def test_no_gap_within_letter(self):
        first, end = edges(".")
        second, _ = edges("-", start=end + U)
        self.assertNotIn(Symbol.CHAR_GAP, tuple(run(first + second)))

    def test_ignores_repeat_edges(self):
        stream = [Edge(True, 0.0), Edge(True, U), Edge(False, U)]
        self.assertEqual(tuple(run(stream)), (Symbol.DIT,))

    def test_word_gap_beats_char_gap(self):
        first, end = edges(".")
        second, _ = edges(".", start=end + 7 * U)
        self.assertIn(Symbol.WORD_GAP, tuple(run(first + second)))


class TestDecode(unittest.TestCase):
    def test_letters(self):
        for code, letter in ((".-", "a"), ("...", "s"), ("-----", "0"), (".", "e")):
            self.assertEqual(decode(tuple(Symbol(c) for c in code)), letter)

    def test_unknown_code(self):
        self.assertIsNone(decode(tuple([Symbol.DIT] * 7)))

    def test_viability(self):
        self.assertTrue(viable((Symbol.DIT, Symbol.DAH)))
        self.assertFalse(viable(tuple([Symbol.DIT] * 6)))


class TestKeymap(unittest.TestCase):
    def load(self, toml):
        path = Path(self.tmp.name) / "k.toml"
        path.write_text(toml)
        return load(path)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_builds_trie(self):
        trie = self.load('"g" = { hint = "git" }\n"g s" = { sh = "git status" }\n'
                         '"h" = { key = "Super_L+h" }\n')
        self.assertEqual(trie.children["g"].hint, "git")
        self.assertEqual(trie.children["g"].children["s"], Action("sh", "git status"))
        self.assertEqual(trie.children["h"].kind, "key")

    def test_branch_label_order_independent(self):
        trie = self.load('"g s" = { sh = "x" }\n"g" = { hint = "git" }\n')
        self.assertEqual(trie.children["g"].hint, "git")
        self.assertIn("s", trie.children["g"].children)

    def test_rejects_conflicting_actions(self):
        with self.assertRaises(ValueError):
            self.load('"a" = { sh = "x", key = "y" }\n')

    def test_rejects_action_used_as_branch(self):
        with self.assertRaises(ValueError):
            self.load('"a" = { sh = "x" }\n"a b" = { sh = "y" }\n')


class TestPassthrough(unittest.TestCase):
    def test_defers_up_until_resolve(self):
        pt, emits = Passthrough().on_edge(True)
        self.assertEqual(emits, (Emit.DOWN,))
        pt, emits = pt.on_edge(False)
        self.assertEqual(emits, ())
        _, emits = pt.on_resolve()
        self.assertEqual(emits, (Emit.UP,))

    def test_single_down_across_multiple_marks(self):
        """Downstream must not see a second Meta-down before any up."""
        pt, first = Passthrough().on_edge(True)
        pt, _ = pt.on_edge(False)
        pt, second = pt.on_edge(True)
        self.assertEqual((first, second), ((Emit.DOWN,), ()))

    def test_never_strands_a_held_modifier(self):
        pt = Passthrough()
        for _ in range(3):
            pt, _ = pt.on_edge(True)
            pt, _ = pt.on_edge(False)
        _, emits = pt.on_resolve()
        self.assertEqual(emits, (Emit.UP,))

    def test_immediate_mode(self):
        pt, _ = Passthrough(immediate=True).on_edge(True)
        _, emits = pt.on_edge(False)
        self.assertEqual(emits, (Emit.UP,))


class TestSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def session(self, toml):
        path = Path(self.tmp.name) / "k.toml"
        path.write_text(toml)
        return Session(load(path))

    def drive(self, state, pattern, start=0.0):
        """Feed a pattern, then tick past the char gap to force resolution."""
        stream, end = edges(pattern, start=start)
        emitted, action = (), None
        for edge in stream:
            state, out, act = state.step(edge)
            emitted += out
            action = action or act
        state, out, act = state.tick(end + 3 * U)
        return state, emitted + out, action or act

    def test_bare_tap_is_e_and_passes_through(self):
        """A lone Meta tap decodes as 'e', is unbound, and replays as a tap."""
        _, emits, action = self.drive(self.session('"a" = { sh = "x" }'), ".")
        self.assertIsNone(action)
        self.assertEqual(emits, (Emit.DOWN, Emit.UP))

    def test_dispatch_fires_and_releases_modifier(self):
        _, emits, action = self.drive(self.session('"a" = { sh = "run" }'), ".-")
        self.assertEqual(action, Action("sh", "run"))
        self.assertEqual(emits, (Emit.DOWN, Emit.UP))

    def test_sequence_walks_branch(self):
        state = self.session('"g" = { hint = "git" }\n"g s" = { sh = "git status" }\n')
        state, _, action = self.drive(state, "--.")
        self.assertIsNone(action)
        self.assertIsNotNone(state.node)
        _, _, action = self.drive(state, "...", start=30 * U)
        self.assertEqual(action, Action("sh", "git status"))

    def test_unbound_letter_resets(self):
        state, _, action = self.drive(self.session('"a" = { sh = "x" }'), "-...")
        self.assertIsNone(action)
        self.assertIsNone(state.node)
        self.assertEqual(state.marks, ())

    def test_impossible_prefix_resets_early(self):
        state, _, _ = self.drive(self.session('"a" = { sh = "x" }'), "......")
        self.assertEqual(state.marks, ())


if __name__ == "__main__":
    unittest.main()
