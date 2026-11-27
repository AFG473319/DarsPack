"""Import dialog: Downloads default folder and Ctrl+V paste (2026-11-27)."""
from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl

from darspack.ui.dialogs import downloads_dir, paths_from_mime


def test_downloads_dir_is_existing_folder_or_empty():
    path = downloads_dir()
    assert path == "" or Path(path).is_dir()


def test_paths_from_mime_files_and_folders(tmp_path):
    f = tmp_path / "جزوه.pdf"
    f.write_bytes(b"x")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(f)), QUrl.fromLocalFile(str(tmp_path)),
                  QUrl("https://example.com/a.pdf")])
    paths = [Path(p) for p in paths_from_mime(mime)]
    assert paths == [f, tmp_path]          # web URL ignored


def test_paths_from_mime_text_only_or_none():
    mime = QMimeData()
    mime.setText("just text")
    assert paths_from_mime(mime) == []
    assert paths_from_mime(None) == []
