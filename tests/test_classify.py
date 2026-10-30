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
    fid, subject, chapter, kind = dlg.rows[0][:4]   # newer fields follow
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


def test_classify_saves_year_and_lesson_and_preserves_teacher(lib, qapp):
    """A3/A3b: year and lesson persist. The teacher input is gone from
    the review form, but removing it must not erase a teacher already
    stored in an existing catalog."""
    from darspack.core import db
    from darspack.ui.dialogs import ClassifyDialog
    ids = [r["id"] for r in lib.conn.execute(
        "SELECT id FROM files ORDER BY id")]
    with lib.conn:
        teacher_id = db.get_or_create(lib.conn, "teachers", "خانم احمدی")
        lib.conn.execute("UPDATE files SET teacher_id=? WHERE id=?",
                         (teacher_id, ids[0]))
    dlg = ClassifyDialog(None, lib, ids)
    dlg.rows[0][1].setCurrentText("ریاضی")
    dlg.rows[0][2].setValue(5)          # chapter (فصل)
    dlg.rows[0][4].setValue(2)          # lesson (درس) — independent field
    dlg.rows[0][5].setCurrentText("1404-1405")
    dlg._save_all()

    rows = {r["id"]: r for r in lib.conn.execute(
        """SELECT f.id, f.chapter, f.lesson, f.school_year,
                  t.name AS teacher_name
           FROM files f LEFT JOIN teachers t ON t.id=f.teacher_id""")}
    saved = rows[ids[0]]
    assert saved["chapter"] == 5 and saved["lesson"] == 2
    assert saved["school_year"] == "1404-1405"
    assert saved["teacher_name"] == "خانم احمدی"   # untouched by the form
    assert rows[ids[1]]["teacher_name"] is None


def test_classify_lesson_defaults_to_current_school_year(lib, qapp):
    """A3: a file without a stored school year shows the current one as
    the pre-fill (the importer also stamps it at import time)."""
    from darspack.core.schoolyear import current_school_year
    from darspack.ui.dialogs import ClassifyDialog
    file_id = lib.conn.execute("SELECT id FROM files LIMIT 1").fetchone()["id"]
    dlg = ClassifyDialog(None, lib, [file_id])
    assert dlg.rows[0][5].currentText() == current_school_year()


def test_bulk_subject_fills_only_empty_rows(lib, qapp):
    """A2: the first row's subject copies onto rows with no subject —
    a row the user already chose a subject for is never overwritten."""
    from darspack.ui.dialogs import ClassifyDialog
    ids = [r["id"] for r in lib.conn.execute(
        "SELECT id FROM files ORDER BY id")]
    dlg = ClassifyDialog(None, lib, ids)
    dlg.rows[0][1].setCurrentText("ریاضی")     # first row's choice
    # rows[1] stays empty (its filename gives no subject hint)
    dlg._bulk_apply("subject")
    assert dlg.rows[1][1].currentText() == "ریاضی"   # empty → filled

    dlg2 = ClassifyDialog(None, lib, ids)      # both rows already chosen
    dlg2.rows[0][1].setCurrentText("ریاضی")
    dlg2.rows[1][1].setCurrentText("هنر")
    dlg2._bulk_apply("subject")
    assert dlg2.rows[1][1].currentText() == "هنر"    # override untouched


def test_bulk_kind_chapter_lesson_fill_undecided_rows(lib, qapp):
    """A2: kind copies over rows still on «سایر»; chapter/lesson copy
    over rows still on 0 («none»). First row undecided → no-op."""
    from darspack.ui.dialogs import ClassifyDialog
    ids = [r["id"] for r in lib.conn.execute(
        "SELECT id FROM files ORDER BY id")]
    dlg = ClassifyDialog(None, lib, ids)
    dlg.rows[0][2].setValue(5)                  # chapter
    dlg.rows[0][3].setCurrentText("جزوه")       # kind
    dlg.rows[0][4].setValue(2)                  # lesson
    dlg._bulk_apply("chapter")
    dlg._bulk_apply("kind")
    dlg._bulk_apply("lesson")
    for row in dlg.rows:
        assert row[2].value() == 5
        assert row[3].currentText() == "جزوه"
        assert row[4].value() == 2

    dlg2 = ClassifyDialog(None, lib, ids)       # first row undecided
    dlg2.rows[0][2].setValue(0)                 # user clears the chapter
    dlg2._bulk_apply("chapter")                 # chapter 0 → nothing happens
    assert dlg2.rows[1][2].value() == 0


def test_bulk_then_save_persists_and_per_row_edit_wins(lib, qapp):
    """A2 acceptance trio: bulk fills only empty, save persists to all
    rows, and a per-row edit AFTER the bulk pass wins."""
    from darspack.ui.dialogs import ClassifyDialog
    ids = [r["id"] for r in lib.conn.execute(
        "SELECT id FROM files ORDER BY id")]
    dlg = ClassifyDialog(None, lib, ids)
    dlg.rows[0][1].setCurrentText("ریاضی")
    dlg._bulk_apply("subject")
    dlg.rows[1][1].setCurrentText("فیزیک")      # per-row override after bulk
    dlg._save_all()
    names = {r["id"]: r["subject_name"] for r in lib.conn.execute(
        """SELECT f.id, s.name AS subject_name FROM files f
           LEFT JOIN subjects s ON s.id=f.subject_id""")}
    assert names[ids[0]] == "ریاضی"
    assert names[ids[1]] == "فیزیک"


