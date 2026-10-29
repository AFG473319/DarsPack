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

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QProgressBar,

    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTabWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
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


def pick_lan_url(urls) -> str | None:
    """D3: the first URL a phone can reach — never a loopback one."""
    from urllib.parse import urlparse
    for url in urls:
        if (urlparse(url).hostname or "") not in ("127.0.0.1", "localhost",
                                                  "::1"):
            return url
    return None


def qr_svg_bytes(url: str) -> bytes:
    """D3: the share URL as a QR-code SVG (pure Python — the `qrcode`
    package, registered in docs/dependencies.md). The QR itself is path
    data with no text, so the URL is embedded as a <title>: the SVG
    stays self-describing and the tests can pin its content."""
    import io

    import qrcode
    import qrcode.image.svg          # needed before the factory resolves
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")
    if url not in svg:
        svg = svg.replace("</svg>", f"<title>{url}</title></svg>")
    return svg.encode("utf-8")


def save_feedback(parent, payload: dict) -> None:
    """Persist one feedback entry (in-app form → feedback.jsonl).

    `payload` is the full dict from build_feedback_payload — the same
    shape the online endpoint receives, so the local file is a complete
    mirror of what was (or could not be) sent.
    """
    target = Path(parent.lib.root) / "feedback.jsonl"
    with open(target, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def build_feedback_payload(rating: int, category: str, message: str,
                           contact: str) -> dict:
    """One dict per feedback entry — the same shape saved locally and
    POSTed online, so nothing is ever lost and the receiver gets one
    predictable schema."""
    from datetime import datetime
    from .. import __version__
    return {
        "app": "DarsPack",
        "version": __version__,
        "rating": rating if rating else None,
        "category": category,
        "message": message,
        "contact": contact,
        "sent_at": datetime.now().isoformat(timespec="seconds"),
    }


class FeedbackDialog(QDialog):
    """The «بازخورد» dialog the way apps actually do it: star rating,
    topic, message, optional contact. Submit saves the entry locally
    FIRST (a failure never loses feedback), then tries the configured
    endpoint in a background thread; with no endpoint the user is told
    it was saved locally (and can open the web form if one is set)."""

    def __init__(self, parent, settings: dict):
        super().__init__(parent)
        self.parent_window = parent
        self.settings = settings
        self.setWindowTitle(tr("btn_feedback"))
        self.rating = 0

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("fb_rating")))
        stars = QHBoxLayout()
        self.star_buttons = []
        for i in range(1, 6):
            star = QPushButton("☆")
            star.setCheckable(True)
            star.setFixedWidth(40)
            star.clicked.connect(lambda checked, n=i: self._set_stars(n))
            stars.addWidget(star)
            self.star_buttons.append(star)
        layout.addLayout(stars)

        layout.addWidget(QLabel(tr("fb_category")))
        self.category = QComboBox()
        for key in ("fb_cat_bug", "fb_cat_idea", "fb_cat_question",
                    "fb_cat_praise"):
            self.category.addItem(tr(key), key)
        layout.addWidget(self.category)

        self.message = QTextEdit()
        self.message.setPlaceholderText(tr("feedback_placeholder"))
        layout.addWidget(self.message)

        self.contact = QLineEdit()
        self.contact.setPlaceholderText(tr("fb_contact"))
        layout.addWidget(self.contact)

        self.submit = QPushButton(tr("fb_submit"))
        self.submit.setDefault(True)
        self.submit.clicked.connect(self._submit)
        layout.addWidget(self.submit)

    def _set_stars(self, n: int) -> None:
        self.rating = n
        for i, star in enumerate(self.star_buttons, start=1):
            star.setText("★" if i <= n else "☆")

    def _endpoint(self) -> str:
        from .. import feedback_config
        return (self.settings.get("feedback_endpoint")
                or feedback_config.FEEDBACK_ENDPOINT)

    def _form_url(self) -> str:
        from .. import feedback_config
        return (self.settings.get("feedback_form_url")
                or feedback_config.FEEDBACK_FORM_URL)

    def _submit(self) -> None:
        text = self.message.toPlainText().strip()
        if not text:
            QMessageBox.information(self, tr("btn_feedback"),
                                    tr("fb_need_message"))
            return
        payload = build_feedback_payload(
            self.rating, self.category.currentData(), text,
            self.contact.text().strip())
        save_feedback(self.parent_window, payload)   # local first: never lost
        db.log(self.parent_window.lib.conn, "feedback", payload["category"])
        endpoint = self._endpoint()
        if endpoint:
            from .workers import FeedbackPoster
            self._poster = FeedbackPoster(endpoint, payload)
            self._poster.done.connect(self._posted)
            self._poster.start()
            self.accept()                     # dialog closes; poster continues
            return
        form_url = self._form_url()
        if form_url:
            button = QPushButton(tr("fb_open_form"))
            button.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(form_url)))
            self.layout().replaceWidget(self.submit, button)
            self.submit.hide()
            button.show()
            QMessageBox.information(self, tr("btn_feedback"),
                                    tr("fb_saved_local"))
            return
        QMessageBox.information(self, tr("btn_feedback"), tr("fb_saved_local"))
        self.accept()

    def _posted(self, ok: bool) -> None:
        parent = self.parent()
        if parent is not None:
            QMessageBox.information(
                parent, tr("btn_feedback"),
                tr("fb_thanks_sent") if ok else tr("fb_saved_local"))


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


