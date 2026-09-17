# PyInstaller spec for the Linux build.
#
# Run from the repo root:  pyinstaller packaging/metamorse-linux.spec
#
# This one BUNDLES evdev, where the Windows and macOS specs exclude it. That
# is the whole point: a Linux binary without evdev could not read a keyboard,
# which is the program. evdev is a C extension, so `collect_dynamic_libs`
# picks up the compiled .so that a bare hiddenimport would miss.
#
# GLIBC. A PyInstaller binary runs only on the glibc it was built against or
# newer, so the runner decides the floor. The workflow builds on ubuntu-22.04
# (glibc 2.35) rather than the newest runner, which keeps Debian 12 (2.36) and
# anything more recent in range. Building on ubuntu-latest would produce a
# binary that will not start on the machine this project is developed on.
#
# Same hiddenimports trap as the other specs: both registries import by
# computed name, which PyInstaller's static analysis cannot follow. See
# metamorse.spec for the full explanation.

import os

from PyInstaller.utils.hooks import collect_dynamic_libs

block_cipher = None

ROOT = os.path.abspath(os.getcwd())

a = Analysis(
    ["../metamorse/__main__.py"],
    pathex=[ROOT],
    binaries=collect_dynamic_libs("evdev"),
    datas=[("../share/keymap.toml", "share"),
           ("../share/metamorse.toml", "share")],
    hiddenimports=[
        "metamorse.inputs.key",
        "metamorse.inputs.key.linux",
        "metamorse.ui.osd",
        "evdev",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # tone stays out: numpy, sounddevice and portaudio have no business
        # in a keyboard utility's download. A checkout still has it.
        "numpy",
        "sounddevice",
        "metamorse.inputs.tone",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="metamorse",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
