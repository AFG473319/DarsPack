# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for DarsPack on Linux (onedir, windowed + headless MCP).

The Linux twin of ``darspack.spec`` (Windows). Same layout — one
``DarsPack`` folder with two executables sharing one ``_internal`` folder:

* ``DarsPack``    - the Qt desktop app (no console).
* ``DarsPackMcp`` - the headless MCP server (console, no Qt).

Differences from the Windows spec: no ``icon=`` (PyInstaller only uses
EXE icons on Windows; the desktop icon lives in ``darspack.desktop``),
and the binaries have no ``.exe`` suffix. Build with
``installer/build-linux.sh``; install with ``installer/install-linux.sh``.
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent

# --- Desktop app -----------------------------------------------------------
a = Analysis(
    [str(ROOT / "installer" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[(str(ROOT / "src" / "darspack" / "web" / "client"),
            "darspack/web/client"),
           (str(ROOT / "src" / "darspack" / "assets"),
            "darspack/assets")],
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
    console=False,          # windowed app - no console window
    disable_windowed_traceback=False,
)

# --- Headless MCP server ---------------------------------------------------
# Separate Analysis so the bundle carries no Qt: the exe stays tiny and the
# process an agent spawns is a plain stdio JSON-RPC server.
a_mcp = Analysis(
    [str(ROOT / "installer" / "mcp_launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc_data", "PySide6", "shiboken6"],
    noarchive=False,
)
pyz_mcp = PYZ(a_mcp.pure)

exe_mcp = EXE(
    pyz_mcp,
    a_mcp.scripts,
    [],
    exclude_binaries=True,
    name="DarsPackMcp",
    console=True,           # stdio transport needs real stdout/stdin
    disable_windowed_traceback=False,
)

# Both exes share one _internal folder. Collect the GUI (superset) binaries
# first and add only what the MCP analysis brings on top, so COLLECT never
# sees a duplicate destination (which strict mode rejects).
_gui_binaries = {dest for dest, _src, _typ in a.binaries}
_gui_datas = {dest for dest, _src, _typ in a.datas}
extra_binaries = [entry for entry in a_mcp.binaries if entry[0] not in _gui_binaries]
extra_datas = [entry for entry in a_mcp.datas if entry[0] not in _gui_datas]

coll = COLLECT(
    exe,
    exe_mcp,
    a.binaries + extra_binaries,
    a.datas + extra_datas,
    strip=False,
    upx=False,              # UPX triggers antivirus false positives
    name="DarsPack",
)