class BulkEditDialog(QDialog):
    """«ویرایش گروهی»: one form applied to every selected file.

    Each field starts at «بدون تغییر»; only the fields the user touches
    are written. A bulk pass never blanks an existing value, and it never
    merges or removes files — the same flag-only spirit as everywhere.
    """

    def __init__(self, parent, lib, file_ids: list):
        super().__init__(parent)
        self.lib = lib
        self.file_ids = list(file_ids)
        self.setWindowTitle(tr("bulk_edit_title"))
        self.resize(420, 260)
        none = tr("bulk_none")

        self.subject = QComboBox()
        self.subject.setEditable(True)
        self.subject.addItem(none)
        for r in lib.conn.execute("SELECT name FROM subjects ORDER BY name"):
            self.subject.addItem(r["name"])

        self.chapter = QSpinBox()
        self.chapter.setRange(0, 40)
        self.chapter.setSpecialValueText(none)

        self.lesson = QSpinBox()
        self.lesson.setRange(0, 40)
        self.lesson.setSpecialValueText(none)

        self.kind = QComboBox()
        self.kind.addItem(none)
        for k in ("جزوه", "نمونه‌سوال", "کاربرگ", "تکلیف", "سایر"):
            self.kind.addItem(k)

        self.year = QComboBox()
        self.year.setEditable(True)
        self.year.addItem(none)
        from ..core.schoolyear import current_school_year
        base = int(current_school_year()[:4])
        for y in (f"{base - 1}-{base}", current_school_year(),
                  f"{base + 1}-{base + 2}"):
            self.year.addItem(y)
        self.year.setCurrentIndex(0)

        form = QVBoxLayout(self)
        form.addWidget(QLabel(tr("bulk_edit_hint").format(
            count=persian_digits(str(len(self.file_ids))))))
        for label, widget in ((tr("meta_subject"), self.subject),
                              (tr("meta_chapter"), self.chapter),
                              (tr("meta_lesson"), self.lesson),
                              (tr("meta_kind"), self.kind),
                              (tr("meta_year"), self.year)):
            row = QHBoxLayout()
            lab = QLabel(label)
            lab.setMinimumWidth(90)
            row.addWidget(lab)
            row.addWidget(widget)
            form.addLayout(row)
        buttons = QHBoxLayout()
        cancel = QPushButton(tr("cancel"))
        cancel.clicked.connect(self.reject)
        save = QPushButton(tr("ok"))
        save.setDefault(True)
        save.clicked.connect(self._apply)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        form.addLayout(buttons)

    def _changes(self) -> tuple[list, list]:
        """(SET clauses, params) for exactly the fields the user chose."""
        sets, params = [], []
        none = tr("bulk_none")
        subject_name = self.subject.currentText().strip()
        if subject_name and subject_name != none:
            sets.append("subject_id=?")
            params.append(db.get_or_create(self.lib.conn, "subjects",
                                           subject_name))
        if self.kind.currentIndex() > 0:
            sets.append("kind=?")
            params.append(self.kind.currentText())
        if self.chapter.value():
            sets.append("chapter=?")
            params.append(self.chapter.value())
        if self.lesson.value():
            sets.append("lesson=?")
            params.append(self.lesson.value())
        year = self.year.currentText().strip()
        if year and year != none:
            sets.append("school_year=?")
            params.append(year)
        return sets, params

    def _apply(self) -> None:
        sets, params = self._changes()
        if not sets:                  # nothing chosen → no write at all
            self.reject()
            return
        conn = self.lib.conn
        with conn:
            for fid in self.file_ids:
                conn.execute(
                    f"UPDATE files SET {', '.join(sets)} WHERE id=?",
                    (*params, fid))
            db.log(conn, "bulk_edit", f"{len(self.file_ids)} files")
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

        from .. import feedback_config
        self.fb_endpoint = QLineEdit(
            str(settings.get("feedback_endpoint",
                             feedback_config.FEEDBACK_ENDPOINT)))
        self.fb_form_url = QLineEdit(
            str(settings.get("feedback_form_url",
                             feedback_config.FEEDBACK_FORM_URL)))

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
        form.addWidget(QLabel(tr("settings_fb_endpoint")))
        form.addWidget(self.fb_endpoint)
        form.addWidget(QLabel(tr("settings_fb_form_url")))
        form.addWidget(self.fb_form_url)
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
        self.settings["feedback_endpoint"] = self.fb_endpoint.text().strip()
        self.settings["feedback_form_url"] = self.fb_form_url.text().strip()
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
        # D3 (design-approved dependency): a scannable QR of the LAN URL —
        # typing the address on a phone keyboard is the share flow's
        # weakest link. The dependency-free URL list above stays.
        lan = pick_lan_url(urls)
        if lan is not None:
            from PySide6.QtSvgWidgets import QSvgWidget
            qr = QSvgWidget()
            qr.load(qr_svg_bytes(lan))
            qr.setFixedSize(180, 180)
            layout.addWidget(QLabel(tr("qr_caption")))
            layout.addWidget(qr, 0, Qt.AlignCenter)
        layout.addWidget(QLabel(tr("share_hint")))
        # D4: poll the catalog every 5 s — a phone upload becomes visible
        # on the desktop while sharing, not only after the dialog closes.
        self._upload_label = QLabel("")
        self._upload_label.setStyleSheet("color: #8fd08f;")
        self._upload_label.hide()
        layout.addWidget(self._upload_label)
        self._file_count_at_start = self._count_files()
        from PySide6.QtCore import QTimer
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self._check_files)
        self._poll_timer.start()
        stop = QPushButton(tr("btn_stop_share"))
        stop.clicked.connect(self.accept)
        layout.addWidget(stop)

    def _count_files(self) -> int:
        parent = self.parent()
        if parent is None or not hasattr(parent, "lib"):
            return -1
        return parent.lib.conn.execute(
            "SELECT COUNT(*) c FROM files").fetchone()["c"]

    def _check_files(self) -> None:
        """D4: refresh the owner window when the file count changed."""
        parent = self.parent()
        count = self._count_files()
        if count < 0 or parent is None:
            return
        if count > self._file_count_at_start >= 0:
            self._upload_label.setText(
                tr("share_new_files").format(
                    persian_digits(str(count - self._file_count_at_start))))
            self._upload_label.show()
            if hasattr(parent, "refresh"):
                parent.refresh()
        elif count != self._file_count_at_start:
            self._file_count_at_start = count   # deletions reset the baseline
            if hasattr(parent, "refresh"):
                parent.refresh()

    def closeEvent(self, event) -> None:
        self._poll_timer.stop()
        self.accept()
        super().closeEvent(event)


