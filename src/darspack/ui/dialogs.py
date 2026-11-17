"""All dialogs in one place (دیالوگ‌ها).

Each dialog is one small class with a single purpose; keeping them in
one file makes the UI easy to read end-to-end. File dialogs never
delete or overwrite anything — export writes a new ZIP, verify only
reads, package-import goes through the normal importer (duplicates
skipped).
"""
from __future__ import annotations

import json
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLocale, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QProgressBar,

    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStackedWidget,
    QTableWidget, QTabWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
    QWidget,
)

from .. import asset_path, i18n
from ..core import db, manifest as manifest_core
from ..core.normalize import persian_digits
from ..i18n import STRINGS, num, tr
from .workers import FeedbackPoster
from .smooth_scroll import enable_smooth_scroll
from .delegates import FileNameDelegate, FileNameLabel, KeycapDelegate, KindBadgeDelegate
from . import icons, theme


def text_dialog(parent, title: str, text: str) -> None:
    msg = QMessageBox(QMessageBox.Information, title, text, QMessageBox.Ok, parent)
    msg.setButtonText(QMessageBox.Ok, tr("btn_confirm"))
    msg.exec()


def polish_dialog(dialog, min_width: int | None = None) -> None:
    """One rhythm for every dialog: breathing room, spacing, min width."""
    layout = dialog.layout()
    if layout is not None:
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
    if min_width:
        dialog.setMinimumWidth(min_width)


def _wrap_table_widget(widget: QWidget, height: int = 28) -> QWidget:
    """Center a cell editor inside a padded transparent cell wrapper."""
    holder = QWidget()
    holder.setAttribute(Qt.WA_TranslucentBackground, True)
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(3, 6, 3, 6)
    lay.setSpacing(0)
    widget.setFixedHeight(height)
    lay.addWidget(widget)
    return holder


def _equalize_label_widths(labels: list[QLabel], padding: int = 8) -> None:
    """Give form labels a uniform width wide enough to avoid clipping."""
    if not labels:
        return
    width = max(lab.sizeHint().width() for lab in labels) + padding
    for lab in labels:
        lab.setFixedWidth(width)


_IMPORT_DETAIL_RE = re.compile(r"^(.*?)\s*→\s*\d+\.[A-Za-z0-9]+$")
_RESTORE_DETAIL_RE = re.compile(r"^(.*?)\s*\(id=\d+\)$")
_FILES_COUNT_RE = re.compile(r"^(\d+)\s+files?$")
_FILES_EXPORT_RE = re.compile(r"^(\d+)\s+files?\s*(?:→|->)\s*(.+)$")
_VERIFY_DETAIL_RE = re.compile(r"^(ok|\d+)\s+problems?\s*[—-]\s*(.+)$")
_ID_DETAIL_RE = re.compile(r"^id=(\d+)$")
_SHARE_URL_RE = re.compile(r"^(\d+)\s+URLs?$")
_HEALTH_DETAIL_RE = re.compile(r"^(\d+)\s+ok,\s*(\d+)\s+missing$")


def _format_activity_detail(action: str, detail: str) -> tuple[str, bool]:
    """Localize internal log details and flag filename rows for badge paint."""
    text = detail.strip()
    if action == "import":
        match = _IMPORT_DETAIL_RE.match(text)
        if match:
            return match.group(1).strip(), True
    elif action == "restore":
        match = _RESTORE_DETAIL_RE.match(text)
        if match:
            return match.group(1).strip(), True
    elif action in ("delete", "web_upload") and text:
        return text, True
    elif action in ("classify", "bulk_edit"):
        m = _FILES_COUNT_RE.match(text)
        if m:
            return (f"{num(m.group(1))} فایل" if i18n.language() == "fa" else text), False
    elif action in ("export", "exam_pack"):
        m = _FILES_EXPORT_RE.match(text)
        if m:
            fname = Path(m.group(2).strip()).name
            if i18n.language() == "fa":
                return f"{num(m.group(1))} فایل ← {fname}", False
            return f"{m.group(1)} files → {fname}", False
    elif action == "verify":
        m = _VERIFY_DETAIL_RE.match(text)
        if m:
            fname = Path(m.group(2).strip()).name
            if m.group(1) == "ok":
                return (f"تأیید شده — {fname}" if i18n.language() == "fa" else f"Verified — {fname}"), False
            return (f"{num(m.group(1))} اشکال — {fname}" if i18n.language() == "fa" else f"{m.group(1)} problems — {fname}"), False
    elif action == "edit_meta":
        m = _ID_DETAIL_RE.match(text)
        if m and i18n.language() == "fa":
            return f"پرونده شماره {num(m.group(1))}", False
    elif action == "feedback":
        if text in STRINGS.get(i18n.language(), {}):
            return tr(text), False
    elif action == "share_start":
        m = _SHARE_URL_RE.match(text)
        if m and i18n.language() == "fa":
            return f"{num(m.group(1))} نشانی شبکه", False
    elif action == "healthcheck":
        m = _HEALTH_DETAIL_RE.match(text)
        if m and i18n.language() == "fa":
            return f"{num(m.group(1))} سالم، {num(m.group(2))} گم‌شده", False
    return (persian_digits(detail) if i18n.language() == "fa" else detail), False


_LATIN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _latin_digits(text: str) -> str:
    return text.translate(_LATIN_DIGITS)


class _PersianSpinBox(QSpinBox):
    """QSpinBox subclass that renders Persian numerals (۰-۹) in `fa` mode."""

    def textFromValue(self, val: int) -> str:
        return num(val)

    def valueFromText(self, text: str) -> int:
        return super().valueFromText(_latin_digits(text))


def make_year_combo(current: str | None) -> QComboBox:
    """Editable school-year combo (A3): the row's year (or the current
    school year) plus the years around it — anything else can be typed,
    the column is free text («1405-1406»)."""
    from ..core.schoolyear import current_school_year
    chosen = _latin_digits(current) if current else current_school_year()
    try:
        base = int(chosen[:4])
    except ValueError:
        base = int(current_school_year()[:4])
    combo = QComboBox()
    combo.setEditable(True)
    for y in (f"{base - 1}-{base}", chosen, f"{base + 1}-{base + 2}"):
        combo.addItem(y)
    combo.setCurrentText(chosen)
    return combo


