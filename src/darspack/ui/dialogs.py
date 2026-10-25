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
    QSpinBox, QTableWidget, QTabWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout,
)

from .. import __version__
from ..core import db, manifest as manifest_core
from ..core.normalize import persian_digits
from ..i18n import STRINGS, tr
from .workers import ImportWorker


def text_dialog(parent, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def make_teacher_combo(conn, current_name: str | None) -> QComboBox:
    """Editable teacher combo (A3): blank = no teacher, existing teachers
    listed, new names are created on save via get_or_create("teachers",…)."""
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItem("")                       # «no teacher» stays possible
    for r in conn.execute("SELECT name FROM teachers ORDER BY name"):
        combo.addItem(r["name"])
    combo.setCurrentText(current_name or "")
    return combo


def make_year_combo(current: str | None) -> QComboBox:
    """Editable school-year combo (A3): the row's year (or the current
    school year) plus the years around it — anything else can be typed,
    the column is free text («1405-1406»)."""
    from ..core.schoolyear import current_school_year
    chosen = current or current_school_year()
    base = int(chosen[:4])
    combo = QComboBox()
    combo.setEditable(True)
    for y in (f"{base - 1}-{base}", chosen, f"{base + 1}-{base + 2}"):
        combo.addItem(y)
    combo.setCurrentText(chosen)
    return combo


def package_metas(zip_path) -> dict:
    """A5: {path under files/: manifest entry} for a verified درس‌پک.

    The import worker matches each extracted file by its path relative
    to the extracted files/ folder; arc names carry the «001 - » prefix,
    so duplicate display names can never collide. Callers verify the
    package first (read_manifest raises on a ZIP without a manifest).
    """
    entries = manifest_core.read_manifest(zip_path)
    return {entry["path"].removeprefix("files/"): entry for entry in entries}


def save_feedback(parent, text: str) -> None:
    """Persist one feedback entry (in-app form → feedback.jsonl)."""
    target = Path(parent.lib.root) / "feedback.jsonl"
    with open(target, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "text": text}, ensure_ascii=False) + "\n")
    db.log(parent.lib.conn, "feedback", "")


def feedback_dialog(parent=None) -> None:
    """In-app feedback form. parent=None default: Qt's clicked signal
    passes its `checked` bool to plain-function slots, so the wiring
    uses a lambda — this default is the second line of defense."""
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
        save_feedback(parent, box.toPlainText().strip())
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


