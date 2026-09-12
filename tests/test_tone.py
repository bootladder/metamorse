"""Tone detection tests. Synthetic audio only -- no microphone required.

python3 -m unittest discover tests
"""
import unittest

import numpy as np

from metamorse.core.demod import Demod
from metamorse.core.symbols import Symbol, Timing
from metamorse.inputs.tone.detect import (HOP, WINDOW, Detector, Gate,
                                          Harmonicity, Spectrum, calibrate)

SR = 44100

# Standard tuning, open strings, plus fretted notes at both extremes.
GUITAR = {"low E": 82.41, "A": 110.0, "D": 146.83, "G": 196.0,
          "B": 246.94, "high E": 329.63, "E 12th": 659.25, "high fret": 1200.0}


def pluck(f0, n=WINDOW, amp=1.0, partials=4):
    """A plucked string: fundamental plus 1/k-weighted partials."""
    t = np.arange(n) / SR
    return amp * sum(np.sin(2 * np.pi * f0 * k * t) / k
                     for k in range(1, partials + 1))


def hum(f0=50.0, n=WINDOW):
    """Mains hum: rooted below the guitar range, partials reaching into it."""
    return pluck(f0, n)


def noise(n=WINDOW, amp=1.0, seed=0):
    return amp * np.random.default_rng(seed).standard_normal(n)


class TestHarmonicity(unittest.TestCase):
    """The pitched-vs-noise decision, which is what keeps a cough from
    dispatching a shell command."""

    def power(self, signal):
        return Harmonicity().hear(Spectrum.of(signal, SR)).power

    def test_any_guitar_note_keys(self):
        for name, f0 in GUITAR.items():
            with self.subTest(note=name):
                self.assertGreater(self.power(pluck(f0)), 0.0)

    def test_note_strength_is_pitch_independent(self):
        """Any note must key like any other, so the gate threshold does not
        have to be retuned per string."""
        powers = [self.power(pluck(f0)) for f0 in GUITAR.values()]
        self.assertLess(max(powers) / min(powers), 2.0)

    def test_rejects_silence(self):
        self.assertEqual(self.power(np.zeros(WINDOW)), 0.0)

    def test_rejects_broadband_noise(self):
        self.assertEqual(self.power(noise()), 0.0)

    def test_rejects_mains_hum(self):
        """Hum is pitched and its partials land inside the guitar window, so
        only the sub-range test excludes it."""
        for mains in (50.0, 60.0):
            with self.subTest(mains=mains):
                self.assertEqual(self.power(hum(mains)), 0.0)

    def test_rejects_subsonic_rumble(self):
        self.assertEqual(self.power(hum(30.0)), 0.0)

    def test_tone_above_range_cannot_key(self):
        """A 2kHz whistle leaks a trace of energy into the guitar window, so
        the honest assertion is not that it reads as zero but that it stays
        orders of magnitude below a real note -- far under any threshold
        `calibrate` would ever choose."""
        t = np.arange(WINDOW) / SR
        leak = self.power(np.sin(2 * np.pi * 2000 * t))
        self.assertLess(leak, 0.001 * self.power(pluck(110.0)))

    def test_quiet_note_still_keys(self):
        """Amplitude must not decide pitchedness -- that is the gate's job."""
        self.assertGreater(self.power(pluck(110.0, amp=0.05)), 0.0)


class TestGate(unittest.TestCase):
    """Hysteresis and hangover over a decaying signal."""

    def gate(self, **kw):
        return Gate(on=100.0, hangover=0.040, **kw)

    def test_opens_above_threshold(self):
        _, edge = self.gate().step(150.0, 1.0)
        self.assertTrue(edge.down)
        self.assertEqual(edge.t, 1.0)

    def test_stays_shut_below_threshold(self):
        _, edge = self.gate().step(50.0, 1.0)
        self.assertIsNone(edge)

    def test_holds_through_decay_above_off(self):
        """A ringing string decays well below the opening threshold; it must
        not release until it falls under the *off* threshold."""
        state, _ = self.gate().step(150.0, 0.0)
        state, edge = state.step(60.0, 0.1)     # below on, above off (25.0)
        self.assertIsNone(edge)
        self.assertTrue(state.down)

    def test_hangover_delays_release(self):
        state, _ = self.gate().step(150.0, 0.0)
        state, edge = state.step(1.0, 0.1)      # falls quiet
        self.assertIsNone(edge)                 # hangover not yet elapsed
        self.assertTrue(state.down)

    def test_releases_after_hangover(self):
        state, _ = self.gate().step(150.0, 0.0)
        state, _ = state.step(1.0, 0.1)
        state, edge = state.step(1.0, 0.2)
        self.assertIsNotNone(edge)
        self.assertFalse(edge.down)

    def test_release_is_dated_to_the_fall(self):
        """The mark ended when the signal fell, not when the hangover expired;
        misdating it would inflate every dit toward a dah."""
        state, _ = self.gate().step(150.0, 0.0)
        state, _ = state.step(1.0, 0.1)
        _, edge = state.step(1.0, 0.2)
        self.assertAlmostEqual(edge.t, 0.1)

    def test_dip_shorter_than_hangover_does_not_chatter(self):
        """Two strums of one sustained note must stay a single mark."""
        state, _ = self.gate().step(150.0, 0.0)
        state, edge = state.step(1.0, 0.10)     # brief dip
        self.assertIsNone(edge)
        state, edge = state.step(150.0, 0.12)   # recovers within hangover
        self.assertIsNone(edge)
        self.assertTrue(state.down)

    def test_no_edge_while_idle(self):
        state = self.gate()
        for i in range(5):
            state, edge = state.step(0.0, i * 0.05)
            self.assertIsNone(edge)


