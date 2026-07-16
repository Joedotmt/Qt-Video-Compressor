# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


ROOT = Path(SPECPATH).resolve().parents[1]
APP_ICON_DIR = ROOT / "data" / "icons"


analysis = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (
            str(APP_ICON_DIR / "io.github.Joedotmt.VideoCompressor.svg"),
            "share/icons/hicolor/scalable/apps",
        ),
        (
            str(APP_ICON_DIR / "io.github.Joedotmt.VideoCompressor-symbolic.svg"),
            "share/icons/hicolor/symbolic/apps",
        ),
    ],
    hiddenimports=[
        "gi.repository.Adw",
        "gi.repository.Gdk",
        "gi.repository.Gio",
        "gi.repository.GLib",
        "gi.repository.Gtk",
    ],
    hookspath=[],
    hooksconfig={
        "gi": {
            "icons": ["Adwaita", "hicolor"],
            "themes": ["Adwaita"],
            "languages": [],
            "module-versions": {
                "Gdk": "4.0",
                "Gtk": "4.0",
            },
        },
    },
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)

# The generic GdkPixbuf hook includes AVIF plus several AV1 codec libraries.
# This app uses FFmpeg for video and needs only the GTK icon loaders, so keeping
# that image loader would add more than 20 MiB of unrelated binaries.
unused_avif_binaries = {
    "libaom.dll",
    "libavif-16.dll",
    "libdav1d-7.dll",
    "libpixbufloader-avif.dll",
    "librav1e.dll",
    "libsvtav1enc-4.dll",
}
analysis.binaries = [
    entry
    for entry in analysis.binaries
    if entry[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
    not in unused_avif_binaries
]

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="VideoCompressor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="VideoCompressor",
)
