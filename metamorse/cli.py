"""Command line entry point: argparse wiring and one run path."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import config, doctor, service
from .core import (Action, Branch, Demod, Dispatcher, NullObserver,
                   Passthrough, Session, load, parse_chord, pump, shell)
from .inputs import open_input
from .ui.popup import OSD_FLAG

def _share() -> Path:
    """Where the default keymap ships.

    Frozen, the checkout is gone and PyInstaller unpacks bundled data under
    sys._MEIPASS, so walking up from __file__ lands in a temp directory that
    has no share/. Unfrozen, it is the sibling of the package.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "share"
    return Path(__file__).resolve().parent.parent / "share"


SHARE = _share()


RUNTIME_FOOTPRINT = {
    "linux": "one /dev/uinput device named 'metamorse' while running",
    "win32": "a low-level keyboard hook while running",
    "darwin": "an event tap while running (needs Accessibility)",
}


def cmd_install(args) -> int:
    """Writes the keymap. It installs nothing else -- the binary runs from
    wherever it sits, and nothing is copied or added to PATH."""
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if config.KEYMAP.exists() and not args.force:
        print(f"keymap already exists: {config.KEYMAP}  (--force to overwrite)")
    else:
        shutil.copy(SHARE / "keymap.toml", config.KEYMAP)
        print(f"wrote {config.KEYMAP}")
    print("\nfootprint:")
    print(f"  config   {config.CONFIG_DIR}/")
    print("  code     this directory (nothing installed system-wide)")
    print(f"  runtime  {RUNTIME_FOOTPRINT.get(sys.platform, 'a keyboard hook')}")
    print("\nnext: metamorse edit   (your keymap)"
          "\n      metamorse doctor  (check it can run)")
    return 0


EDITORS = {
    "win32": lambda path: ["notepad", str(path)],
    "darwin": lambda path: ["open", "-t", str(path)],
}


def editor_command(path: Path) -> list[str]:
    """How this platform opens a text file for editing.

    $EDITOR wins everywhere when it is set -- someone who exported it means
    it. Otherwise each platform has an obvious answer and Linux falls back to
    the desktop's.
    """
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if editor:
        return [editor, str(path)]
    return EDITORS.get(sys.platform, lambda p: ["xdg-open", str(p)])(path)


def cmd_edit(args) -> int:
    """Open the keymap in an editor. Finding the file is the hard part on
    Windows, where it lives somewhere no one would think to look."""
    if not config.KEYMAP.exists():
        print(f"no keymap at {config.KEYMAP}\nrun: metamorse install")
        return 1
    command = editor_command(config.KEYMAP)
    print(f"opening {config.KEYMAP}")
    try:
        return subprocess.call(command)
    except FileNotFoundError:
        print(f"could not run {command[0]!r}.\nedit it yourself: {config.KEYMAP}")
        return 1


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


def cmd_logs(args) -> int:
    """The daemon runs under systemd, so its output lives in the journal."""
    return subprocess.call(["journalctl", "--user", "-u", service.UNIT,
                            *(["-f"] if args.follow else ["-n", "50"])])


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


def _observer(args, keymap):
    """Tap mode narrates to stdout; otherwise the OSD, unless suppressed."""
    if getattr(args, "dry_run", False) or getattr(args, "tap", False):
        return TapObserver()
    if getattr(args, "no_popup", False):
        return NullObserver()
    from .ui import PopupObserver
    return PopupObserver(keymap)


def _dispatcher(args, sink) -> Dispatcher:
    """Dry runs decode and print but never execute -- that is what makes them
    safe for tuning `unit` against real keying."""
    if getattr(args, "dry_run", False) or getattr(args, "tap", False):
        return Dispatcher(lambda command: None, lambda chord: None)
    return Dispatcher(shell, lambda chord: sink.chord(*parse_chord(chord)))


def run(args, source: str | None = None) -> int:
    """The one run path. `run`, `tap` and `listen` differ only in which input
    they open, whether they narrate, and whether they execute."""
    settings = config.Settings.load()
    keymap = load(config.KEYMAP)
    source = open_input(source or settings.input, settings,
                        **({"notes": True} if getattr(args, "notes", False) else {}))
    print(f"{source.banner}.  ctrl-c to stop.")

    observer = _observer(args, keymap)
    starter = getattr(observer, "start", None)
    if starter:
        starter()            # pay GUI startup now, not on the first menu

    session = Session(keymap, source.timing, observer, Demod(source.timing),
                      Passthrough(settings.immediate))
    try:
        # The clock comes from the source: evdev stamps CLOCK_REALTIME, audio
        # counts samples, and tick() compares against those stamps directly.
        pump(session, source.stream, source.sink, source.key,
             _dispatcher(args, source.sink), source.clock)
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        stopper = getattr(observer, "stop", None)
        if stopper:
            stopper()
    return 0


def _add_tone_parsers(subs) -> None:
    """Tone is optional. Its parsers describe commands that need numpy and
    sounddevice; when those are absent the commands simply do not exist, and
    the rest of the CLI is unaffected."""
    try:
        from .inputs.tone.commands import add_parsers
    except ImportError:
        return
    add_parsers(subs, run)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == OSD_FLAG:
        from .ui.osd import main as osd_main
        return osd_main()          # the frozen exe re-invoking itself

    parser = argparse.ArgumentParser(prog="metamorse",
                                     description="Morse code on the meta key.")
    subs = parser.add_subparsers(dest="cmd", required=True)

    install = subs.add_parser("install", help="write the default config")
    install.add_argument("--force", action="store_true")
    install.set_defaults(fn=cmd_install)

    subs.add_parser("doctor", help="check the system can run metamorse"
                    ).set_defaults(fn=cmd_doctor)
    subs.add_parser("keys", help="print the keymap").set_defaults(fn=cmd_keys)
    subs.add_parser("edit", help="open the keymap in an editor"
                    ).set_defaults(fn=cmd_edit)

    run_cmd = subs.add_parser("run", help="start the daemon")
    run_cmd.add_argument("--no-popup", action="store_true",
                         help="suppress the on-screen menu")
    run_cmd.set_defaults(fn=run)

    tap = subs.add_parser("tap", help="decode to stdout without dispatching")
    tap.add_argument("--no-popup", action="store_true", help=argparse.SUPPRESS)
    tap.set_defaults(fn=run, tap=True)

    logs = subs.add_parser("logs", help="show the daemon's journal")
    logs.add_argument("-f", "--follow", action="store_true")
    logs.set_defaults(fn=cmd_logs)

    service.add_parsers(subs)
    _add_tone_parsers(subs)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
