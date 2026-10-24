"""All dialogs in one place (دیالوگ‌ها).

Each dialog is one small class with a single purpose; keeping them in
one file makes the UI easy to read end-to-end. File dialogs never
delete or overwrite anything — export writes a new ZIP, verify only
reads, package-import goes through the normal importer (duplicates
skipped).
"""
from __future__ import annotations

import json
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton,
    QSpinBox, QTabWidget, QTextEdit, QVBoxLayout,
)

from .. import __version__
from ..core import db, manifest as manifest_core
from ..core.normalize import persian_digits
from ..i18n import STRINGS, tr
from .workers import ImportWorker


def text_dialog(parent, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def feedback_dialog(parent) -> None:
    """In-app feedback form: saved to feedback.jsonl in the library root."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("btn_feedback"))
    box = QTextEdit()
    box.setPlaceholderText(tr("feedback_placeholder"))
    save = QPushButton(tr("ok"))
    layout = QVBoxLayout(dlg)
    layout.addWidget(box)
    layout.addWidget(save)
    save.clicked.connect(dlg.accept)
    if dlg.exec() and box.toPlainText().strip():
        target = Path(parent.lib.root) / "feedback.jsonl"
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "text": box.toPlainText().strip()}, ensure_ascii=False) + "\n")
        db.log(parent.lib.conn, "feedback", "")
        QMessageBox.information(parent, tr("btn_feedback"), tr("feedback_thanks"))


class ImportDialog(QDialog):
    """Pick files or a folder; import runs in a background worker."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("import_title"))
        self.parent_window = parent
        pick_files = QPushButton(tr("import_pick_files"))
        pick_folder = QPushButton(tr("import_pick_folder"))
        self.keep = QCheckBox(tr("import_keep"))
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(pick_files)
        row.addWidget(pick_folder)
        layout.addLayout(row)
        layout.addWidget(self.keep)
        pick_files.clicked.connect(self._pick_files)
        pick_folder.clicked.connect(self._pick_folder)

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, tr("import_title"))
        if paths:
            self._start(paths)

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("import_title"))
        if path:
            self._start([path])

    def _start(self, paths) -> None:
        self.parent_window.run_import_worker(paths, self.keep.isChecked())
        self.accept()


class ExportDialog(QDialog):
    """Export selected files or the whole current filter as a درس‌پک."""

    def __init__(self, parent, selected_ids: list):
        super().__init__(parent)
        self.parent_window = parent
        self.selected_ids = selected_ids
        self.setWindowTitle(tr("export_title"))

        btn_selected = QPushButton(
            tr("export_scope_selected").format(len(selected_ids)))
        btn_filtered = QPushButton(
            tr("export_scope_filtered").format(len(parent.last_rows)))
        btn_selected.setEnabled(bool(selected_ids))
        layout = QVBoxLayout(self)
        layout.addWidget(btn_selected)
        layout.addWidget(btn_filtered)
        btn_selected.clicked.connect(lambda: self._export(selected_ids))
        btn_filtered.clicked.connect(
            lambda: self._export([r["id"] for r in parent.last_rows]))

    def _export(self, file_ids: list) -> None:
        if not file_ids:
            return
        default = f"darspack-{datetime.now():%Y%m%d-%H%M}.zip"
        path, _ = QFileDialog.getSaveFileName(
            self, tr("export_title"), default, "ZIP (*.zip)")
        if not path:
            return
        lib = self.parent_window.lib
        info = manifest_core.export_package(
            lib.conn, lib.files_dir, file_ids, path)
        db.log(lib.conn, "export", f"{info['count']} files → {path}")
        QMessageBox.information(
            self, tr("export_title"),
            tr("export_done").format(info["count"], info["manifest_sha256"][:16]))
        self.accept()


