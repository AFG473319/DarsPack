"""Tests for user onboarding, welcome tour, help center dialog, and empty state guidance."""
import json
from pathlib import Path
import pytest
from PySide6.QtCore import Qt

from darspack import i18n
from darspack.core.importer import import_file
from darspack.ui.dialogs import HelpDialog, WelcomeDialog
from darspack.ui.main_window import MainWindow


@pytest.fixture()
def window(tmp_path, qapp):
    win = MainWindow(tmp_path / "lib",
                     {"language": "fa", "font_size": 10,
                      "library": str(tmp_path / "lib")},
                     tmp_path / "settings.json")
    yield win
    win.lib.close()


def test_welcome_dialog_navigation_and_settings(qapp, tmp_path):
    settings_path = tmp_path / "settings.json"
    settings = {"show_welcome": True}
    dlg = WelcomeDialog(None, settings=settings, settings_path=settings_path)

    # Slide 1
    assert dlg.stack.currentIndex() == 0
    assert not dlg.btn_prev.isEnabled()
    assert dlg.btn_next.text() == i18n.tr("welcome_next")
    assert "۱" in dlg.indicator_lbl.text() or "1" in dlg.indicator_lbl.text()

    # Move to slide 2
    dlg.btn_next.click()
    assert dlg.stack.currentIndex() == 1
    assert dlg.btn_prev.isEnabled()
    assert dlg.btn_next.text() == i18n.tr("welcome_next")

    # Move to slide 3
    dlg.btn_next.click()
    assert dlg.stack.currentIndex() == 2
    assert dlg.btn_prev.isEnabled()
    assert dlg.btn_next.text() == i18n.tr("welcome_start")

    # Move back to slide 2
    dlg.btn_prev.click()
    assert dlg.stack.currentIndex() == 1

    # Move back to slide 3 and finish
    dlg.btn_next.click()
    assert dlg.stack.currentIndex() == 2
    assert dlg.dont_show_check.isChecked()

    dlg.btn_next.click()
    assert settings["show_welcome"] is False
    assert settings_path.exists()
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved.get("show_welcome") is False


def test_welcome_dialog_keep_enabled_if_unchecked(qapp, tmp_path):
    settings_path = tmp_path / "settings.json"
    settings = {"show_welcome": True}
    dlg = WelcomeDialog(None, settings=settings, settings_path=settings_path)

    dlg.dont_show_check.setChecked(False)
    # Go to end
    dlg.stack.setCurrentIndex(2)
    dlg._update_slide_view()
    dlg.btn_next.click()

    assert settings.get("show_welcome") is True


def test_help_dialog_structure_and_tabs(qapp):
    dlg = HelpDialog(None)
    assert dlg.tabs.count() == 5
    tab_titles = [dlg.tabs.tabText(i) for i in range(5)]
    assert i18n.tr("help_tab_quick") in tab_titles
    assert i18n.tr("help_tab_shortcuts") in tab_titles
    assert i18n.tr("help_tab_phone") in tab_titles
    assert i18n.tr("help_tab_mcp") in tab_titles
    assert i18n.tr("help_tab_faq") in tab_titles

    # Verify shortcuts table in tab 1
    sc_widget = dlg.tabs.widget(1)
    from PySide6.QtWidgets import QTableWidget
    table = sc_widget.findChild(QTableWidget)
    assert table is not None
    assert table.rowCount() >= 7
    keys = [table.item(r, 0).text() for r in range(table.rowCount())]
    assert "Enter" in keys
    assert "Ctrl + E" in keys
    assert "Delete" in keys
    assert "F1" in keys

    # Verify MCP tab (tab 3)
    assert hasattr(dlg, "btn_copy_mcp_prompt")
    assert hasattr(dlg, "btn_copy_mcp_json")
    assert hasattr(dlg, "btn_copy_mcp_cli")
    assert hasattr(dlg, "btn_copy_mcp_cli_opencode")
    assert "Connect to DarsPack MCP Server" in dlg._mcp_prompt
    assert "darspack.mcp" in dlg._mcp_prompt
    assert "mcpServers" in dlg._mcp_json_str
    # The generated config must point at the headless server, never the GUI.
    assert "--library" in dlg._mcp_json_str
    assert "--selftest" in dlg._mcp_prompt
    assert "opencode.cmd mcp add darspack" in dlg._opencode_cli_cmd

    # Test copy prompt button
    dlg.btn_copy_mcp_prompt.click()
    from PySide6.QtWidgets import QApplication
    cb = QApplication.clipboard()
    assert cb.text() == dlg._mcp_prompt
    assert dlg.btn_copy_mcp_prompt.text() == i18n.tr("help_mcp_copied")

    # Test copy json button
    dlg.btn_copy_mcp_json.click()
    assert cb.text() == dlg._mcp_json_str
    assert dlg.btn_copy_mcp_json.text() == i18n.tr("help_mcp_json_copied")


def test_main_window_empty_state_guide_button(window):
    window.refresh()
    assert not window.empty_button.isHidden()
    assert not window.empty_guide_button.isHidden()

    calls = []
    window.open_help_dialog = lambda: calls.append(1)
    window.empty_guide_button.click()
    assert calls == [1]

    # When a file is imported, empty state buttons hide
    src = window.lib.root.parent / "test_doc.pdf"
    src.write_bytes(b"content")
    import_file(window.lib, src)
    window.refresh()

    assert window.empty_button.isHidden()
    assert window.empty_guide_button.isHidden()
