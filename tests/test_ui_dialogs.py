"""Tests for the desktop dialogs (offscreen Qt, no display needed).

The metadata dialog crashed on open when the file had no subject
(IndexError: No item with that key — sqlite3.Row's way of saying the
column is missing). These tests would have caught it.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from darspack.core.importer import import_file
from darspack.core.library import Library


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def lib_with_file(tmp_path):
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "نمونه سوال ریاضی فصل 3.pdf"
        src.write_bytes(b"demo")
        import_file(lib, src)
        file_id = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        yield lib, file_id, tmp_path


def test_metadata_dialog_opens_with_suggestion(lib_with_file, qapp):
    from darspack.ui.dialogs import MetadataDialog
    lib, file_id, _ = lib_with_file
    dlg = MetadataDialog(None, lib, file_id)          # used to crash here
    assert dlg.subject.currentText() == "ریاضی"       # suggestion pre-filled
    assert dlg.chapter.value() == 3
    assert dlg.kind.currentText() == "نمونه‌سوال"


def test_metadata_dialog_save_updates_catalog(lib_with_file, qapp):
    from darspack.ui.dialogs import MetadataDialog
    lib, file_id, _ = lib_with_file
    dlg = MetadataDialog(None, lib, file_id)
    dlg.subject.setCurrentText("فیزیک")
    dlg.chapter.setValue(4)
    dlg.kind.setCurrentText("جزوه")
    dlg.tags.setText("امتحان، فصل اول")
    dlg.note.setText("تست")
    dlg._save()

    row = lib.conn.execute(
        """SELECT f.chapter, f.kind, f.note, s.name AS subject_name
           FROM files f LEFT JOIN subjects s ON s.id = f.subject_id
           WHERE f.id=?""", (file_id,)).fetchone()
    assert row["subject_name"] == "فیزیک"             # new subject created
    assert row["chapter"] == 4 and row["kind"] == "جزوه"
    tags = [t["name"] for t in lib.conn.execute(
        """SELECT t.name FROM tags t JOIN file_tags ft ON ft.tag_id=t.id
           WHERE ft.file_id=? ORDER BY t.id""", (file_id,))]
    assert tags == ["امتحان", "فصل اول"]


def test_metadata_dialog_opens_for_unclassified_file(tmp_path, qapp):
    """A file with no suggestions at all must still open the dialog."""
    from darspack.ui.dialogs import MetadataDialog
    with Library(tmp_path / "lib") as lib:
        src = tmp_path / "IMG_20260101_1234.pdf"
        src.write_bytes(b"camera-dump")
        import_file(lib, src)
        file_id = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        dlg = MetadataDialog(None, lib, file_id)
        assert dlg.subject.currentText() == ""
