"""Main window (پنجره‌ی اصلی): search, filters, catalog table, actions.

Layout mirrors how a student thinks: a search box + subject/kind filters
on top, the file table in the middle, and action buttons below. The
whole catalog is read through core.search(), so the window never builds
SQL itself. Heavy work (import, package import) runs in workers.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import jdatetime
from PySide6.QtCore import Qt, QUrl
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
    try:
        return jdatetime.datetime.fromisoformat(iso).strftime("%Y/%m/%d")
    except ValueError:
        return iso


class MainWindow(QMainWindow):
    def __init__(self, library_root: Path, settings: dict, settings_path: Path):
        super().__init__()
        from ..core.library import Library
        self.settings = settings
        self.settings_path = settings_path
        self.lib = Library(library_root).open()
        self.share_server: ShareServer | None = None
        self.last_rows: list = []

        self.setWindowTitle(f"{tr('app_title')} — {library_root}")
        self.resize(1000, 640)

        # --- top row: search + filters -------------------------------
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(tr("search_placeholder"))
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self.refresh)

        self.subject_combo = QComboBox()
        self.kind_combo = QComboBox()
        self.subject_combo.currentIndexChanged.connect(self.refresh)
        self.kind_combo.currentIndexChanged.connect(self.refresh)

        top = QHBoxLayout()
        top.addWidget(self.search_box, 3)
        top.addWidget(self.subject_combo, 1)
        top.addWidget(self.kind_combo, 1)

        # --- center: catalog table -----------------------------------
        columns = [tr("col_name"), tr("col_subject"), tr("col_chapter"),
                   tr("col_kind"), tr("col_size"), tr("col_date")]
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 420)
        self.table.doubleClicked.connect(self.open_selected_file)

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
                (tr("btn_feedback"), dialogs.feedback_dialog),
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
        self.subject_combo.blockSignals(False)
        self.kind_combo.blockSignals(False)

    def refresh(self) -> None:
        subject_data = self.subject_combo.currentData()
        rows = catalog_search(
            self.lib.conn,
            self.search_box.text(),
            subject_id=subject_data if isinstance(subject_data, int) and subject_data > 0 else None,
            kind=self.kind_combo.currentData(),
            unclassified_only=(subject_data == -1),
            limit=2000)
        self.last_rows = rows
        self.table.setRowCount(len(rows))
        from ..core.normalize import persian_digits
        for i, row in enumerate(rows):
            chapter = persian_digits(str(row["chapter"])) if row["chapter"] else "—"
            values = [row["original_name"], row["subject_name"] or "—", chapter,
                      row["kind"] or "—", human_size(row["size_bytes"]),
                      persian_digits(jalali_date(row["imported_at"]))]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row["id"])
                self.table.setItem(i, col, item)
        self.statusBar().showMessage(
            tr("status_files").format(len(rows))
            + ("  ·  " + tr("status_unclassified").format(
                unclassified_count(self.lib.conn))
               if unclassified_count(self.lib.conn) else ""))

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

    def run_import_worker(self, paths: list, keep_duplicates: bool = False) -> None:
        self._worker = ImportWorker(
            str(self.lib.root), paths, keep_duplicates)
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
        # right away, pre-filled with the filename suggestions.
        if new_ids:
            dialogs.ClassifyDialog(self, self.lib, new_ids).exec()
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
        ids = {item.data(Qt.UserRole) for item in self.table.selectedItems()}
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
