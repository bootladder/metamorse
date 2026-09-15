# metamorse

Morse code on the meta key.

Tap Meta and it stays a plain Meta tap. Hold it in patterns — dot, dash — and
it dispatches commands. `Meta+x` chords keep working untouched.

## The `e` contract

A single dot is Morse `e`. A bare Meta tap is a single dot. So `e` is
permanently unbound: tapping Meta decodes to `e`, dispatches nothing, and the
keypress is replayed to whatever has focus. That one reserved letter is what
buys collision-free coexistence with every existing Meta binding.

## Install

    ./install.sh

It prints its full footprint and asks before each step. `--yes` to accept all,
`--uninstall` to reverse it.

**Footprint — everything it touches:**

| Path | What |
|---|---|
| `~/.local/bin/metamorse` | 3-line launcher pointing at this checkout |
| `~/.config/metamorse/keymap.toml` | your keymap; never overwritten |
| `~/.config/metamorse/tone.toml` | tone settings, if you use `tune` |
| `~/.config/systemd/user/metamorse.service` | user unit, enabled to start with your graphical session (optional) |
| `/etc/udev/rules.d/99-metamorse.rules` | `input` group access to `/dev/uinput` (sudo, optional) |
| `input` group membership | needed to read the keyboard (sudo, optional) |

No system-wide unit, no shell rc edits, no system python changes, nothing
copied outside those paths.

The unit is a *user* unit, not a system one: metamorse runs as you, inside
your session. It sets `DISPLAY=:0` — the OSD is a tkinter subprocess and a
systemd user unit inherits no display of its own. Decline it and metamorse
runs when you say so.

    metamorse service enable    install the unit and start it at login
    metamorse service remove    stop it and delete the unit
    metamorse logs [-f]         what the daemon is saying

**Dependencies:** python 3.11+ and `python-evdev` from your distro
(`apt install python3-evdev`). Nothing from pip; no virtualenv.

Keying with a guitar instead (`metamorse listen`) additionally needs numpy and
sounddevice. That input is optional and self-contained: without those packages
the tone commands simply do nothing you would notice, and `metamorse run`
never imports them.

## Windows

Download `metamorse.exe` from the build artifacts — a single file, no Python
to install. Then:

    metamorse.exe doctor    check it can run
    metamorse.exe install   write the default keymap
    metamorse.exe run       start it in this terminal

The default key is the left Windows key. Windows binds that itself: a bare
tap opens the Start menu, and Win+L and Win+G are reserved by the shell.
metamorse replays the tap only when your gesture decodes to a bare `e`, so
tapping still opens Start — but the reserved chords stay Windows'. If you
would rather not share, name another key:

    # %USERPROFILE%\.config\metamorse\metamorse.toml
    key = "capslock"

The shipped keymap launches Linux programs, so it is a starting point to
edit rather than something to use as-is.

**Not yet on Windows:** starting at login (no service equivalent of the
systemd unit yet), and keying with a guitar — the tone input is Linux-only
on purpose and its commands simply do not appear.

Building it yourself needs a Windows machine: PyInstaller bundles the host
interpreter and cannot cross-compile from Linux. `pip install pyinstaller`
then `pyinstaller packaging/metamorse.spec`. The GitHub Actions workflow in
`.github/workflows/windows.yml` does exactly that on every push.

## macOS

Download the `metamorse-macos` build, then:

    chmod +x metamorse
    ./metamorse doctor     tells you what is missing, including permission
    ./metamorse install    write the default keymap
    ./metamorse run        start it in this terminal

**Accessibility permission is required.** An event tap without it installs
successfully and then silently delivers nothing, so metamorse checks up
front and refuses rather than looking broken. Grant it in System Settings >
Privacy & Security > Accessibility.

The default key is **right Command**. Left Command runs the entire platform —
copy, paste, every menu shortcut — so keying Morse on it would be a fight.
Right Command is the same key as far as the OS is concerned, and almost
nothing binds it alone. `key = "capslock"` is the other good answer.

If macOS quarantines the download (browser downloads only), either
`xattr -d com.apple.quarantine metamorse` or fetch it with `curl`, which
does not set the flag. The binary is unsigned: signing it so *other* people
avoid that prompt needs a paid Apple Developer ID, which this project does
not have.