# --- E1: activity history + learned rules (A4 transparency) ----------------

# Persian display names for the activity_log actions (the log stores
# short English keys; this is the only place that translates them).
ACTION_FA = {
    "import": "وارد کردن",
    "classify": "دسته‌بندی",
    "edit_meta": "ویرایش اطلاعات",
    "export": "خروجی بسته",
    "verify": "راستی‌آزمایی",
    "share_start": "شروع اشتراک‌گذاری",
    "share_stop": "قطع اشتراک‌گذاری",
    "web_upload": "دریافت از گوشی",
    "delete": "حذف از کتابخانه",
    "feedback": "بازخورد",
    "healthcheck": "بررسی سلامت فایل‌ها",
    "seed_subjects": "درس‌های پیش‌فرض",
    "backup": "پشتیبان‌گیری",
}


class ActivityDialog(QDialog):
    """«تاریخچه»: the last 50 activity_log events, plus the A4
    transparency tab listing the learned token→subject rules."""

    def __init__(self, parent, lib):
        super().__init__(parent)
        self.lib = lib
        self.setWindowTitle(tr("history_title"))
        self.resize(640, 460)
        tabs = QTabWidget()

        events = lib.conn.execute(
            """SELECT ts, action, detail FROM activity_log
               ORDER BY id DESC LIMIT 50""").fetchall()
        if events:
            self.event_table = QTableWidget(len(events), 3)
            self.event_table.setHorizontalHeaderLabels(
                (tr("hist_time"), tr("hist_action"), tr("hist_detail")))
            self.event_table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.event_table.horizontalHeader().setStretchLastSection(True)
            from .main_window import jalali_date
            for i, ev in enumerate(events):
                values = (persian_digits(jalali_date(ev["ts"])),
                          ACTION_FA.get(ev["action"], ev["action"]),
                          ev["detail"])
                for col, value in enumerate(values):
                    self.event_table.setItem(
                        i, col, QTableWidgetItem(str(value)))
            layout = QVBoxLayout()
            layout.addWidget(self.event_table)
            page = QWidget()
            page.setLayout(layout)
            tabs.addTab(page, tr("history_title"))
        else:
            tabs.addTab(self._message_page(tr("history_empty")),
                        tr("history_title"))

        rules = lib.conn.execute(
            """SELECT h.token, h.hits, s.name AS subject
               FROM hint_rules h JOIN subjects s ON s.id=h.subject_id
               ORDER BY h.hits DESC""").fetchall()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(tr("hints_explain")))
        if rules:
            from PySide6.QtWidgets import QHeaderView
            self.rule_table = QTableWidget(len(rules), 3)
            self.rule_table.setHorizontalHeaderLabels(
                ("#", tr("meta_subject"), tr("hints_hits")))
            self.rule_table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.rule_table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.Stretch)
            for i, rule in enumerate(rules):
                self.rule_table.setItem(i, 0, QTableWidgetItem(rule["token"]))
                self.rule_table.setItem(i, 1, QTableWidgetItem(rule["subject"]))
                self.rule_table.setItem(
                    i, 2, QTableWidgetItem(tr("hints_hits").format(
                        persian_digits(str(rule["hits"])))))
            layout.addWidget(self.rule_table)
            forget = QPushButton(tr("hints_forget"))
            forget.clicked.connect(self._forget_selected_rule)
            layout.addWidget(forget)
        else:
            layout.addWidget(self._message_page(tr("hints_empty")))
        tabs.addTab(page, tr("hints_title"))

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

    def _forget_selected_rule(self) -> None:
        """A4 transparency: delete the selected learned rule — the app's
        memory is fully user-controllable, nothing hidden."""
        from ..core.suggest import forget_hint
        row = self.rule_table.currentRow()
        if row < 0:
            return
        token = self.rule_table.item(row, 0).text()
        with self.lib.conn:
            forget_hint(self.lib.conn, token)
        self.rule_table.removeRow(row)

    def _message_page(self, text: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        return page


# --- E5: library stats (dependency-free Unicode bars) ----------------------

def bar(count: int, max_count: int, width: int = 12) -> str:
    """A proportional ▓▓▓░░ bar — plain text, no chart dependency, and
    direction-neutral glyphs that survive the RTL layout."""
    if max_count <= 0 or count <= 0:
        return "░" * width
    filled = round(count / max_count * width)
    return "▓" * filled + "░" * (width - filled)


def library_stats(conn) -> dict:
    """The numbers behind the stats dialog — one dict so the M10/M11
    benchmark scripts can reuse the exact same queries."""
    per_subject = [(r["name"], r["c"]) for r in conn.execute(
        """SELECT s.name, COUNT(*) c FROM files f
           JOIN subjects s ON s.id=f.subject_id
           GROUP BY s.name ORDER BY c DESC""")]
    per_kind = [(r["kind"], r["c"]) for r in conn.execute(
        """SELECT kind, COUNT(*) c FROM files WHERE kind IS NOT NULL
           GROUP BY kind ORDER BY c DESC""")]
    total = conn.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(size_bytes),0) s FROM files"
    ).fetchone()
    dedup = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) saved FROM import_skips"
    ).fetchone()["saved"]
    unclassified = conn.execute(
        "SELECT COUNT(*) c FROM files WHERE subject_id IS NULL").fetchone()["c"]
    return {
        "file_count": total["c"],
        "total_bytes": total["s"],
        "dedup_bytes": dedup,
        "unclassified": unclassified,
        "per_subject": per_subject,
        "per_kind": per_kind,
    }


