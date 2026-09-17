# PyInstaller spec for the Windows build.
#
# Run from the repo root:  pyinstaller packaging/metamorse.spec
#
# HIDDENIMPORTS -- the one thing that will break this build silently.
# Both registries import by computed name: `inputs/__init__.py` does
# __import__(f"{__name__}.{name}") and `inputs/key/__init__.py` does the same
# to pick a platform. PyInstaller follows `import x.y` statically and cannot
# see either, so the backend must be named here. Leave it out and the exe
# builds cleanly, then dies at runtime with "unknown input: 'key'".
#
# EXCLUDES -- tone is Linux-only by choice (it needs numpy, sounddevice and
# portaudio, none of which belong in a keyboard utility's download), and evdev
# is Linux-only by nature. Excluding them keeps the exe small and stops
# PyInstaller warning about imports it cannot resolve on Windows.

import os

block_cipher = None

ROOT = os.path.abspath(os.getcwd())

a = Analysis(
    ["../metamorse/__main__.py"],
    pathex=[ROOT],
    binaries=[],
    datas=[("../share/keymap-windows.toml", "share"),
           ("../share/metamorse-windows.toml", "share")],
    hiddenimports=[
        "metamorse.inputs.key",
        "metamorse.inputs.key.windows",
        "metamorse.ui.osd",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "evdev",
        "numpy",
        "sounddevice",
        "metamorse.inputs.tone",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
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
    upx=False,          # UPX-packed keyboard hooks are antivirus bait
    runtime_tmpdir=None,
    console=True,       # `doctor`, `keys` and `tap` are console commands
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