def test_classify_learns_token_hints(lib, qapp):
    """A4: two saves of similarly-named files → the token's rule has
    2 hits, and the NEXT import's dialog pre-fills it. Tokens that are
    subject names are never learned."""
    from darspack.core.importer import import_file
    from darspack.ui.dialogs import ClassifyDialog

    def classify_named(name):
        src = lib.root.parent / name
        src.write_bytes(f"content {name}".encode("utf-8"))
        import_file(lib, src)
        fid = lib.conn.execute(
            "SELECT id FROM files WHERE original_name=?", (name,)).fetchone()["id"]
        dlg = ClassifyDialog(None, lib, [fid])
        dlg.rows[0][1].setCurrentText("ریاضی")
        dlg._save_all()

    classify_named("جزوه رضایی فصل 1.pdf")
    classify_named("جزوه رضایی فصل 2.pdf")

    from darspack.core.suggest import load_hints
    hints = load_hints(lib.conn)
    assert "رضایی" in hints and hints["رضایی"]["hits"] == 2
    assert "ریاضی" not in hints                  # subject names aren't rules

    # the third import: the dialog's pre-fill now knows the token
    src = lib.root.parent / "جزوه رضایی فصل 3.pdf"
    src.write_bytes(b"content third")
    import_file(lib, src)
    fid = lib.conn.execute(
        "SELECT id FROM files WHERE original_name=?",
        ("جزوه رضایی فصل 3.pdf",)).fetchone()["id"]
    dlg = ClassifyDialog(None, lib, [fid])
    assert dlg.rows[0][1].currentText() == "ریاضی"   # learned pre-fill


def test_package_import_prefills_from_manifest(tmp_path, qapp):
    """A5 round-trip: a classified file is exported as a درس‌پک and
    imported into a fresh library — kind/chapter/school_year are applied
    from the manifest, subject/tags arrive as ClassifyDialog pre-fill,
    and saving makes them real. Mirrors VerifyReportDialog._import_contents."""
    import zipfile

    from darspack.core import db
    from darspack.core.manifest import export_package
    from darspack.ui.dialogs import ClassifyDialog, package_metas
    from darspack.ui.workers import ImportWorker

    with Library(tmp_path / "sender") as lib:
        src = tmp_path / "جزوه فیزیک فصل 2.pdf"
        src.write_bytes(b"pkg demo")
        import_file(lib, src)
        fid = lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        with lib.conn:
            sid = db.get_or_create(lib.conn, "subjects", "فیزیک")
            lib.conn.execute(
                "UPDATE files SET subject_id=? WHERE id=?", (sid, fid))
            tid = db.get_or_create(lib.conn, "tags", "امتحان")
            lib.conn.execute(
                "INSERT INTO file_tags(file_id, tag_id) VALUES (?,?)", (fid, tid))
        export_package(lib.conn, lib.files_dir, [fid],
                       str(tmp_path / "pkg.zip"))

    metas = package_metas(tmp_path / "pkg.zip")
    assert len(metas) == 1                 # keyed by the arc name's file part

    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with zipfile.ZipFile(tmp_path / "pkg.zip") as zf:
        zf.extractall(extracted)
    files_dir = extracted / "files"

    worker = ImportWorker(str(tmp_path / "receiver"), [files_dir],
                          metas=metas, meta_base=files_dir,
                          cleanup_dir=extracted)
    worker.run()                           # direct call — no thread needed
    assert len(worker.result_prefills) == 1
    (new_id, prefill), = worker.result_prefills.items()
    assert prefill["subject"] == "فیزیک"
    assert prefill["tags"] == ["امتحان"]
    assert not extracted.exists()          # worker cleaned the temp folder

    with Library(tmp_path / "receiver") as lib2:
        row = lib2.conn.execute(
            "SELECT kind, chapter, school_year FROM files WHERE id=?",
            (new_id,)).fetchone()
        assert row["kind"] == "جزوه"                # manifest kind applied
        assert row["chapter"] == 2                  # manifest chapter applied
        dlg = ClassifyDialog(None, lib2, [new_id],
                             prefills=worker.result_prefills)
        assert dlg.rows[0][1].currentText() == "فیزیک"   # pre-fill shown
        assert dlg.rows[0][6].text() == "امتحان"         # tags pre-filled
        dlg._save_all()                                  # review → real
        saved = lib2.conn.execute(
            """SELECT s.name AS subject_name FROM files f
               LEFT JOIN subjects s ON s.id=f.subject_id WHERE f.id=?""",
            (new_id,)).fetchone()
        assert saved["subject_name"] == "فیزیک"
        tags = [t["name"] for t in lib2.conn.execute(
            """SELECT t.name FROM tags t JOIN file_tags ft ON ft.tag_id=t.id
               WHERE ft.file_id=?""", (new_id,))]
        assert tags == ["امتحان"]
