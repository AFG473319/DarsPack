"""Tests for the main window's pure helper functions.

jalali_date guards the «تاریخ ورود» column: imported_at is stored as a
GREGORIAN isoformat string, so the helper must parse with the stdlib and
convert to Jalali — parsing with jdatetime directly used to pass the
Gregorian digits through unchanged (۲۰۲۶/۱۰/۲۴ dressed up as a Jalali
date). These cases pin the correct conversion, the Nowruz year boundary
and the never-crash fallback. No Qt objects needed — but importing the
module pulls in PySide6, so conftest's offscreen env applies.
"""
import os
import time

from darspack.ui.main_window import chapter_lesson_display, human_size, jalali_date, TableSortItem


def test_jalali_date_converts_gregorian_import_dates():
    assert jalali_date("2026-10-24T13:05:00") == "1405/08/02"


def test_jalali_date_nowruz_year_boundary():
    # 21 March 2027 is 1 Farvardin 1406 — the school-year turn of the year
    assert jalali_date("2027-03-21T00:00:00") == "1406/01/01"


def test_jalali_date_bad_input_passes_through():
    # never crash the catalog table: garbage comes back as-is
    assert jalali_date("garbage") == "garbage"


def test_human_size_table():
    # the sizes column: bytes stay integers, bigger units get a decimal
    # only when needed (no «660.0 KB» noise)
    assert human_size(0, "en") == "0 B"
    assert human_size(1023, "en") == "1023 B"
    assert human_size(1024, "en") == "1 KB"
    assert human_size(1536, "en") == "1.5 KB"
    assert human_size(5 * 1024 ** 3, "en") == "5 GB"
    # Persian UI: Persian digits, Persian units, Persian decimal separator
    assert human_size(0, "fa") == "۰ بایت"
    assert human_size(1023, "fa") == "۱۰۲۳ بایت"
    assert human_size(1024, "fa") == "۱ کیلوبایت"
    assert human_size(1536, "fa") == "۱٫۵ کیلوبایت"
    assert human_size(660 * 1024, "fa") == "۶۶۰ کیلوبایت"
    assert human_size(5 * 1024 ** 3, "fa") == "۵ گیگابایت"


def test_chapter_lesson_display_cases():
    assert chapter_lesson_display(3, None) == "فصل ۳"
    assert chapter_lesson_display(None, 5) == "درس ۵"
    assert chapter_lesson_display(3, 5) == "فصل ۳ / درس ۵"
    assert chapter_lesson_display(None, None) == "—"


def test_table_sort_item_order(qapp):
    item1 = TableSortItem("۱۰۲۴ بایت")
    item1.setData(TableSortItem.SORT_KEY_ROLE, 1024)
    item2 = TableSortItem("۵۱۲ بایت")
    item2.setData(TableSortItem.SORT_KEY_ROLE, 512)

    # item2 (512) < item1 (1024)
    assert item2 < item1
    assert not (item1 < item2)

    # fallback when SORT_KEY_ROLE is not set
    item3 = TableSortItem("apple")
    item4 = TableSortItem("banana")
    assert item3 < item4


# --- MainWindow-level behavior (offscreen) ---------------------------------

import pytest

import darspack.ui.main_window as mw_module
from darspack.core.importer import import_file
from darspack.core.library import Library


@pytest.fixture()
def window(tmp_path, qapp):
    """One MainWindow over a throwaway library, closed afterwards."""
    win = mw_module.MainWindow(tmp_path / "lib",
                               {"language": "fa", "font_size": 10,
                                "library": str(tmp_path / "lib")},
                               tmp_path / "settings.json")
    yield win
    win.lib.close()


def test_fast_typing_triggers_exactly_one_refresh(window, monkeypatch):
    """C3: the debounced search box — three keystrokes in a row must run
    the catalog query once, after the 200 ms countdown settles."""
    from PySide6.QtTest import QTest

    calls = []
    real_search = mw_module.catalog_search

    def counting_search(*args, **kwargs):
        calls.append(1)
        return real_search(*args, **kwargs)
    monkeypatch.setattr(mw_module, "catalog_search", counting_search)

    calls.clear()
    window.search_box.setText("ریاضی")
    window.search_box.setText("ریاضی فصل")
    window.search_box.setText("ریاضی فصل ۳")
    assert calls == []                    # countdown still running
    QTest.qWait(350)
    assert len(calls) == 1                # one refresh for the whole burst


