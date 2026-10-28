# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for DarsPack (onedir, windowed).

onedir (not onefile) on purpose: much faster startup and antivirus-
friendlier; the whole folder is what gets zipped / wrapped by the
installer. The web client (HTML) ships as data under darspack/web/client
so the frozen server finds it via sys._MEIPASS.
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "installer" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[(str(ROOT / "src" / "darspack" / "web" / "client"),
            "darspack/web/client")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc_data"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DarsPack",
    console=False,          # windowed app — no console flash
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,              # UPX triggers antivirus false positives
    name="DarsPack",
)
