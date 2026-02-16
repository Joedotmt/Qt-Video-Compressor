# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'pandas', 'scipy', 'tkinter', 
        'unittest', 'email', 'http', 'xml', 'pydoc', 'ssl', 
        'asyncio', 'multiprocessing', 'decimal', 'distutils', 'setuptools',
        'PyQt6.QtQml', 'PyQt6.QtQuick', 'PyQt6.QtWebEngine', 'PyQt6.QtSql',
        'PyQt6.QtNetwork', 'PyQt6.QtMultimedia', 'PyQt6.QtBluetooth'
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# --- START CUSTOM FILTER ---
# Iterate through the binaries and remove stuff we don't need
# This removes specific DLLs and Translation files bundled by Qt
new_binaries = []
for (name, path, typecode) in a.binaries:
    name_lower = name.lower()
    
    # Remove Qt Translations (saves ~5-10MB)
    if "qt6/translations" in path.lower() or name_lower.endswith(".qm"):
        continue
        
    # Remove OpenGL/Svg if your app is simple 2D widgets (saves ~10MB)
    # WARNING: Test your app after this. Some styles need SVG.
    if "opengl" in name_lower or "svg" in name_lower:
        continue
    
    # Remove D3D compiler if strictly software rendering
    if "d3dcompiler" in name_lower:
        continue
        
    new_binaries.append((name, path, typecode))

a.binaries = new_binaries
# --- END CUSTOM FILTER ---

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='QtVC',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    upx_dir=r'C:\UPX',
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)