def test_filter_changes_stay_immediate(window, monkeypatch):
    """C3 scoping: only the search box is debounced — the kind filter
    refreshes the table the moment it changes."""
    calls = []
    real_search = mw_module.catalog_search

    def counting_search(*args, **kwargs):
        calls.append(1)
        return real_search(*args, **kwargs)
    monkeypatch.setattr(mw_module, "catalog_search", counting_search)

    calls.clear()
    window.kind_combo.setCurrentIndex(1)   # first real kind («جزوه»)
    assert len(calls) == 1                 # immediate, no timer wait


def test_display_strs_cache_hits_on_second_refresh(window):
    """F2.4: the Jalali/size strings are cached per file id — importing one
    file and refreshing twice formats the date/size only once."""
    src = window.lib.root.parent / "نمونه سوال ریاضی فصل 3.pdf"
    src.write_bytes(b"demo")
    import_file(window.lib, src)

    window.refresh()
    first = window._display_strs.copy()
    window.refresh()
    assert window._display_strs == first   # same dict entries, no re-format
    assert len(first) == 1                 # one cached id


def test_empty_library_shows_start_hint(window):
    """E2: a fresh library greets with a short line; the CTA below it
    carries the action, so the sentence no longer repeats the button."""
    window.refresh()
    assert not window.empty_label.isHidden()
    assert window.empty_label.text() == "هنوز فایلی اینجا نیست."


def test_empty_library_offers_the_import_cta(window):
    """The empty state must offer the action, not just describe
    it — one click on the welcome button starts the import dialog."""
    window.refresh()
    assert not window.empty_button.isHidden()
    calls = []
    window.open_import_dialog = lambda: calls.append(1)
    window.empty_button.click()
    assert calls == [1]


def test_empty_state_is_centered_on_first_show(window, qapp):
    """Bug report 2026-10-29: the welcome text sat left of center on the
    first show. The label is centered against the table viewport, whose
    final geometry arrives only after the window is laid out — the
    viewport resize must re-center it."""
    window.resize(1200, 700)
    window.show()
    qapp.processEvents()
    try:
        center = window.table.viewport().rect().center().x()
        assert abs(window.empty_label.geometry().center().x() - center) <= 4
        assert abs(window.empty_button.geometry().center().x() - center) <= 4
    finally:
        window.close()


def test_empty_search_hides_the_import_cta(window):
    src = window.lib.root.parent / "a.pdf"
    src.write_bytes(b"a")
    import_file(window.lib, src)
    window.search_box.setText("چیزی-که-نیست")
    window.refresh()
    assert not window.empty_label.isHidden()
    assert window.empty_button.isHidden()


def test_window_title_is_the_product_name(window):
    """The title bar used to expose the full library path."""
    assert window.windowTitle() == "درس‌پک"


def test_table_stretches_the_name_column_not_the_year(window):
    """setStretchLastSection(True) stretched «سال» (the last
    logical column in RTL), squeezing «درس» to «مطالعات ...» while the
    name stayed fixed."""
    from PySide6.QtWidgets import QHeaderView
    header = window.table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.Stretch
    assert header.stretchLastSection() is False
    assert window.table.columnWidth(1) >= 120     # «درس» no longer squeezed


def test_selection_dependent_buttons_are_disabled_without_a_row(window):
    """Edit/delete must be disabled until a row is selected, instead of
    popping «چیزی انتخاب نشده» after the click."""
    assert not window.edit_action.isEnabled()
    assert not window.delete_action.isEnabled()
    src = window.lib.root.parent / "b.pdf"
    src.write_bytes(b"b")
    import_file(window.lib, src)
    window.refresh()
    assert not window.edit_action.isEnabled()      # refresh clears selection
    window.table.selectRow(0)
    assert window.edit_action.isEnabled()
    assert window.delete_action.isEnabled()
    window.table.clearSelection()
    assert not window.edit_action.isEnabled()
    assert not window.delete_action.isEnabled()


def test_status_bar_count_uses_persian_digits(window):
    src = window.lib.root.parent / "c.pdf"
    src.write_bytes(b"c")
    import_file(window.lib, src)
    window.refresh()
    assert "۱ فایل در کتابخانه" in window.count_label.text()


def test_action_hierarchy_replaces_the_flat_button_row(window):
    """Wave 1: one primary action in the app bar, a compact secondary
    toolbar, and everything else in an overflow menu."""
    from darspack.i18n import tr
    from darspack.ui.delegates import KindBadgeDelegate

    assert window.import_button.objectName() == "Primary"
    assert window.packages_button.menu() is not None
    package_actions = [a.text() for a in window.packages_button.menu().actions()]
    for text in (tr("btn_export"), tr("btn_verify"), tr("btn_import_pkg")):
        assert text in package_actions
    menu_texts = [a.text() for a in window.more_menu.actions() if a.text()]
    for text in (tr("btn_edit_meta"), tr("btn_delete"), tr("btn_history"),
                 tr("btn_stats"), tr("btn_feedback"), tr("btn_help"),
                 tr("btn_about"), tr("btn_settings")):
        assert text in menu_texts
    assert window.table.verticalHeader().isHidden()
    assert window.table.alternatingRowColors()
    assert isinstance(window.table.itemDelegateForColumn(3),
                      KindBadgeDelegate)