class StatsProgressDialog(QDialog):
    """Opens the instant «آمار» is clicked: says what is happening and
    offers a real cancel (the user asked for exactly this after the old
    silent UI-thread freeze). The worker runs in the background."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("stats_title"))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("stats_computing")))
        bar = QProgressBar()
        bar.setRange(0, 0)                    # indeterminate = "working…"
        layout.addWidget(bar)
        cancel = QPushButton(tr("cancel"))
        cancel.clicked.connect(self._cancel)
        layout.addWidget(cancel)

    def _cancel(self) -> None:
        parent = self.parent()
        worker = getattr(parent, "_stats_worker", None)
        if worker is not None:
            worker.cancel()
        self.reject()


class StatsDialog(QDialog):
    """«آمار»: the results view. Pure display — it receives the already
    computed stats dict (StatsWorker computed it off the UI thread)."""

    def __init__(self, parent, stats: dict):
        super().__init__(parent)
        self.setWindowTitle(tr("stats_title"))
        self.resize(480, 520)

        layout = QVBoxLayout(self)
        if stats["file_count"] == 0 and not stats["dedup_bytes"]:
            layout.addWidget(QLabel(tr("stats_empty")))
        else:
            from .main_window import human_size
            layout.addWidget(QLabel(
                f"{tr('stats_total')}: "
                f"{human_size(stats['total_bytes'])}"))
            layout.addWidget(QLabel(
                f"{tr('stats_dedup')}: "
                f"{human_size(stats['dedup_bytes'])}"))
            layout.addWidget(QLabel(
                f"{tr('stats_unclassified')}: "
                f"{persian_digits(str(stats['unclassified']))}"))

            layout.addWidget(QLabel(f"<b>{tr('stats_per_subject')}</b>"))
            max_sub = max((c for _, c in stats["per_subject"]), default=0)
            for name, count in stats["per_subject"]:
                layout.addWidget(QLabel(
                    f"{persian_digits(str(count))}  {bar(count, max_sub)}  {name}"))
            layout.addWidget(QLabel(f"<b>{tr('stats_per_kind')}</b>"))
            max_kind = max((c for _, c in stats["per_kind"]), default=0)
            for kind, count in stats["per_kind"]:
                layout.addWidget(QLabel(
                    f"{persian_digits(str(count))}  {bar(count, max_kind)}  {kind}"))
