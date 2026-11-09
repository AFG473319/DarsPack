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

from PySide6.QtCore import QLocale, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QProgressBar,

    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTabWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from .. import __version__, i18n
from ..core import db, manifest as manifest_core
from ..core.normalize import persian_digits
from ..i18n import STRINGS, num, tr
from .workers import ImportWorker
from .smooth_scroll import enable_smooth_scroll
from . import theme


def text_dialog(parent, title: str, text: str) -> None:
    QMessageBox.information(parent, title, text)


def polish_dialog(dialog, min_width: int | None = None) -> None:
    """One rhythm for every dialog: breathing room, spacing, min width."""
    layout = dialog.layout()
    if layout is not None:
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
    if min_width:
        dialog.setMinimumWidth(min_width)


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


def make_spinbox(minimum: int = 0, maximum: int = 40) -> QSpinBox:
    """A number field that renders ۰-۹ in the Persian UI (a Persian
    QLocale is what makes QSpinBox display Persian digits)."""
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    if i18n.language() == "fa":
        spin.setLocale(QLocale(QLocale.Persian, QLocale.Iran))
    return spin


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
            star.setObjectName("Star")          # flat QSS toggle, not a blue box
            star.setCheckable(True)
            star.setFixedSize(40, 40)
            star.setCursor(Qt.PointingHandCursor)
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
        self.submit.setObjectName("Primary")
        self.submit.setDefault(True)
        self.submit.clicked.connect(self._submit)
        cancel = QPushButton(tr("cancel"))
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)
        self.buttons = QHBoxLayout()
        self.buttons.addWidget(self.submit)
        self.buttons.addWidget(cancel)
        self.buttons.addStretch(1)
        layout.addLayout(self.buttons)
        polish_dialog(self, 460)

    def _set_stars(self, n: int) -> None:
        self.rating = n
        for i, star in enumerate(self.star_buttons, start=1):
            star.setChecked(i <= n)             # QSS paints checked stars gold
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
            self.buttons.replaceWidget(self.submit, button)
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
        pick_files.setObjectName("Primary")
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
        polish_dialog(self, 420)

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
        polish_dialog(self, 460)

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
        self.resize(940, 560)

        headers = [tr("col_name"), tr("meta_subject"), tr("meta_chapter"),
                   tr("meta_kind"), tr("meta_lesson"),
                   tr("meta_year"), tr("meta_tags_col")]
        self.table = QTableWidget(len(file_ids), len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 150), (2, 85), (3, 110),
                           (4, 85), (5, 130), (6, 140)):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, width)
        self._scroller = enable_smooth_scroll(self.table)

        subjects = [r["name"] for r in lib.conn.execute(
            "SELECT name FROM subjects ORDER BY name")]
        self.rows = []                            # (file_id, widgets)
        for r, fid in enumerate(file_ids):
            file_row = lib.conn.execute(
                """SELECT f.*, s.name AS subject_name
                   FROM files f
                   LEFT JOIN subjects s ON s.id=f.subject_id
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

            chapter = make_spinbox()
            chapter.setValue(file_row["chapter"] or 0)
            self.table.setCellWidget(r, 2, chapter)

            kind = QComboBox()
            kind.addItems(("جزوه", "نمونه‌سوال", "کاربرگ", "تکلیف", "سایر"))
            kind.setCurrentText(file_row["kind"] or "سایر")
            self.table.setCellWidget(r, 3, kind)

            # A3b: درس (lesson) is a separate number from فصل (chapter) —
            # either, both, or neither may be set (design decision).
            lesson = make_spinbox()
            lesson.setValue(file_row["lesson"] or 0)
            self.table.setCellWidget(r, 4, lesson)

            year = make_year_combo(file_row["school_year"])
            self.table.setCellWidget(r, 5, year)

            # A5: the manifest's tags arrive as pre-fill too
            tags_edit = QLineEdit()
            tags_edit.setText("، ".join(prefill.get("tags") or []))
            self.table.setCellWidget(r, 6, tags_edit)

            # widget positions 0–3 are pinned by existing tests; the
            # newer fields go after them
            self.rows.append((fid, subject, chapter, kind, lesson,
                              year, tags_edit))

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        banner = QFrame()
        banner.setObjectName("BannerCard")
        banner_layout = QVBoxLayout(banner)
        banner_layout.setContentsMargins(14, 10, 14, 10)
        banner_layout.setSpacing(4)
        title_lbl = QLabel(tr("classify_title"))
        title_lbl.setObjectName("DialogTitle")
        hint_lbl = QLabel(tr("classify_hint"))
        hint_lbl.setObjectName("DialogHint")
        hint_lbl.setWordWrap(True)
        banner_layout.addWidget(title_lbl)
        banner_layout.addWidget(hint_lbl)
        layout.addWidget(banner)

        # A2: bulk actions toolbar
        bulk_bar = QFrame()
        bulk_bar.setObjectName("BulkBar")
        bulk_layout = QHBoxLayout(bulk_bar)
        bulk_layout.setContentsMargins(12, 6, 12, 6)
        bulk_layout.setSpacing(8)

        bulk_caption = QLabel(tr("bulk_caption"))
        bulk_caption.setObjectName("Muted")
        bulk_caption.setStyleSheet("font-weight: 600;")
        bulk_layout.addWidget(bulk_caption)

        for attr, key in (("subject", "bulk_subject"),
                          ("chapter", "bulk_chapter"),
                          ("kind", "bulk_kind"),
                          ("lesson", "bulk_lesson")):
            btn = QPushButton(tr(key))
            btn.setObjectName("BulkBtn")
            btn.clicked.connect(lambda _, a=attr: self._bulk_apply(a))
            bulk_layout.addWidget(btn)
        bulk_layout.addStretch(1)
        layout.addWidget(bulk_bar)

        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 4, 0, 0)
        buttons.setSpacing(10)
        later = QPushButton(tr("classify_later"))
        later.setObjectName("Secondary")
        later.clicked.connect(self.reject)
        save = QPushButton(tr("classify_save"))
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._save_all)
        buttons.addWidget(save)
        buttons.addWidget(later)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        polish_dialog(self, 980)

    # self.rows layout (positions 0–3 pinned by existing tests):
    # (file_id, subject, chapter, kind, lesson, year, tags)
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
            for fid, subject, chapter, kind, lesson, year, tags in self.rows:
                name = subject.currentText().strip()
                subject_id = (db.get_or_create(conn, "subjects", name)
                              if name else None)
                conn.execute(
                    """UPDATE files SET subject_id=?, chapter=?, kind=?,
                       lesson=?, school_year=? WHERE id=?""",
                    (subject_id, chapter.value() or None,
                     kind.currentText(), lesson.value() or None,
                     year.currentText().strip() or None, fid))
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
            btn.setObjectName("Primary")
            btn.clicked.connect(self._import_contents)
            layout.addWidget(btn)
        polish_dialog(self, 520)

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
            enable_smooth_scroll(listing)
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
        # joins so the dialog can show the current subject's NAME
        # instead of a bare id
        self.row = lib.conn.execute(
            """SELECT f.*, s.name AS subject_name
               FROM files f
               LEFT JOIN subjects s ON s.id = f.subject_id
               WHERE f.id=?""", (file_id,)).fetchone()

        self.subject = QComboBox()
        self.subject.setEditable(True)
        for r in lib.conn.execute("SELECT name FROM subjects ORDER BY name"):
            self.subject.addItem(r["name"])
        self.subject.setCurrentText(self.row["subject_name"] or "")

        self.chapter = make_spinbox()         # 0 = no chapter
        self.chapter.setValue(self.row["chapter"] or 0)

        self.kind = QComboBox()
        for k in ("جزوه", "نمونه‌سوال", "کاربرگ", "تکلیف", "سایر"):
            self.kind.addItem(k)
        self.kind.setCurrentText(self.row["kind"] or "سایر")

        # A3b: درس (lesson) is a separate number from فصل (chapter) —
        # either, both, or neither may be set (design decision).
        self.lesson = make_spinbox()
        self.lesson.setValue(self.row["lesson"] or 0)

        self.year = make_year_combo(self.row["school_year"])

        self.tags = QLineEdit()
        tag_names = [t["name"] for t in lib.conn.execute(
            """SELECT t.name FROM tags t JOIN file_tags ft ON ft.tag_id=t.id
               WHERE ft.file_id=?""", (file_id,))]
        self.tags.setText("، ".join(tag_names))

        self.note = QLineEdit(self.row["note"] or "")

        save = QPushButton(tr("ok"))
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._save)
        cancel = QPushButton(tr("cancel"))
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)

        form = QVBoxLayout(self)
        from .main_window import human_size, jalali_date
        header = QLabel(
            f"{self.row['original_name']}\n"
            f"{human_size(self.row['size_bytes'])} · "
            f"{num(jalali_date(self.row['imported_at']))}")
        header.setObjectName("DialogHint")
        header.setWordWrap(True)
        form.addWidget(header)
        for label, widget in ((tr("meta_subject"), self.subject),
                              (tr("meta_chapter"), self.chapter),
                              (tr("meta_lesson"), self.lesson),
                              (tr("meta_kind"), self.kind),
                              (tr("meta_year"), self.year),
                              (tr("meta_tags"), self.tags),
                              (tr("meta_note"), self.note)):
            row = QHBoxLayout()
            lab = QLabel(label)
            lab.setMinimumWidth(90)
            row.addWidget(lab)
            row.addWidget(widget)
            form.addLayout(row)
        buttons = QHBoxLayout()
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        form.addLayout(buttons)
        polish_dialog(self, 460)

    def _save(self) -> None:
        conn = self.lib.conn
        with conn:
            subject_id = (db.get_or_create(conn, "subjects",
                                           self.subject.currentText())
                          if self.subject.currentText().strip() else None)
            chapter = self.chapter.value() or None
            conn.execute(
                """UPDATE files SET subject_id=?, chapter=?, lesson=?,
                   kind=?, school_year=?, note=?
                   WHERE id=?""",
                (subject_id, chapter, self.lesson.value() or None,
                 self.kind.currentText(),
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

        self.chapter = make_spinbox()
        self.chapter.setSpecialValueText(none)

        self.lesson = make_spinbox()
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
            count=num(len(self.file_ids)))))
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
        save = QPushButton(tr("ok"))
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._apply)
        cancel = QPushButton(tr("cancel"))
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        form.addLayout(buttons)
        polish_dialog(self, 460)

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

        self.font_size = make_spinbox(8, 18)
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
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._save)
        cancel = QPushButton(tr("cancel"))
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)

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

        # endpoints are developer-facing: behind an «پیشرفته» toggle
        self.advanced = QCheckBox(tr("settings_advanced"))
        self.advanced_fields = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_fields)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(6)
        advanced_layout.addWidget(QLabel(tr("settings_fb_endpoint")))
        advanced_layout.addWidget(self.fb_endpoint)
        advanced_layout.addWidget(QLabel(tr("settings_fb_form_url")))
        advanced_layout.addWidget(self.fb_form_url)
        self.advanced_fields.setVisible(False)
        self.advanced.toggled.connect(self.advanced_fields.setVisible)
        form.addWidget(self.advanced)
        form.addWidget(self.advanced_fields)

        restart = QLabel(tr("settings_restart"))
        restart.setObjectName("DialogHint")
        restart.setWordWrap(True)
        form.addWidget(restart)
        buttons = QHBoxLayout()
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        form.addLayout(buttons)
        polish_dialog(self, 460)

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
        caption = QLabel(tr("share_pin"))
        caption.setAlignment(Qt.AlignCenter)
        caption.setStyleSheet("color: #a0a0a8;")
        layout.addWidget(caption)
        pin_label = QLabel(persian_digits(str(server.pin)))
        pin_label.setAlignment(Qt.AlignCenter)
        pin_label.setStyleSheet(
            "font-size: 30px; font-weight: bold; letter-spacing: 6px;")
        layout.addWidget(pin_label)
        copy_pin = QPushButton(tr("copy_pin"))
        copy_pin.setObjectName("Ghost")
        copy_pin.clicked.connect(
            lambda: QApplication.clipboard().setText(str(server.pin)))
        layout.addWidget(copy_pin, 0, Qt.AlignCenter)
        layout.addWidget(QLabel(tr("share_urls")))
        for url in urls:
            line = QLabel(url)
            line.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(line)
        lan = pick_lan_url(urls)
        if lan is not None:
            copy_url = QPushButton(tr("copy_url"))
            copy_url.setObjectName("Ghost")
            copy_url.clicked.connect(
                lambda: QApplication.clipboard().setText(lan))
            layout.addWidget(copy_url, 0, Qt.AlignCenter)
        # D3 (design-approved dependency): a scannable QR of the LAN URL —
        # typing the address on a phone keyboard is the share flow's
        # weakest link. The dependency-free URL list above stays. The QR
        # sits on a padded white card instead of a bare white block.
        if lan is not None:
            from PySide6.QtSvgWidgets import QSvgWidget
            qr = QSvgWidget()
            qr.load(qr_svg_bytes(lan))
            qr.setFixedSize(180, 180)
            card = QFrame()
            card.setObjectName("QrCard")
            card.setStyleSheet(
                "QFrame#QrCard { background: #ffffff; border-radius: 12px; }")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 12, 12, 12)
            card_layout.addWidget(qr, 0, Qt.AlignCenter)
            layout.addWidget(QLabel(tr("qr_caption")))
            layout.addWidget(card, 0, Qt.AlignCenter)
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
        stop.setObjectName("Secondary")
        stop.clicked.connect(self.accept)
        layout.addWidget(stop)
        polish_dialog(self, 440)

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
                    num(count - self._file_count_at_start)))
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
    "restore": "بازیابی از سطل زباله",
    "empty_trash": "پاک‌سازی سطل زباله",
    "exam_pack": "بسته شب امتحان",
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
            self.event_table.verticalHeader().setVisible(False)
            self.event_table.verticalHeader().setDefaultSectionSize(38)
            self.event_table.setShowGrid(False)
            self.event_table.setAlternatingRowColors(True)
            self.event_table.setSelectionBehavior(QTableWidget.SelectRows)
            self.event_table.horizontalHeader().setStretchLastSection(True)
            enable_smooth_scroll(self.event_table)
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
                (tr("hints_token"), tr("meta_subject"), tr("hints_hits_col")))
            self.rule_table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.rule_table.verticalHeader().setVisible(False)
            self.rule_table.verticalHeader().setDefaultSectionSize(38)
            self.rule_table.setShowGrid(False)
            self.rule_table.setAlternatingRowColors(True)
            self.rule_table.setSelectionBehavior(QTableWidget.SelectRows)
            self.rule_table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.Stretch)
            enable_smooth_scroll(self.rule_table)
            for i, rule in enumerate(rules):
                self.rule_table.setItem(i, 0, QTableWidgetItem(rule["token"]))
                self.rule_table.setItem(i, 1, QTableWidgetItem(rule["subject"]))
                self.rule_table.setItem(
                    i, 2, QTableWidgetItem(tr("hints_hits").format(
                        num(rule["hits"]))))
            layout.addWidget(self.rule_table)
            forget = QPushButton(tr("hints_forget"))
            forget.setObjectName("Danger")
            forget.clicked.connect(self._forget_selected_rule)
            layout.addWidget(forget)
        else:
            layout.addWidget(self._message_page(tr("hints_empty")))
        tabs.addTab(page, tr("hints_title"))

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        polish_dialog(self, 720)

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


# --- E5: library stats -----------------------------------------------------

def stat_bar_row(name: str, count: int, max_count: int) -> QWidget:
    """One stats row: label + a real bar + count. The old ▓/░ text bar
    rendered as gray tiles in Segoe UI."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    name_label = QLabel(name)
    name_label.setMinimumWidth(110)
    bar = QProgressBar()
    bar.setRange(0, max(1, max_count))
    bar.setValue(count)
    bar.setTextVisible(False)
    bar.setFixedHeight(8)
    bar.setObjectName("StatBar")
    count_label = QLabel(num(count))
    count_label.setMinimumWidth(32)
    count_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(name_label)
    layout.addWidget(bar, 1)
    layout.addWidget(count_label)
    return row


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
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self._cancel)
        layout.addWidget(cancel)
        polish_dialog(self, 420)

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
                f"{num(stats['unclassified'])}"))

            layout.addWidget(QLabel(f"<b>{tr('stats_per_subject')}</b>"))
            max_sub = max((c for _, c in stats["per_subject"]), default=0)
            for name, count in stats["per_subject"]:
                layout.addWidget(stat_bar_row(name, count, max_sub))
            layout.addWidget(QLabel(f"<b>{tr('stats_per_kind')}</b>"))
            max_kind = max((c for _, c in stats["per_kind"]), default=0)
            for kind, count in stats["per_kind"]:
                layout.addWidget(stat_bar_row(kind, count, max_kind))

        close = QPushButton(tr("close"))
        close.setObjectName("Secondary")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(close)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        polish_dialog(self, 520)