class VerifyReportDialog(QDialog):
    """Show a درس‌پک verification report; optionally import its contents."""

    def __init__(self, parent, path, report, library, offer_import=False):
        super().__init__(parent)
        self.parent_window = parent
        self.path, self.report = path, report
        self.setWindowTitle(tr("btn_verify"))
        text = (tr("verify_ok") if report.ok
                else tr("verify_problems") + "\n" + "\n".join(report.problems))
        label = QLabel(text)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        db.log(library.conn, "verify",
               f"{'ok' if report.ok else len(report.problems)} problems — {path}")
        if report.ok and offer_import:
            btn = QPushButton(tr("pkg_import_btn"))
            btn.clicked.connect(self._import_contents)
            layout.addWidget(btn)

    def _import_contents(self) -> None:
        """Extract to a temp folder and import through the normal pipeline."""
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(self.path) as zf:
                zf.extractall(tmp)
            files_dir = Path(tmp) / "files"
            self.parent_window.run_import_worker([files_dir])
        self.accept()


class DuplicatesDialog(QDialog):
    """Read-only flag view of R1/R2/R3 groups. Double-click searches the name."""

    def __init__(self, parent, groups_by_tab: dict):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle(tr("btn_dups"))
        self.resize(700, 420)
        tabs = QTabWidget()
        for title, groups in groups_by_tab.items():
            listing = QListWidget()
            for group in groups:
                names = " ، ".join(r["original_name"] for r in group.rows)
                listing.addItem(f"[{group.label_fa}] {names}\n    {group.detail_fa}")
            listing.itemDoubleClicked.connect(self._jump)
            tabs.addTab(listing, f"{title} ({len(groups)})")
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

    def _jump(self, item) -> None:
        # item text: "[label] name1 ، name2\n    detail" — search the first name
        first = item.text().split("] ", 1)[1].split(" ، ", 1)[0].strip()
        self.parent_window.search_box.setText(first)
        self.accept()


class MetadataDialog(QDialog):
    """Edit one file's subject/chapter/kind/tags/note."""

    def __init__(self, parent, lib, file_id: int):
        super().__init__(parent)
        self.lib, self.file_id = lib, file_id
        self.setWindowTitle(tr("meta_title"))
        # join subjects so the dialog can show the current subject's NAME
        self.row = lib.conn.execute(
            """SELECT f.*, s.name AS subject_name
               FROM files f LEFT JOIN subjects s ON s.id = f.subject_id
               WHERE f.id=?""", (file_id,)).fetchone()

        self.subject = QComboBox()
        self.subject.setEditable(True)
        for r in lib.conn.execute("SELECT name FROM subjects ORDER BY name"):
            self.subject.addItem(r["name"])
        self.subject.setCurrentText(self.row["subject_name"] or "")

        self.chapter = QSpinBox()
        self.chapter.setRange(0, 40)          # 0 = no chapter
        self.chapter.setValue(self.row["chapter"] or 0)

        self.kind = QComboBox()
        for k in ("جزوه", "نمونه‌سوال", "کاربرگ", "تکلیف", "سایر"):
            self.kind.addItem(k)
        self.kind.setCurrentText(self.row["kind"] or "سایر")

        self.tags = QLineEdit()
        tag_names = [t["name"] for t in lib.conn.execute(
            """SELECT t.name FROM tags t JOIN file_tags ft ON ft.tag_id=t.id
               WHERE ft.file_id=?""", (file_id,))]
        self.tags.setText("، ".join(tag_names))

        self.note = QLineEdit(self.row["note"] or "")

        save = QPushButton(tr("ok"))
        save.clicked.connect(self._save)

        form = QVBoxLayout(self)
        for label, widget in ((tr("meta_subject"), self.subject),
                              (tr("meta_chapter"), self.chapter),
                              (tr("meta_kind"), self.kind),
                              (tr("meta_tags"), self.tags),
                              (tr("meta_note"), self.note)):
            row = QHBoxLayout()
            lab = QLabel(label)
            lab.setMinimumWidth(90)
            row.addWidget(lab)
            row.addWidget(widget)
            form.addLayout(row)
        form.addWidget(save)

    def _save(self) -> None:
        conn = self.lib.conn
        with conn:
            subject_id = (db.get_or_create(conn, "subjects",
                                           self.subject.currentText())
                          if self.subject.currentText().strip() else None)
            chapter = self.chapter.value() or None
            conn.execute(
                """UPDATE files SET subject_id=?, chapter=?, kind=?, note=?
                   WHERE id=?""",
                (subject_id, chapter, self.kind.currentText(),
                 self.note.text(), self.file_id))
            conn.execute("DELETE FROM file_tags WHERE file_id=?", (self.file_id,))
            for tag in self.tags.text().replace(",", "،").split("،"):
                tag = tag.strip()
                if not tag:
                    continue
                tag_id = db.get_or_create(conn, "tags", tag)
                conn.execute(
                    "INSERT OR IGNORE INTO file_tags(file_id, tag_id) VALUES (?,?)",
                    (self.file_id, tag_id))
            db.log(conn, "edit_meta", f"id={self.file_id}")
        self.accept()