class ClassifyDialog(QDialog):
    """Review the info of freshly imported files (بازبینی اطلاعات).

    Categorizing IS the app's main job, so after every import this
    dialog asks for each new file's subject / chapter / kind, pre-filled
    from the filename heuristic. Saving is one bulk update; «بعداً»
    leaves files unclassified (the «بدون درس» filter finds them again).
    """

    def __init__(self, parent, lib, file_ids: list, prefills: dict | None = None):
        """prefills (A5): {file_id: {"subject": str, "tags": [str]}} from a
        درس‌پک manifest — overrides the filename heuristic for those ids.
        Pre-fill only: saving still goes through the user's review."""
        super().__init__(parent)
        self.lib = lib
        self.setWindowTitle(tr("classify_title"))
        self.resize(860, 520)

        headers = [tr("col_name"), tr("meta_subject"), tr("meta_chapter"),
                   tr("meta_kind"), tr("meta_lesson"), tr("meta_teacher"),
                   tr("meta_year"), tr("meta_tags_col")]
        self.table = QTableWidget(len(file_ids), len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setColumnWidth(0, 380)
        self.table.setColumnWidth(5, 120)
        self.table.setColumnWidth(6, 110)
        self.table.horizontalHeader().setStretchLastSection(True)

        subjects = [r["name"] for r in lib.conn.execute(
            "SELECT name FROM subjects ORDER BY name")]
        self.rows = []                            # (file_id, widgets)
        for r, fid in enumerate(file_ids):
            file_row = lib.conn.execute(
                """SELECT f.*, s.name AS subject_name, t.name AS teacher_name
                   FROM files f
                   LEFT JOIN subjects s ON s.id=f.subject_id
                   LEFT JOIN teachers t ON t.id=f.teacher_id
                   WHERE f.id=?""", (fid,)).fetchone()

            name_item = QTableWidgetItem(file_row["original_name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 0, name_item)

            # Pre-fill: the stored subject, then the package manifest's
            # subject (A5), then the filename heuristic's suggestion —
            # for files the importer left unclassified.
            from ..core.suggest import load_hints, suggest
            suggested = suggest(Path(file_row["original_name"]).stem,
                                learned=load_hints(lib.conn))
            prefill = (prefills or {}).get(fid) or {}
            subject = QComboBox()
            subject.setEditable(True)
            subject.addItem("")                   # «no subject» stays possible
            subject.addItems(subjects)
            subject.setCurrentText(
                file_row["subject_name"] or prefill.get("subject")
                or suggested["subject"] or "")
            self.table.setCellWidget(r, 1, subject)

            chapter = QSpinBox()
            chapter.setRange(0, 40)
            chapter.setValue(file_row["chapter"] or 0)
            self.table.setCellWidget(r, 2, chapter)

            kind = QComboBox()
            kind.addItems(("جزوه", "نمونه‌سوال", "کاربرگ", "تکلیف", "سایر"))
            kind.setCurrentText(file_row["kind"] or "سایر")
            self.table.setCellWidget(r, 3, kind)

            # A3b: درس (lesson) is a separate number from فصل (chapter) —
            # either, both, or neither may be set (design decision).
            lesson = QSpinBox()
            lesson.setRange(0, 40)
            lesson.setValue(file_row["lesson"] or 0)
            self.table.setCellWidget(r, 4, lesson)

            teacher = make_teacher_combo(lib.conn, file_row["teacher_name"])
            self.table.setCellWidget(r, 5, teacher)

            year = make_year_combo(file_row["school_year"])
            self.table.setCellWidget(r, 6, year)

            # A5: the manifest's tags arrive as pre-fill too
            tags_edit = QLineEdit()
            tags_edit.setText("، ".join(prefill.get("tags") or []))
            self.table.setCellWidget(r, 7, tags_edit)

            # widget positions 0–3 are pinned by existing tests; the
            # newer fields go after them
            self.rows.append((fid, subject, chapter, kind, lesson,
                              teacher, year, tags_edit))

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("classify_hint")))

        # A2: bulk actions — the realistic import is a whole per-subject
        # folder, so the FIRST row's value can be copied onto every row
        # where that field is still empty/undecided. Per-row edits always
        # win: the bulk pass runs once, here, before saving.
        bulk = QHBoxLayout()
        for attr, key in (("subject", "bulk_subject"),
                          ("chapter", "bulk_chapter"),
                          ("kind", "bulk_kind"),
                          ("lesson", "bulk_lesson")):
            btn = QPushButton(tr(key))
            btn.clicked.connect(lambda _, a=attr: self._bulk_apply(a))
            bulk.addWidget(btn)
        layout.addLayout(bulk)

        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        later = QPushButton(tr("classify_later"))
        later.clicked.connect(self.reject)
        save = QPushButton(tr("classify_save"))
        save.setDefault(True)
        save.clicked.connect(self._save_all)
        buttons.addWidget(later)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    # self.rows layout (positions 0–3 pinned by existing tests):
    # (file_id, subject, chapter, kind, lesson, teacher, year, tags)
    _BULK_INDEX = {"subject": 1, "chapter": 2, "kind": 3, "lesson": 4}
    _BULK_EMPTY = {"chapter": 0, "lesson": 0, "kind": "سایر"}

    def _bulk_apply(self, attr: str) -> None:
        """A2: copy the first row's value onto rows where the field is
        still undecided. «Undecided» = empty subject text, chapter/lesson
        0 (this app's «none»), or kind «سایر» — a deliberate user choice
        is never overwritten. A no-op when the first row itself is
        undecided."""
        if not self.rows:
            return
        index = self._BULK_INDEX[attr]
        source = self.rows[0][index]
        if attr == "subject":
            value = source.currentText().strip()
        elif attr == "kind":
            value = source.currentText()
        else:
            value = source.value()
        if value == self._BULK_EMPTY.get(attr, ""):
            return                     # first row undecided → nothing to copy
        for row in self.rows:
            widget = row[index]
            if attr == "subject":
                if not widget.currentText().strip():
                    widget.setCurrentText(value)
            elif attr == "kind":
                if widget.currentText() == self._BULK_EMPTY["kind"]:
                    widget.setCurrentText(value)
            else:                      # chapter / lesson spinboxes
                if widget.value() == self._BULK_EMPTY[attr]:
                    widget.setValue(value)

    def _learn_tokens(self, fid: int, subject_name: str) -> None:
        """A4: remember the class's naming habits — each filename token
        (≥3 chars, not itself a subject name) votes token→subject. Only
        the next import's PRE-FILL gets smarter; nothing is auto-applied.
        """
        from ..core.normalize import match_key
        from ..core.suggest import learn_hint
        row = self.lib.conn.execute(
            "SELECT original_name FROM files WHERE id=?", (fid,)).fetchone()
        if row is None:
            return
        subject_keys = {match_key(r["name"]) for r in self.lib.conn.execute(
            "SELECT name FROM subjects")}
        for token in match_key(Path(row["original_name"]).stem).split():
            if len(token) >= 3 and token not in subject_keys:
                learn_hint(self.lib.conn, token, subject_name)

    def _save_all(self) -> None:
        conn = self.lib.conn
        with conn:
            for fid, subject, chapter, kind, lesson, teacher, year, tags in self.rows:
                name = subject.currentText().strip()
                subject_id = (db.get_or_create(conn, "subjects", name)
                              if name else None)
                teacher_name = teacher.currentText().strip()
                teacher_id = (db.get_or_create(conn, "teachers", teacher_name)
                              if teacher_name else None)
                conn.execute(
                    """UPDATE files SET subject_id=?, chapter=?, kind=?,
                       lesson=?, teacher_id=?, school_year=? WHERE id=?""",
                    (subject_id, chapter.value() or None,
                     kind.currentText(), lesson.value() or None,
                     teacher_id, year.currentText().strip() or None, fid))
                if name:
                    self._learn_tokens(fid, name)
                self._save_tags(conn, fid, tags.text())
            db.log(conn, "classify", f"{len(self.rows)} files")
        self.accept()

    def _save_tags(self, conn, fid: int, text: str) -> None:
        """Replace the file's tags with the comma/«،»-separated field."""
        conn.execute("DELETE FROM file_tags WHERE file_id=?", (fid,))
        for tag in text.replace(",", "،").split("،"):
            tag = tag.strip()
            if not tag:
                continue
            tag_id = db.get_or_create(conn, "tags", tag)
            conn.execute(
                "INSERT OR IGNORE INTO file_tags(file_id, tag_id) VALUES (?,?)",
                (fid, tag_id))


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
        """Extract to a temp folder and import through the normal pipeline.

        A5: the manifest's kind/chapter/lesson/school_year apply like
        filename suggestions, and its subject/tags come back as pre-fill
        for the classify dialog — never auto-applied. The extracted temp
        folder is removed by the import worker after it finishes (the
        worker outlives this dialog, which returns right away)."""
        metas = package_metas(self.path)
        tmp = tempfile.mkdtemp(prefix="darspack-pkg-")
        with zipfile.ZipFile(self.path) as zf:
            zf.extractall(tmp)
        files_dir = Path(tmp) / "files"
        self.parent_window.run_import_worker(
            [files_dir], metas=metas, meta_base=files_dir, cleanup_dir=Path(tmp))
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
        # joins so the dialog can show the current subject's and teacher's
        # NAMES instead of bare ids
        self.row = lib.conn.execute(
            """SELECT f.*, s.name AS subject_name, t.name AS teacher_name
               FROM files f
               LEFT JOIN subjects s ON s.id = f.subject_id
               LEFT JOIN teachers t ON t.id = f.teacher_id
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

        # A3b: درس (lesson) is a separate number from فصل (chapter) —
        # either, both, or neither may be set (design decision).
        self.lesson = QSpinBox()
        self.lesson.setRange(0, 40)
        self.lesson.setValue(self.row["lesson"] or 0)

        self.teacher = make_teacher_combo(lib.conn, self.row["teacher_name"])
        self.year = make_year_combo(self.row["school_year"])

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
                              (tr("meta_lesson"), self.lesson),
                              (tr("meta_kind"), self.kind),
                              (tr("meta_teacher"), self.teacher),
                              (tr("meta_year"), self.year),
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
            teacher_id = (db.get_or_create(conn, "teachers",
                                           self.teacher.currentText())
                          if self.teacher.currentText().strip() else None)
            chapter = self.chapter.value() or None
            conn.execute(
                """UPDATE files SET subject_id=?, chapter=?, lesson=?,
                   kind=?, teacher_id=?, school_year=?, note=?
                   WHERE id=?""",
                (subject_id, chapter, self.lesson.value() or None,
                 self.kind.currentText(), teacher_id,
                 self.year.currentText().strip() or None,
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
