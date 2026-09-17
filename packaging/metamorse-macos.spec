# PyInstaller spec for the macOS build.
#
# Run from the repo root:  pyinstaller packaging/metamorse-macos.spec
#
# Same hiddenimports trap as the Windows spec: both registries import by
# computed name, which PyInstaller's static analysis cannot follow. See
# metamorse.spec for the full explanation.
#
# NO .app BUNDLE, deliberately. metamorse is a console program -- doctor,
# keys and tap all print to a terminal -- and a windowed .app has no stdout
# to print to. A plain binary is also what a Homebrew-shaped install wants.
# The .app only starts earning its keep once there is a login item to
# register, which needs the backend first.

import os

block_cipher = None

ROOT = os.path.abspath(os.getcwd())

a = Analysis(
    ["../metamorse/__main__.py"],
    pathex=[ROOT],
    binaries=[],
    datas=[("../share/keymap.toml", "share"),
           ("../share/keymap-darwin.toml", "share"),
           ("../share/metamorse.toml", "share"),
           ("../share/metamorse-darwin.toml", "share")],
    hiddenimports=[
        "metamorse.inputs.key",
        "metamorse.inputs.key.macos",
        "metamorse.ui.osd",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "evdev",            # Linux-only by nature
        "numpy",            # tone is Linux-only by choice
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
    target_arch=None,   # whatever the runner is; universal2 needs a fat python
    codesign_identity=None,
    entitlements_file=None,
)
