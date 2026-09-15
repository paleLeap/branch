# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Branch. One folder, not one file.

    pyinstaller --clean --noconfirm branch.spec

WHY ONE FOLDER. A one-file build unpacks ~200MB of Qt to a temp directory on
every launch, which makes a five-second startup and makes a crash almost
impossible to diagnose because the files are gone by the time you look. One
folder starts fast, and a friend reporting a problem can see what is in it.

WHAT MUST BE BUNDLED, and what breaks when it is not. None of these raise --
they all fail quietly, which is why each is listed rather than globbed:

  data/cities.csv.gz             no city suggestions, no "nearest major city"
  data/craigslist_areas.csv.gz   Craigslist cannot pick an area, so it is dead
  profiles/*.yaml                no trades in the dropdown; nothing to scan for
  branch/ui/theme.json           falls back to defaults; the window looks wrong

QtWebEngine is what makes this build large. It is not optional: the Facebook,
FB Groups and Craigslist adapters are the browser, and they are the sources that
produce leads. Expect roughly 250-400MB unpacked.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "data" / "cities.csv.gz"), "data"),
    (str(ROOT / "data" / "craigslist_areas.csv.gz"), "data"),
    (str(ROOT / "branch" / "ui" / "theme.json"), "branch/ui"),
    (str(ROOT / "NOTICE"), "."),          # GeoNames attribution -- CC BY 4.0 requires it
    (str(ROOT / "LICENSE"), "."),
]
# Trade profiles are the part users edit and share, so every one ships.
datas += [(str(path), "profiles") for path in sorted((ROOT / "profiles").glob("*.yaml"))]
# PySide6 ships its Qt resources through a hook; QtWebEngine's are easy to miss.
datas += collect_data_files("PySide6", subdir="Qt/resources")

a = Analysis(
    # NOT branch/app.py: it uses relative imports, and PyInstaller runs the
    # entry script with no parent package. See run_branch.py.
    [str(ROOT / "run_branch.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # Imported lazily so a user who never touches Facebook does not pay to
        # load Chromium -- which also means PyInstaller cannot see them.
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "branch.ui.browser",
        "branch.ui.notice",
    ],
    hookspath=[],
    runtime_hooks=[],
    # Qt bindings that are not installed but which PySide6's hooks probe for.
    # Leaving them in adds nothing and produces confusing warnings.
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "matplotlib", "numpy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Branch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX and Qt DLLs do not get on; it breaks WebEngine
    console=False,      # a GUI app: no console window flashing up on Windows
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Branch",
)
