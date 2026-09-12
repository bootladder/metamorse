"""Tone's own subcommands. Registered by the CLI only when tone is asked for,
so `metamorse run` never imports numpy."""
from __future__ import annotations

from dataclasses import replace

from . import SETTINGS, Tone
from .notes import name


def cmd_devices(args) -> int:
    from .capture import devices, require_audio
    found = devices(require_audio())
    if not found:
        print("no audio input devices found.")
        return 1
    print("audio inputs:\n")
    for index, name, rate in found:
        print(f"  [{index}]  {name}   ({rate:.0f} Hz)")
    print(f"\nset one in {SETTINGS}:\n\n  device = \"pulse\"")
    return 0


def cmd_tune(args) -> int:
    """Measure a gate threshold from actual playing, then save it.

    Nothing about a threshold can be guessed -- it depends on the guitar, the
    mic and the gain -- so it is measured rather than defaulted.
    """
    from .capture import find_input, measure, open_stream, require_audio
    from .detect import Detector
    sd = require_audio()
    tone = Tone.load()
    stream = open_stream(sd, find_input(sd, tone.name), tone.samplerate)
    print(f"tuning for {args.seconds:.0f}s -- play single notes, "
          "as you would key them.\n")

    def meter(t, note):
        """`notes.bar` draws against a threshold, and tuning is what produces
        one -- so the scale here is absolute. The pitch is still worth showing:
        it is what tells you `tune` is hearing the guitar and not the fridge."""
        bar = "#" * min(40, int(note.power / 25))
        pitch = f"{note.f0:6.1f}Hz {name(note.f0):>4}" if note.sounding else " " * 12
        print(f"\r  {t:5.1f}s  {pitch}  {note.power:9.1f}  {bar:<40}",
              end="", flush=True)

    threshold = measure(stream, Detector(tone.samplerate), args.seconds, meter)
    print()
    if threshold <= 0.0:
        print("\nheard no pitched notes. Is the right device selected?  "
              "`metamorse devices`")
        return 1
    print(f"\nthreshold = {threshold:.6g}")
    if args.dry_run:
        print("(--dry-run: not saved)")
        return 0
    replace(tone, threshold=threshold).save()
    print(f"saved to {SETTINGS}\n\nnext: metamorse listen --dry-run")
    return 0


def add_parsers(subs, run) -> None:
    """Contribute tone's commands. `run` is the shared runner from the CLI."""
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
    listen.add_argument("--notes", action="store_true",
                        help="print every block: pitch, note name, power, gate")
    listen.set_defaults(fn=lambda args: run(args, source="tone"))