class TrashDialog(QDialog):
    """View deleted files in files/.trash/ with one-click restore and safe empty."""

    def __init__(self, parent, lib):
        super().__init__(parent)
        self.lib = lib
        self.restored_any = False
        self.setWindowTitle(tr("trash_title"))
        self.resize(750, 480)

        layout = QVBoxLayout(self)

        headers = [tr("trash_col_name"), tr("trash_col_subject"), tr("trash_col_size"), tr("trash_col_date")]
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 120)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 90)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 130)
        self._scroller = enable_smooth_scroll(self.table)

        layout.addWidget(self.table)

        self.empty_label = QLabel(tr("trash_empty_state"))
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet(f"color: {theme.PALETTE['muted']}; padding: 20px; font-size: 13px;")
        layout.addWidget(self.empty_label)

        btn_box = QHBoxLayout()
        self.btn_restore = QPushButton(tr("trash_restore_btn"))
        self.btn_restore.clicked.connect(self._restore_selected)
        btn_box.addWidget(self.btn_restore)

        self.btn_empty = QPushButton(tr("trash_empty_btn"))
        self.btn_empty.setObjectName("Danger")
        self.btn_empty.setStyleSheet(f"color: {theme.PALETTE['danger']};")
        self.btn_empty.clicked.connect(self._empty_trash)
        btn_box.addWidget(self.btn_empty)

        btn_box.addStretch()
        btn_close = QPushButton(tr("close"))
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)

        layout.addLayout(btn_box)
        polish_dialog(self, 650)
        self._reload()

    def _reload(self) -> None:
        from .main_window import human_size, jalali_date
        items = self.lib.list_trash()
        self.trash_items = items
        self.table.setRowCount(len(items))
        if not items:
            self.table.hide()
            self.empty_label.show()
            self.btn_restore.setEnabled(False)
            self.btn_empty.setEnabled(False)
            return

        self.table.show()
        self.empty_label.hide()
        self.btn_restore.setEnabled(True)
        self.btn_empty.setEnabled(True)

        for row, it in enumerate(items):
            name_item = QTableWidgetItem(it["original_name"])
            name_item.setData(Qt.UserRole, it["trash_name"])
            name_item.setToolTip(it["trash_name"])
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 0, name_item)

            sub_item = QTableWidgetItem(it["subject_name"] or "—")
            sub_item.setTextAlignment(Qt.AlignCenter)
            sub_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 1, sub_item)

            size_item = QTableWidgetItem(human_size(it["size"]))
            size_item.setTextAlignment(Qt.AlignCenter)
            size_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 2, size_item)

            date_str = jalali_date(it["deleted_at"]) if it.get("deleted_at") else "—"
            date_item = QTableWidgetItem(date_str)
            date_item.setTextAlignment(Qt.AlignCenter)
            date_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 3, date_item)

    def _restore_selected(self) -> None:
        selected_rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()))
        if not selected_rows:
            QMessageBox.information(self, tr("trash_title"), tr("trash_no_selection"))
            return

        restored_count = 0
        failed_names = []
        for r in selected_rows:
            item = self.table.item(r, 0)
            if item is None:
                continue
            trash_name = item.data(Qt.UserRole)
            try:
                self.lib.restore_trash_file(trash_name)
                restored_count += 1
            except Exception:
                failed_names.append(item.text())

        if restored_count > 0:
            self.restored_any = True
            QMessageBox.information(
                self, tr("trash_title"),
                tr("trash_restore_done").format(i18n.num(restored_count)))
            self._reload()
        if failed_names:
            QMessageBox.warning(
                self, tr("trash_title"),
                tr("trash_restore_failed").format(i18n.num(len(failed_names))) + f"\n({', '.join(failed_names[:3])})")

    def _empty_trash(self) -> None:
        ans = QMessageBox.question(
            self, tr("trash_empty_btn"), tr("trash_empty_confirm"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans == QMessageBox.Yes:
            count = self.lib.empty_trash()
            QMessageBox.information(
                self, tr("trash_empty_btn"),
                tr("trash_empty_done").format(i18n.num(count)))
            self._reload()


class ExamPackDialog(QDialog):
    """Build a curated exam revision package ('بسته‌ساز شب امتحان') for a subject."""

    EXAM_KINDS = {"نمونه‌سوال", "جزوه", "کاربرگ"}

    def __init__(self, parent, lib):
        super().__init__(parent)
        self.lib = lib
        self.setWindowTitle(tr("exam_pack_title"))
        self.resize(750, 520)

        layout = QVBoxLayout(self)

        filter_card = QFrame()
        filter_card.setObjectName("filterCard")
        filter_card.setStyleSheet(
            f"QFrame#filterCard {{ background-color: {theme.PALETTE['surface_2']}; "
            f"border: 1px solid {theme.PALETTE['border_soft']}; border-radius: 8px; }}"
        )
        card_layout = QHBoxLayout(filter_card)
        card_layout.setContentsMargins(12, 8, 12, 8)
        card_layout.setSpacing(14)

        card_layout.addWidget(QLabel(tr("exam_pack_subject")))
        self.subject_combo = QComboBox()
        self.subject_combo.setMinimumWidth(160)
        self.subject_combo.addItem(tr("all_subjects"), "")
        subjects = [r["name"] for r in lib.conn.execute("SELECT name FROM subjects ORDER BY name")]
        for s in subjects:
            self.subject_combo.addItem(s, s)
        self.subject_combo.currentIndexChanged.connect(self._reload_files)
        card_layout.addWidget(self.subject_combo)

        card_layout.addSpacing(15)
        self.exam_only_check = QCheckBox(tr("exam_pack_filter_kinds"))
        self.exam_only_check.setChecked(True)
        self.exam_only_check.toggled.connect(self._reload_files)
        card_layout.addWidget(self.exam_only_check)
        card_layout.addStretch()

        layout.addWidget(filter_card)

        headers = ["✓", tr("col_name"), tr("col_subject"), tr("col_kind"), tr("col_chapter"), tr("col_size")]
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 36)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for col, width in ((2, 120), (3, 110), (4, 90), (5, 90)):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, width)
        self._scroller = enable_smooth_scroll(self.table)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        self.summary_label = QLabel()
        self.summary_label.setStyleSheet(f"color: {theme.PALETTE['muted']}; font-size: 12.5px; padding: 2px 4px;")
        layout.addWidget(self.summary_label)

        btn_box = QHBoxLayout()
        btn_create = QPushButton(tr("exam_pack_btn_create"))
        btn_create.setObjectName("Primary")
        btn_create.setStyleSheet(
            f"background-color: {theme.PALETTE['primary']}; color: {theme.PALETTE['text']}; "
            f"font-weight: bold; padding: 6px 18px; border-radius: 6px;"
        )
        btn_create.clicked.connect(self._create_package)
        btn_box.addWidget(btn_create)

        btn_box.addStretch()
        btn_cancel = QPushButton(tr("cancel"))
        btn_cancel.setObjectName("Secondary")
        btn_cancel.setStyleSheet("padding: 6px 14px; border-radius: 6px;")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        layout.addLayout(btn_box)
        polish_dialog(self, 680)
        self._updating = False
        self._reload_files()

    def _reload_files(self) -> None:
        from .main_window import human_size
        self._updating = True
        subject = self.subject_combo.currentData()
        exam_only = self.exam_only_check.isChecked()

        query = """SELECT f.*, s.name AS subject_name FROM files f
                   LEFT JOIN subjects s ON s.id=f.subject_id
                   WHERE f.available=1"""
        params = []
        if subject:
            query += " AND s.name=?"
            params.append(subject)
        query += " ORDER BY s.name, f.kind, f.original_name"

        rows = self.lib.conn.execute(query, params).fetchall()
        matching_rows = []
        for r in rows:
            if exam_only:
                kind = r["kind"] or ""
                orig = r["original_name"] or ""
                is_exam = (any(k in kind for k in self.EXAM_KINDS) or
                           any(k in orig for k in ("امتحان", "سوال", "سؤال", "خلاصه", "فرمول", "جزوه")))
                if not is_exam:
                    continue
            matching_rows.append(r)

        self.table.setRowCount(len(matching_rows))
        for i, r in enumerate(matching_rows):
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            chk_item.setCheckState(Qt.Checked)
            chk_item.setData(Qt.UserRole, r["id"])
            self.table.setItem(i, 0, chk_item)

            name_item = QTableWidgetItem(r["original_name"])
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(i, 1, name_item)

            sub_item = QTableWidgetItem(r["subject_name"] or "—")
            sub_item.setTextAlignment(Qt.AlignCenter)
            sub_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(i, 2, sub_item)

            kind_item = QTableWidgetItem(r["kind"] or "—")
            kind_item.setTextAlignment(Qt.AlignCenter)
            kind_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(i, 3, kind_item)

            chap_item = QTableWidgetItem(persian_digits(str(r["chapter"])) if r["chapter"] is not None else "—")
            chap_item.setTextAlignment(Qt.AlignCenter)
            chap_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(i, 4, chap_item)

            sz_item = QTableWidgetItem(human_size(r["size_bytes"]))
            sz_item.setData(Qt.UserRole, r["size_bytes"])
            sz_item.setTextAlignment(Qt.AlignCenter)
            sz_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(i, 5, sz_item)

        self._updating = False
        self._update_summary()

    def _on_item_changed(self, item) -> None:
        if not self._updating and item.column() == 0:
            self._update_summary()

    def _selected_file_ids_and_size(self) -> tuple[list[int], int]:
        ids = []
        total_size = 0
        for r in range(self.table.rowCount()):
            chk_item = self.table.item(r, 0)
            if chk_item and chk_item.checkState() == Qt.Checked:
                ids.append(chk_item.data(Qt.UserRole))
                sz_item = self.table.item(r, 5)
                if sz_item:
                    total_size += sz_item.data(Qt.UserRole) or 0
        return ids, total_size

    def _update_summary(self) -> None:
        from .main_window import human_size
        ids, total_sz = self._selected_file_ids_and_size()
        self.summary_label.setText(
            tr("exam_pack_summary_count").format(
                i18n.num(len(ids)), human_size(total_sz)))

    def _create_package(self) -> None:
        ids, _ = self._selected_file_ids_and_size()
        if not ids:
            QMessageBox.information(
                self, tr("exam_pack_title"), tr("exam_pack_no_files"))
            return

        subject = self.subject_combo.currentText()
        if not self.subject_combo.currentData():
            subject = "جامع"
        default_name = f"بسته-امتحان-{subject}-{datetime.now():%Y%m%d}.zip"

        path, _ = QFileDialog.getSaveFileName(
            self, tr("exam_pack_title"), default_name, "ZIP (*.zip)")
        if not path:
            return

        info = manifest_core.export_package(
            self.lib.conn, self.lib.files_dir, ids, path)
        with self.lib.conn:
            db.log(self.lib.conn, "exam_pack", f"{info['count']} files -> {path}")
        QMessageBox.information(
            self, tr("exam_pack_title"),
            tr("exam_pack_done").format(i18n.num(info["count"])))
        self.accept()
