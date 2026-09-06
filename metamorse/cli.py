"""Command line entry point."""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from . import config, doctor
from .decode import decode
from .dispatch import Dispatcher, parse_chord, shell
from .keymap import Action, Branch, load
from .observer import NullObserver
from .policy import Emit
from .session import Session
from .source import (events, find_keyboards, open_sink, pump, require_evdev,
                     resolve_key, TICK)
from .symbols import Symbol

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


def _session(settings, keymap, observer=None) -> Session:
    from .policy import Passthrough
    from .demod import Demod
    return Session(keymap, settings.timing, observer or NullObserver(),
                   Demod(settings.timing), Passthrough(settings.immediate))


class TapObserver:
    """Prints the buffer as it fills. Used by `metamorse tap`."""

    def on_symbol(self, marks):
        code = "".join(m.value for m in marks)
        print(f"\r  {code:<8}", end="", flush=True)

    def on_branch(self, path, node):
        print(f"\r  {path} ...  {node.hint}")

    def on_dispatch(self, path, node):
        print(f"\r  {path}  ->  {node.kind}: {node.arg}")

    def on_reset(self, reason):
        print(f"\r  --  {reason}")


def _run(args, make_observer, make_dispatcher) -> int:
    evdev = require_evdev()
    settings = config.Settings.load()
    keymap = load(config.KEYMAP)
    key = resolve_key(evdev, settings.key)
    devices = find_keyboards(evdev)
    if not devices:
        raise SystemExit("no keyboard found (are you in the 'input' group?)")
    sink = open_sink(evdev)
    print(f"metamorse: {settings.key} on {len(devices)} device(s), "
          f"unit={settings.timing.unit*1000:.0f}ms.  ctrl-c to stop.")
    stream = events(evdev, devices, key, TICK)
    observer = make_observer(args, keymap)
    starter = getattr(observer, "start", None)
    if starter:
        starter()            # pay GUI startup now, not on the first menu
    try:
        # time.time(), not monotonic: evdev timestamps are CLOCK_REALTIME
        # and tick() compares against them directly.
        pump(_session(settings, keymap, observer),
             stream, sink, key, make_dispatcher(sink), time.time)
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
    from .popup import PopupObserver
    return PopupObserver(keymap)


def cmd_run(args) -> int:
    def live(sink) -> Dispatcher:
        return Dispatcher(shell, lambda chord: sink.chord(*parse_chord(chord)))
    return _run(args, _observer, live)


def cmd_tap(args) -> int:
    """Decode and print, but never execute. For tuning `unit`."""
    noop = Dispatcher(lambda cmd: None, lambda chord: None)
    return _run(args, lambda a, k: TapObserver(), lambda sink: noop)


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

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
