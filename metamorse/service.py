"""The systemd user unit: install, enable, remove.

A user unit, not a system one: the uinput chord and the tkinter menu both need
a graphical session, so metamorse is bound to `graphical-session.target`
rather than starting at boot into a display that is not there yet.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

UNIT = "metamorse.service"
UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
UNIT_PATH = UNIT_DIR / UNIT

TEMPLATE = """\
[Unit]
Description=metamorse -- morse code on the meta key
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart={exec_start} run
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
"""


def _systemctl(*args: str) -> int:
    return subprocess.call(["systemctl", "--user", *args])


def unit_text(launcher: Path | str) -> str:
    return TEMPLATE.format(exec_start=launcher)


def install(launcher: Path | str, enable: bool = True) -> int:
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    UNIT_PATH.write_text(unit_text(launcher))
    print(f"wrote {UNIT_PATH}")
    _systemctl("daemon-reload")
    if not enable:
        print(f"not enabled. Start it with: systemctl --user start {UNIT}")
        return 0
    code = _systemctl("enable", "--now", UNIT)
    print(f"enabled and started {UNIT}" if code == 0 else
          f"could not enable {UNIT} -- see: systemctl --user status {UNIT}")
    return code


def uninstall() -> int:
    if UNIT_PATH.exists():
        _systemctl("disable", "--now", UNIT)
        UNIT_PATH.unlink()
        _systemctl("daemon-reload")
        print(f"removed {UNIT_PATH}")
    else:
        print(f"no unit at {UNIT_PATH}")
    return 0


def cmd_service(args) -> int:
    if args.action == "remove":
        return uninstall()
    launcher = Path.home() / ".local" / "bin" / "metamorse"
    return install(launcher, enable=args.action == "enable")


def add_parsers(subs) -> None:
    service = subs.add_parser("service", help="manage the systemd user unit")
    service.add_argument("action", choices=("enable", "install", "remove"),
                         help="enable: install and start at login; "
                              "install: write the unit only; "
                              "remove: stop and delete it")
    service.set_defaults(fn=cmd_service)
