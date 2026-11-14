# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for DarsPack (onedir, windowed + headless MCP server).

onedir (not onefile) on purpose: much faster startup and antivirus-
friendlier; the whole folder is what gets zipped / wrapped by the
installer. The web client (HTML) ships as data under darspack/web/client
so the frozen server finds it via sys._MEIPASS.

Two executables share one ``_internal`` folder:

* ``DarsPack.exe``    - the Qt desktop app (console=False).
* ``DarsPackMcp.exe`` - the headless MCP server (console=True, no Qt).
  AI agents need a console stdio process; pointing them at the GUI exe
  would open a window and answer nothing. Generated configs therefore use
  this exe (see darspack/mcp/launch.py).
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "src" / "darspack" / "assets" / "icon" / "darspack.ico")

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
    icon=ICON,
    console=False,          # windowed app - no console flash
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
    icon=ICON,
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