class TestCalibrate(unittest.TestCase):
    def test_ignores_silent_blocks(self):
        """Silence between notes must not drag the estimate toward zero."""
        self.assertEqual(calibrate([0.0, 0.0, 100.0, 100.0]),
                         calibrate([100.0, 100.0]))

    def test_resists_one_hard_pluck(self):
        """An outlier must not raise the bar above every normal note."""
        normal = calibrate([100.0] * 9)
        with_spike = calibrate([100.0] * 9 + [5000.0])
        self.assertAlmostEqual(normal, with_spike)

    def test_threshold_sits_below_a_normal_note(self):
        self.assertLess(calibrate([100.0] * 5), 100.0)

    def test_no_notes_heard(self):
        self.assertEqual(calibrate([0.0, 0.0]), 0.0)
        self.assertEqual(calibrate([]), 0.0)


class TestDetector(unittest.TestCase):
    """The composed chain, fed one hop at a time as `listen` feeds it."""

    def feed(self, detector, signal, start=0.0):
        """Push `signal` through in HOP-sized pieces, collecting edges."""
        edges, t = [], start
        for i in range(0, len(signal) - HOP + 1, HOP):
            t += HOP / SR
            detector, edge, _ = detector.step(signal[i:i + HOP], t)
            if edge:
                edges.append(edge)
        return detector, edges, t

    def detector(self, threshold=200.0):
        return Detector(SR, Harmonicity(), Gate(on=threshold, hangover=0.040))

    def test_note_then_silence_yields_a_mark(self):
        note = pluck(110.0, n=WINDOW * 3)
        quiet = np.zeros(WINDOW * 2)
        _, edges, _ = self.feed(self.detector(), np.concatenate((note, quiet)))
        self.assertGreaterEqual(len(edges), 2)
        self.assertTrue(edges[0].down)
        self.assertFalse(edges[1].down)

    def test_silence_alone_yields_nothing(self):
        _, edges, _ = self.feed(self.detector(), np.zeros(WINDOW * 4))
        self.assertEqual(edges, [])

    def test_noise_alone_yields_nothing(self):
        _, edges, _ = self.feed(self.detector(), noise(WINDOW * 4))
        self.assertEqual(edges, [])

    def test_observe_reports_power_without_gating(self):
        detector = self.detector()
        for i in range(0, WINDOW, HOP):
            detector, note = detector.observe(pluck(110.0)[i:i + HOP])
        self.assertGreater(note.power, 0.0)
        self.assertFalse(detector.gate.down)

    def test_observe_reports_the_pitch_it_heard(self):
        """The meter's whole purpose: play an A and be told it was an A."""
        detector = self.detector()
        for i in range(0, WINDOW, HOP):
            detector, note = detector.observe(pluck(110.0)[i:i + HOP])
        self.assertAlmostEqual(note.f0, 110.0, delta=6.0)
        self.assertTrue(note.sounding)


class TestToneToMorse(unittest.TestCase):
    """End to end over the real Demod: played notes must decode as Morse.

    This is the integration that matters -- it proves the audio front end
    produces edges the existing pure core already understands.
    """

    UNIT = 0.12          # the audio default: a string keys slower than a finger

    def render(self, pattern):
        """Render Morse as audio: notes for marks, silence for gaps."""
        parts = []
        for i, mark in enumerate(pattern):
            if i:
                parts.append(np.zeros(int(self.UNIT * SR)))       # 1u gap
            length = int(self.UNIT * SR * (3 if mark == "-" else 1))
            parts.append(pluck(110.0, n=length))
        return np.concatenate(parts)

    def symbols(self, pattern, trailing=6):
        """Play `pattern`, then hold silence so the final gap resolves."""
        audio = np.concatenate((np.zeros(WINDOW),          # settle the window
                                self.render(pattern),
                                np.zeros(int(trailing * self.UNIT * SR))))
        detector = Detector(SR, Harmonicity(), Gate(on=200.0, hangover=0.040))
        demod, out = Demod(Timing(self.UNIT, 10.0)), []
        t = 0.0
        for i in range(0, len(audio) - HOP + 1, HOP):
            t += HOP / SR
            detector, edge, _ = detector.step(audio[i:i + HOP], t)
            demod, symbols = (demod.step(edge) if edge else demod.tick(t))
            out.extend(symbols)
        return [s for s in out if s in (Symbol.DIT, Symbol.DAH)]

    def test_dit(self):
        self.assertEqual(self.symbols("."), [Symbol.DIT])

    def test_dah(self):
        self.assertEqual(self.symbols("-"), [Symbol.DAH])

    def test_letter_a(self):
        self.assertEqual(self.symbols(".-"), [Symbol.DIT, Symbol.DAH])

    def test_letter_n(self):
        self.assertEqual(self.symbols("-."), [Symbol.DAH, Symbol.DIT])

    def test_letter_s(self):
        self.assertEqual(self.symbols("..."), [Symbol.DIT] * 3)


if __name__ == "__main__":
    unittest.main()
