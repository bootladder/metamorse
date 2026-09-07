"""Command line entry point."""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import config, doctor
from .core import (Action, Branch, Dispatcher, NullObserver, Session, Timing,
                   load, parse_chord, pump, shell)
from .inputs.key import (TICK, events, find_keyboards, open_sink,
                         require_evdev, resolve_key)

SHARE = Path(__file__).resolve().parent.parent / "share"


def cmd_install(args) -> int:
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if config.KEYMAP.exists() and not args.force:
        print(f"keymap already exists: {config.KEYMAP}  (--force to overwrite)")
    else:
        shutil.copy(SHARE / "keymap.toml", config.KEYMAP)
        print(f"wrote {config.KEYMAP}")
    print("\nfootprint:")
    print(f"  config   {config.CONFIG_DIR}/")
    print("  code     this directory (nothing installed system-wide)")
    print("  runtime  one /dev/uinput device named 'metamorse' while running")
    print("\nnext: metamorse doctor")
    return 0


def cmd_doctor(args) -> int:
    return doctor.report()


def _walk(node: Branch, prefix: str = "") -> list[tuple[str, str, str]]:
    rows = []
    for letter, child in sorted(node.children.items()):
        path = f"{prefix}{letter}"
        if isinstance(child, Action):
            rows.append((path, f"{child.kind}: {child.arg}", child.hint))
        else:
            rows.append((path, f"+{len(child.children)} more", child.hint))
            rows.extend(_walk(child, f"{path} "))
    return rows


def cmd_keys(args) -> int:
    keymap = load(config.KEYMAP)
    rows = _walk(keymap)
    width = max((len(path) for path, _, _ in rows), default=0)
    for path, what, hint in rows:
        note = f"   ({hint})" if hint else ""
        print(f"  {path:<{width}}  {what}{note}")
    return 0


def _session(settings, keymap, observer=None, timing=None) -> Session:
    """`timing` overrides the key timing -- audio keys slower than a finger."""
    from .core import Demod, Passthrough
    timing = timing or settings.timing
    return Session(keymap, timing, observer or NullObserver(),
                   Demod(timing), Passthrough(settings.immediate))


class TapObserver:
    """Prints the buffer as it fills. Used by `metamorse tap`."""

    def on_symbol(self, marks):
        code = "".join(m.value for m in marks)
        print(f"\r  {code:<8}", end="", flush=True)

    def on_branch(self, path, node):
        print(f"\r  {path} ...  {node.hint}")

    def on_dispatch(self, path, node):
        print(f"\r  {path}  ->  {node.kind}: {node.arg}")

    def on_stray(self, letter, node):
        print(f"\r  ??  '{letter}' not in this menu")

    def on_reset(self, reason):
        print(f"\r  --  {reason}")


@dataclass(frozen=True, slots=True)
class Source:
    """Everything a run needs from its input, including its clock.

    The clock travels with the source because each one owns its timebase and
    Demod requires edges and idle ticks to share it: evdev stamps events with
    CLOCK_REALTIME, while audio counts samples. Letting a caller pair the
    wrong clock with a stream is the bug this bundling prevents.
    """
    stream: object
    sink: object
    key: int
    clock: object
    timing: Timing
    banner: str


def _key_source(settings) -> Source:
    evdev = require_evdev()
    key = resolve_key(evdev, settings.key)
    found = find_keyboards(evdev)
    if not found:
        raise SystemExit("no keyboard found (are you in the 'input' group?)")
    sink = open_sink(evdev)
    return Source(events(evdev, found, key, TICK), sink, key,
                  time.time,          # CLOCK_REALTIME, matching evdev stamps
                  settings.timing,
                  f"metamorse: {settings.key} on {len(found)} device(s), "
                  f"unit={settings.timing.unit*1000:.0f}ms")


def _tone_source(settings) -> Source:
    """Audio in, same sink out: a tone resolves to a letter and dispatches
    exactly as a keyed one does, and chord actions still need a real Meta to
    press, so the uinput sink is unchanged."""
    from .inputs.tone.capture import (Clock, edges, find_input,
                                     open_stream, require_audio)
    from .inputs.tone.detect import Detector, Gate, Harmonicity
    audio = settings.audio
    if audio.threshold <= 0.0:
        raise SystemExit("audio threshold is not calibrated.\n"
                         "Run `metamorse tune` first (it plays nothing; you play).")
    sd = require_audio()
    evdev = require_evdev()
    key = resolve_key(evdev, settings.key)
    sink = open_sink(evdev)
    stream = open_stream(sd, find_input(sd, audio.name), audio.samplerate)
    detector = Detector(audio.samplerate, Harmonicity(),
                        Gate(audio.threshold, hangover=audio.hangover))
    clock = Clock()
    return Source(edges(stream, detector, TICK, clock), sink, key,
                  clock, audio.timing,
                  f"metamorse: listening, unit={audio.timing.unit*1000:.0f}ms, "
                  f"threshold={audio.threshold:.4g}")