def test_search_bar_has_a_leading_icon(window):
    """The magnifier lives inside the rounded search shell on the leading
    (right) side; QLineEdit actions sat on the physical left next to
    right-aligned Persian text."""
    from PySide6.QtWidgets import QFrame, QLabel

    shell = window.findChild(QFrame, "SearchShell")
    assert shell is not None
    assert window.search_box.parent() is shell
    assert any(not label.pixmap().isNull()
               for label in shell.findChildren(QLabel))


def test_search_clear_button_is_centered_and_clears(window, qapp):
    """The native clear button sat low; a shell button is vertically
    centered and only appears while there is text."""
    window.resize(1000, 640)
    window.show()
    qapp.processEvents()
    try:
        assert window.clear_search_button.isHidden()
        window.search_box.setText("ریاضی")
        assert not window.clear_search_button.isHidden()
        button_center = window.clear_search_button.mapTo(
            window.search_shell,
            window.clear_search_button.rect().center())
        assert abs(button_center.y()
                   - window.search_shell.rect().center().y()) <= 2
        window.clear_search_button.click()
        assert window.search_box.text() == ""
        assert window.clear_search_button.isHidden()
    finally:
        window.close()


def test_tooltips_are_reserved_for_elided_text_and_icon_buttons(window, qapp):
    """Text buttons show their label already; only icon-only buttons and
    genuinely truncated cells need a tooltip box."""
    assert window.packages_button.toolTip() == ""
    assert window.duplicates_button.toolTip() == ""
    assert window.share_button.toolTip() == ""
    assert window.more_button.toolTip() != ""
    assert window.more_button.text() == ""
    assert not window.more_button.icon().isNull()
    assert window.more_menu.minimumWidth() >= 220

    short = window.lib.root.parent / "a.pdf"
    short.write_bytes(b"a")
    long_name = "x" * 120 + ".pdf"
    long_path = window.lib.root.parent / long_name
    long_path.write_bytes(b"b")
    import_file(window.lib, short)
    import_file(window.lib, long_path)
    window.refresh()
    window.resize(1000, 640)
    window.show()
    qapp.processEvents()
    try:
        model = window.table.model()
        indexes = {model.index(row, 0).data(): model.index(row, 0)
                   for row in range(model.rowCount())}
        assert window._cell_text_fits(indexes["a.pdf"])
        assert not window._cell_text_fits(indexes[long_name])
    finally:
        window.close()


def test_every_kind_has_a_badge_palette():
    from darspack.ui.delegates import KIND_BADGES
    from darspack.ui.main_window import KINDS
    assert set(KINDS) <= set(KIND_BADGES)


def test_chapter_and_lesson_are_both_shown(window):
    """A file can carry both a chapter and a lesson; the merged cell must
    show both («فصل ۳ / درس ۵»). The column is wide enough for the
    longest pair at larger font sizes — the move to Vazirmatn made the
    old 110 px column elide it."""
    src = window.lib.root.parent / "both.pdf"
    src.write_bytes(b"both")
    import_file(window.lib, src)
    with window.lib.conn:
        window.lib.conn.execute(
            "UPDATE files SET chapter=3, lesson=5")
    window.refresh()
    assert window.table.item(0, 2).text() == "فصل ۳ / درس ۵"
    assert window.table.columnWidth(2) >= 140


def test_search_no_result_shows_digit_hint(window):
    """E2: an empty search result gets the Persian/Latin digits hint."""
    src = window.lib.root.parent / "نمونه سوال ریاضی فصل 3.pdf"
    src.write_bytes(b"demo")
    import_file(window.lib, src)
    window.refresh()
    assert window.empty_label.isHidden()          # rows exist

    window.search_box.setText("چیزی-که-نیست")     # debounced — fire it
    window.refresh()
    assert not window.empty_label.isHidden()
    assert "اعداد فارسی" in window.empty_label.text()


