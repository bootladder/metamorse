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
| `/etc/udev/rules.d/99-metamorse.rules` | `input` group access to `/dev/uinput` (sudo, optional) |
| `input` group membership | needed to read the keyboard (sudo, optional) |

No systemd unit, no autostart, no shell rc edits, no system python changes,
nothing copied outside those paths. It runs only when you start it.

**Dependencies:** python 3.11+ and `python-evdev` from your distro
(`apt install python3-evdev`). Nothing from pip; no virtualenv.

## Use

    metamorse doctor   check the system is ready; prints a fix for each failure
    metamorse keys     print the keymap as a tree
    metamorse tap      decode to stdout, dispatching nothing — tune timing here
    metamorse run      start it

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
    immediate = false   # release Meta-up instantly (see Timing)

Decoding is reliable to about ±30% timing jitter. If you misfire often, raise
`unit` — slower is more forgiving.

## Timing

Meta-down is emitted downstream immediately, so chords stay zero-latency.
Meta-up is withheld until the letter resolves, because a *held* modifier is
inert in X11 while a *released* one can trigger menu and overlay bindings.
The delay lands only on the release edge of Morse input, where nothing
perceives it.

If your WM binds a bare Meta *press* (some overlay keys do), set
`immediate = true`. You'll see the overlay flicker during Morse entry.

## Architecture

    evdev ─→ Demod ─→ Decode ─→ Session ─→ Dispatch ─→ sh / uinput chord
               │         │         │
               └─────────┴─────────┴──→ Observer  (NullObserver today, OSD later)
                         │
              Passthrough policy ──→ uinput (replays the real meta key)

`demod`, `decode`, `keymap`, `policy` are pure — no I/O, no display, no device.
They are the whole correctness surface and they test without X11 or root:

    python3 -m unittest discover -s tests

`source.py` is the only module that touches hardware. `Observer` is the seam
where feedback lands; `NullObserver` is four no-ops today.

## Status

Working: capture, demodulation, decoding, trie dispatch, passthrough, CLI,
installer. Not built: the on-screen display (stubbed at the `Observer`
protocol), and Wayland — evdev capture is compositor-agnostic, but synthesized
chords still go through uinput and depend on the compositor accepting them.