def _run(args, make_observer, make_dispatcher, open_source=_key_source) -> int:
    settings = config.Settings.load()
    keymap = load(config.KEYMAP)
    source = open_source(settings)
    print(f"{source.banner}.  ctrl-c to stop.")
    observer = make_observer(args, keymap)
    starter = getattr(observer, "start", None)
    if starter:
        starter()            # pay GUI startup now, not on the first menu
    try:
        # The clock comes from the source: evdev stamps CLOCK_REALTIME, audio
        # counts samples, and tick() compares against those stamps directly.
        pump(_session(settings, keymap, observer, source.timing),
             source.stream, source.sink, source.key,
             make_dispatcher(source.sink), source.clock)
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        stopper = getattr(observer, "stop", None)
        if stopper:
            stopper()
    return 0


def _observer(args, keymap):
    if args.no_popup:
        return NullObserver()
    from .ui import PopupObserver
    return PopupObserver(keymap)


def cmd_run(args) -> int:
    def live(sink) -> Dispatcher:
        return Dispatcher(shell, lambda chord: sink.chord(*parse_chord(chord)))
    return _run(args, _observer, live)


def cmd_tap(args) -> int:
    """Decode and print, but never execute. For tuning `unit`."""
    noop = Dispatcher(lambda cmd: None, lambda chord: None)
    return _run(args, lambda a, k: TapObserver(), lambda sink: noop)


def cmd_listen(args) -> int:
    """Same pipeline, guitar instead of the meta key."""
    def live(sink) -> Dispatcher:
        return Dispatcher(shell, lambda chord: sink.chord(*parse_chord(chord)))
    dispatcher = (lambda sink: Dispatcher(lambda c: None, lambda c: None)) \
        if args.dry_run else live
    observer = (lambda a, k: TapObserver()) if args.dry_run else _observer
    return _run(args, observer, dispatcher, _tone_source)


def cmd_devices(args) -> int:
    from .inputs.tone.capture import devices, require_audio
    found = devices(require_audio())
    if not found:
        print("no audio input devices found.")
        return 1
    print("audio inputs:\n")
    for index, name, rate in found:
        print(f"  [{index}]  {name}   ({rate:.0f} Hz)")
    print("\nset one in metamorse.toml:\n\n  [audio]\n  device = \"pulse\"")
    return 0


def cmd_tune(args) -> int:
    """Measure a gate threshold from actual playing, then save it.

    Nothing about a threshold can be guessed -- it depends on the guitar, the
    mic and the gain -- so it is measured rather than defaulted.
    """
    from .inputs.tone.capture import (find_input, measure, open_stream,
                                     require_audio)
    from .inputs.tone.detect import Detector
    sd = require_audio()
    settings = config.Settings.load()
    audio = settings.audio
    stream = open_stream(sd, find_input(sd, audio.name), audio.samplerate)
    print(f"tuning for {args.seconds:.0f}s -- play single notes, "
          "as you would key them.\n")

    def meter(t, power):
        bar = "#" * min(40, int(power / 25))
        print(f"\r  {t:5.1f}s  {power:9.1f}  {bar:<40}", end="", flush=True)

    threshold = measure(stream, Detector(audio.samplerate), args.seconds, meter)
    print()
    if threshold <= 0.0:
        print("\nheard no pitched notes. Is the right device selected?  "
              "`metamorse devices`")
        return 1
    print(f"\nthreshold = {threshold:.6g}")
    if args.dry_run:
        print("(--dry-run: not saved)")
        return 0
    config.save_threshold(threshold)
    print(f"saved to {config.SETTINGS}\n\nnext: metamorse listen --dry-run")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="metamorse",
                                     description="Morse code on the meta key.")
    subs = parser.add_subparsers(dest="cmd", required=True)

    install = subs.add_parser("install", help="write the default config")
    install.add_argument("--force", action="store_true")
    install.set_defaults(fn=cmd_install)

    subs.add_parser("doctor", help="check the system can run metamorse"
                    ).set_defaults(fn=cmd_doctor)
    subs.add_parser("keys", help="print the keymap").set_defaults(fn=cmd_keys)
    run_cmd = subs.add_parser("run", help="start the daemon")
    run_cmd.add_argument("--no-popup", action="store_true",
                         help="suppress the on-screen menu")
    run_cmd.set_defaults(fn=cmd_run)

    tap = subs.add_parser("tap", help="decode to stdout without dispatching")
    tap.add_argument("--no-popup", action="store_true", help=argparse.SUPPRESS)
    tap.set_defaults(fn=cmd_tap)

    subs.add_parser("devices", help="list audio inputs"
                    ).set_defaults(fn=cmd_devices)

    tune = subs.add_parser("tune", help="calibrate the tone threshold")
    tune.add_argument("--seconds", type=float, default=10.0,
                      help="how long to listen (default 10)")
    tune.add_argument("--dry-run", action="store_true",
                      help="measure but do not save")
    tune.set_defaults(fn=cmd_tune)

    listen = subs.add_parser("listen", help="key metamorse with a guitar")
    listen.add_argument("--dry-run", action="store_true",
                        help="decode to stdout without dispatching")
    listen.add_argument("--no-popup", action="store_true",
                        help="suppress the on-screen menu")
    listen.set_defaults(fn=cmd_listen)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
