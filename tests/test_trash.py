from PySide6.QtWidgets import QMessageBox, QTableWidget
from darspack.core.library import Library
from darspack.core.importer import import_file
from darspack.core import db
from darspack.ui import dialogs, main_window as mw_module


def test_trash_empty_library(tmp_path):
    with Library(tmp_path / "lib") as lib:
        assert lib.list_trash() == []
        assert lib.empty_trash() == 0


def test_trash_restore_and_empty(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(mw_module.QMessageBox, "question", lambda *args, **kw: QMessageBox.Yes)
    win = mw_module.MainWindow(tmp_path / "lib",
                               {"language": "fa", "font_size": 10,
                                "library": str(tmp_path / "lib")},
                               tmp_path / "settings.json")
    try:
        f1 = tmp_path / "sample_math.pdf"
        f1.write_bytes(b"%PDF-math")
        import_file(win.lib, f1)

        row = win.lib.conn.execute("SELECT id, stored_name, imported_at FROM files").fetchone()
        assert row is not None
        file_id = row["id"]
        original_imported_at = row["imported_at"]

        # Add tags to the file
        t1 = db.get_or_create(win.lib.conn, "tags", "امتحان")
        t2 = db.get_or_create(win.lib.conn, "tags", "مهم")
        with win.lib.conn:
            win.lib.conn.execute("INSERT INTO file_tags (file_id, tag_id) VALUES (?, ?)", (file_id, t1))
            win.lib.conn.execute("INSERT INTO file_tags (file_id, tag_id) VALUES (?, ?)", (file_id, t2))

        # 1. Delete file using delete_file / delete_selected_files
        win.delete_file(file_id)

        # File is gone from catalog and file_tags cascaded
        assert win.lib.conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"] == 0
        assert win.lib.conn.execute("SELECT COUNT(*) c FROM file_tags").fetchone()["c"] == 0

        # Trash contains file and sidecar with tags and imported_at
        trash_items = win.lib.list_trash()
        assert len(trash_items) == 1
        assert trash_items[0]["original_name"] == "sample_math.pdf"
        assert set(trash_items[0]["meta"].get("tags", [])) == {"امتحان", "مهم"}
        assert trash_items[0]["meta"].get("imported_at") == original_imported_at

        # 2. Restore file
        trash_name = trash_items[0]["trash_name"]
        res = win.lib.restore_trash_file(trash_name)
        assert res["original_name"] == "sample_math.pdf"

        # Catalog has restored file with original imported_at and tags restored!
        restored_row = win.lib.conn.execute("SELECT * FROM files WHERE id=?", (res["id"],)).fetchone()
        assert restored_row is not None
        assert restored_row["imported_at"] == original_imported_at

        restored_tags = [
            r[0] for r in win.lib.conn.execute(
                "SELECT t.name FROM tags t JOIN file_tags ft ON ft.tag_id=t.id WHERE ft.file_id=?",
                (res["id"],)
            ).fetchall()
        ]
        assert set(restored_tags) == {"امتحان", "مهم"}
        assert len(win.lib.list_trash()) == 0

        # 3. Test empty_trash
        new_row = win.lib.conn.execute("SELECT id FROM files").fetchone()
        win.delete_file(new_row["id"])
        assert len(win.lib.list_trash()) == 1

        cleared = win.lib.empty_trash()
        assert cleared == 1
        assert len(win.lib.list_trash()) == 0
    finally:
        win.lib.close()


def test_trash_restore_name_collision(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(mw_module.QMessageBox, "question", lambda *args, **kw: QMessageBox.Yes)
    win = mw_module.MainWindow(tmp_path / "lib",
                               {"language": "fa", "font_size": 10,
                                "library": str(tmp_path / "lib")},
                               tmp_path / "settings.json")
    try:
        f1 = tmp_path / "sample.pdf"
        f1.write_bytes(b"%PDF-1")
        import_file(win.lib, f1)

        row = win.lib.conn.execute("SELECT id, stored_name FROM files").fetchone()
        stored_name = row["stored_name"]
        win.delete_file(row["id"])

        # Re-create a file in files/ with the same stored_name
        collision_file = win.lib.files_dir / stored_name
        collision_file.write_bytes(b"%PDF-collision")

        # Restore from trash
        trash_item = win.lib.list_trash()[0]
        res = win.lib.restore_trash_file(trash_item["trash_name"])

        # Restored file is renamed with ~1
        assert res["stored_name"] != stored_name
        assert "~1" in res["stored_name"]
        assert (win.lib.files_dir / res["stored_name"]).exists()
        assert collision_file.exists()  # existing file was preserved!
    finally:
        win.lib.close()


def test_trash_dialog_ui(tmp_path, qapp, monkeypatch):
    monkeypatch.setattr(mw_module.QMessageBox, "question", lambda *args, **kw: QMessageBox.Yes)
    win = mw_module.MainWindow(tmp_path / "lib",
                               {"language": "fa", "font_size": 10,
                                "library": str(tmp_path / "lib")},
                               tmp_path / "settings.json")
    try:
        # 1. TrashDialog when empty
        dlg = dialogs.TrashDialog(win, win.lib)
        assert dlg.table.editTriggers() == QTableWidget.NoEditTriggers
        assert not dlg.empty_label.isHidden()
        assert not dlg.btn_restore.isEnabled()

        # No selection test
        info_called = []
        monkeypatch.setattr(dialogs.QMessageBox, "information", lambda *args, **kw: info_called.append(True))
        dlg._restore_selected()
        assert len(info_called) == 1
        dlg.close()

        # 2. Add file and delete to populate trash
        f1 = tmp_path / "exam1.pdf"
        f1.write_bytes(b"%PDF-exam")
        import_file(win.lib, f1)
        fid = win.lib.conn.execute("SELECT id FROM files").fetchone()["id"]
        win.delete_file(fid)

        dlg2 = dialogs.TrashDialog(win, win.lib)
        assert dlg2.empty_label.isHidden()
        assert dlg2.table.rowCount() == 1
        assert dlg2.btn_restore.isEnabled()

        # Select row and restore
        dlg2.table.selectAll()
        dlg2._restore_selected()
        assert dlg2.restored_any is True
        assert dlg2.table.rowCount() == 0
        dlg2.close()

        # Verify back in catalog
        assert win.lib.conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"] == 1
    finally:
        win.lib.close()