def test_school_year_filter_isolates_years(tmp_path, qapp):
    """A3: the year filter combo shows only one school year's files, and
    the «سال» column carries each file's year."""
    from darspack.core.normalize import persian_digits

    with Library(tmp_path / "lib") as lib:
        for name, year in (("جزوه ریاضی فصل 1.pdf", "1404-1405"),
                           ("جزوه ریاضی فصل 2.pdf", "1405-1406"),
                           ("جزوه ریاضی فصل 3.pdf", "1405-1406")):
            src = tmp_path / name
            src.write_bytes(f"content {name}".encode("utf-8"))
            import_file(lib, src, meta={"school_year": year})
        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            idx = win.year_combo.findData("1404-1405")
            assert idx > 0                       # listed after «همه‌ی سال‌ها»
            win.year_combo.setCurrentIndex(idx)  # fires refresh itself
            assert [r["original_name"] for r in win.last_rows] == \
                ["جزوه ریاضی فصل 1.pdf"]

            win.year_combo.setCurrentIndex(win.year_combo.findData("1405-1406"))
            assert len(win.last_rows) == 2

            win.year_combo.setCurrentIndex(0)    # «همه‌ی سال‌ها»
            assert len(win.last_rows) == 3
            # «سال» column (index 6) shows the Persian-digit year label
            shown = win.table.item(0, 6).text()
            assert shown == persian_digits("1404-1405") or \
                shown == persian_digits("1405-1406")
        finally:
            win.lib.close()


# --- E3: confirmed manual delete (design-approved 2026-10-24) -------------

from PySide6.QtWidgets import QMessageBox


def test_delete_moves_file_to_trash_and_removes_row(tmp_path, qapp, monkeypatch):
    """E3: the confirmed delete MOVES the stored file to files/.trash
    (never unlinked), deletes the row + its tag links, and logs the
    action. Re-importing the same content works afterwards."""
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "جزوه اشتباهی.pdf"
        src.write_bytes(b"wrong file")
        import_file(lib, src)
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        with lib.conn:      # explicit commit — an open transaction would
            #                # block the window's connection (WAL writer)
            lib.conn.execute(
                "INSERT INTO file_tags(file_id, tag_id) VALUES (?, ?)",
                (fid, lib.conn.execute(
                    "INSERT INTO tags(name, normalized) VALUES ('x', 'x')")
                 .lastrowid))

        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            monkeypatch.setattr(
                QMessageBox, "question",
                staticmethod(lambda *a, **k: QMessageBox.Yes))
            win.delete_file(fid)

            assert lib.conn.execute(
                "SELECT COUNT(*) c FROM files").fetchone()["c"] == 0
            assert lib.conn.execute(
                "SELECT COUNT(*) c FROM file_tags").fetchone()["c"] == 0
            trash = lib.files_dir / ".trash"
            trashed = list(trash.iterdir())
            assert len(trashed) == 1          # the file MOVED, not erased
            assert trashed[0].read_bytes() == b"wrong file"
            action = lib.conn.execute(
                "SELECT action, detail FROM activity_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert action["action"] == "delete"
            assert "جزوه اشتباهی" in action["detail"]

            # re-importing the same content works — the row is gone
            result = import_file(lib, src)
            assert result.status == "imported"
        finally:
            win.lib.close()


def test_delete_declined_keeps_everything(tmp_path, qapp, monkeypatch):
    """E3: «No» in the confirmation changes nothing — flag-only rule."""
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "جزوه مهم.pdf"
        src.write_bytes(b"keep me")
        import_file(lib, src)
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]

        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            monkeypatch.setattr(
                QMessageBox, "question",
                staticmethod(lambda *a, **k: QMessageBox.No))
            win.delete_file(fid)
            assert lib.conn.execute(
                "SELECT COUNT(*) c FROM files").fetchone()["c"] == 1
            assert src.exists()
            assert win.table.rowCount() == 1   # table still shows it
        finally:
            win.lib.close()


def test_bulk_delete_moves_every_selected_file_to_the_trash(
        tmp_path, qapp, monkeypatch):
    """Bulk delete (2026-10-29): one confirmation for the whole selection,
    every file moved to files/.trash, one activity row per file."""
    from PySide6.QtWidgets import QTableWidgetSelectionRange
    with Library(tmp_path / "lib") as lib:
        for name in ("a.pdf", "b.pdf"):
            src = tmp_path / name
            src.write_bytes(name.encode())
            import_file(lib, src)

        asked = {}

        def fake_question(parent, title, text, *args, **kwargs):
            asked["text"] = text
            return QMessageBox.Yes

        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            monkeypatch.setattr(QMessageBox, "question", fake_question)
            win.table.setRangeSelected(
                QTableWidgetSelectionRange(0, 0, 1, win.table.columnCount() - 1),
                True)
            win.delete_selected_files()

            assert "۲" in asked["text"]              # the count is Persian
            assert lib.conn.execute(
                "SELECT COUNT(*) c FROM files").fetchone()["c"] == 0
            trashed = {p.read_bytes() for p in (lib.files_dir / ".trash").iterdir()}
            assert trashed == {b"a.pdf", b"b.pdf"}
            deletes = lib.conn.execute(
                "SELECT COUNT(*) c FROM activity_log WHERE action='delete'"
            ).fetchone()["c"]
            assert deletes == 2
        finally:
            win.lib.close()


