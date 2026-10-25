"""Main window (پنجره‌ی اصلی): search, filters, catalog table, actions.

Layout mirrors how a student thinks: a search box + subject/kind filters
on top, the file table in the middle, and action buttons below. The
whole catalog is read through core.search(), so the window never builds
SQL itself. Heavy work (import, package import) runs in workers.
"""
from __future__ import annotations

import datetime as _dt
import os
import subprocess
import sys
from pathlib import Path

import jdatetime
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QStatusBar, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__, i18n
from ..core.dedup import duplicate_groups, rename_hints, version_conflicts
from ..core.search import search as catalog_search
from ..core.search import unclassified_count
from ..core import manifest as manifest_core
from ..i18n import tr
from ..web.server import ShareServer
from . import dialogs
from .workers import ImportWorker

KINDS = ["جزوه", "نمونه‌سوال", "کاربرگ", "تکلیف", "سایر"]


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n} B"


def jalali_date(iso: str) -> str:
    # imported_at is stored as a GREGORIAN isoformat string, so it must be
    # parsed by the stdlib first and then converted — parsing it directly
    # with jdatetime used to read the digits as a Jalali date and pass the
    # Gregorian components through unchanged (۲۰۲۶/۱۰/۲۴ shown as if Jalali).
    try:
        gregorian = _dt.datetime.fromisoformat(iso)
        return jdatetime.datetime.fromgregorian(
            datetime=gregorian).strftime("%Y/%m/%d")
    except ValueError:
        return iso          # bad input never crashes the table — passes through


