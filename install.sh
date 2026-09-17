#!/bin/sh
# metamorse installer. Shows every change before making it; makes none without
# consent. Re-runnable. Uninstall with: ./install.sh --uninstall
set -eu

PREFIX="${PREFIX:-$HOME/.local}"
BIN="$PREFIX/bin/metamorse"
SRC="$(cd "$(dirname "$0")" && pwd)"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/metamorse"
RULE=/etc/udev/rules.d/99-metamorse.rules
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/metamorse.service"

ASSUME_YES=${ASSUME_YES:-0}

say() { printf '%s\n' "$*"; }
ask() {
    [ "$ASSUME_YES" = 1 ] && { say "$1 [auto-yes]"; return 0; }
    printf '%s [y/N] ' "$1"
    if { : </dev/tty; } 2>/dev/null; then
        read -r reply </dev/tty || reply=n
    else
        read -r reply || reply=n
    fi
    case "$reply" in [yY]*) return 0 ;; *) return 1 ;; esac
}

uninstall() {
    say "This removes:"
    say "  $BIN"
    say "  $UNIT  (stopped and disabled first)"
    say "  $RULE            (needs sudo)"
    say "  $CONFIG/  -- your keymap, KEPT unless you delete it yourself"
    ask "Proceed?" || exit 0
    if [ -f "$UNIT" ]; then
        systemctl --user disable --now metamorse.service 2>/dev/null || true
        rm -f "$UNIT"
        systemctl --user daemon-reload 2>/dev/null || true
        say "removed $UNIT"
    fi
    rm -f "$BIN" && say "removed $BIN"
    [ -f "$RULE" ] && sudo rm -f "$RULE" && sudo udevadm control --reload-rules
    say "done. config left at $CONFIG"
    exit 0
}

for arg in "$@"; do
    case "$arg" in
        --uninstall) UNINSTALL=1 ;;
        --yes|-y) ASSUME_YES=1 ;;
        *) say "unknown option: $arg"; exit 2 ;;
    esac
done
[ "${UNINSTALL:-0}" = 1 ] && uninstall

cat <<EOF
metamorse install
=================

Morse code on the meta key. A bare Meta tap stays a bare Meta tap; longer
patterns dispatch commands.

FOOTPRINT -- everything this touches:

  1. $BIN
     A 3-line launcher pointing at this checkout. Nothing is copied;
     the code stays in $SRC

  2. $CONFIG/keymap.toml and $CONFIG/metamorse.toml
     Your keymap and daemon settings. Written only if absent -- yours are
     never overwritten.

  3. $RULE
     Grants the 'input' group access to /dev/uinput, needed to replay the
     meta key. Requires sudo. Skipped if you decline.

  4. Group membership: adds you to 'input' if needed (sudo, needs re-login).

  5. $UNIT
     A systemd *user* unit, enabled so metamorse starts at login. No root:
     it runs as you. Decline and nothing is written; start it yourself
     with 'metamorse run'.

NOT touched: no system-wide unit, no shell rc, no system python, no files
outside the paths above.

Dependencies: python 3.11+ and python-evdev (from your distro's packages).

EOF

ask "Continue?" || exit 0

# 1. launcher
mkdir -p "$PREFIX/bin"
cat > "$BIN" <<LAUNCHER
#!/bin/sh
cd '$SRC' || exit 1
exec python3 -m metamorse.cli "\$@"
LAUNCHER
chmod +x "$BIN"
say "installed $BIN"

# 2. config
mkdir -p "$CONFIG"
for f in keymap metamorse; do
    if [ -f "$CONFIG/$f.toml" ]; then
        say "kept existing $CONFIG/$f.toml"
    else
        cp "$SRC/share/$f.toml" "$CONFIG/$f.toml"
        say "wrote $CONFIG/$f.toml"
    fi
done

# 3. udev rule
if [ -w /dev/uinput ]; then
    say "/dev/uinput already writable -- skipping udev rule"
elif ask "Install udev rule at $RULE? (needs sudo)"; then
    if echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee "$RULE" >/dev/null; then
        sudo udevadm control --reload-rules && sudo udevadm trigger
        sudo modprobe uinput 2>/dev/null || true
        say "installed $RULE"
    else
        say "could not write $RULE -- run 'metamorse doctor' for the manual steps"
    fi
else
    say "skipped -- metamorse will need to run as root without it"
fi

# 4. input group
if id -nG | tr ' ' '\n' | grep -qx input; then
    say "already in 'input' group"
elif ask "Add ${USER:-$(id -un)} to the 'input' group? (needs sudo, then re-login)"; then
    if sudo usermod -aG input "${USER:-$(id -un)}"; then
        say "added -- LOG OUT AND BACK IN for this to take effect"
    else
        say "could not add to group -- see 'metamorse doctor'"
    fi
fi

# 5. systemd user unit -- written by the CLI, so the unit lives in one place
if ask "Install and enable the systemd user unit at $UNIT?"; then
    "$BIN" service enable || say "could not enable -- 'metamorse logs' for why"
else
    say "skipped -- run 'metamorse service enable' later, or just 'metamorse run'"
fi

cat <<EOF

done.

  metamorse doctor   check everything is ready
  metamorse keys     show your keymap
  metamorse tap      watch decoding live, dispatching nothing
  metamorse logs     the running daemon's output
  metamorse run      start it in this terminal

If '$BIN' is not found, add $PREFIX/bin to your PATH.
EOF