def test_row_menu_opens_on_any_column(tmp_path, qapp, monkeypatch):
    """The file id lives only on the name cell (perf F2.2) — right-clicking
    the subject or size cell must still resolve the row (bug report
    2026-10-29: the menu only opened on the name column)."""
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "a.pdf"
        src.write_bytes(b"row menu")
        import_file(lib, src)

        class FakeMenu:
            """Stands in for QMenu; exec() picks the last action = delete."""
            def __init__(self, parent=None):
                self.actions = []

            def addAction(self, text):
                action = object()
                self.actions.append((text, action))
                return action

            def addSeparator(self):
                pass

            def exec(self, *_args):
                return self.actions[-1][1]

        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            monkeypatch.setattr(mw_module, "QMenu", FakeMenu)
            monkeypatch.setattr(
                QMessageBox, "question",
                staticmethod(lambda *a, **k: QMessageBox.Yes))
            click = win.table.visualItemRect(win.table.item(0, 2)).center()
            win._show_row_menu(click)       # column 2 (فصل / درس) is not col 0

            assert lib.conn.execute(
                "SELECT COUNT(*) c FROM files").fetchone()["c"] == 0
            assert len(list((lib.files_dir / ".trash").iterdir())) == 1
        finally:
            win.lib.close()


def test_sweep_never_touches_the_trash(tmp_path):
    """E3 safety net: files/.trash is a subfolder of files/ and
    sweep_orphans only reconciles top-level files — a trashed file
    survives a library reopen with unknown leftovers around it."""
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "a.pdf"
        src.write_bytes(b"a")
        import_file(lib, src)
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        trash = lib.files_dir / ".trash"
        trash.mkdir(exist_ok=True)
        (lib.files_dir / "tmp_009.pdf").write_bytes(b"leftover")
        # the tmp copy must be stale for the sweep to touch it
        old = time.time() - 3600
        os.utime(lib.files_dir / "tmp_009.pdf", (old, old))
        import shutil
        shutil.move(str(lib.stored_path(
            lib.conn.execute("SELECT * FROM files").fetchone())),
            str(trash / "000001.pdf"))
        lib.conn.execute("DELETE FROM files WHERE id=?", (fid,))
        lib.conn.commit()

    with Library(tmp_path / "lib") as lib2:      # reopen → sweep runs
        assert (trash / "000001.pdf").exists()   # trash untouched
        assert not (lib2.files_dir / "tmp_009.pdf").exists()  # tmp swept


def test_delete_collision_preserves_extension(tmp_path, qapp, monkeypatch):
    """Regression test for trash collision naming: existing trash files
    must cause collision suffixes of the form stem~N.ext (preserving extension)."""
    from pathlib import Path
    from PySide6.QtWidgets import QMessageBox

    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "document.pdf"
        src.write_bytes(b"content to trash")
        import_file(lib, src)
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        stored_name = lib.conn.execute(
            "SELECT stored_name FROM files WHERE id=?", (fid,)
        ).fetchone()["stored_name"]

        trash = lib.files_dir / ".trash"
        trash.mkdir(exist_ok=True)
        (trash / stored_name).write_bytes(b"existing trashed content")

        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            monkeypatch.setattr(
                QMessageBox, "question",
                staticmethod(lambda *a, **k: QMessageBox.Yes))
            win.delete_file(fid)

            stored_p = Path(stored_name)
            expected_name = f"{stored_p.stem}~1{stored_p.suffix}"
            collided_file = trash / expected_name
            assert collided_file.exists()
            assert collided_file.read_bytes() == b"content to trash"
            assert collided_file.suffix == ".pdf"
        finally:
            win.lib.close()


def test_row_menu_dismiss_fires_no_actions(tmp_path, qapp, monkeypatch):
    """Dismissing the row context menu (Esc / click away) must return None
    and NEVER trigger any actions (e.g. bulk edit or open)."""
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "a.pdf"
        src.write_bytes(b"content")
        import_file(lib, src)

        class DismissMenu:
            def __init__(self, parent=None):
                self.actions = []
            def addAction(self, text):
                action = object()
                self.actions.append((text, action))
                return action
            def addSeparator(self):
                pass
            def exec(self, *_args):
                return None  # User dismissed the menu

        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            called = []
            monkeypatch.setattr(mw_module, "QMenu", DismissMenu)
            monkeypatch.setattr(win, "bulk_edit_selected", lambda: called.append("bulk"))
            monkeypatch.setattr(win, "open_selected_file", lambda: called.append("open"))
            monkeypatch.setattr(win, "delete_selected_files", lambda: called.append("delete"))

            click = win.table.visualItemRect(win.table.item(0, 0)).center()
            win._show_row_menu(click)

            assert called == [], f"Expected no action on menu dismiss, got {called}"
        finally:
            win.lib.close()