The shipped keymap launches Linux programs, so it is a starting point to
edit rather than something to use as-is.

**Not yet on macOS:** starting at login, and keying with a guitar — the tone
input is Linux-only on purpose.

## Use

    metamorse doctor   check the system is ready; prints a fix for each failure
    metamorse keys     print the keymap as a tree
    metamorse tap      decode to stdout, dispatching nothing — tune timing here
    metamorse run      start it in this terminal
    metamorse logs     what the daemon under systemd is saying

Start with `tap`. It shows what you're actually keying without running
anything, which is how you find your `unit`.

## Configure

`~/.config/metamorse/keymap.toml` — paths are space-separated Morse letters:

    "t"   = { sh = "x-terminal-emulator" }
    "g"   = { hint = "git" }              # a branch: prefix, no action
    "g s" = { sh = "git status" }
    "w c" = { key = "super+c" }           # synthesize a chord

`sh` runs a detached shell command; `key` synthesizes a chord; `hint` labels
a branch for the (not yet built) on-screen display.

`~/.config/metamorse/metamorse.toml` — daemon settings:

    key = "leftmeta"    # any evdev key name; "capslock" is a common choice
    unit = 0.09         # seconds. dit=1u, dah=3u, char gap=3u, word gap=7u
    hold = 2.0          # seconds to wait mid-sequence before giving up
    immediate = false   # release Meta-up instantly (see Timing)

`~/.config/metamorse/tone.toml` — only if you key with a guitar. Written by
`metamorse tune`, which measures the gate threshold from you actually playing;
it cannot be guessed, since it depends on the guitar, the mic and the gain.

Decoding is reliable to about ±30% timing jitter. If you misfire often, raise
`unit` — slower is more forgiving.

`hold` is separate from Morse timing on purpose: it is how long a half-typed
sequence like `g …` waits for its next letter. Morse's own word gap (7 units,
~630ms) is far too brisk for a human deciding what to press next.

## Timing

Meta-down is emitted downstream immediately, so chords stay zero-latency.
Meta-up is withheld until the letter resolves, because a *held* modifier is
inert in X11 while a *released* one can trigger menu and overlay bindings.
The delay lands only on the release edge of Morse input, where nothing
perceives it.

If your WM binds a bare Meta *press* (some overlay keys do), set
`immediate = true`. You'll see the overlay flicker during Morse entry.

## Architecture

    metamorse/
      core/     the correctness surface — pure, no I/O, no display, no device
      inputs/   key.py (evdev), tone/ (guitar, optional)
      ui/       the on-screen menu
      cli.py    argparse wiring and one run path

    Input ─→ Demod ─→ Decode ─→ Session ─→ Dispatch ─→ sh / uinput chord
                │        │         │
                └────────┴─────────┴──→ Observer ──→ OSD
                         │
              Passthrough policy ──→ uinput (replays the real meta key)

The arrows run one way. `core/` imports neither `inputs/` nor `ui/`, so the
whole decoding path tests without X11, audio or root:

    python3 -m unittest discover -s tests

**Inputs.** An input is anything that produces key edges. `inputs.Input`
bundles a stream with its sink, clock and timing; openers register by name and
are imported only when asked for, which is why running on the meta key never
imports numpy. Adding an input means writing an opener and registering it —
no other file changes.

The clock travels *with* the stream because each source owns its timebase:
evdev stamps `CLOCK_REALTIME` while audio counts samples, and `Demod` requires
edges and idle ticks to share one. Mixing them makes every gap read as
enormous and floods the decoder with word gaps.

**Feedback.** `Observer` is the seam the OSD implements. The popup runs as its
own process so tkinter's mainloop never blocks the event loop, and it is
spawned at start and parked off-screen rather than mapped and unmapped per
menu — the window manager re-mapping from nothing was the dominant cost of
showing a menu.

## Status

Working: capture, demodulation, decoding, trie dispatch, passthrough, the
on-screen menu, tone input, the CLI, the installer and the systemd unit.

Not built: Wayland — evdev capture is compositor-agnostic, but synthesized
chords still go through uinput and depend on the compositor accepting them.
