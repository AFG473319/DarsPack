"""Tests for darspack.paths — platform-aware defaults (Linux port)."""
import sys
from pathlib import Path

import pytest

from darspack.mcp.launch import SERVER_EXE_NAME
from darspack.paths import (
    app_exe_name,
    default_library_path,
    opencode_command,
    server_exe_name,
    user_documents_dir,
)


def test_exe_names_follow_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert server_exe_name() == "DarsPackMcp.exe"
    assert app_exe_name() == "DarsPack.exe"
    assert opencode_command() == "opencode.cmd"
    monkeypatch.setattr(sys, "platform", "linux")
    assert server_exe_name() == "DarsPackMcp"
    assert app_exe_name() == "DarsPack"
    assert opencode_command() == "opencode"


def test_default_library_uses_xdg_data_home_without_documents(
    tmp_path, monkeypatch
):
    """No ~/Documents and no user-dirs.dirs: XDG_DATA_HOME wins."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    assert default_library_path() == tmp_path / "xdg-data" / "DarsPackLibrary"


def test_default_library_prefers_existing_documents(tmp_path, monkeypatch):
    """A Linux desktop with ~/Documents keeps the Windows layout."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Documents").mkdir()
    assert default_library_path() == tmp_path / "Documents" / "DarsPackLibrary"


def test_default_library_respects_xdg_documents_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config"
    cfg.mkdir()
    (cfg / "user-dirs.dirs").write_text(
        'XDG_DOCUMENTS_DIR="$HOME/MyDocs"\n', encoding="utf-8"
    )
    assert user_documents_dir() == tmp_path / "MyDocs"
    assert default_library_path() == tmp_path / "MyDocs" / "DarsPackLibrary"


def test_default_library_is_windows_documents_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("HOME", str(Path("/home/someone")))
    # On Windows the documents folder is ~/Documents, XDG is ignored.
    assert default_library_path() == Path("/home/someone") / "Documents" / "DarsPackLibrary"


def test_launch_server_exe_name_matches_platform():
    expected = "DarsPackMcp.exe" if sys.platform == "win32" else "DarsPackMcp"
    assert SERVER_EXE_NAME == expected