def test_header_click_sorts_table(tmp_path, qapp):
    """Clicking column header sorts table by logical sort key."""
    with Library(tmp_path / "lib") as lib:
        f1 = tmp_path / "small.pdf"
        f1.write_bytes(b"small")
        import_file(lib, f1)

        f2 = tmp_path / "large.pdf"
        f2.write_bytes(b"large" * 100)
        import_file(lib, f2)

    win = mw_module.MainWindow(tmp_path / "lib",
                               {"language": "fa", "font_size": 10,
                                "library": str(tmp_path / "lib")},
                               tmp_path / "settings.json")
    try:
        # Column 4 is size
        win._on_header_clicked(4)
        row0_name = win.table.item(0, 0).text()
        assert row0_name == "small.pdf"

        win._on_header_clicked(4)
        row0_name = win.table.item(0, 0).text()
        assert row0_name == "large.pdf"
    finally:
        win.lib.close()


def test_drag_and_drop_import(tmp_path, qapp, monkeypatch):
    """Dragging and dropping local files onto MainWindow or table viewport triggers run_import_worker."""
    from PySide6.QtCore import QMimeData, QUrl, QPointF, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent

    win = mw_module.MainWindow(tmp_path / "lib",
                               {"language": "fa", "font_size": 10,
                                "library": str(tmp_path / "lib")},
                               tmp_path / "settings.json")
    try:
        sample = tmp_path / "dragged.pdf"
        sample.write_bytes(b"content")

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(sample))])
        enter_ev = QDragEnterEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)

        # 1. DragEnter directly on MainWindow and through eventFilter
        win.dragEnterEvent(enter_ev)
        assert enter_ev.isAccepted()

        enter_ev2 = QDragEnterEvent(QPointF(15, 15), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        res_enter = win.eventFilter(win.table.viewport(), enter_ev2)
        assert res_enter is True
        assert enter_ev2.isAccepted()

        imported = []
        monkeypatch.setattr(win, "run_import_worker", lambda paths: imported.extend(paths))

        # 2. Drop directly on MainWindow
        event = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        win.dropEvent(event)
        assert len(imported) == 1
        assert imported[0] == sample

        # 3. Drop on table viewport through eventFilter
        imported.clear()
        event2 = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        res = win.eventFilter(win.table.viewport(), event2)
        assert res is True
        assert len(imported) == 1
        assert imported[0] == sample
    finally:
        win.lib.close()


def test_import_worker_reentrancy_guard(tmp_path, qapp):
    """Calling run_import_worker while busy or running is rejected."""
    from darspack.i18n import tr
    win = mw_module.MainWindow(tmp_path / "lib",
                               {"language": "fa", "font_size": 10,
                                "library": str(tmp_path / "lib")},
                               tmp_path / "settings.json")
    try:
        class FakeRunningWorker:
            def isRunning(self):
                return True

        # Case 1: the import thread isRunning
        win._worker_thread = FakeRunningWorker()
        win.run_import_worker([tmp_path / "foo.pdf"])
        assert win._worker_thread is not None and isinstance(win._worker_thread, FakeRunningWorker)
        assert tr("import_running_busy") in win.statusBar().currentMessage()

        # Case 2: _import_busy flag (e.g. during modal ClassifyDialog review)
        win._worker = None
        win._import_busy = True
        win.run_import_worker([tmp_path / "bar.pdf"])
        assert win._worker is None
        assert tr("import_running_busy") in win.statusBar().currentMessage()
    finally:
        win.lib.close()


def test_open_selected_file_empty_selection_nudge(tmp_path, qapp):
    """Enter / open_selected_file with empty selection shows status bar message, no modal."""
    from darspack.i18n import tr
    win = mw_module.MainWindow(tmp_path / "lib",
                               {"language": "fa", "font_size": 10,
                                "library": str(tmp_path / "lib")},
                               tmp_path / "settings.json")
    try:
        win.table.clearSelection()
        win.open_selected_file()
        assert tr("err_no_selection") in win.statusBar().currentMessage()
    finally:
        win.lib.close()


def test_keyboard_shortcuts_esc_and_edit(tmp_path, qapp, monkeypatch):
    """Esc clears search box or table selection; Ctrl+E opens edit dialog."""
    with Library(tmp_path / "lib") as lib:
        f1 = tmp_path / "f1.pdf"
        f1.write_bytes(b"1")
        import_file(lib, f1)
        f2 = tmp_path / "f2.pdf"
        f2.write_bytes(b"2")
        import_file(lib, f2)

    win = mw_module.MainWindow(tmp_path / "lib",
                               {"language": "fa", "font_size": 10,
                                "library": str(tmp_path / "lib")},
                               tmp_path / "settings.json")
    try:
        # 1. Esc clears search box text
        win.search_box.setText("test query")
        win._on_shortcut_esc()
        assert win.search_box.text() == ""

        # 2. Esc clears selection if search box is empty
        win.table.selectAll()
        assert len(win.table.selectedItems()) > 0
        win._on_shortcut_esc()
        assert len(win.table.selectedItems()) == 0

        # 3. Ctrl+E on 1 item calls edit_metadata
        actions = []
        monkeypatch.setattr(win, "edit_metadata", lambda: actions.append("single"))
        monkeypatch.setattr(win, "bulk_edit_selected", lambda: actions.append("bulk"))

        win.table.selectRow(0)
        win._on_shortcut_edit()
        assert actions == ["single"]

        # 4. Ctrl+E on 2 items calls bulk_edit_selected
        win.table.selectAll()
        win._on_shortcut_edit()
        assert actions == ["single", "bulk"]
    finally:
        win.lib.close()


def test_create_localized_line_edit_context_menu_fa(qapp):
    from PySide6.QtWidgets import QLineEdit
    from darspack.i18n import set_language, tr
    from darspack.ui.main_window import create_localized_line_edit_context_menu

    set_language("fa")
    edit = QLineEdit("سلام دنیا")
    menu = create_localized_line_edit_context_menu(edit, include_clear=True)
    actions = menu.actions()

    # Verify no submenus exist (e.g. Insert Unicode control character is removed)
    assert not any(a.menu() is not None for a in actions)

    # Verify standard actions are translated to Persian
    texts = [a.text() for a in actions if not a.isSeparator()]
    assert any("بازگردانی" in t for t in texts)
    assert any("کپی" in t for t in texts)
    assert any("چسباندن" in t for t in texts)
    assert any("انتخاب همه" in t for t in texts)
    assert any(tr("clear_search") in t for t in texts)

    # Verify last action is clear_search and works
    clear_act = [a for a in actions if tr("clear_search") in a.text()][0]
    clear_act.trigger()
    assert edit.text() == ""


def test_create_localized_line_edit_context_menu_en(qapp):
    from PySide6.QtWidgets import QLineEdit
    from darspack.i18n import set_language, tr
    from darspack.ui.main_window import create_localized_line_edit_context_menu

    set_language("en")
    try:
        edit = QLineEdit("hello world")
        menu = create_localized_line_edit_context_menu(edit, include_clear=True)
        actions = menu.actions()

        assert not any(a.menu() is not None for a in actions)
        texts = [a.text() for a in actions if not a.isSeparator()]
        assert any("Undo" in t for t in texts)
        assert any("Copy" in t for t in texts)
        assert any("Paste" in t for t in texts)
        assert any("Select All" in t for t in texts)
        assert any(tr("clear_search") in t for t in texts)
    finally:
        set_language("fa")


def test_search_box_has_custom_context_menu(window, monkeypatch):
    from PySide6.QtCore import QPoint

    calls = []
    monkeypatch.setattr(window, "_show_search_context_menu", lambda pos: calls.append(pos))
    window.search_box.customContextMenuRequested.emit(QPoint(10, 10))
    assert calls == [QPoint(10, 10)]


def test_persian_translator_preserves_unmapped_strings(qapp):
    from darspack.ui.app import PersianTranslator

    translator = PersianTranslator(qapp)
    assert translator.translate("QPlatformTheme", "&Yes") == "بله"
    assert translator.translate("QWidgetTextControl", "&Undo\tCtrl+Z") is None


def test_localized_search_context_menu_with_translator_is_popup_and_dismissible(qapp, window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit
    from darspack.i18n import set_language, tr
    from darspack.ui.app import PersianTranslator
    from darspack.ui.main_window import create_localized_line_edit_context_menu

    set_language("fa")
    translator = PersianTranslator(qapp)
    qapp.installTranslator(translator)
    try:
        edit = QLineEdit("سلام دنیا")
        menu = create_localized_line_edit_context_menu(
            edit, parent=window, include_clear=True
        )
        texts = [act.text() for act in menu.actions() if not act.isSeparator()]
        assert "بازگردانی\tCtrl+Z" in texts
        assert "کپی\tCtrl+C" in texts
        assert "چسباندن\tCtrl+V" in texts
        assert "انتخاب همه\tCtrl+A" in texts
        assert tr("clear_search") in texts
        assert not any(t.startswith("\t") for t in texts)

        flags = menu.windowFlags()
        assert bool(flags & Qt.WindowType.Popup)
        assert bool(flags & Qt.WindowType.FramelessWindowHint)
        assert bool(flags & Qt.WindowType.NoDropShadowWindowHint)
        assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        menu.show()
        qapp.processEvents()
        assert menu.isVisible()
        QTest.keyClick(menu, Qt.Key.Key_Escape)
        qapp.processEvents()
        assert not menu.isVisible()
    finally:
        menu.close()
        qapp.removeTranslator(translator)





# --- M21/M22/M27: close mid-import, stale rows, partial bulk delete -------


def test_close_during_import_waits_for_worker(tmp_path, qapp, monkeypatch):
    """M21: closing the window mid-import waits for the worker instead
    of destroying a running QThread (Qt aborts the process) — and no
    import-finished popup appears on the closing window."""
    import time

    import darspack.ui.workers as workers_mod
    from PySide6.QtWidgets import QApplication

    with Library(tmp_path / "lib") as lib:
        folder = tmp_path / "from"
        folder.mkdir()
        (folder / "big.pdf").write_bytes(b"x")
        real_import = workers_mod.import_file

        def slow_import(lib_, path, **kwargs):
            time.sleep(1.5)
            return real_import(lib_, path, **kwargs)

        monkeypatch.setattr(workers_mod, "import_file", slow_import)

        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            win.show()
            win.run_import_worker([folder])
            deadline = time.time() + 10
            while not win._worker_thread.isRunning() and time.time() < deadline:
                qapp.processEvents()
                time.sleep(0.02)
            assert win._worker_thread.isRunning()
            win.close()
            assert not win._worker_thread.isRunning()
            qapp.processEvents()
            assert QApplication.activeModalWidget() is None
        finally:
            win.lib.close()


def test_open_selected_file_missing_row_shows_message(tmp_path, qapp):
    """M22: opening a file whose row vanished (deleted by another
    instance while the table was showing it) shows a status message
    and refreshes instead of crashing on a None row."""
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "a.pdf"
        src.write_bytes(b"a")
        import_file(lib, src)
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]

        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            win.refresh()
            win.table.setCurrentCell(0, 0)
            with lib.conn:
                lib.conn.execute("DELETE FROM files WHERE id=?", (fid,))
            win.open_selected_file()   # must not raise
            assert "دیگر در کتابخانه نیست" in win.statusBar().currentMessage()
        finally:
            win.lib.close()


def test_edit_metadata_missing_row_shows_message(tmp_path, qapp):
    """M22: editing a file whose row vanished shows a status message
    instead of crashing inside MetadataDialog."""
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "a.pdf"
        src.write_bytes(b"a")
        import_file(lib, src)
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]

        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            win.refresh()
            win.table.selectRow(0)
            with lib.conn:
                lib.conn.execute("DELETE FROM files WHERE id=?", (fid,))
            win.edit_metadata()        # must not raise
            assert "دیگر در کتابخانه نیست" in win.statusBar().currentMessage()
        finally:
            win.lib.close()


