import zipfile
from PySide6.QtWidgets import QTableWidget
from darspack.core.library import Library
from darspack.core.importer import import_file
from darspack.core import db
from darspack.ui import dialogs, main_window as mw_module


def test_exam_pack_dialog_and_export(tmp_path, qapp, monkeypatch):
    with Library(tmp_path / "lib") as lib:
        sub_math = db.get_or_create(lib.conn, "subjects", "ریاضی")
        sub_sci = db.get_or_create(lib.conn, "subjects", "علوم")

        # File 1: Math exam (exam kind)
        f1 = tmp_path / "math_exam.pdf"
        f1.write_bytes(b"%PDF-exam")
        import_file(lib, f1)

        # File 2: Math notes (notes kind)
        f2 = tmp_path / "math_summary.pdf"
        f2.write_bytes(b"%PDF-summary")
        import_file(lib, f2)

        # File 3: Math homework (non-exam kind)
        f3 = tmp_path / "math_general.pdf"
        f3.write_bytes(b"%PDF-general")
        import_file(lib, f3)

        # File 4: Science exam (exam kind)
        f4 = tmp_path / "sci_exam.pdf"
        f4.write_bytes(b"%PDF-sci")
        import_file(lib, f4)

        with lib.conn:
            lib.conn.execute("UPDATE files SET subject_id=?, kind='نمونه‌سوال' WHERE original_name='math_exam.pdf'", (sub_math,))
            lib.conn.execute("UPDATE files SET subject_id=?, kind='جزوه' WHERE original_name='math_summary.pdf'", (sub_math,))
            lib.conn.execute("UPDATE files SET subject_id=?, kind='تکلیف' WHERE original_name='math_general.pdf'", (sub_math,))
            lib.conn.execute("UPDATE files SET subject_id=?, kind='نمونه‌سوال' WHERE original_name='sci_exam.pdf'", (sub_sci,))

    win = mw_module.MainWindow(tmp_path / "lib",
                               {"language": "fa", "font_size": 10,
                                "library": str(tmp_path / "lib")},
                               tmp_path / "settings.json")
    try:
        dlg = dialogs.ExamPackDialog(win, win.lib)

        # Edit triggers are disabled
        assert dlg.table.editTriggers() == QTableWidget.NoEditTriggers

        # 1. By default, exam_only is True, all subjects -> files 1, 2, 4 (3 items)
        assert dlg.table.rowCount() == 3

        # 2. Filter by Math subject
        idx = dlg.subject_combo.findText("ریاضی")
        assert idx != -1
        dlg.subject_combo.setCurrentIndex(idx)
        # Math has 2 exam items (exam + notes)
        assert dlg.table.rowCount() == 2

        # 3. Uncheck exam_only -> all 3 Math files appear
        dlg.exam_only_check.setChecked(False)
        assert dlg.table.rowCount() == 3

        # 4. Check package creation
        export_target = tmp_path / "out_math_pack.zip"
        monkeypatch.setattr(dialogs.QFileDialog, "getSaveFileName", lambda *args, **kw: (str(export_target), "ZIP"))
        monkeypatch.setattr(dialogs.QMessageBox, "information", lambda *args, **kw: None)

        dlg._create_package()
        assert export_target.exists()

        # Verify package integrity
        with zipfile.ZipFile(export_target, "r") as zf:
            namelist = zf.namelist()
            assert "manifest.json" in namelist
            assert "index.html" in namelist
            stored_files = [n for n in namelist if n.startswith("files/")]
            assert len(stored_files) == 3

        # Verify activity log
        log_row = win.lib.conn.execute("SELECT * FROM activity_log WHERE action='exam_pack'").fetchone()
        assert log_row is not None
        assert "3 files" in log_row["detail"]
    finally:
        win.lib.close()