def make_spinbox(minimum: int = 0, maximum: int = 40, special_value: str = "—") -> QSpinBox:
    """A number field that renders ۰-۹ in the Persian UI."""
    spin = _PersianSpinBox()
    spin.setRange(minimum, maximum)
    if special_value and minimum == 0:
        spin.setSpecialValueText(special_value)
    if i18n.language() == "fa":
        spin.setLocale(QLocale(QLocale.Persian, QLocale.Iran))
        spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
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
    mirror of what was (or could not be) sent. Raises OSError on a
    failing disk; the caller (the dialog) decides how to tell the user.
    """
    target = Path(parent.lib.root) / "feedback.jsonl"
    with open(target, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


MAX_MESSAGE_CHARS = 2000
MAX_CONTACT_CHARS = 120


def _lib_root(parent):
    """The folder where a dialog's sidecar files live, or None when the
    caller is a bare test double with no library."""
    try:
        return Path(parent.lib.root)
    except (AttributeError, TypeError):
        return None


def _json_read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None                      # missing or corrupt == absent


# --- the unsent queue (feedback_pending.json) -----------------------------

def load_pending(parent) -> list:
    """Feedback entries queued for sending: [{"payload": …, "mirrored":
    …}]. An entry goes in when the user submits and only leaves when a
    POST really got a 2xx — so detached Wi-Fi retries cleanly later,
    from the same dialog, without writing the entry to feedback.jsonl
    twice."""
    root = _lib_root(parent)
    if root is None:
        return []
    data = _json_read(root / "feedback_pending.json")
    return data if isinstance(data, list) else []


def save_pending(parent, entries: list) -> bool:
    root = _lib_root(parent)
    if root is None:
        return False
    try:
        (root / "feedback_pending.json").write_text(
            json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        return True
    except OSError:
        return False


def queue_pending(parent, payload: dict, mirrored: bool = True) -> bool:
    """Append one submitted entry to the unsent queue. `mirrored`
    records whether the feedback.jsonl append actually worked, so a
    later successful send can re-do that mirror."""
    entries = load_pending(parent)
    entries.append({"payload": payload, "mirrored": bool(mirrored)})
    return save_pending(parent, entries)


def drop_pending(parent, payload: dict) -> list:
    """Remove every queued entry whose payload equals `payload`; returns
    what was removed (the caller re-mirrors any non-mirrored one)."""
    entries = load_pending(parent)
    if not entries:
        return []
    removed = [e for e in entries if e.get("payload") == payload]
    if removed and not save_pending(parent, [e for e in entries
                                             if e.get("payload") != payload]):
        return []                        # disk still failing: try next time
    return removed


# --- the draft (feedback_draft.json) --------------------------------------

def load_draft(parent) -> dict:
    """What the user typed in the form before closing it; {} when none.
    Accidental close (or Cancel, or the X button) must never throw a
    partially written report away."""
    root = _lib_root(parent)
    if root is None:
        return {}
    data = _json_read(root / "feedback_draft.json")
    return data if isinstance(data, dict) else {}


def save_draft(parent, state: dict) -> bool:
    root = _lib_root(parent)
    if root is None:
        return False
    try:
        (root / "feedback_draft.json").write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8")
        return True
    except OSError:
        return False


def clear_draft(parent) -> None:
    root = _lib_root(parent)
    if root is None:
        return
    try:
        (root / "feedback_draft.json").unlink(missing_ok=True)
    except OSError:
        pass


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
    topic, message, optional contact.

    Nothing typed here can be lost:
    - the whole form is auto-saved as a draft (feedback_draft.json) as
      the user types and restored the next time the dialog opens;
    - the message has a visible character limit (free-hosted forms cap
      the body — the user finds out while typing, not in an error);
    - submit saves locally FIRST (a failure never loses feedback),
      queues the entry in feedback_pending.json, then posts in a
      background thread with the form kept open and «در حال ارسال…» on
      the button — so a double click cannot queue one entry twice;
    - a network failure (or a dead/absent endpoint) keeps the entry
      queued and offers «ارسال دوباره»; the same prompt fires next time
      the dialog opens for whatever was left unsent;
    - Cancel during a send is safe: the post continues in the main
      window, the queued entry retries on the next open."""

    def __init__(self, parent, settings: dict):
        super().__init__(parent)
        self.parent_window = parent
        self.settings = settings
        self.setWindowTitle(tr("btn_feedback"))
        self.rating = 0
        self._submitted = False          # a later hide must NOT re-draft
        self._posting = False
        self._chain_active = False       # sending older queued entries
        self._pending_prompted = False   # one «ارسال نشده؟» per dialog
        self._active_payload = None
        self._posting_from_chain = False
        self._poster = None

        layout = QVBoxLayout(self)
        self.notice = QLabel("")          # «پیش‌نویسِ قبلی بازگردانده شد»
        self.notice.setObjectName("SuccessText")
        self.notice.hide()
        layout.addWidget(self.notice)
        layout.addWidget(QLabel(tr("fb_rating")))
        stars = QHBoxLayout()
        stars.setSpacing(10)
        stars.addStretch(1)
        self.star_buttons = []
        for i in range(1, 6):
            star = QPushButton("☆")
            star.setObjectName("Star")          # flat QSS toggle, not a blue box
            star.setCheckable(True)
            star.setFixedSize(40, 40)
            star.setIconSize(QSize(28, 28))
            star.setIcon(icons.icon("star", theme.PALETTE["muted"], 28))
            star.setCursor(Qt.PointingHandCursor)
            star.clicked.connect(lambda checked, n=i: self._toggle_star(n))
            stars.addWidget(star)
            self.star_buttons.append(star)
        stars.addStretch(1)
        layout.addLayout(stars)

        layout.addWidget(QLabel(tr("fb_category")))
        self.category = QComboBox()
        for key in ("fb_cat_bug", "fb_cat_idea", "fb_cat_question",
                    "fb_cat_praise"):
            self.category.addItem(tr(key), key)
        layout.addWidget(self.category)

        msg_box = QVBoxLayout()
        msg_box.setContentsMargins(0, 0, 0, 0)
        msg_box.setSpacing(4)
        self.message = QTextEdit()
        self.message.setPlaceholderText(tr("feedback_placeholder"))
        self.message.setMinimumHeight(110)
        msg_box.addWidget(self.message)

        self.counter = QLabel("")
        self.counter.setObjectName("Counter")
        msg_box.addWidget(self.counter)
        layout.addLayout(msg_box)

        self.contact = QLineEdit()
        self.contact.setPlaceholderText(tr("fb_contact"))
        self.contact.setMaxLength(MAX_CONTACT_CHARS)
        self.contact.setLayoutDirection(Qt.LeftToRight)
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

        # the debounced draft writer lives before the restore below, so
        # widget signal handlers can already call it
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(600)
        self._draft_timer.timeout.connect(self._flush_draft)

        draft = load_draft(parent)
        if draft:
            self._set_stars(int(draft.get("rating") or 0))
            key = draft.get("category")
            if key:
                idx = self.category.findData(key)
                if idx >= 0:
                    self.category.setCurrentIndex(idx)
            self.message.setPlainText(str(draft.get("message") or ""))
            self.contact.setText(str(draft.get("contact") or ""))
            self.notice.setText(tr("fb_draft_restored"))
            self.notice.show()

        self.message.textChanged.connect(self._on_message_changed)
        self.contact.textChanged.connect(self._schedule_draft)
        self.category.currentIndexChanged.connect(self._schedule_draft)
        self._on_message_changed()

        polish_dialog(self, 480)

    def showEvent(self, event) -> None:
        """Queue the «ارسال نشده؟» prompt ONLY once the dialog is really
        shown — queued, not inline, so exec()'s event loop picks it up
        after the dialog is on screen. A test that never shows the
        dialog can therefore never accidentally open the modal."""
        if not self._pending_prompted:
            self._pending_prompted = True
            QTimer.singleShot(0, self._maybe_prompt_pending)
        super().showEvent(event)

    def _toggle_star(self, n: int) -> None:
        self._set_stars(0 if self.rating == n else n)

    def _set_stars(self, n: int) -> None:
        self.rating = n
        for i, star in enumerate(self.star_buttons, start=1):
            is_active = (i <= n)
            star.setChecked(is_active)
            star.setText("★" if is_active else "☆")
            star.setIcon(
                icons.icon("star-filled" if is_active else "star",
                           theme.PALETTE["accent"] if is_active else theme.PALETTE["muted"],
                           28)
            )
        self._schedule_draft()

    def _draft_state(self) -> dict:
        return {"rating": self.rating,
                "category": self.category.currentData(),
                "message": self.message.toPlainText(),
                "contact": self.contact.text()}

    def _schedule_draft(self, *_) -> None:
        self._draft_timer.start()

    def _flush_draft(self) -> None:
        if self._submitted:
            clear_draft(self.parent_window)     # sent: the draft is done
            return
        save_draft(self.parent_window, self._draft_state())

    def hideEvent(self, event) -> None:
        """Dialogs hide on accept, reject AND the window X — flush the
        draft on all three paths (or clear it after a submission)."""
        self._flush_draft()
        super().hideEvent(event)

    def _on_message_changed(self) -> None:
        """Live length counter: the online receiver caps the body, so
        the bubble must burst while typing, not at a server 413."""
        n = len(self.message.toPlainText())
        over = n > MAX_MESSAGE_CHARS
        self.counter.setText(tr("fb_limit").format(
            num(n), num(MAX_MESSAGE_CHARS)))
        self.counter.setStyleSheet("color:#e5484d;" if over else "")
        if not self._posting:
            self.submit.setEnabled(not over)

    def _endpoint(self) -> str:
        from .. import feedback_config
        return (self.settings.get("feedback_endpoint")
                or feedback_config.FEEDBACK_ENDPOINT)

    def _form_url(self) -> str:
        from .. import feedback_config
        return (self.settings.get("feedback_form_url")
                or feedback_config.FEEDBACK_FORM_URL)

    def _submit(self) -> None:
        if self._posting:
            return                        # double click → one entry, not two
        text = self.message.toPlainText().strip()
        if not text:
            QMessageBox.information(self, tr("btn_feedback"),
                                    tr("fb_need_message"))
            return
        if len(text) > MAX_MESSAGE_CHARS:
            QMessageBox.warning(
                self, tr("btn_feedback"),
                tr("fb_too_long").format(num(MAX_MESSAGE_CHARS)))
            return
        payload = build_feedback_payload(
            self.rating, self.category.currentData(), text,
            self.contact.text().strip())

        try:
            save_feedback(self.parent_window, payload)  # local first
            mirrored = True
        except OSError:
            mirrored = False
        queued = queue_pending(self.parent_window, payload,
                               mirrored=mirrored)
        if not (mirrored or queued):
            # both writes failed: the entry would live nowhere, so keep
            # the dialog open with the text intact and explain
            QMessageBox.critical(self, tr("btn_feedback"),
                                 tr("fb_buffer_failed"))
            return
        self._submitted = True
        try:
            db.log(self.parent_window.lib.conn, "feedback",
                   payload["category"])
        except Exception:
            pass                          # the log must not sink feedback

        if self._endpoint():
            self._start_post(payload)
            return                        # dialog stays open while sending
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

    # --- sending ------------------------------------------------------------

    def _start_post(self, payload: dict, from_chain: bool = False) -> None:
        endpoint = self._endpoint()
        if not endpoint:
            return
        self._posting = True
        self._active_payload = payload
        self._posting_from_chain = from_chain
        self.submit.setEnabled(False)
        self.submit.setText(tr("fb_sending"))
        # parented to the MAIN WINDOW: closing this dialog must never
        # delete a running thread (the failed-send contract: the queued
        # entry just retries on the next open)
        poster = FeedbackPoster(endpoint, payload,
                                parent=self.parent_window)
        self._poster = poster
        poster.done.connect(self._post_done)
        poster.start()

    def _post_done(self, ok: bool) -> None:
        payload = self._active_payload
        from_chain = self._posting_from_chain
        self._posting = False
        self._active_payload = None
        self.submit.setText(tr("fb_submit"))
        self._on_message_changed()        # recompute counter + submit state
        if not ok:
            if from_chain:
                self._chain_active = False
                QMessageBox.warning(self, tr("btn_feedback"),
                                    tr("fb_unsent_failed"))
            else:
                answer = QMessageBox.question(
                    self, tr("btn_feedback"), tr("fb_retry_failed"),
                    QMessageBox.Retry | QMessageBox.Close,
                    QMessageBox.Retry)
                if answer == QMessageBox.Retry:
                    self._start_post(payload)
            return
        removed = drop_pending(self.parent_window, payload)
        for entry in removed:
            if not entry.get("mirrored"):
                try:                       # the jsonl mirror missed earlier
                    save_feedback(self.parent_window,
                                  entry["payload"])
                except OSError:
                    pass
        if from_chain:
            self._send_next_pending()
        else:
            QMessageBox.information(self, tr("btn_feedback"),
                                    tr("fb_thanks_sent"))
            self.accept()

    def _maybe_prompt_pending(self) -> None:
        """Entries left queued from earlier (failing Wi-Fi…) get one
        «اکنون ارسال شود؟» as the dialog opens."""
        entries = load_pending(self.parent_window)
        if not entries or not self._endpoint():
            return
        text = (tr("fb_unsent_one_prompt") if len(entries) == 1 else
                tr("fb_unsent_prompt").format(num(len(entries))))
        answer = QMessageBox.question(
            self, tr("btn_feedback"), text,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            self._chain_active = True
            self._send_next_pending()

    def _send_next_pending(self) -> None:
        if not self._chain_active or self._posting:
            return
        entries = load_pending(self.parent_window)
        if not entries:
            self._chain_active = False
            QMessageBox.information(self, tr("btn_feedback"),
                                    tr("fb_all_sent"))
            return
        self._start_post(entries[0]["payload"], from_chain=True)


class ImportDialog(QDialog):
    """Pick files or a folder; import runs in a background worker."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("import_title"))
        self.parent_window = parent
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        header_frame = QFrame()
        header_frame.setObjectName("BannerCard")
        header_lay = QVBoxLayout(header_frame)
        header_lay.setContentsMargins(16, 12, 16, 12)
        header_lay.setSpacing(4)
        title_lbl = QLabel(tr("import_title"))
        title_lbl.setObjectName("DialogTitle")
        hint_lbl = QLabel(tr("import_hint"))
        hint_lbl.setObjectName("DialogHint")
        hint_lbl.setWordWrap(True)
        header_lay.addWidget(title_lbl)
        header_lay.addWidget(hint_lbl)
        layout.addWidget(header_frame)

        drop_zone = QFrame()
        drop_zone.setObjectName("DropZone")
        dz_lay = QVBoxLayout(drop_zone)
        dz_lay.setContentsMargins(16, 18, 16, 18)
        dz_lay.setSpacing(8)
        dz_icon = QLabel()
        dz_icon.setAlignment(Qt.AlignCenter)
        dz_icon.setPixmap(icons.tinted_pixmap("upload", theme.PALETTE["accent"], 28))
        dz_lbl = QLabel(tr("import_drop_hint"))
        dz_lbl.setObjectName("DialogHint")
        dz_lbl.setAlignment(Qt.AlignCenter)
        dz_lbl.setWordWrap(True)
        dz_lay.addWidget(dz_icon)
        dz_lay.addWidget(dz_lbl)
        layout.addWidget(drop_zone)

        pick_files = QPushButton(tr("import_pick_files"))
        pick_files.setObjectName("Primary")
        pick_files.setIcon(icons.icon("file-text", theme.PALETTE["on_accent"], 18))
        pick_files.setIconSize(QSize(18, 18))
        pick_files.setFixedHeight(38)

        pick_folder = QPushButton(tr("import_pick_folder"))
        pick_folder.setObjectName("Secondary")
        pick_folder.setIcon(icons.icon("folder-open", theme.PALETTE["text"], 18))
        pick_folder.setIconSize(QSize(18, 18))
        pick_folder.setFixedHeight(38)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(pick_files)
        row.addWidget(pick_folder)
        layout.addLayout(row)

        self.keep = QCheckBox(tr("import_keep"))
        layout.addWidget(self.keep)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton(tr("cancel"))
        cancel_btn.setObjectName("Secondary")
        cancel_btn.setFixedHeight(36)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        pick_files.clicked.connect(self._pick_files)
        pick_folder.clicked.connect(self._pick_folder)
        polish_dialog(self, 480)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self._start(paths)
        else:
            event.ignore()

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

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("BannerCard")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(14, 10, 14, 10)
        h_lay.setSpacing(12)
        h_icon = QLabel()
        h_icon.setPixmap(icons.tinted_pixmap("package", theme.PALETTE["accent"], 26))
        h_lay.addWidget(h_icon)
        h_text = QVBoxLayout()
        h_text.setSpacing(3)
        h_title = QLabel(tr("export_title"))
        h_title.setObjectName("DialogTitle")
        h_sub = QLabel(tr("export_header_sub"))
        h_sub.setObjectName("DialogHint")
        h_sub.setWordWrap(True)
        h_text.addWidget(h_title)
        h_text.addWidget(h_sub)
        h_lay.addLayout(h_text, 1)
        layout.addWidget(header)

        btn_selected = QPushButton(
            tr("export_scope_selected").format(num(len(selected_ids))))
        btn_filtered = QPushButton(
            tr("export_scope_filtered").format(num(len(parent.last_rows))))
        btn_selected.setEnabled(bool(selected_ids))
        btn_filtered.setEnabled(bool(parent.last_rows))
        btn_selected.setObjectName("Primary" if selected_ids else "Secondary")
        btn_filtered.setObjectName("Secondary" if selected_ids else "Primary")
        btn_selected.setFixedHeight(38)
        btn_filtered.setFixedHeight(38)
        btn_selected.setIcon(icons.icon(
            "package",
            theme.PALETTE["on_accent"] if selected_ids else theme.PALETTE["muted"],
            16,
        ))
        btn_filtered.setIcon(icons.icon(
            "download",
            theme.PALETTE["text"] if selected_ids else theme.PALETTE["on_accent"],
            16,
        ))
        layout.addWidget(btn_selected)
        layout.addWidget(btn_filtered)

        btn_box = QHBoxLayout()
        btn_box.addStretch(1)
        btn_cancel = QPushButton(tr("cancel"))
        btn_cancel.setObjectName("Secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)
        layout.addLayout(btn_box)

        btn_selected.clicked.connect(lambda: self._export(selected_ids))
        btn_filtered.clicked.connect(
            lambda: self._export([r["id"] for r in parent.last_rows]))
        polish_dialog(self, 480)

    def _export(self, file_ids: list) -> None:
        if not file_ids:
            return
        default = f"darspack-{datetime.now():%Y%m%d-%H%M}.zip"
        path, _ = QFileDialog.getSaveFileName(
            self, tr("export_title"), default, "ZIP (*.zip)")
        if not path:
            return
        lib = self.parent_window.lib
        try:
            info = manifest_core.export_package(
                lib.conn, lib.files_dir, file_ids, path)
            with lib.conn:
                db.log(lib.conn, "export", f"{info['count']} files → {path}")
        except OSError as exc:
            QMessageBox.critical(self, tr("export_title"), str(exc))
            return
        QMessageBox.information(
            self, tr("export_title"),
            tr("export_done").format(num(info["count"]), info["manifest_sha256"][:16]))
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
        self.resize(1120, max(360, min(580, 230 + len(file_ids) * 46)))

        headers = [tr("col_name"), tr("meta_subject"), tr("meta_chapter"),
                   tr("meta_kind"), tr("meta_lesson"),
                   tr("meta_year"), tr("meta_tags_col")]
        self.table = QTableWidget(len(file_ids), len(headers))
        self.table.setObjectName("InlineEditTable")
        self.table.setFocusPolicy(Qt.ClickFocus)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setItemDelegateForColumn(0, FileNameDelegate(self.table))
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 165), (2, 86), (3, 128),
                           (4, 86), (5, 132), (6, 170)):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            self.table.setColumnWidth(col, width)
        name_align = Qt.AlignLeading | Qt.AlignVCenter
        for col in range(len(headers)):
            hi = self.table.horizontalHeaderItem(col)
            if hi is not None:
                hi.setTextAlignment(name_align if col == 0 else Qt.AlignCenter)
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
            name_item.setToolTip(file_row["original_name"])
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
            self.table.setCellWidget(r, 1, _wrap_table_widget(subject))

            chapter = make_spinbox()
            chapter.setValue(file_row["chapter"] or 0)
            self.table.setCellWidget(r, 2, _wrap_table_widget(chapter))

            kind = QComboBox()
            kind.addItems(("جزوه", "نمونه‌سوال", "کاربرگ", "تکلیف", "سایر"))
            kind.setCurrentText(file_row["kind"] or "سایر")
            self.table.setCellWidget(r, 3, _wrap_table_widget(kind))

            # A3b: درس (lesson) is a separate number from فصل (chapter) —
            # either, both, or neither may be set (design decision).
            lesson = make_spinbox()
            lesson.setValue(file_row["lesson"] or 0)
            self.table.setCellWidget(r, 4, _wrap_table_widget(lesson))

            year = make_year_combo(file_row["school_year"])
            self.table.setCellWidget(r, 5, _wrap_table_widget(year))

            # A5: the manifest's tags arrive as pre-fill too
            tags_edit = QLineEdit()
            tags_edit.setPlaceholderText(tr("meta_tags_placeholder"))
            tags_edit.setText("، ".join(prefill.get("tags") or []))
            self.table.setCellWidget(r, 6, _wrap_table_widget(tags_edit))

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
        bulk_bar.setVisible(len(file_ids) > 1)
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
        save.setDefault(False)
        save.setAutoDefault(False)
        save.clicked.connect(self._save_all)
        buttons.addWidget(save)
        buttons.addWidget(later)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        polish_dialog(self, 1100)

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
                     _latin_digits(year.currentText().strip()) or None, fid))
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
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QFrame()
        header.setObjectName("BannerCard")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(14, 10, 14, 10)
        h_lay.setSpacing(12)
        h_icon = QLabel()
        h_icon.setPixmap(icons.tinted_pixmap(
            "circle-check" if report.ok else "triangle-alert",
            theme.PALETTE["success"] if report.ok else theme.PALETTE["danger"],
            26,
        ))
        h_lay.addWidget(h_icon)
        h_text = QVBoxLayout()
        h_text.setSpacing(4)
        h_title = QLabel(tr("verify_header_title"))
        h_title.setObjectName("DialogTitle")
        file_row = QHBoxLayout()
        file_row.setContentsMargins(0, 0, 0, 0)
        file_row.setSpacing(6)
        h_sub = QLabel(tr("verify_file_label"))
        h_sub.setObjectName("DialogHint")
        fn_lbl = FileNameLabel(Path(str(path)).name)
        fn_lbl.setToolTip(str(path))
        file_row.addWidget(h_sub)
        file_row.addWidget(fn_lbl, 1)
        h_text.addWidget(h_title)
        h_text.addLayout(file_row)
        h_lay.addLayout(h_text, 1)
        layout.addWidget(header)

        body = QFrame()
        body.setObjectName("SuccessCard" if report.ok else "DangerCard")
        b_lay = QVBoxLayout(body)
        b_lay.setContentsMargins(14, 12, 14, 12)
        b_lay.setSpacing(8)
        if report.ok:
            label = QLabel(tr("verify_ok"))
            label.setWordWrap(True)
            label.setObjectName("SuccessText")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            b_lay.addWidget(label)
        else:
            head_err = QLabel(f"<b>{tr('verify_problems')}</b>")
            head_err.setStyleSheet(f"color: {theme.PALETTE['danger']};")
            b_lay.addWidget(head_err)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setMaximumHeight(220)
            inner = QWidget()
            inner_lay = QVBoxLayout(inner)
            inner_lay.setContentsMargins(0, 0, 0, 0)
            inner_lay.setSpacing(4)
            for prob in report.problems:
                p_lbl = QLabel(f"• {prob}")
                p_lbl.setWordWrap(True)
                p_lbl.setStyleSheet("color: #ff9d96;")
                p_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                inner_lay.addWidget(p_lbl)
            inner_lay.addStretch(1)
            scroll.setWidget(inner)
            enable_smooth_scroll(scroll)
            b_lay.addWidget(scroll)
            bad_hint = QLabel(tr("verify_bad_hint"))
            bad_hint.setObjectName("DialogHint")
            bad_hint.setWordWrap(True)
            b_lay.addWidget(bad_hint)
        layout.addWidget(body)

        with library.conn:
            db.log(library.conn, "verify",
                   f"{'ok' if report.ok else len(report.problems)} problems — {path}")
        if report.ok and offer_import:
            btn = QPushButton(tr("pkg_import_btn"))
            btn.setObjectName("Primary")
            btn.setFixedHeight(38)
            btn.setIcon(icons.icon("download", theme.PALETTE["on_accent"], 16))
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
        clean_sub_keys = ("dups_clean_sub1", "dups_clean_sub2", "dups_clean_sub3")
        for tab_idx, (title, groups) in enumerate(groups_by_tab.items()):
            if not groups:
                empty_card = QFrame()
                empty_card.setStyleSheet("QFrame { background: transparent; border: none; }")
                e_lay = QVBoxLayout(empty_card)
                e_lay.setContentsMargins(20, 40, 20, 40)
                e_lay.setAlignment(Qt.AlignCenter)
                ic_lbl = QLabel()
                ic_lbl.setAlignment(Qt.AlignCenter)
                ic_lbl.setPixmap(icons.tinted_pixmap("circle-check", theme.PALETTE["success"], 36))
                msg_lbl = QLabel(tr("dups_clean_msg"))
                msg_lbl.setObjectName("DialogTitle")
                msg_lbl.setAlignment(Qt.AlignCenter)
                sub_key = clean_sub_keys[tab_idx] if tab_idx < len(clean_sub_keys) else "dups_clean_sub"
                sub_lbl = QLabel(tr(sub_key))
                sub_lbl.setObjectName("DialogHint")
                sub_lbl.setWordWrap(True)
                sub_lbl.setAlignment(Qt.AlignCenter)
                e_lay.addWidget(ic_lbl)
                e_lay.addSpacing(8)
                e_lay.addWidget(msg_lbl)
                e_lay.addWidget(sub_lbl)
                tabs.addTab(empty_card, f"{title} ({num(0)})")
            else:
                listing = QListWidget()
                enable_smooth_scroll(listing)
                for group in groups:
                    names = " ، ".join(
                        i18n.bidi_filename(r["original_name"]) for r in group.rows)
                    detail_txt = persian_digits(group.detail_fa) if i18n.language() == "fa" else group.detail_fa
                    listing.addItem(f"[{group.label_fa}] {names}\n    {detail_txt}")
                listing.itemDoubleClicked.connect(self._jump)
                tabs.addTab(listing, f"{title} ({num(len(groups))})")
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        close_btn = QPushButton(tr("close"))
        close_btn.setObjectName("Secondary")
        close_btn.clicked.connect(self.accept)
        btn_box.addWidget(close_btn)
        layout.addLayout(btn_box)
        polish_dialog(self, 700)

    def _jump(self, item) -> None:
        # item text: "[label] name1 ، name2\n    detail" — search the first name
        body = item.text().split("] ", 1)[1] if "] " in item.text() else item.text()
        first = body.splitlines()[0].split(" ، ", 1)[0].strip()
        first = first.translate(str.maketrans("", "", "\u200f\u2066\u2067\u2068\u2069"))
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
        self.note.setPlaceholderText(tr("meta_note_placeholder"))

        save = QPushButton(tr("ok"))
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._save)
        cancel = QPushButton(tr("cancel"))
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)

        form = QVBoxLayout(self)
        from .main_window import human_size, jalali_date
        header_card = QFrame()
        header_card.setObjectName("BannerCard")
        header_lay = QVBoxLayout(header_card)
        header_lay.setContentsMargins(14, 10, 14, 10)
        header_lay.setSpacing(3)
        fn_lbl = FileNameLabel(self.row['original_name'])
        fn_lbl.setObjectName("DialogTitle")
        fn_lbl.setToolTip(self.row['original_name'])
        sub_lbl = QLabel(
            f"{human_size(self.row['size_bytes'])} · "
            f"{num(jalali_date(self.row['imported_at']))}")
        sub_lbl.setObjectName("DialogHint")
        header_lay.addWidget(fn_lbl)
        header_lay.addWidget(sub_lbl)
        form.addWidget(header_card)
        self.tags.setPlaceholderText(tr("meta_tags_placeholder"))
        row_labels: list[QLabel] = []
        for label, widget in ((tr("meta_subject"), self.subject),
                              (tr("meta_chapter"), self.chapter),
                              (tr("meta_lesson"), self.lesson),
                              (tr("meta_kind"), self.kind),
                              (tr("meta_year"), self.year),
                              (tr("meta_tags_short"), self.tags),
                              (tr("meta_note"), self.note)):
            row = QHBoxLayout()
            lab = QLabel(label)
            row_labels.append(lab)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            row.addWidget(lab)
            row.addWidget(widget, 1)
            form.addLayout(row)
        _equalize_label_widths(row_labels)
        buttons = QHBoxLayout()
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        form.addLayout(buttons)
        polish_dialog(self, 520)

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
                 _latin_digits(self.year.currentText().strip()) or None,
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
        self.setMinimumWidth(480)
        self.resize(500, 360)
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

        # Select «بدون تغییر» automatically on focus so first typed key replaces it
        for combo in (self.subject, self.year):
            le = combo.lineEdit()
            if le is not None:
                le.installEventFilter(self)

        form = QVBoxLayout(self)
        header_card = QFrame()
        header_card.setObjectName("BannerCard")
        header_lay = QVBoxLayout(header_card)
        header_lay.setContentsMargins(14, 12, 14, 12)
        header_lay.setSpacing(4)
        title_lbl = QLabel(tr("bulk_edit_title"))
        title_lbl.setObjectName("DialogTitle")
        hint = QLabel(tr("bulk_edit_hint").format(
            count=num(len(self.file_ids))))
        hint.setObjectName("DialogHint")
        hint.setWordWrap(True)
        hint.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        header_lay.addWidget(title_lbl)
        header_lay.addWidget(hint)
        form.addWidget(header_card)
        row_labels: list[QLabel] = []
        for label, widget in ((tr("meta_subject"), self.subject),
                              (tr("meta_chapter"), self.chapter),
                              (tr("meta_lesson"), self.lesson),
                              (tr("meta_kind"), self.kind),
                              (tr("meta_year"), self.year)):
            row = QHBoxLayout()
            lab = QLabel(label)
            row_labels.append(lab)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            row.addWidget(lab)
            row.addWidget(widget, 1)
            form.addLayout(row)
        _equalize_label_widths(row_labels)
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
        polish_dialog(self, 520)
        self.adjustSize()
        self.resize(max(self.width(), 520), max(395, self.sizeHint().height()))

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.FocusIn and isinstance(obj, QLineEdit):
            if obj.text() == tr("bulk_none"):
                QTimer.singleShot(0, obj.selectAll)
        return super().eventFilter(obj, event)

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
        year = _latin_digits(self.year.currentText().strip())
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
        self.font_size.setSuffix(" pt")
        self.font_size.setValue(int(settings.get("font_size", 10)))

        self.library = QLineEdit(str(settings.get("library", "")))
        self.library.setPlaceholderText(tr("settings_lib_placeholder"))

        browse = QPushButton()
        browse.setObjectName("Secondary")
        browse.setIcon(icons.icon("folder-open", theme.PALETTE["text"], 16))
        browse.setIconSize(QSize(16, 16))
        browse.setFixedSize(38, 36)
        browse.setToolTip(tr("import_pick_folder"))
        browse.clicked.connect(self._browse)

        from .. import feedback_config
        ep = (settings["feedback_endpoint"] if "feedback_endpoint" in settings
              else feedback_config.FEEDBACK_ENDPOINT)
        fu = (settings["feedback_form_url"] if "feedback_form_url" in settings
              else feedback_config.FEEDBACK_FORM_URL)
        self.fb_endpoint = QLineEdit(str(ep or ""))
        self.fb_endpoint.setLayoutDirection(Qt.LeftToRight)
        self.fb_form_url = QLineEdit(str(fu or ""))
        self.fb_form_url.setLayoutDirection(Qt.LeftToRight)

        save = QPushButton(tr("btn_save"))
        save.setObjectName("Primary")
        save.setDefault(True)
        save.clicked.connect(self._save)
        reset_btn = QPushButton(tr("settings_reset"))
        reset_btn.setObjectName("Ghost")
        reset_btn.clicked.connect(self._reset_defaults)
        cancel = QPushButton(tr("cancel"))
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self.reject)

        form = QVBoxLayout(self)
        form.setSpacing(10)
        row_labels: list[QLabel] = []
        for label, widget in ((tr("settings_lang"), self.lang),
                              (tr("settings_font"), self.font_size),
                              (tr("settings_lib"), None)):
            row = QHBoxLayout()
            lab = QLabel(label)
            row_labels.append(lab)
            row.addWidget(lab)
            if widget is None:
                self.library.setLayoutDirection(Qt.LeftToRight)
                row.addWidget(self.library, 1)
                row.addWidget(browse)
            else:
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                row.addWidget(widget, 1)
            form.addLayout(row)
        _equalize_label_widths(row_labels)

        restart = QLabel(tr("settings_restart"))
        restart.setObjectName("DialogHint")
        restart.setWordWrap(True)
        form.addWidget(restart)

        # endpoints are developer-facing: behind an «پیشرفته» toggle
        self.advanced = QCheckBox(tr("settings_advanced"))
        self.advanced_fields = QFrame()
        self.advanced_fields.setObjectName("BannerCard")
        advanced_layout = QVBoxLayout(self.advanced_fields)
        advanced_layout.setContentsMargins(12, 10, 12, 10)
        advanced_layout.setSpacing(8)
        for lbl_key, field in (("settings_fb_endpoint", self.fb_endpoint),
                               ("settings_fb_form_url", self.fb_form_url)):
            adv_lbl = QLabel(tr(lbl_key))
            adv_lbl.setObjectName("DialogHint")
            advanced_layout.addWidget(adv_lbl)
            advanced_layout.addWidget(field)
        self.advanced_fields.setVisible(False)
        self.advanced.toggled.connect(self._toggle_advanced)
        form.addWidget(self.advanced)
        form.addWidget(self.advanced_fields)

        buttons = QHBoxLayout()
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        buttons.addWidget(reset_btn)
        form.addLayout(buttons)
        polish_dialog(self, 540)

    def _toggle_advanced(self, visible: bool) -> None:
        self.advanced_fields.setVisible(visible)
        if self.layout() is not None:
            self.layout().activate()
        self.adjustSize()
        self.resize(max(self.width(), 540), self.sizeHint().height())

    def _reset_defaults(self) -> None:
        from .. import feedback_config
        self.lang.setCurrentIndex(0)
        self.font_size.setValue(10)
        self.fb_endpoint.setText(feedback_config.FEEDBACK_ENDPOINT)
        self.fb_form_url.setText(feedback_config.FEEDBACK_FORM_URL)

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
        self._closed_notified = False
        self.setWindowTitle(tr("share_title"))
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        port = getattr(server, "port", None)
        if not port and urls:
            import urllib.parse as _up
            try:
                port = _up.urlparse(urls[0]).port
            except ValueError:
                port = None
        if port:
            live_text = tr("share_status_live").format(persian_digits(str(port)))
        else:
            live_text = (
                tr("share_status_live")
                .replace(" (پورت {})", "")
                .replace(" (port {})", "")
            )
        live_pill = QLabel(live_text)
        live_pill.setObjectName("SuccessText")
        live_pill.setAlignment(Qt.AlignCenter)
        layout.addWidget(live_pill)

        caption = QLabel(tr("share_pin"))
        caption.setObjectName("DialogHint")
        caption.setAlignment(Qt.AlignCenter)
        layout.addWidget(caption)
        pin_label = QLabel(persian_digits(str(server.pin)))
        pin_label.setObjectName("PinDigits")
        pin_label.setAlignment(Qt.AlignCenter)
        pin_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(pin_label)
        copy_pin = QPushButton(tr("copy_pin"))
        copy_pin.setObjectName("Secondary")
        copy_pin.setIcon(icons.icon("copy", theme.PALETTE["text"], 14))

        def _copy_with_feedback(btn: QPushButton, text: str, orig_label: str, orig_icon: str) -> None:
            cb = QApplication.clipboard()
            if cb:
                cb.setText(text)
            btn.setText(tr("copied_done"))
            btn.setIcon(icons.icon("check", theme.PALETTE["success"], 14))
            QTimer.singleShot(1800, btn, lambda b=btn, lbl=orig_label, i=orig_icon: (
                b.setText(lbl),
                b.setIcon(icons.icon(i, theme.PALETTE["text"], 14)),
            ))

        copy_pin.clicked.connect(
            lambda: _copy_with_feedback(copy_pin, str(server.pin), tr("copy_pin"), "copy"))
        layout.addWidget(copy_pin, 0, Qt.AlignCenter)

        urls_lbl = QLabel(tr("share_urls"))
        urls_lbl.setWordWrap(True)
        urls_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(urls_lbl)
        from urllib.parse import urlparse
        non_loopback = [
            u for u in urls
            if (urlparse(u).hostname or "") not in ("127.0.0.1", "localhost", "::1")
        ]
        shown_urls = non_loopback or urls
        for url in shown_urls:
            u_row = QHBoxLayout()
            u_row.setSpacing(6)
            line = QLineEdit(url)
            line.setReadOnly(True)
            line.setLayoutDirection(Qt.LeftToRight)
            line.setAlignment(Qt.AlignCenter)
            u_btn = QPushButton()
            u_btn.setObjectName("Secondary")
            u_btn.setFixedSize(36, 36)
            u_btn.setToolTip(tr("copy_url"))
            u_btn.setIcon(icons.icon("copy", theme.PALETTE["text"], 14))
            u_btn.clicked.connect(
                lambda _, u=url, b=u_btn: (
                    QApplication.clipboard().setText(u),
                    b.setIcon(icons.icon("check", theme.PALETTE["success"], 14)),
                    QTimer.singleShot(1800, b, lambda btn=b: btn.setIcon(
                        icons.icon("copy", theme.PALETTE["text"], 14))),
                ))
            u_row.addWidget(line, 1)
            u_row.addWidget(u_btn)
            layout.addLayout(u_row)
        lan = pick_lan_url(urls)
        if lan is not None:
            copy_url = QPushButton(tr("copy_url"))
            copy_url.setObjectName("Secondary")
            copy_url.setIcon(icons.icon("link", theme.PALETTE["text"], 14))
            copy_url.clicked.connect(
                lambda: _copy_with_feedback(copy_url, lan, tr("copy_url"), "link"))
            layout.addWidget(copy_url, 0, Qt.AlignCenter)
        else:
            warn = QFrame()
            warn.setObjectName("InfoCallout")
            w_lay = QHBoxLayout(warn)
            w_lay.setContentsMargins(12, 8, 12, 8)
            w_lay.setSpacing(8)
            w_ic = QLabel()
            w_ic.setPixmap(icons.tinted_pixmap("triangle-alert", theme.PALETTE["accent"], 18))
            w_lbl = QLabel(tr("share_no_lan_warn"))
            w_lbl.setObjectName("DialogHint")
            w_lbl.setWordWrap(True)
            w_lay.addWidget(w_ic)
            w_lay.addWidget(w_lbl, 1)
            layout.addWidget(warn)
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
                "QFrame#QrCard { background: #ffffff; border: 1px solid #d7deea; border-radius: 12px; }")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 10, 10, 10)
            card_layout.addWidget(qr, 0, Qt.AlignCenter)
            qr_cap = QLabel(tr("qr_caption"))
            qr_cap.setObjectName("DialogHint")
            qr_cap.setAlignment(Qt.AlignCenter)
            layout.addWidget(qr_cap)
            layout.addWidget(card, 0, Qt.AlignCenter)
        hint_lbl = QLabel(tr("share_hint"))
        hint_lbl.setObjectName("DialogHint")
        hint_lbl.setAlignment(Qt.AlignCenter)
        hint_lbl.setWordWrap(True)
        layout.addWidget(hint_lbl)
        # D4: poll the catalog every 5 s — a phone upload becomes visible
        # on the desktop while sharing, not only after the dialog closes.
        self._upload_label = QLabel("")
        self._upload_label.setObjectName("SuccessText")
        self._upload_label.setAlignment(Qt.AlignCenter)
        self._upload_label.hide()
        layout.addWidget(self._upload_label)
        self._file_count_at_start = self._count_files()
        from PySide6.QtCore import QTimer
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self._check_files)
        self._poll_timer.start()
        stop_row = QHBoxLayout()
        stop_row.addStretch(1)
        stop = QPushButton(tr("btn_stop_share"))
        stop.setObjectName("Secondary")
        stop.clicked.connect(self.accept)
        stop_row.addWidget(stop)
        stop_row.addStretch(1)
        layout.addLayout(stop_row)
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
            self._upload_label.hide()
            if hasattr(parent, "refresh"):
                parent.refresh()

    def _notify_closed(self) -> None:
        self._poll_timer.stop()
        if not self._closed_notified:
            self._closed_notified = True
            if callable(self.on_close):
                self.on_close()

    def done(self, result: int) -> None:
        self._notify_closed()
        super().done(result)

    def closeEvent(self, event) -> None:
        self._notify_closed()
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
            self.event_table.setFocusPolicy(Qt.ClickFocus)
            self.event_table.setWordWrap(False)
            eh = self.event_table.horizontalHeader()
            eh.setSectionResizeMode(0, QHeaderView.Fixed)
            self.event_table.setColumnWidth(0, 115)
            eh.setSectionResizeMode(1, QHeaderView.Fixed)
            self.event_table.setColumnWidth(1, 140)
            eh.setSectionResizeMode(2, QHeaderView.Stretch)
            detail_align = Qt.AlignLeading | Qt.AlignVCenter
            for col in range(3):
                hi = self.event_table.horizontalHeaderItem(col)
                if hi is not None:
                    hi.setTextAlignment(detail_align if col == 2 else Qt.AlignCenter)
            self.event_table.setItemDelegateForColumn(
                2, FileNameDelegate(self.event_table, filename_role=Qt.UserRole)
            )
            enable_smooth_scroll(self.event_table)
            from .main_window import jalali_date
            for i, ev in enumerate(events):
                detail_str = str(ev["detail"] or "")
                shown_detail, is_filename = _format_activity_detail(
                    ev["action"], detail_str
                )
                values = (persian_digits(jalali_date(ev["ts"])),
                          ACTION_FA.get(ev["action"], ev["action"]),
                          shown_detail)
                for col, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if col in (0, 1):
                        item.setTextAlignment(Qt.AlignCenter)
                    elif col == 2:
                        item.setData(Qt.UserRole, is_filename)
                        item.setToolTip(shown_detail)
                    self.event_table.setItem(i, col, item)
            layout = QVBoxLayout()
            layout.setContentsMargins(6, 10, 6, 4)
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
        layout.setContentsMargins(6, 10, 6, 4)
        layout.setSpacing(10)
        explain_lbl = QLabel(tr("hints_explain"))
        explain_lbl.setObjectName("DialogHint")
        explain_lbl.setWordWrap(True)
        layout.addWidget(explain_lbl)
        self._rules_empty_page = self._message_page(tr("hints_empty"))
        self._rules_empty_page.hide()
        if rules:
            self.rule_table = QTableWidget(len(rules), 3)
            self.rule_table.setHorizontalHeaderLabels(
                (tr("hints_token"), tr("meta_subject"), tr("hints_hits_col")))
            self.rule_table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.rule_table.verticalHeader().setVisible(False)
            self.rule_table.verticalHeader().setDefaultSectionSize(38)
            self.rule_table.setShowGrid(False)
            self.rule_table.setAlternatingRowColors(True)
            self.rule_table.setSelectionBehavior(QTableWidget.SelectRows)
            self.rule_table.setFocusPolicy(Qt.ClickFocus)
            rh = self.rule_table.horizontalHeader()
            rh.setSectionResizeMode(0, QHeaderView.Stretch)
            rh.setSectionResizeMode(1, QHeaderView.Fixed)
            self.rule_table.setColumnWidth(1, 140)
            rh.setSectionResizeMode(2, QHeaderView.Fixed)
            self.rule_table.setColumnWidth(2, 110)
            tok_align = Qt.AlignLeading | Qt.AlignVCenter
            for col in range(3):
                hi = self.rule_table.horizontalHeaderItem(col)
                if hi is not None:
                    hi.setTextAlignment(Qt.AlignCenter if col == 2 else tok_align)
            enable_smooth_scroll(self.rule_table)
            for i, rule in enumerate(rules):
                self.rule_table.setItem(i, 0, QTableWidgetItem(rule["token"]))
                self.rule_table.setItem(i, 1, QTableWidgetItem(rule["subject"]))
                hits_item = QTableWidgetItem(tr("hints_hits").format(
                    num(rule["hits"])))
                hits_item.setTextAlignment(Qt.AlignCenter)
                self.rule_table.setItem(i, 2, hits_item)
            layout.addWidget(self.rule_table)
            forget_row = QHBoxLayout()
            self.forget_btn = QPushButton(tr("hints_forget"))
            self.forget_btn.setObjectName("Danger")
            self.forget_btn.setIcon(icons.icon("trash-2", theme.PALETTE["danger"], 15))
            self.forget_btn.setEnabled(False)
            self.rule_table.itemSelectionChanged.connect(
                lambda: self.forget_btn.setEnabled(
                    bool(self.rule_table.selectedItems())
                )
            )
            self.forget_btn.clicked.connect(self._forget_selected_rule)
            forget_row.addWidget(self.forget_btn)
            forget_row.addStretch(1)
            layout.addLayout(forget_row)
            layout.addWidget(self._rules_empty_page)
        else:
            self._rules_empty_page.show()
            layout.addWidget(self._rules_empty_page, 1)
        tabs.addTab(page, tr("hints_title"))

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton(tr("close"))
        close_btn.setObjectName("Secondary")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
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
        if self.rule_table.rowCount() == 0:
            self.rule_table.hide()
            self.forget_btn.hide()
            self._rules_empty_page.show()

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
    name_label.setObjectName("StatNameLabel")
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
        self.resize(600, 540)

        layout = QVBoxLayout(self)
        if stats["file_count"] == 0 and not stats["dedup_bytes"]:
            layout.addWidget(QLabel(tr("stats_empty")))
        else:
            from .main_window import human_size
            stat_cards_layout = QHBoxLayout()
            stat_cards_layout.setSpacing(10)

            def make_stat_card(title: str, value: str, icon_name: str,
                               tooltip: str = "") -> QFrame:
                card = QFrame()
                card.setObjectName("BannerCard")
                if tooltip:
                    card.setToolTip(tooltip)
                c_lay = QVBoxLayout(card)
                c_lay.setContentsMargins(12, 10, 12, 10)
                c_lay.setSpacing(4)
                top_row = QHBoxLayout()
                ic_lbl = QLabel()
                ic_lbl.setPixmap(icons.tinted_pixmap(icon_name, theme.PALETTE["accent"], 18))
                t_lbl = QLabel(title)
                t_lbl.setObjectName("DialogHint")
                top_row.addWidget(ic_lbl)
                top_row.addWidget(t_lbl)
                top_row.addStretch()
                v_lbl = QLabel(value)
                v_lbl.setObjectName("DialogTitle")
                c_lay.addLayout(top_row)
                c_lay.addWidget(v_lbl)
                return card

            stat_cards_layout.addWidget(make_stat_card(tr("stats_total"), human_size(stats["total_bytes"]), "archive"))
            stat_cards_layout.addWidget(make_stat_card(
                tr("stats_dedup"), human_size(stats["dedup_bytes"]),
                "sparkles", tr("stats_dedup_hint")))
            stat_cards_layout.addWidget(make_stat_card(tr("stats_unclassified"), num(stats["unclassified"]), "file-text"))
            layout.addLayout(stat_cards_layout)

            scroll = QScrollArea()
            scroll.setObjectName("TabScrollArea")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.viewport().setObjectName("TabScrollViewport")
            scroll.viewport().setAutoFillBackground(False)
            bars_host = QWidget()
            bars_host.setObjectName("TabScrollContent")
            bars_host.setAutoFillBackground(False)
            bars_layout = QVBoxLayout(bars_host)
            bars_layout.setContentsMargins(0, 6, 0, 6)
            bars_layout.setSpacing(8)

            bar_labels: list[QLabel] = []
            bars_layout.addWidget(QLabel(f"<b>{tr('stats_per_subject')}</b>"))
            max_sub = max((c for _, c in stats["per_subject"]), default=0)
            for name, count in stats["per_subject"]:
                row_w = stat_bar_row(name, count, max_sub)
                lbl = row_w.findChild(QLabel, "StatNameLabel")
                if lbl is not None:
                    bar_labels.append(lbl)
                bars_layout.addWidget(row_w)
            bars_layout.addSpacing(8)
            bars_layout.addWidget(QLabel(f"<b>{tr('stats_per_kind')}</b>"))
            max_kind = max((c for _, c in stats["per_kind"]), default=0)
            for kind, count in stats["per_kind"]:
                row_w = stat_bar_row(kind, count, max_kind)
                lbl = row_w.findChild(QLabel, "StatNameLabel")
                if lbl is not None:
                    bar_labels.append(lbl)
                bars_layout.addWidget(row_w)
            bars_layout.addStretch(1)
            _equalize_label_widths(bar_labels, padding=10)
            scroll.setWidget(bars_host)
            enable_smooth_scroll(scroll)
            layout.addWidget(scroll, 1)

        close = QPushButton(tr("close"))
        close.setObjectName("Secondary")
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        polish_dialog(self, 600)


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
        self.table.verticalHeader().setDefaultSectionSize(theme.METRICS["row_height"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.ClickFocus)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setItemDelegateForColumn(0, FileNameDelegate(self.table))

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 130)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 95)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 130)
        name_align = Qt.AlignLeading | Qt.AlignVCenter
        for col in range(len(headers)):
            hi = self.table.horizontalHeaderItem(col)
            if hi is not None:
                hi.setTextAlignment(name_align if col == 0 else Qt.AlignCenter)
        self._scroller = enable_smooth_scroll(self.table)

        layout.addWidget(self.table)

        self.empty_label = QFrame()
        self.empty_label.setObjectName("BannerCard")
        e_lay = QVBoxLayout(self.empty_label)
        e_lay.setContentsMargins(24, 36, 24, 36)
        e_lay.setSpacing(8)
        e_lay.setAlignment(Qt.AlignCenter)
        e_icon = QLabel()
        e_icon.setAlignment(Qt.AlignCenter)
        e_icon.setPixmap(icons.tinted_pixmap("archive", theme.PALETTE["muted"], 36))
        e_title = QLabel(tr("trash_empty_state"))
        e_title.setObjectName("DialogTitle")
        e_title.setAlignment(Qt.AlignCenter)
        e_hint = QLabel(tr("trash_empty_hint"))
        e_hint.setObjectName("DialogHint")
        e_hint.setWordWrap(True)
        e_hint.setAlignment(Qt.AlignCenter)
        e_lay.addWidget(e_icon)
        e_lay.addWidget(e_title)
        e_lay.addWidget(e_hint)
        layout.addWidget(self.empty_label)

        btn_box = QHBoxLayout()
        self.btn_restore = QPushButton(tr("trash_restore_btn"))
        self.btn_restore.setObjectName("Primary")
        self.btn_restore.setIcon(icons.icon("refresh-cw", theme.PALETTE["on_accent"], 16))
        self.btn_restore.setIconSize(QSize(16, 16))
        self.btn_restore.clicked.connect(self._restore_selected)
        btn_box.addWidget(self.btn_restore)

        self.btn_empty = QPushButton(tr("trash_empty_btn"))
        self.btn_empty.setObjectName("Danger")
        self.btn_empty.setIcon(icons.icon("trash-2", theme.PALETTE["danger"], 16))
        self.btn_empty.setIconSize(QSize(16, 16))
        self.btn_empty.clicked.connect(self._empty_trash)
        btn_box.addWidget(self.btn_empty)

        btn_box.addStretch()
        btn_close = QPushButton(tr("close"))
        btn_close.setObjectName("Secondary")
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
            name_item.setIcon(icons.icon("file-text", theme.PALETTE["muted"], 16))
            name_item.setData(Qt.UserRole, it["trash_name"])
            name_item.setToolTip(it["original_name"])
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 0, name_item)

            subj_raw = it["subject_name"]
            subj = "" if subj_raw in (None, "", "?") else subj_raw
            sub_item = QTableWidgetItem(subj or "—")
            sub_item.setTextAlignment(Qt.AlignCenter)
            sub_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 1, sub_item)

            size_item = QTableWidgetItem(human_size(it["size"]))
            size_item.setTextAlignment(Qt.AlignCenter)
            size_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, 2, size_item)

            date_str = num(jalali_date(it["deleted_at"])) if it.get("deleted_at") else "—"
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
        if QMessageBox.question(
            self,
            tr("trash_empty_btn"),
            tr("trash_empty_confirm"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) == QMessageBox.Yes:
            count = self.lib.empty_trash()
            QMessageBox.information(
                self, tr("trash_empty_btn"),
                tr("trash_empty_done").format(i18n.num(count)))
            self._reload()


class _CheckableHeader(QHeaderView):
    """Paints a native-style select-all checkbox inside column 0 of ExamPackDialog."""

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._state = Qt.Checked
        self.setSectionsClickable(True)

    def set_check_state(self, state: Qt.CheckState) -> None:
        if self._state != state:
            self._state = state
            self.viewport().update()

    def paintSection(self, painter, rect, logicalIndex: int) -> None:
        painter.save()
        super().paintSection(painter, rect, logicalIndex)
        painter.restore()
        if logicalIndex != 0 or not rect.isValid():
            return
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter, QPainterPath, QPen
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        sz = 16
        box = QRectF(
            rect.center().x() - sz / 2.0,
            rect.center().y() - sz / 2.0,
            sz, sz,
        )
        if self._state in (Qt.Checked, Qt.PartiallyChecked):
            painter.setBrush(QColor(theme.PALETTE["accent"]))
            painter.setPen(QPen(QColor(theme.PALETTE["accent"]), 1))
            painter.drawRoundedRect(box, 4, 4)
            pen = QPen(QColor(theme.PALETTE["on_accent"]), 2.0)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            if self._state == Qt.Checked:
                path = QPainterPath()
                path.moveTo(box.left() + 3.5, box.center().y() + 0.5)
                path.lineTo(box.center().x() - 1.0, box.bottom() - 3.8)
                path.lineTo(box.right() - 3.3, box.top() + 4.0)
                painter.drawPath(path)
            else:
                painter.drawLine(
                    int(box.left() + 4), int(box.center().y()),
                    int(box.right() - 4), int(box.center().y()),
                )
        else:
            painter.setBrush(QColor(theme.PALETTE["surface_2"]))
            painter.setPen(QPen(QColor(theme.PALETTE["border"]), 1.4))
            painter.drawRoundedRect(box, 4, 4)
        painter.restore()


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
        filter_card.setObjectName("BannerCard")
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

        headers = ["", tr("col_name"), tr("col_subject"), tr("col_kind"), tr("col_chapter"), tr("col_size")]
        self.table = QTableWidget(0, len(headers))
        self._chk_header = _CheckableHeader(self.table)
        self.table.setHorizontalHeader(self._chk_header)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(theme.METRICS["row_height"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.ClickFocus)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setItemDelegateForColumn(1, FileNameDelegate(self.table))
        self.table.setItemDelegateForColumn(3, KindBadgeDelegate(self.table))

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 42)
        header.sectionClicked.connect(self._on_header_clicked)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for col, width in ((2, 130), (3, 110), (4, 95), (5, 90)):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, width)
        name_align = Qt.AlignLeading | Qt.AlignVCenter
        for col in range(len(headers)):
            hi = self.table.horizontalHeaderItem(col)
            if hi is not None:
                hi.setTextAlignment(name_align if col == 1 else Qt.AlignCenter)
        self._scroller = enable_smooth_scroll(self.table)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("DialogHint")
        layout.addWidget(self.summary_label)

        btn_box = QHBoxLayout()
        self.btn_create = QPushButton(tr("exam_pack_btn_create"))
        self.btn_create.setObjectName("Primary")
        self.btn_create.clicked.connect(self._create_package)
        btn_box.addWidget(self.btn_create)

        btn_box.addStretch()
        btn_cancel = QPushButton(tr("cancel"))
        btn_cancel.setObjectName("Secondary")
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
            name_item.setToolTip(r["original_name"])
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

            if r["chapter"] is not None:
                pos_txt = persian_digits(str(r["chapter"]))
            elif r["lesson"] is not None:
                pos_txt = f"درس {persian_digits(str(r['lesson']))}"
            else:
                pos_txt = "—"
            chap_item = QTableWidgetItem(pos_txt)
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

    def _on_header_clicked(self, col: int) -> None:
        if col != 0 or self.table.rowCount() == 0:
            return
        all_checked = all(
            (self.table.item(r, 0).checkState() == Qt.Checked)
            for r in range(self.table.rowCount())
            if self.table.item(r, 0) is not None
        )
        new_state = Qt.Unchecked if all_checked else Qt.Checked
        self._updating = True
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is not None:
                it.setCheckState(new_state)
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
        if hasattr(self, "btn_create"):
            self.btn_create.setEnabled(bool(ids))
        total_rows = self.table.rowCount()
        if total_rows == 0 or len(ids) == 0:
            self._chk_header.set_check_state(Qt.Unchecked)
        elif len(ids) == total_rows:
            self._chk_header.set_check_state(Qt.Checked)
        else:
            self._chk_header.set_check_state(Qt.PartiallyChecked)

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
class WelcomeDialog(QDialog):
    """Interactive first-run welcome tour with 3 visual slides."""

    def __init__(self, parent=None, settings: dict | None = None, settings_path: Path | None = None):
        super().__init__(parent)
        self.settings = settings if settings is not None else {}
        self.settings_path = settings_path
        self.setWindowTitle(tr("welcome_title"))
        self.setModal(True)
        self.resize(600, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)
        try:
            from PySide6.QtSvgWidgets import QSvgWidget
            logo = QSvgWidget(str(asset_path("icon/darspack.svg")))
            logo.setFixedSize(40, 40)
            header_layout.addWidget(logo)
        except Exception:
            pass

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        title_lbl = QLabel(tr("welcome_title"))
        title_lbl.setObjectName("DialogTitle")
        sub_lbl = QLabel(tr("welcome_subtitle"))
        sub_lbl.setObjectName("DialogHint")
        title_layout.addWidget(title_lbl)
        title_layout.addWidget(sub_lbl)
        header_layout.addLayout(title_layout)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        self.stack = QStackedWidget()
        slides_data = [
            ("folder-open", tr("welcome_slide1_title"), tr("welcome_slide1_desc")),
            ("search", tr("welcome_slide2_title"), tr("welcome_slide2_desc")),
            ("share-2", tr("welcome_slide3_title"), tr("welcome_slide3_desc")),
        ]
        for icon_name, heading, desc in slides_data:
            slide_widget = QFrame()
            slide_widget.setObjectName("SlideCard")
            s_layout = QVBoxLayout(slide_widget)
            s_layout.setContentsMargins(28, 32, 28, 24)
            s_layout.setSpacing(14)

            badge_wrap = QFrame()
            badge_wrap.setObjectName("WelcomeIconBadge")
            badge_wrap.setFixedSize(76, 76)
            badge_wrap.setStyleSheet(
                "#WelcomeIconBadge { background: #242a38; border: 1px solid #354159; border-radius: 38px; } "
                "#WelcomeIconBadge QLabel { background: transparent; border: none; }"
            )
            bw_lay = QVBoxLayout(badge_wrap)
            bw_lay.setContentsMargins(0, 0, 0, 0)
            icon_lbl = QLabel()
            icon_lbl.setAlignment(Qt.AlignCenter)
            icon_lbl.setPixmap(icons.tinted_pixmap(icon_name, theme.PALETTE["accent"], 38))
            bw_lay.addWidget(icon_lbl)
            s_layout.addWidget(badge_wrap, 0, Qt.AlignHCenter)

            h_lbl = QLabel(heading)
            h_lbl.setObjectName("DialogTitle")
            h_lbl.setAlignment(Qt.AlignCenter)
            s_layout.addWidget(h_lbl, 0, Qt.AlignHCenter)

            d_lbl = QLabel(desc)
            d_lbl.setObjectName("DialogHint")
            d_lbl.setAlignment(Qt.AlignCenter)
            d_lbl.setWordWrap(True)
            d_lbl.setMinimumWidth(400)
            s_layout.addWidget(d_lbl)
            s_layout.addStretch()

            self.stack.addWidget(slide_widget)

        self.stack.currentChanged.connect(lambda _: self._update_slide_view())
        layout.addWidget(self.stack, 1)

        dots_row = QHBoxLayout()
        dots_row.setSpacing(6)
        dots_row.addStretch(1)
        self._step_dots = []
        for _ in slides_data:
            dot = QFrame()
            dot.setFixedHeight(6)
            dots_row.addWidget(dot)
            self._step_dots.append(dot)
        dots_row.addSpacing(8)
        self.indicator_lbl = QLabel()
        self.indicator_lbl.setObjectName("DialogHint")
        self.indicator_lbl.setAlignment(Qt.AlignCenter)
        dots_row.addWidget(self.indicator_lbl)
        dots_row.addStretch(1)
        layout.addLayout(dots_row)

        self.dont_show_check = QCheckBox(tr("welcome_dont_show"))
        self.dont_show_check.setChecked(True)
        layout.addWidget(self.dont_show_check)

        btn_bar = QHBoxLayout()
        self.btn_prev = QPushButton(tr("welcome_prev"))
        self.btn_prev.setObjectName("Secondary")
        self.btn_prev.clicked.connect(self._prev_slide)
        btn_bar.addWidget(self.btn_prev)

        btn_bar.addStretch()

        self.btn_next = QPushButton(tr("welcome_next"))
        self.btn_next.setObjectName("Primary")
        self.btn_next.clicked.connect(self._next_slide)
        btn_bar.addWidget(self.btn_next)

        layout.addLayout(btn_bar)

        self._update_slide_view()
        polish_dialog(self, 560)

    def _update_slide_view(self) -> None:
        idx = self.stack.currentIndex()
        count = self.stack.count()
        self.indicator_lbl.setText(
            tr("welcome_step").format(i18n.num(idx + 1), i18n.num(count)))
        for d_idx, dot in enumerate(getattr(self, "_step_dots", [])):
            is_cur = (d_idx == idx)
            dot.setFixedWidth(22 if is_cur else 6)
            color = theme.PALETTE["accent"] if is_cur else "#3c4659"
            dot.setStyleSheet(f"QFrame {{ background: {color}; border-radius: 3px; }}")
        self.btn_prev.setEnabled(idx > 0)
        if idx == count - 1:
            self.btn_next.setText(tr("welcome_start"))
        else:
            self.btn_next.setText(tr("welcome_next"))

    def _prev_slide(self) -> None:
        idx = self.stack.currentIndex()
        if idx > 0:
            self.stack.setCurrentIndex(idx - 1)
            self._update_slide_view()

    def _next_slide(self) -> None:
        idx = self.stack.currentIndex()
        if idx < self.stack.count() - 1:
            self.stack.setCurrentIndex(idx + 1)
            self._update_slide_view()
        else:
            self._finish()

    def _finish(self) -> None:
        if self.dont_show_check.isChecked():
            self.settings["show_welcome"] = False
            if self.settings_path:
                try:
                    self.settings_path.write_text(
                        json.dumps(self.settings, ensure_ascii=False, indent=2),
                        encoding="utf-8"
                    )
                except Exception:
                    pass
        self.accept()


class HelpDialog(QDialog):
    """Comprehensive offline in-app help center with tabs for quick guide, shortcuts, Wi-Fi phone sharing, and FAQ."""

    def __init__(self, parent=None, settings: dict | None = None, settings_path: Path | None = None):
        super().__init__(parent)
        self.settings = settings or {}
        self.settings_path = settings_path
        self.setWindowTitle(tr("help_dialog_title"))
        self.setMinimumSize(620, 460)
        self.resize(780, 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        top_bar = QHBoxLayout()
        title_lbl = QLabel(tr("help_dialog_title"))
        title_lbl.setObjectName("DialogTitle")
        top_bar.addWidget(title_lbl)
        top_bar.addStretch()

        btn_tour = QPushButton(tr("btn_tour"))
        btn_tour.setObjectName("Secondary")
        btn_tour.setIcon(icons.icon("compass", theme.PALETTE["text"], 16))
        btn_tour.clicked.connect(self._launch_tour)
        top_bar.addWidget(btn_tour)
        layout.addLayout(top_bar)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._make_scrollable(self._build_quick_tab()), tr("help_tab_quick"))
        self.tabs.addTab(self._build_shortcuts_tab(), tr("help_tab_shortcuts"))
        self.tabs.addTab(self._make_scrollable(self._build_phone_tab()), tr("help_tab_phone"))
        self.tabs.addTab(self._make_scrollable(self._build_mcp_tab()), tr("help_tab_mcp"))
        self.tabs.addTab(self._make_scrollable(self._build_faq_tab()), tr("help_tab_faq"))
        layout.addWidget(self.tabs, 1)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_close = QPushButton(tr("close"))
        btn_close.setObjectName("Secondary")
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)

        polish_dialog(self, 620)
        self._clamp_to_screen()

    def _make_scrollable(self, widget: QWidget) -> QScrollArea:
        """Wrap a tab content widget in a smooth-scrolling frameless QScrollArea."""
        scroll = QScrollArea()
        scroll.setObjectName("TabScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.viewport().setObjectName("TabScrollViewport")
        widget.setObjectName("TabScrollContent")
        enable_smooth_scroll(scroll)
        scroll.setWidget(widget)
        return scroll

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._clamp_to_screen()

    def _clamp_to_screen(self) -> None:
        """Keep the dialog well within the available screen area.

        If the dialog's default geometry would place it too close to (or
        below) the bottom edge, shrink it and re-position so there is always
        a comfortable breathing room (at least 48px) higher than the
        absolute bottom and taskbar.
        """
        from PySide6.QtWidgets import QApplication
        screen = None
        if self.parent():
            screen = self.parent().screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        margin = 48
        max_h = avail.height() - margin * 2
        if self.height() > max_h:
            self.resize(self.width(), max(360, max_h))
        # Center horizontally, and keep comfortably above the bottom edge
        geo = self.frameGeometry()
        geo.moveCenter(avail.center())
        if geo.bottom() > avail.bottom() - margin:
            geo.moveBottom(avail.bottom() - margin)
        if geo.top() < avail.top() + margin:
            geo.moveTop(avail.top() + margin)
        self.move(geo.topLeft())

    def _launch_tour(self) -> None:
        dlg = WelcomeDialog(self, self.settings, self.settings_path)
        dlg.exec()

    def _build_quick_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(8)

        intro = QLabel(f"<b>{tr('help_quick_title')}</b>")
        intro.setStyleSheet(f"QLabel {{ font-size: 13.5px; color: {theme.PALETTE['accent_text']}; }}")
        vbox.addWidget(intro)

        steps = [
            ("plus", tr("help_quick_step1")),
            ("file-text", tr("help_quick_step2")),
            ("search", tr("help_quick_step3")),
            ("share-2", tr("help_quick_step4")),
        ]
        for icon_name, text in steps:
            card = QFrame()
            card.setObjectName("StepCard")
            c_lay = QHBoxLayout(card)
            c_lay.setContentsMargins(14, 10, 14, 10)
            c_lay.setSpacing(12)

            ic = QLabel()
            ic.setPixmap(icons.tinted_pixmap(icon_name, theme.PALETTE["accent"], 20))
            c_lay.addWidget(ic)

            lbl = QLabel(text)
            lbl.setWordWrap(True)
            c_lay.addWidget(lbl, 1)

            vbox.addWidget(card)

        vbox.addStretch()
        return widget

    def _build_shortcuts_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(8)

        shortcuts = [
            ("Enter", tr("help_sc_open")),
            ("Ctrl + E", tr("help_sc_edit")),
            ("Delete", tr("help_sc_delete")),
            ("Ctrl + F", tr("help_sc_find")),
            ("Ctrl + O", tr("help_sc_import")),
            ("Esc", tr("help_sc_esc")),
            ("F1", tr("help_sc_f1")),
            ("F5", tr("help_sc_f5")),
        ]

        table = QTableWidget(len(shortcuts), 2)
        table.setHorizontalHeaderLabels([tr("help_col_key"), tr("help_col_action")])
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(44)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.setItemDelegateForColumn(0, KeycapDelegate(table))
        h_hdr = table.horizontalHeader()
        h_hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        table.setColumnWidth(0, 165)
        h_hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        enable_smooth_scroll(table)
        h_hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        action_align = Qt.AlignLeading | Qt.AlignVCenter
        if table.horizontalHeaderItem(0):
            table.horizontalHeaderItem(0).setTextAlignment(Qt.AlignCenter)
        if table.horizontalHeaderItem(1):
            table.horizontalHeaderItem(1).setTextAlignment(Qt.AlignLeading | Qt.AlignVCenter)

        key_font = QFont("Consolas", 10, QFont.Bold)
        key_brush = QBrush(QColor(theme.PALETTE["accent_text"]))
        for i, (k, action) in enumerate(shortcuts):
            k_item = QTableWidgetItem(k)
            k_item.setTextAlignment(Qt.AlignCenter)
            k_item.setFont(key_font)
            k_item.setForeground(key_brush)
            k_item.setFlags(Qt.ItemIsEnabled)
            table.setItem(i, 0, k_item)

            a_item = QTableWidgetItem(action)
            a_item.setTextAlignment(action_align)
            a_item.setFlags(Qt.ItemIsEnabled)
            table.setItem(i, 1, a_item)

        vbox.addWidget(table)
        return widget

    def _build_phone_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(12, 8, 12, 6)
        vbox.setSpacing(6)

        intro = QLabel(f"<b>{tr('help_phone_title')}</b>")
        intro.setStyleSheet(f"QLabel {{ font-size: 13.5px; color: {theme.PALETTE['accent_text']}; }}")
        intro.setWordWrap(True)
        vbox.addWidget(intro)

        phone_steps = [
            ("share-2", tr("help_phone_step1_t"), tr("help_phone_step1_d")),
            ("link", tr("help_phone_step2_t"), tr("help_phone_step2_d")),
            ("circle-check", tr("help_phone_step3_t"), tr("help_phone_step3_d")),
        ]
        for icon_name, title, desc in phone_steps:
            card = QFrame()
            card.setObjectName("StepCard")
            c_lay = QHBoxLayout(card)
            c_lay.setContentsMargins(12, 7, 12, 7)
            c_lay.setSpacing(10)

            ic = QLabel()
            ic.setPixmap(icons.tinted_pixmap(icon_name, theme.PALETTE["accent"], 20))
            ic.setAlignment(Qt.AlignTop)
            c_lay.addWidget(ic)

            txt = QVBoxLayout()
            txt.setSpacing(2)
            t_lbl = QLabel(f"<b>{title}</b>")
            t_lbl.setWordWrap(True)
            d_lbl = QLabel(desc)
            d_lbl.setObjectName("DialogHint")
            d_lbl.setWordWrap(True)
            txt.addWidget(t_lbl)
            txt.addWidget(d_lbl)
            c_lay.addLayout(txt, 1)
            vbox.addWidget(card)

        note_card = QFrame()
        note_card.setObjectName("InfoCallout")
        n_lay = QHBoxLayout(note_card)
        n_lay.setContentsMargins(12, 7, 12, 7)
        n_lay.setSpacing(10)
        n_ic = QLabel()
        n_ic.setPixmap(icons.tinted_pixmap("info", theme.PALETTE["accent"], 18))
        n_lay.addWidget(n_ic)
        n_lbl = QLabel(tr("help_phone_note"))
        n_lbl.setObjectName("DialogHint")
        n_lbl.setWordWrap(True)
        n_lay.addWidget(n_lbl, 1)
        vbox.addWidget(note_card)

        vbox.addStretch()
        return widget

    def _build_mcp_tab(self) -> QWidget:
        from ..mcp.launch import (
            build_mcp_config,
            config_json,
            resolve_launch,
        )
        from ..mcp.prompt import build_agent_prompt

        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(10)

        library_path = self.settings.get("library")
        self._mcp_launch = resolve_launch(library_path)
        self._mcp_prompt = build_agent_prompt(library_path)
        mcp_config = build_mcp_config(library_path)
        self._mcp_json_str = config_json(mcp_config)
        self._claude_cli_cmd = (
            f"claude mcp add darspack -- {self._mcp_launch.command_line()}"
        )
        self._opencode_cli_cmd = (
            f"opencode.cmd mcp add darspack -- {self._mcp_launch.command_line()}"
        )

        # 1. Overview Card
        intro_card = QFrame()
        intro_card.setObjectName("StepCard")
        intro_lay = QHBoxLayout(intro_card)
        intro_lay.setContentsMargins(14, 10, 14, 10)
        intro_lay.setSpacing(12)

        ic = QLabel()
        ic.setPixmap(icons.tinted_pixmap("sparkles", theme.PALETTE["accent"], 22))
        ic.setAlignment(Qt.AlignTop)
        intro_lay.addWidget(ic)

        text_box = QVBoxLayout()
        text_box.setSpacing(3)
        title_lbl = QLabel(f"<b>{tr('help_mcp_title')}</b>")
        title_lbl.setStyleSheet(f"QLabel {{ font-size: 13.5px; color: {theme.PALETTE['accent_text']}; }}")
        text_box.addWidget(title_lbl)

        desc_lbl = QLabel(tr("help_mcp_intro"))
        desc_lbl.setObjectName("DialogHint")
        desc_lbl.setWordWrap(True)
        text_box.addWidget(desc_lbl)
        intro_lay.addLayout(text_box, 1)
        vbox.addWidget(intro_card)

        headless_lbl = QLabel(tr("help_mcp_headless_note"))
        headless_lbl.setObjectName("DialogHint")
        headless_lbl.setWordWrap(True)
        vbox.addWidget(headless_lbl)

        if not self._mcp_launch.available:
            warn_lbl = QLabel(tr("help_mcp_unavailable"))
            warn_lbl.setWordWrap(True)
            warn_lbl.setStyleSheet(f"color: {theme.PALETTE['danger']};")
            vbox.addWidget(warn_lbl)

        # 2. 1-Click Agent Setup Card
        auto_card = QFrame()
        auto_card.setObjectName("StepCard")
        auto_lay = QVBoxLayout(auto_card)
        auto_lay.setContentsMargins(14, 12, 14, 12)
        auto_lay.setSpacing(8)

        step_heading = QLabel(f"<b>{tr('help_mcp_step_heading')}</b>")
        step_heading.setStyleSheet(f"QLabel {{ font-size: 13px; color: {theme.PALETTE['accent_text']}; }}")
        auto_lay.addWidget(step_heading)

        step_desc = QLabel(tr("help_mcp_step_desc"))
        step_desc.setWordWrap(True)
        auto_lay.addWidget(step_desc)

        btn_row = QHBoxLayout()
        self.btn_copy_mcp_prompt = QPushButton(tr("help_mcp_btn_copy"))
        self.btn_copy_mcp_prompt.setObjectName("Primary")
        self.btn_copy_mcp_prompt.setFixedHeight(36)
        self.btn_copy_mcp_prompt.setIcon(icons.icon("copy", theme.PALETTE["on_accent"], 16))
        self.btn_copy_mcp_prompt.setCursor(Qt.PointingHandCursor)

        def on_copy_prompt():
            cb = QApplication.clipboard()
            if cb:
                cb.setText(self._mcp_prompt)
            self.btn_copy_mcp_prompt.setText(tr("help_mcp_copied"))
            self.btn_copy_mcp_prompt.setIcon(icons.icon("check", theme.PALETTE["on_accent"], 16))
            QTimer.singleShot(2500, self, lambda: (
                self.btn_copy_mcp_prompt.setText(tr("help_mcp_btn_copy")),
                self.btn_copy_mcp_prompt.setIcon(icons.icon("copy", theme.PALETTE["on_accent"], 16))
            ))

        self.btn_copy_mcp_prompt.clicked.connect(on_copy_prompt)
        btn_row.addWidget(self.btn_copy_mcp_prompt)
        btn_row.addStretch()
        auto_lay.addLayout(btn_row)

        preview_lbl = QLabel(f"<small>{tr('help_mcp_prompt_preview')}</small>")
        preview_lbl.setObjectName("DialogHint")
        auto_lay.addWidget(preview_lbl)

        prompt_box = QTextEdit()
        prompt_box.setObjectName("McpCodeBox")
        prompt_box.setLayoutDirection(Qt.LeftToRight)
        prompt_box.setPlainText(self._mcp_prompt)
        prompt_box.setReadOnly(True)
        prompt_box.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        prompt_lines = self._mcp_prompt.count("\n") + 4
        prompt_box.setFixedHeight(max(210, min(320, prompt_lines * 19)))
        prompt_box.setStyleSheet(
            f"QTextEdit#McpCodeBox {{ background: #141720; color: {theme.PALETTE['text']}; "
            f"border: 1px solid #3a4457; border-radius: {theme.METRICS['radius']}px; "
            f"font-family: Consolas, 'Cascadia Code', monospace; font-size: 12px; padding: 12px; }}"
        )
        auto_lay.addWidget(prompt_box)
        vbox.addWidget(auto_card)

        # 3. Manual Configuration Card
        manual_card = QFrame()
        manual_card.setObjectName("StepCard")
        manual_lay = QVBoxLayout(manual_card)
        manual_lay.setContentsMargins(14, 12, 14, 12)
        manual_lay.setSpacing(8)

        man_heading = QLabel(f"<b>{tr('help_mcp_manual_heading')}</b>")
        manual_lay.addWidget(man_heading)

        def add_cli_row(heading_key: str, command: str) -> QPushButton:
            """One read-only command line plus its own copy button."""
            lbl = QLabel(f"<small>{tr(heading_key)}</small>")
            lbl.setObjectName("DialogHint")
            manual_lay.addWidget(lbl)

            row = QHBoxLayout()
            field = QLineEdit(command)
            field.setObjectName("McpCliInput")
            field.setLayoutDirection(Qt.LeftToRight)
            field.setReadOnly(True)
            field.setToolTip(command)
            field.setCursorPosition(0)
            field.setStyleSheet(
                f"QLineEdit#McpCliInput {{ background: #141720; color: {theme.PALETTE['text']}; "
                f"border: 1px solid #3a4457; border-radius: {theme.METRICS['radius']}px; "
                f"font-family: Consolas, monospace; font-size: 12px; padding: 6px 10px; }}"
            )
            row.addWidget(field, 1)

            btn = QPushButton()
            btn.setObjectName("Secondary")
            btn.setFixedSize(36, 36)
            btn.setToolTip("کپی دستور" if i18n.language() == "fa" else "Copy command")
            btn.setIcon(icons.icon("copy", theme.PALETTE["text"], 15))

            def on_copy():
                cb = QApplication.clipboard()
                if cb:
                    cb.setText(command)
                btn.setIcon(icons.icon("check", theme.PALETTE["success"], 15))
                QTimer.singleShot(
                    2500,
                    self,
                    lambda: btn.setIcon(icons.icon("copy", theme.PALETTE["text"], 15)),
                )

            btn.clicked.connect(on_copy)
            row.addWidget(btn)
            manual_lay.addLayout(row)
            return btn

        self.btn_copy_mcp_cli = add_cli_row("help_mcp_cli_heading", self._claude_cli_cmd)
        self.btn_copy_mcp_cli_opencode = add_cli_row(
            "help_mcp_cli_heading_opencode", self._opencode_cli_cmd
        )

        # JSON config
        json_lbl_row = QHBoxLayout()
        json_title = QLabel(f"<small>{tr('help_mcp_json_label')}</small>")
        json_title.setObjectName("DialogHint")
        json_lbl_row.addWidget(json_title)
        json_lbl_row.addStretch()

        self.btn_copy_mcp_json = QPushButton(tr("help_mcp_btn_copy_json"))
        self.btn_copy_mcp_json.setObjectName("Secondary")
        self.btn_copy_mcp_json.setIcon(icons.icon("copy", theme.PALETTE["text"], 14))

        def on_copy_json():
            cb = QApplication.clipboard()
            if cb:
                cb.setText(self._mcp_json_str)
            self.btn_copy_mcp_json.setText(tr("help_mcp_json_copied"))
            self.btn_copy_mcp_json.setIcon(icons.icon("check", theme.PALETTE["success"], 14))
            QTimer.singleShot(2500, self, lambda: (
                self.btn_copy_mcp_json.setText(tr("help_mcp_btn_copy_json")),
                self.btn_copy_mcp_json.setIcon(icons.icon("copy", theme.PALETTE["text"], 14))
            ))

        self.btn_copy_mcp_json.clicked.connect(on_copy_json)
        json_lbl_row.addWidget(self.btn_copy_mcp_json)
        manual_lay.addLayout(json_lbl_row)

        json_box = QTextEdit()
        json_box.setObjectName("McpJsonBox")
        json_box.setLayoutDirection(Qt.LeftToRight)
        json_box.setPlainText(self._mcp_json_str)
        json_box.setReadOnly(True)
        json_box.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        json_lines = self._mcp_json_str.count("\n") + 2
        json_box.setFixedHeight(max(150, min(260, json_lines * 19)))
        json_box.setStyleSheet(
            f"QTextEdit#McpJsonBox {{ background: #141720; color: {theme.PALETTE['text']}; "
            f"border: 1px solid #3a4457; border-radius: {theme.METRICS['radius']}px; "
            f"font-family: Consolas, monospace; font-size: 12px; padding: 12px; }}"
        )
        manual_lay.addWidget(json_box)
        vbox.addWidget(manual_card)

        vbox.addStretch()
        return widget

    def _build_faq_tab(self) -> QWidget:
        widget = QWidget()
        vbox = QVBoxLayout(widget)
        vbox.setContentsMargins(12, 10, 12, 8)
        vbox.setSpacing(8)

        faqs = [
            (tr("help_faq_q1"), tr("help_faq_a1")),
            (tr("help_faq_q2"), tr("help_faq_a2")),
            (tr("help_faq_q3"), tr("help_faq_a3")),
            (tr("help_faq_q4"), tr("help_faq_a4")),
        ]

        for q, a in faqs:
            card = QFrame()
            card.setObjectName("StepCard")
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(14, 10, 14, 10)
            c_lay.setSpacing(4)

            q_lbl = QLabel(f"<b>{q}</b>")
            q_lbl.setStyleSheet(f"QLabel {{ font-size: 13px; color: {theme.PALETTE['accent_text']}; }}")
            q_lbl.setWordWrap(True)
            c_lay.addWidget(q_lbl)

            a_lbl = QLabel(a)
            a_lbl.setWordWrap(True)
            c_lay.addWidget(a_lbl)

            vbox.addWidget(card)

        vbox.addStretch()
        return widget

