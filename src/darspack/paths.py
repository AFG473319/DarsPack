"""Platform-aware default paths and executable names.

Windows behaviour is unchanged: the library lives in
``~/Documents/DarsPackLibrary`` and the frozen executables keep their
``.exe`` names.  On Linux the same folder is used when the XDG documents
directory exists; otherwise the library defaults to
``$XDG_DATA_HOME/DarsPackLibrary`` (``~/.local/share/DarsPackLibrary``),
so the app never creates a ``~/Documents`` folder on a machine that
does not use one.  Frozen executables have no ``.exe`` suffix on Linux.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

APP_DIR_NAME = "DarsPackLibrary"


def is_windows() -> bool:
    return sys.platform == "win32"


def app_exe_name() -> str:
    """Name of the frozen GUI executable on this platform."""
    return "DarsPack.exe" if is_windows() else "DarsPack"


def server_exe_name() -> str:
    """Name of the frozen headless MCP server executable on this platform."""
    return "DarsPackMcp.exe" if is_windows() else "DarsPackMcp"


def opencode_command() -> str:
    """OpenCode CLI binary name: ``opencode.cmd`` on Windows (the
    ``opencode.ps1`` shim drops the ``--`` separator), plain ``opencode``
    everywhere else."""
    return "opencode.cmd" if is_windows() else "opencode"


def _xdg_documents_dir() -> Path | None:
    """XDG_DOCUMENTS_DIR from ``~/.config/user-dirs.dirs``, if configured."""
    if is_windows():
        return None
    try:
        text = (Path.home() / ".config" / "user-dirs.dirs").read_text(
            encoding="utf-8"
        )
    except OSError:
        return None
    match = re.search(r'^XDG_DOCUMENTS_DIR="([^"]+)"', text, re.MULTILINE)
    if not match:
        return None
    raw = match.group(1).replace("${HOME}", str(Path.home())).replace(
        "$HOME", str(Path.home())
    )
    path = Path(raw).expanduser()
    return path if path.is_absolute() else Path.home() / path


def user_documents_dir() -> Path:
    """Where the user keeps documents on this platform.

    Windows: ``~/Documents``.  Linux: the XDG documents directory when
    configured, else ``~/Documents`` when it exists, else the XDG data
    directory (so nothing is created under a ``~/Documents`` the user
    never had).
    """
    if is_windows():
        return Path.home() / "Documents"
    xdg_docs = _xdg_documents_dir()
    if xdg_docs is not None:
        return xdg_docs
    documents = Path.home() / "Documents"
    if documents.is_dir():
        return documents
    xdg_data = os.environ.get("XDG_DATA_HOME") or str(
        Path.home() / ".local" / "share"
    )
    return Path(xdg_data)


def default_library_path() -> Path:
    """Default library folder: ``<documents>/DarsPackLibrary``.

    Identical to the old behaviour on Windows (``~/Documents``) and on
    Linux desktops that have a documents folder; on Linux without one
    it falls back to ``$XDG_DATA_HOME/DarsPackLibrary``.
    """
    return user_documents_dir() / APP_DIR_NAME