class SettingsDialog(QDialog):
    """Language, font size, library folder. Saved next to the catalog."""

    def __init__(self, parent, settings: dict, settings_path: Path):
        super().__init__(parent)
        self.settings, self.settings_path = settings, settings_path
        self.setWindowTitle(tr("settings_title"))

        self.lang = QComboBox()
        self.lang.addItem("فارسی", "fa")
        self.lang.addItem("English", "en")
        self.lang.setCurrentIndex(0 if settings.get("language", "fa") == "fa" else 1)

        self.font_size = QSpinBox()
        self.font_size.setRange(8, 18)
        self.font_size.setValue(int(settings.get("font_size", 10)))

        self.library = QLineEdit(str(settings.get("library", "")))

        browse = QPushButton("…")
        browse.clicked.connect(self._browse)

        save = QPushButton(tr("ok"))
        save.clicked.connect(self._save)

        form = QVBoxLayout(self)
        for label, widget in ((tr("settings_lang"), self.lang),
                              (tr("settings_font"), self.font_size),
                              (tr("settings_lib"), None)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            if widget is None:
                row.addWidget(self.library, 1)
                row.addWidget(browse)
            else:
                row.addWidget(widget, 1)
            form.addLayout(row)
        form.addWidget(QLabel(tr("settings_restart")))
        form.addWidget(save)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("settings_lib"))
        if path:
            self.library.setText(path)

    def _save(self) -> None:
        self.settings["language"] = self.lang.currentData()
        self.settings["font_size"] = self.font_size.value()
        self.settings["library"] = self.library.text().strip()
        self.settings_path.write_text(
            json.dumps(self.settings, ensure_ascii=False, indent=2),
            encoding="utf-8")
        self.accept()


class ShareDialog(QDialog):
    """Shows the PIN + phone URLs while the LAN server runs."""

    def __init__(self, parent, server, urls: list, on_close):
        super().__init__(parent)
        self.on_close = on_close
        self.setWindowTitle(tr("share_title"))
        layout = QVBoxLayout(self)
        pin_label = QLabel(f"{tr('share_pin')}: {persian_digits(server.pin)}")
        pin_label.setAlignment(Qt.AlignCenter)
        pin_label.setStyleSheet("font-size: 26px; font-weight: bold;")
        layout.addWidget(pin_label)
        layout.addWidget(QLabel(tr("share_urls")))
        for url in urls:
            line = QLabel(url)
            line.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(line)
        layout.addWidget(QLabel(tr("share_hint")))
        stop = QPushButton(tr("btn_stop_share"))
        stop.clicked.connect(self.accept)
        layout.addWidget(stop)

    def closeEvent(self, event) -> None:
        self.accept()
        super().closeEvent(event)
