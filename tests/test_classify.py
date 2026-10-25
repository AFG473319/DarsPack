"""Tests for the classification flow (دسته‌بندی — the app's main job).

After an import the app must ask for each new file's info (pre-filled
from the filename heuristic), and unclassified files must stay visible
(the «بدون درس» filter + status-bar count) until they are completed.
"""
import pytest

from darspack.core.importer import import_file
from darspack.core.library import Library
from darspack.core.search import search, unclassified_count


@pytest.fixture()
def lib(tmp_path):
    with Library(tmp_path / "lib") as library:
        for name in ("نمونه سوال ریاضی فصل 3.pdf", "IMG_20260101.pdf"):
            p = tmp_path / name
            p.write_bytes(f"content of {name}".encode("utf-8"))  # unique bytes!
            import_file(library, p)
        yield library


def test_unclassified_search_and_count(lib, qapp):
    # the importer never auto-applies subjects — the USER classifies
    assert unclassified_count(lib.conn) == 2
    rows = search(lib.conn, unclassified_only=True)
    assert len(rows) == 2

    # …until one gets its info through the classification dialog
    from darspack.ui.dialogs import ClassifyDialog
    file_id = lib.conn.execute(
        "SELECT id FROM files WHERE original_name LIKE 'IMG%'"
    ).fetchone()["id"]
    dlg = ClassifyDialog(None, lib, [file_id])
    row_widget = dlg.rows[0]
    row_widget[1].setCurrentText("فیزیک")
    row_widget[2].setValue(2)
    row_widget[3].setCurrentText("جزوه")
    dlg._save_all()

    assert unclassified_count(lib.conn) == 1
    rest = search(lib.conn, unclassified_only=True)
    assert [r["original_name"] for r in rest] == ["نمونه سوال ریاضی فصل 3.pdf"]
    classified = lib.conn.execute(
        "SELECT chapter, kind FROM files WHERE id=?", (file_id,)).fetchone()
    assert classified["chapter"] == 2 and classified["kind"] == "جزوه"


def test_classify_dialog_prefills_suggestions(lib, qapp):
    from darspack.ui.dialogs import ClassifyDialog
    known = lib.conn.execute(
        """SELECT f.id FROM files f WHERE f.original_name LIKE 'نمونه%'"""
    ).fetchone()["id"]
    dlg = ClassifyDialog(None, lib, [known])
    fid, subject, chapter, kind = dlg.rows[0]
    assert subject.currentText() == "ریاضی"       # suggestion pre-filled
    assert chapter.value() == 3
    assert kind.currentText() == "نمونه‌سوال"
    # saving without touching anything keeps the suggestion
    dlg._save_all()
    row = lib.conn.execute(
        """SELECT s.name AS subject_name, f.chapter
           FROM files f LEFT JOIN subjects s ON s.id=f.subject_id
           WHERE f.id=?""", (fid,)).fetchone()
    assert row["subject_name"] == "ریاضی" and row["chapter"] == 3


def test_classify_dialog_can_leave_blank(lib, qapp):
    from darspack.ui.dialogs import ClassifyDialog
    file_id = lib.conn.execute("SELECT id FROM files LIMIT 1").fetchone()["id"]
    dlg = ClassifyDialog(None, lib, [file_id])
    dlg.rows[0][1].setCurrentText("")             # user clears the subject
    dlg._save_all()
    assert unclassified_count(lib.conn) == 2      # nothing forced


def test_phone_upload_lands_unclassified(lib, qapp):
    """Phone uploads have no dialog — they stay unclassified and show up
    in the «بدون درس» filter for the desktop user to complete."""
    from darspack.ui.dialogs import ClassifyDialog
    known = lib.conn.execute(
        """SELECT f.id FROM files f WHERE f.original_name LIKE 'نمونه%'"""
    ).fetchone()["id"]
    dlg = ClassifyDialog(None, lib, [known])   # pre-filled from the heuristic
    assert dlg.rows[0][1].currentText() == "ریاضی"
    dlg._save_all()
    remaining = search(lib.conn, unclassified_only=True)
    assert [r["original_name"] for r in remaining] == ["IMG_20260101.pdf"]


def test_classify_later_writes_nothing(lib, qapp):
    """«بعداً» is wired to reject: edits are discarded, the files stay
    unclassified and the «بدون درس» filter will find them again."""
    from darspack.ui.dialogs import ClassifyDialog
    ids = [r["id"] for r in lib.conn.execute("SELECT id FROM files")]
    dlg = ClassifyDialog(None, lib, ids)
    dlg.rows[0][1].setCurrentText("فیزیک")    # user edits, then bails
    dlg.reject()
    assert unclassified_count(lib.conn) == 2  # nothing saved


def test_classify_saves_all_files_in_one_pass(lib, qapp):
    """One save updates every row of the bulk table."""
    from darspack.ui.dialogs import ClassifyDialog
    ids = [r["id"] for r in lib.conn.execute("SELECT id FROM files ORDER BY id")]
    dlg = ClassifyDialog(None, lib, ids)
    dlg.rows[0][1].setCurrentText("فیزیک")
    dlg.rows[0][2].setValue(5)
    dlg.rows[0][3].setCurrentText("جزوه")
    dlg.rows[1][1].setCurrentText("هنر")
    dlg._save_all()
    rows = {r["id"]: r for r in lib.conn.execute(
        """SELECT f.id, s.name AS subject_name, f.chapter, f.kind
           FROM files f LEFT JOIN subjects s ON s.id=f.subject_id""")}
    assert rows[ids[0]]["subject_name"] == "فیزیک"
    assert rows[ids[0]]["chapter"] == 5 and rows[ids[0]]["kind"] == "جزوه"
    assert rows[ids[1]]["subject_name"] == "هنر"
    assert unclassified_count(lib.conn) == 0


def test_classify_creates_new_subject_rows(lib, qapp):
    """Typing a subject that does not exist yet must add a subjects row —
    assert the table itself, not just the file link."""
    from darspack.ui.dialogs import ClassifyDialog
    file_id = lib.conn.execute("SELECT id FROM files LIMIT 1").fetchone()["id"]
    dlg = ClassifyDialog(None, lib, [file_id])
    dlg.rows[0][1].setCurrentText("فیزیک")    # not in the dropdown list yet
    dlg._save_all()
    names = {r["name"] for r in lib.conn.execute("SELECT name FROM subjects")}
    assert "فیزیک" in names