def test_bulk_delete_partial_failure_reports_split(tmp_path, qapp, monkeypatch):
    """M27: one locked file must not abort the whole bulk delete — the
    rest still moves to trash and the status bar reports the split."""
    from PySide6.QtWidgets import QMessageBox

    with Library(tmp_path / "lib") as lib:
        for name in ("a.pdf", "b.pdf"):
            src = tmp_path / name
            src.write_bytes(name.encode())
            import_file(lib, src)
        ids = [r["id"] for r in lib.conn.execute(
            "SELECT id FROM files ORDER BY id")]

        win = mw_module.MainWindow(lib.root,
                                   {"language": "fa", "font_size": 10,
                                    "library": str(lib.root)},
                                   tmp_path / "settings.json")
        try:
            monkeypatch.setattr(
                QMessageBox, "question",
                staticmethod(lambda *a, **k: QMessageBox.Yes))
            real_move = win.lib.move_to_trash

            def flaky_move(fid):
                if fid == ids[1]:
                    raise PermissionError("file open in another program")
                return real_move(fid)

            monkeypatch.setattr(win.lib, "move_to_trash", flaky_move)
            win.delete_files(ids)

            assert lib.conn.execute(
                "SELECT COUNT(*) c FROM files").fetchone()["c"] == 1
            trash = lib.files_dir / ".trash"
            trashed = list(trash.iterdir())
            assert len(trashed) == 1
            assert trashed[0].read_bytes() == b"a.pdf"
            assert "منتقل نشد" in win.statusBar().currentMessage()
        finally:
            win.lib.close()