class MainWindow(QMainWindow):
    def __init__(self, library_root: Path, settings: dict, settings_path: Path):
        super().__init__()
        from ..core.library import Library
        self.settings = settings
        self.settings_path = settings_path
        self.lib = Library(library_root).open()
        self.share_server: ShareServer | None = None
        self.last_rows: list = []
        # Perf audit F2.4: (Jalali date, size) strings per file id — a
        # row's date never changes, re-formatting it on every keystroke
        # was the single most expensive part of the refresh fill.
        self._display_strs: dict = {}

        self.setWindowTitle(f"{tr('app_title')} — {library_root}")
        self.resize(1000, 640)

        # --- top row: search + filters -------------------------------
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(tr("search_placeholder"))
        self.search_box.setClearButtonEnabled(True)
        # C3 (perf audit F2.1): typing re-triggers the countdown instead of
        # refreshing per keystroke — fast typing costs exactly one refresh.
        # Filter combos stay connected to refresh directly (immediate).
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self.refresh)
        self.search_box.textChanged.connect(self._search_changed)

        self.subject_combo = QComboBox()
        self.kind_combo = QComboBox()
        self.year_combo = QComboBox()
        self.subject_combo.currentIndexChanged.connect(self.refresh)
        self.kind_combo.currentIndexChanged.connect(self.refresh)
        self.year_combo.currentIndexChanged.connect(self.refresh)

        top = QHBoxLayout()
        top.addWidget(self.search_box, 3)
        top.addWidget(self.subject_combo, 1)
        top.addWidget(self.kind_combo, 1)
        top.addWidget(self.year_combo, 1)

        # --- center: catalog table -----------------------------------
        columns = [tr("col_name"), tr("col_subject"), tr("col_chapter"),
                   tr("col_kind"), tr("col_size"), tr("col_date"),
                   tr("col_year")]
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 420)
        self.table.doubleClicked.connect(self.open_selected_file)

        # E2: empty states — a fresh library and an empty search each get
        # one sentence instead of a silent blank table. The label lives on
        # the table's viewport so refresh() can show/hide it in place.
        self.empty_label = QLabel(self.table.viewport())
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet("color: #a0a0a8; font-size: 14px;")
        self.empty_label.hide()

        # --- bottom: action buttons ----------------------------------
        buttons = QHBoxLayout()
        for text, handler in [
                (tr("btn_import"), self.open_import_dialog),
                (tr("btn_export"), self.export_package),
                (tr("btn_verify"), self.verify_package),
                (tr("btn_import_pkg"), self.import_package),
                (tr("btn_dups"), self.show_duplicates),
                (tr("btn_edit_meta"), self.edit_metadata),
                (tr("btn_share"), self.toggle_share),
                (tr("btn_feedback"), lambda: dialogs.feedback_dialog(self)),
                (tr("btn_help"), lambda: dialogs.text_dialog(
                    self, tr("btn_help"), tr("help_text"))),
                (tr("btn_about"), lambda: dialogs.text_dialog(
                    self, tr("btn_about"),
                    tr("about_text").format(__version__))),
                (tr("btn_settings"), self.open_settings)]:
            btn = QPushButton(text)
            btn.clicked.connect(handler)
            buttons.addWidget(btn)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self.reload_filters()
        self.refresh()

    # ---- catalog view -------------------------------------------------

    def reload_filters(self) -> None:
        self.subject_combo.blockSignals(True)
        self.kind_combo.blockSignals(True)
        self.year_combo.blockSignals(True)
        self.subject_combo.clear()
        self.subject_combo.addItem(tr("all_subjects"), None)
        self.subject_combo.addItem(tr("unclassified"), -1)  # files missing info
        for row in self.lib.conn.execute(
                "SELECT id, name FROM subjects ORDER BY name"):
            self.subject_combo.addItem(row["name"], row["id"])
        self.kind_combo.clear()
        self.kind_combo.addItem(tr("all_kinds"), None)
        for kind in KINDS:
            self.kind_combo.addItem(kind, kind)
        self.year_combo.clear()
        self.year_combo.addItem(tr("all_years"), None)
        from ..core.normalize import persian_digits
        years = sorted({r["school_year"] for r in self.lib.conn.execute(
            "SELECT DISTINCT school_year FROM files WHERE school_year IS NOT NULL")},
            reverse=True)
        for y in years:
            self.year_combo.addItem(persian_digits(y), y)
        self.subject_combo.blockSignals(False)
        self.kind_combo.blockSignals(False)
        self.year_combo.blockSignals(False)

    def _year_map(self) -> dict:
        """{file id: school_year} for the «سال» column and filter.

        search() rows don't carry school_year yet (the core-side
        `school_year=` filter parameter is pending — tracked for later), so
        the year is read directly, the same way reload_filters reads the
        subjects table.
        """
        return {r["id"]: r["school_year"] for r in self.lib.conn.execute(
            "SELECT id, school_year FROM files")}

    def _search_changed(self) -> None:
        self._search_timer.start()      # restart the countdown per keystroke

    def _display_strs_for(self, row) -> tuple:
        """Cached (Jalali date, human size) for one file id (perf F2.4)."""
        cached = self._display_strs.get(row["id"])
        if cached is None:
            cached = (jalali_date(row["imported_at"]),
                      human_size(row["size_bytes"]))
            self._display_strs[row["id"]] = cached
        return cached

    def refresh(self) -> None:
        subject_data = self.subject_combo.currentData()
        rows = catalog_search(
            self.lib.conn,
            self.search_box.text(),
            subject_id=subject_data if isinstance(subject_data, int) and subject_data > 0 else None,
            kind=self.kind_combo.currentData(),
            unclassified_only=(subject_data == -1),
            limit=2000)
        year_map = self._year_map()
        year = self.year_combo.currentData()
        if year is not None:            # school-year filter (A3)
            rows = [r for r in rows if year_map.get(r["id"]) == year]
        self.last_rows = rows
        # Perf audit F2.2–F2.3: this fill runs on every debounced keystroke,
        # so mid-fill repaints are off and only column 0 carries the file id
        # (selected_file_id reads selectedItems()[0]; selection is row-wide).
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        from ..core.normalize import persian_digits
        for i, row in enumerate(rows):
            date_str, size_str = self._display_strs_for(row)
            chapter = persian_digits(str(row["chapter"])) if row["chapter"] else "—"
            year = year_map.get(row["id"]) or "—"
            values = [row["original_name"], row["subject_name"] or "—", chapter,
                      row["kind"] or "—", size_str,
                      persian_digits(date_str), persian_digits(year)]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.UserRole, row["id"])
                self.table.setItem(i, col, item)
        self.table.setUpdatesEnabled(True)
        self._update_empty_state(len(rows))
        unclassified = unclassified_count(self.lib.conn)   # F6: computed once
        self.statusBar().showMessage(
            tr("status_files").format(len(rows))
            + ("  ·  " + tr("status_unclassified").format(unclassified)
               if unclassified else ""))

    def _update_empty_state(self, shown: int) -> None:
        """E2: hide the hint when rows exist; otherwise pick the right
        message — a fresh library vs a search that found nothing."""
        if shown:
            self.empty_label.hide()
            return
        total = self.lib.conn.execute(
            "SELECT COUNT(*) c FROM files").fetchone()["c"]
        self.empty_label.setText(
            tr("empty_library") if total == 0 else tr("empty_search"))
        self._center_empty_label()
        self.empty_label.show()

    def _center_empty_label(self) -> None:
        vp = self.table.viewport()
        self.empty_label.adjustSize()
        self.empty_label.move(max(8, (vp.width() - self.empty_label.width()) // 2),
                              max(8, (vp.height() - self.empty_label.height()) // 2))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self.empty_label.isHidden():
            self._center_empty_label()

    def selected_file_id(self) -> int | None:
        selected = self.table.selectedItems()
        if not selected:
            QMessageBox.information(self, APP_NAME, tr("err_no_selection"))
            return None
        return selected[0].data(Qt.UserRole)

    def open_selected_file(self) -> None:
        """Double-click: open the file with the OS default app (PDF viewer…)."""
        file_id = self.selected_file_id()
        if file_id is None:
            return
        row = self.lib.conn.execute(
            "SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        QDesktopServices.openUrl(QUrl.fromLocalFile(
            str(self.lib.stored_path(row))))

    # ---- actions ------------------------------------------------------

    def open_import_dialog(self) -> None:
        dialogs.ImportDialog(self).exec()

    def run_import_worker(self, paths: list, keep_duplicates: bool = False,
                          **kwargs) -> None:
        # kwargs (A5): metas/meta_base/cleanup_dir for a درس‌پک import
        self._worker = ImportWorker(
            str(self.lib.root), paths, keep_duplicates, **kwargs)
        self._worker.progress.connect(
            lambda d, t, name: self.statusBar().showMessage(
                tr("import_running").format(d, t, name)))
        self._worker.done.connect(self._import_finished)
        self._worker.start()

    def _import_finished(self, imported, duplicates, errors, messages,
                         new_ids) -> None:
        self.reload_filters()
        self.refresh()
        # Categorizing is the app's main job — ask for the new files' info
        # right away, pre-filled with the filename suggestions (and, for a
        # درس‌پک import, the manifest's subject/tags as pre-fill — A5).
        if new_ids:
            prefills = getattr(self._worker, "result_prefills", {})
            dialogs.ClassifyDialog(self, self.lib, new_ids,
                                   prefills=prefills).exec()
            self.reload_filters()
            self.refresh()
        text = tr("import_done").format(imported, duplicates, errors)
        if messages:
            text += "\n" + "\n".join(messages[:5])
        QMessageBox.information(self, APP_NAME, text)

    def export_package(self) -> None:
        selected_scope = [r["id"] for r in self._selected_rows()]
        dialogs.ExportDialog(self, selected_scope).exec()

    def _selected_rows(self) -> list:
        ids = set()
        for item in self.table.selectedItems():
            fid = item.data(Qt.UserRole)
            if fid is not None:    # only column 0 carries the id (perf F2.2)
                ids.add(fid)
        return [r for r in self.last_rows if r["id"] in ids]

    def verify_package(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("verify_pick"), "", "ZIP (*.zip)")
        if not path:
            return
        report = manifest_core.verify_package(path)
        dialogs.VerifyReportDialog(self, path, report, library=self.lib).exec()

    def import_package(self) -> None:
        """Open a درس‌پک, verify it, offer to import its contents."""
        path, _ = QFileDialog.getOpenFileName(
            self, tr("verify_pick"), "", "ZIP (*.zip)")
        if not path:
            return
        report = manifest_core.verify_package(path)
        dialogs.VerifyReportDialog(self, path, report, library=self.lib,
                                   offer_import=True).exec()

    def show_duplicates(self) -> None:
        dialogs.DuplicatesDialog(self, {
            tr("dups_tab1"): duplicate_groups(self.lib.conn),
            tr("dups_tab2"): version_conflicts(self.lib.conn),
            tr("dups_tab3"): rename_hints(self.lib.conn),
        }).exec()

    def edit_metadata(self) -> None:
        file_id = self.selected_file_id()
        if file_id is None:
            return
        if dialogs.MetadataDialog(self, self.lib, file_id).exec():
            self.reload_filters()
            self.refresh()

    def open_settings(self) -> None:
        if dialogs.SettingsDialog(self, self.settings,
                                  self.settings_path).exec():
            from .app import apply_font_size
            apply_font_size(self.settings)

    # ---- LAN sharing ----------------------------------------------------

    def toggle_share(self) -> None:
        if self.share_server is None:
            self.share_server = ShareServer(str(self.lib.root))
            try:
                urls = self.share_server.start()
            except OSError as exc:
                QMessageBox.critical(self, APP_NAME, str(exc))
                self.share_server = None
                return
            from ..core import db
            db.log(self.lib.conn, "share_start",
                   f"port={self.share_server.port}")
            # The dialog stays open while sharing; whatever closes it
            # (stop button, X) ends the server right after.
            dialogs.ShareDialog(self, self.share_server, urls,
                                on_close=self.stop_share).exec()
            self.stop_share()
        else:
            self.stop_share()

    def stop_share(self) -> None:
        if self.share_server is not None:
            from ..core import db
            db.log(self.lib.conn, "share_stop", "")
            self.share_server.stop()
            self.share_server = None
            self.refresh()

    def closeEvent(self, event) -> None:
        self.stop_share()          # never leave the server thread running
        self.lib.close()
        super().closeEvent(event)
