"""Where things live, and how the daemon is configured."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .core.symbols import Timing

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_DIR = CONFIG_HOME / "metamorse"
KEYMAP = CONFIG_DIR / "keymap.toml"
SETTINGS = CONFIG_DIR / "metamorse.toml"

DEFAULTS = {"key": "leftmeta", "unit": 0.09, "hold": 10.0, "immediate": False}

# Audio lives under [audio] so the key-driven daemon's config is untouched.
# `threshold` is 0.0 until `metamorse tune` measures it: the right value
# depends on the guitar, the mic and the gain, so there is no useful default.
AUDIO_DEFAULTS = {"device": "", "samplerate": 44100, "threshold": 0.0,
                  "unit": 0.12, "hangover": 0.040}


@dataclass(frozen=True, slots=True)
class Audio:
    """Tone-input settings. `unit` is separate from the key `unit` because a
    plucked string is a coarser instrument than a finger: comfortable Morse on
    a guitar runs slower than on a key."""
    device: str = ""
    samplerate: int = AUDIO_DEFAULTS["samplerate"]
    threshold: float = 0.0
    timing: Timing = Timing(AUDIO_DEFAULTS["unit"], 10.0)
    hangover: float = AUDIO_DEFAULTS["hangover"]

    @property
    def name(self) -> str | None:
        return self.device or None

    @classmethod
    def of(cls, raw: dict, hold: float) -> Audio:
        merged = {**AUDIO_DEFAULTS, **raw}
        return cls(str(merged["device"]), int(merged["samplerate"]),
                   float(merged["threshold"]),
                   Timing(float(merged["unit"]), hold),
                   float(merged["hangover"]))


@dataclass(frozen=True, slots=True)
class Settings:
    key: str = DEFAULTS["key"]
    timing: Timing = Timing()
    immediate: bool = False
    audio: Audio = Audio()

    @classmethod
    def load(cls, path: Path = SETTINGS) -> Settings:
        raw = tomllib.loads(path.read_text()) if path.exists() else {}
        merged = {**DEFAULTS, **raw}
        hold = float(merged["hold"])
        return cls(str(merged["key"]),
                   Timing(float(merged["unit"]), hold),
                   bool(merged["immediate"]),
                   Audio.of(raw.get("audio", {}), hold))


def save_threshold(value: float, path: Path = SETTINGS) -> None:
    """Persist `audio.threshold` without disturbing the rest of the file.

    tomllib reads but does not write, and pulling in a TOML writer for one
    float is not worth it. The [audio] block is rewritten in place if present
    and appended if not; anything else in the file is passed through verbatim.
    """
    line = f"threshold = {value:.6g}"
    existing = path.read_text().splitlines() if path.exists() else []
    out, in_audio, written = [], False, False
    for text in existing:
        stripped = text.strip()
        if stripped.startswith("["):
            if in_audio and not written:
                out.append(line)
                written = True
            in_audio = stripped == "[audio]"
        if in_audio and stripped.startswith("threshold"):
            out.append(line)
            written = True
            continue
        out.append(text)
    if not written:
        out += ([] if in_audio else ["", "[audio]"]) + [line]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).strip() + "\n")
