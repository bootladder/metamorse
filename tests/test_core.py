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


class TestTick(unittest.TestCase):
    """Idle-tick behaviour. Regression: ticks used a different clock from
    edges, so every tick read as an enormous gap and spammed WORD_GAP."""

    def idle(self, elapsed):
        """A demod that saw a dit ending at t=0, then ticked `elapsed` later."""
        from metamorse.demod import Demod
        state = Demod()
        for edge in edges(".")[0]:
            state, _ = state.step(edge)
        return state.tick(state.since + elapsed)

    def test_reports_each_gap_once(self):
        state, first = self.idle(3 * U)
        self.assertEqual(first, (Symbol.CHAR_GAP,))
        _, again = state.tick(state.since + 3.5 * U)
        self.assertEqual(again, ())

    def test_escalates_char_gap_to_word_gap(self):
        state, _ = self.idle(3 * U)
        _, later = state.tick(state.since + 8 * U)
        self.assertEqual(later, (Symbol.WORD_GAP,))

    def test_word_gap_reported_once(self):
        state, _ = self.idle(8 * U)
        _, again = state.tick(state.since + 20 * U)
        self.assertEqual(again, ())

    def test_no_gap_before_threshold(self):
        _, out = self.idle(U)
        self.assertEqual(out, ())

    def test_new_edge_rearms_gap_reporting(self):
        state, _ = self.idle(8 * U)
        state, _ = state.step(Edge(True, state.since + 10 * U))
        state, _ = state.step(Edge(False, state.since + U))
        _, out = state.tick(state.since + 3 * U)
        self.assertEqual(out, (Symbol.CHAR_GAP,))


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


class RecordingObserver:
    def __init__(self, resets):
        self.resets = resets

    def on_symbol(self, marks): pass
    def on_branch(self, path, node): pass
    def on_dispatch(self, path, node): pass
    def on_stray(self, letter, node): pass
    def on_reset(self, reason): self.resets.append(reason)


def replace_observer(session, resets):
    import dataclasses
    return dataclasses.replace(session, observer=RecordingObserver(resets))


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

    def test_idle_word_gap_is_silent(self):
        """Regression: idle ticks spammed 'word gap' resets forever."""
        state = self.session('"a" = { sh = "x" }')
        resets = []
        state = replace_observer(state, resets)
        for n in range(1, 6):
            state, _, _ = state.tick(n * 20 * U)
        self.assertEqual(resets, [])

    def test_letter_resolves_on_idle_tick(self):
        """Regression: '.--' printed marks but never dispatched."""
        state = self.session('"w" = { sh = "went" }')
        stream, end = edges(".--")
        for edge in stream:
            state, _, _ = state.step(edge)
        _, _, action = state.tick(end + 3 * U)
        self.assertEqual(action, Action("sh", "went"))

    def test_branch_survives_a_long_pause(self):
        """A word gap must not abandon a pending sequence; `hold` governs."""
        state = self.session('"g" = { hint = "git" }\n"g s" = { sh = "ok" }\n')
        state, _, _ = self.drive(state, "--.")
        self.assertIsNotNone(state.node)
        state, _, _ = state.tick(state.demod.since + 5.0)     # under hold
        self.assertIsNotNone(state.node)

    def test_branch_expires_after_hold(self):
        state = self.session('"g" = { hint = "git" }\n"g s" = { sh = "ok" }\n')
        state, _, _ = self.drive(state, "--.")
        state, _, _ = state.tick(state.demod.since + 12.0)    # over hold
        self.assertIsNone(state.node)

    def test_impossible_prefix_resets_early(self):
        state, _, _ = self.drive(self.session('"a" = { sh = "x" }'), "......")
        self.assertEqual(state.marks, ())


if __name__ == "__main__":
    unittest.main()
