"""Main window (پنجره‌ی اصلی): search, filters, catalog table, actions.

Layout mirrors how a student thinks: a search box + subject/kind filters
on top, the file table in the middle, and action buttons below. The
whole catalog is read through core.search(), so the window never builds
SQL itself. Heavy work (import, package import) runs in workers.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QApplication,
    QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
    QStatusBar, QTableWidget, QTableWidgetItem, QToolButton, QToolTip,
    QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__, asset_path, i18n
from ..core.dedup import duplicate_groups, rename_hints, version_conflicts
from ..core.search import search as catalog_search
from ..core.search import unclassified_count
from ..core import manifest as manifest_core
from ..i18n import tr
from . import dialogs, icons, theme
from .delegates import KindBadgeDelegate
from .smooth_scroll import enable_smooth_scroll
from .workers import ImportWorker

if TYPE_CHECKING:      # F4 (perf audit): ShareServer pulls http/ssl/email —
    from ..web.server import ShareServer   # only needed when sharing starts

KINDS = ["جزوه", "نمونه‌سوال", "کاربرگ", "تکلیف", "سایر"]


def human_size(n: int, lang: str | None = None) -> str:
    """Bytes → a human size in the UI language («۱٫۵ کیلوبایت», «1.5 KB»)."""
    lang = lang or i18n.language()
    for unit, key in (("B", "unit_b"), ("KB", "unit_kb"),
                      ("MB", "unit_mb"), ("GB", "unit_gb")):
        if n < 1024 or unit == "GB":
            text = (str(int(n)) if unit == "B"
                    else f"{n:.1f}".rstrip("0").rstrip("."))
            if lang == "fa":
                text = text.replace(".", "٫")
            return f"{i18n.num(text, lang)} {tr(key, lang)}"
        n /= 1024
    return f"{i18n.num(n, lang)} {tr('unit_b', lang)}"


def chapter_lesson_display(chapter, lesson) -> str:
    """One table cell for the book position: «فصل ۳»، «درس ۵»، both, or —.

    The catalog keeps chapter (فصل) and lesson (درس) as separate optional
    columns (either, both, or neither may be set), so the table merges
    them into one readable cell instead of two mostly-empty columns.
    """
    from ..core.normalize import persian_digits
    parts = []
    if chapter:
        parts.append("فصل " + persian_digits(str(chapter)))
    if lesson:
        parts.append("درس " + persian_digits(str(lesson)))
    return " / ".join(parts) if parts else "—"


def jalali_date(iso: str) -> str:
    # F4 (perf audit): jdatetime costs ~200 ms of import time, but rows
    # need it only when the table fills — deferring it past window show
    # speeds up source runs (Python caches the module after first call).
    import jdatetime
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


class TableSortItem(QTableWidgetItem):
    """QTableWidgetItem with support for logical sort keys stored in SORT_KEY_ROLE."""
    SORT_KEY_ROLE = Qt.UserRole + 1

    def __lt__(self, other: object) -> bool:
        if isinstance(other, QTableWidgetItem):
            my_key = self.data(self.SORT_KEY_ROLE)
            other_key = other.data(self.SORT_KEY_ROLE)
            if my_key is not None and other_key is not None:
                try:
                    return my_key < other_key
                except TypeError:
                    pass
        return super().__lt__(other)


_STD_ACTION_KEYS: dict[str, tuple[str, str]] = {
    "undo": ("menu_undo", "Ctrl+Z"),
    "redo": ("menu_redo", "Ctrl+Y"),
    "cut": ("menu_cut", "Ctrl+X"),
    "copy": ("menu_copy", "Ctrl+C"),
    "paste": ("menu_paste", "Ctrl+V"),
    "delete": ("menu_delete", "Del"),
    "select all": ("menu_select_all", "Ctrl+A"),
}


def create_localized_line_edit_context_menu(
    edit: QLineEdit,
    parent: QWidget | None = None,
    include_clear: bool = False,
) -> QMenu:
    """Create a localized, clutter-free context menu for a QLineEdit.

    Translates standard action labels into the active language, formats
    shortcuts cleanly, removes unwanted platform submenus (like 'Insert Unicode
    control character'), strips redundant separators, and optionally adds a
    'Clear search' action if the field contains text.
    """
    menu = edit.createStandardContextMenu()
    if parent is not None:
        menu.setParent(parent)

    for action in list(menu.actions()):
        if action.menu():
            # Remove platform submenus such as "Insert Unicode control character"
            menu.removeAction(action)
            continue
        if action.isSeparator():
            continue
        raw_text = action.text().replace("&", "")
        parts = raw_text.split("\t")
        keyword = parts[0].strip().lower()
        if keyword in _STD_ACTION_KEYS:
            trans_key, default_shortcut = _STD_ACTION_KEYS[keyword]
            shortcut = parts[1].strip() if len(parts) > 1 else default_shortcut
            localized = tr(trans_key)
            action.setText(f"{localized}\t{shortcut}" if shortcut else localized)

    # Clean up consecutive separators
    prev_sep = False
    for action in list(menu.actions()):
        if action.isSeparator():
            if prev_sep:
                menu.removeAction(action)
            else:
                prev_sep = True
        else:
            prev_sep = False

    # Strip trailing separators
    while menu.actions() and menu.actions()[-1].isSeparator():
        menu.removeAction(menu.actions()[-1])

    if include_clear and bool(edit.text()):
        menu.addSeparator()
        clear_act = menu.addAction(tr("clear_search"))
        clear_act.setIcon(icons.icon("x", theme.PALETTE["muted"], 16))
        clear_act.triggered.connect(edit.clear)

    return menu


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

        self.setWindowTitle(tr("app_title"))
        self.resize(1150, 720)
        self.setMinimumSize(1000, 600)
        self._file_icon = icons.icon("file-text", theme.PALETTE["muted"], 16)
        self._pdf_icon = icons.icon("file-text", theme.PALETTE["accent"], 16)
        self._archive_icon = icons.icon("archive", theme.PALETTE["muted"], 16)
        self._package_icon = icons.icon("package", theme.PALETTE["accent"], 16)

        # --- search + filter state -----------------------------------
        # A shell puts the magnifier on the leading (right) edge in RTL,
        # inside the field's rounded border — QLineEdit actions sit on the
        # physical left and looked misplaced next to right-aligned text.
        self.search_shell = QFrame()
        self.search_shell.setObjectName("SearchShell")
        self.search_shell.setFixedWidth(350)
        self.search_shell.setFixedHeight(38)
        shell = QHBoxLayout(self.search_shell)
        shell.setContentsMargins(10, 0, 6, 0)
        shell.setSpacing(6)
        search_icon = QLabel()
        search_icon.setPixmap(
            icons.tinted_pixmap("search", theme.PALETTE["muted"], 18))
        search_icon.setFixedSize(18, 18)
        search_icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        shell.addWidget(search_icon)
        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchField")
        self.search_box.setPlaceholderText(tr("search_placeholder"))
        self.search_box.setContextMenuPolicy(Qt.CustomContextMenu)
        self.search_box.customContextMenuRequested.connect(
            self._show_search_context_menu)
        shell.addWidget(self.search_box, 1)
        self.clear_search_button = QToolButton()
        self.clear_search_button.setObjectName("SearchClear")
        self.clear_search_button.setIcon(
            icons.icon("x", theme.PALETTE["muted"], 14))
        self.clear_search_button.setIconSize(QSize(14, 14))
        self.clear_search_button.setFixedSize(24, 24)
        self.clear_search_button.setToolTip(tr("clear_search"))
        self.clear_search_button.setCursor(Qt.PointingHandCursor)
        self.clear_search_button.clicked.connect(self.search_box.clear)
        self.clear_search_button.hide()
        shell.addWidget(self.clear_search_button)
        self.search_box.textChanged.connect(self._update_clear_button)
        self.search_box.installEventFilter(self)
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
        for combo, width in ((self.subject_combo, 150),
                             (self.kind_combo, 130),
                             (self.year_combo, 120)):
            combo.setFixedWidth(width)
            combo.setFixedHeight(36)
        self.subject_combo.currentIndexChanged.connect(self.refresh)
        self.kind_combo.currentIndexChanged.connect(self.refresh)
        self.year_combo.currentIndexChanged.connect(self.refresh)

        # --- app bar: brand + search + one primary action -------------
        app_bar = QWidget()
        app_bar.setObjectName("AppBar")
        bar = QHBoxLayout(app_bar)
        bar.setContentsMargins(16, 10, 16, 10)
        bar.setSpacing(12)

        brand = QSvgWidget(str(asset_path("icon/darspack.svg")))
        brand.setFixedSize(34, 34)
        bar.addWidget(brand)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel(tr("app_title"))
        title.setObjectName("BrandTitle")
        subtitle = QLabel(tr("app_subtitle"))
        subtitle.setObjectName("BrandSub")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        bar.addLayout(titles)
        bar.addStretch(1)
        bar.addWidget(self.search_shell)
        self.import_button = QPushButton(tr("btn_import"))
        self.import_button.setObjectName("Primary")
        self.import_button.setIcon(
            icons.icon("plus", theme.PALETTE["on_accent"], 18))
        self.import_button.setIconSize(QSize(18, 18))
        self.import_button.setFixedHeight(38)
        self.import_button.clicked.connect(self.open_import_dialog)
        bar.addWidget(self.import_button)

        # --- secondary bar: grouped actions + filters -----------------
        filter_bar = QWidget()
        filter_bar.setObjectName("FilterBar")
        toolbar = QHBoxLayout(filter_bar)
        toolbar.setContentsMargins(16, 8, 16, 8)
        toolbar.setSpacing(8)

        self.packages_menu = QMenu(self)
        self._menu_action(self.packages_menu, tr("btn_export"), "download",
                          self.export_package)
        self._menu_action(self.packages_menu, tr("btn_exam_pack"), "package",
                          self.open_exam_pack_dialog)
        self._menu_action(self.packages_menu, tr("btn_verify"), "circle-check",
                          self.verify_package)
        self._menu_action(self.packages_menu, tr("btn_import_pkg"),
                          "folder-open", self.import_package)
        self.packages_button = self._tool_button(tr("btn_packages"),
                                                 "package")
        self.packages_button.setPopupMode(QToolButton.InstantPopup)
        self.packages_button.setMenu(self.packages_menu)
        toolbar.addWidget(self.packages_button)

        self.duplicates_button = self._tool_button(tr("btn_dups"), "copy")
        self.duplicates_button.clicked.connect(self.show_duplicates)
        toolbar.addWidget(self.duplicates_button)

        self.share_button = self._tool_button(tr("btn_share"), "share-2")
        self.share_button.clicked.connect(self.toggle_share)
        toolbar.addWidget(self.share_button)

        self.help_button = self._tool_button(tr("btn_help"), "circle-help")
        self.help_button.clicked.connect(self.open_help_dialog)
        toolbar.addWidget(self.help_button)

        self.more_menu = QMenu(self)
        self.more_menu.setMinimumWidth(220)
        self.edit_action = self._menu_action(
            self.more_menu, tr("btn_edit_meta"), "file-text", self.edit_metadata)
        self.delete_action = self._menu_action(
            self.more_menu, tr("btn_delete"), "trash-2",
            self.delete_selected_files)
        self.edit_action.setEnabled(False)
        self._menu_action(self.more_menu, tr("btn_trash_bin"), "trash-2",
                          self.open_trash_dialog)
        self.delete_action.setEnabled(False)
        self.more_menu.addSeparator()
        self._menu_action(self.more_menu, tr("btn_history"), "history",
                          self.show_history)
        self._menu_action(self.more_menu, tr("btn_stats"), "chart-column",
                          self.show_stats)
        self.more_menu.addSeparator()
        self._menu_action(
            self.more_menu, tr("btn_feedback"), "message-square",
            lambda: dialogs.FeedbackDialog(self, self.settings).exec())
        self._menu_action(self.more_menu, tr("btn_tour"), "history",
                          self.open_welcome_tour)
        self._menu_action(self.more_menu, tr("btn_help"), "circle-help",
                          self.open_help_dialog)
        self._menu_action(
            self.more_menu, tr("btn_about"), "info",
            lambda: dialogs.text_dialog(
                self, tr("btn_about"),
                tr("about_text").format(__version__)))
        self._menu_action(self.more_menu, tr("btn_settings"), "settings",
                          self.open_settings)
        self.more_button = QToolButton()
        self.more_button.setObjectName("IconGhost")
        self.more_button.setIcon(
            icons.icon("ellipsis-vertical", theme.PALETTE["muted"], 18))
        self.more_button.setIconSize(QSize(18, 18))
        self.more_button.setToolTip(tr("more_actions"))
        self.more_button.setFixedSize(36, 36)
        self.more_button.setPopupMode(QToolButton.InstantPopup)
        self.more_button.setMenu(self.more_menu)
        toolbar.addWidget(self.more_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.subject_combo)
        toolbar.addWidget(self.kind_combo)
        toolbar.addWidget(self.year_combo)

        # --- center: catalog table -----------------------------------
        columns = [tr("col_name"), tr("col_subject"), tr("col_chapter_lesson"),
                   tr("col_kind"), tr("col_size"), tr("col_date"),
                   tr("col_year")]
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        # multi-select (Ctrl/Shift) feeds the bulk actions below
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setMouseTracking(True)
        self.table.setIconSize(QSize(16, 16))
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(
            theme.METRICS["row_height"])
        self.table.setItemDelegateForColumn(
            3, KindBadgeDelegate(self.table))
        # Stretch the NAME column. setStretchLastSection stretched
        # «سال» (the last logical column in RTL), which squeezed «درس» into
        # «مطالعات ...» while the name stayed fixed at 420 px.
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(80)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 150), (2, 150), (3, 110),
                           (4, 100), (5, 120), (6, 100)):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, width)
        self._sort_orders: dict[int, Qt.SortOrder] = {}
        header.sectionClicked.connect(self._on_header_clicked)
        self.table.doubleClicked.connect(self.open_selected_file)
        # E3: right-click a row → «حذف از کتابخانه…» (confirmed, and the
        # file is MOVED to files/.trash — never erased)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_row_menu)
        # Drag & Drop support on window and table
        self.setAcceptDrops(True)
        self.table.setAcceptDrops(True)
        self.table.viewport().setAcceptDrops(True)
        self.table.installEventFilter(self)
        self._scroller = enable_smooth_scroll(self.table)

        # Table shortcuts
        self.delete_shortcut = QShortcut(QKeySequence.Delete, self.table)
        self.delete_shortcut.setContext(Qt.WidgetShortcut)
        self.delete_shortcut.activated.connect(self.delete_selected_files)

        self.enter_shortcut = QShortcut(QKeySequence(Qt.Key_Return), self.table)
        self.enter_shortcut.setContext(Qt.WidgetShortcut)
        self.enter_shortcut.activated.connect(self.open_selected_file)

        self.enter_shortcut2 = QShortcut(QKeySequence(Qt.Key_Enter), self.table)
        self.enter_shortcut2.setContext(Qt.WidgetShortcut)
        self.enter_shortcut2.activated.connect(self.open_selected_file)

        self.table.itemSelectionChanged.connect(self._update_action_states)

        # E2: empty states — a fresh library and an empty search each get
        # one sentence instead of a silent blank table. The label lives on
        # the table's viewport so refresh() can show/hide it in place.
        self.empty_label = QLabel(self.table.viewport())
        self.empty_label.setObjectName("EmptyHint")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setFixedWidth(380)     # stable centered wrap
        self.empty_label.hide()
        # The empty state offers the action instead of only describing
        # it — one primary click starts the import dialog.
        self.empty_button = QPushButton(tr("btn_import"),
                                        self.table.viewport())
        self.empty_button.setObjectName("EmptyCta")
        self.empty_button.setFixedSize(170, 38)
        self.empty_button.clicked.connect(self.open_import_dialog)
        self.empty_button.hide()
        self.empty_guide_button = QPushButton(tr("empty_btn_help"),
                                              self.table.viewport())
        self.empty_guide_button.setObjectName("Secondary")
        self.empty_guide_button.setIcon(
            icons.icon("circle-help", theme.PALETTE["text"], 16))
        self.empty_guide_button.setFixedSize(170, 36)
        self.empty_guide_button.clicked.connect(self.open_help_dialog)
        self.empty_guide_button.hide()
        # The viewport's final geometry arrives after the first layout, so
        # centering at refresh() time is stale — re-center on every
        # viewport resize (first show, scrollbars, window resizes).
        self.table.viewport().installEventFilter(self)

        # --- assembly -------------------------------------------------
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 12, 16, 12)
        content_layout.addWidget(self.table)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(app_bar)
        layout.addWidget(filter_bar)
        layout.addWidget(content, 1)
        self.setCentralWidget(central)

        status = QStatusBar()
        status.setSizeGripEnabled(False)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        self.count_label.setContentsMargins(12, 0, 0, 0)
        status.addWidget(self.count_label)
        self.unclassified_button = QPushButton("")
        self.unclassified_button.setObjectName("WarnPill")
        self.unclassified_button.setCursor(Qt.PointingHandCursor)
        self.unclassified_button.clicked.connect(self._show_unclassified)
        status.addPermanentWidget(self.unclassified_button)
        self.setStatusBar(status)

        QShortcut(QKeySequence(QKeySequence.StandardKey.Find),
                  self).activated.connect(self.search_box.setFocus)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Open),
                  self).activated.connect(self.open_import_dialog)
        QShortcut(QKeySequence("Ctrl+E"), self).activated.connect(self._on_shortcut_edit)
        QShortcut(QKeySequence(Qt.Key_Escape), self).activated.connect(self._on_shortcut_esc)
        QShortcut(QKeySequence("F5"), self).activated.connect(self.refresh)
        QShortcut(QKeySequence(Qt.Key_F1), self).activated.connect(self.open_help_dialog)

        self.reload_filters()
        self.refresh()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        paths = [Path(u.toLocalFile()) for u in urls if u.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.run_import_worker(paths)
        else:
            event.ignore()

    def _on_shortcut_edit(self) -> None:
        rows = self._selected_rows()
        if len(rows) == 1:
            self.edit_metadata()
        elif len(rows) > 1:
            self.bulk_edit_selected()

    def _on_shortcut_esc(self) -> None:
        if self.search_box.text():
            self.search_box.clear()
        elif self.table.selectedItems():
            self.table.clearSelection()

    def _tool_button(self, text: str, icon_name: str) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setIcon(icons.icon(icon_name, theme.PALETTE["text"], 18))
        button.setIconSize(QSize(18, 18))
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(36)
        return button

    def _menu_action(self, menu: QMenu, text: str, icon_name: str,
                     slot) -> QAction:
        action = menu.addAction(
            icons.icon(icon_name, theme.PALETTE["muted"], 16), text)
        action.triggered.connect(slot)
        return action

    def _update_clear_button(self, text: str) -> None:
        self.clear_search_button.setVisible(bool(text))

    def _show_unclassified(self) -> None:
        index = self.subject_combo.findData(-1)
        if index >= 0:
            self.subject_combo.setCurrentIndex(index)

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

    def _file_icon_for(self, name: str):
        ext = Path(name).suffix.lower()
        if ext in (".zip", ".rar", ".7z", ".tar", ".gz"):
            return self._archive_icon
        if ext == ".darspack":
            return self._package_icon
        if ext == ".pdf":
            return self._pdf_icon
        return self._file_icon

    def _on_header_clicked(self, logical_index: int) -> None:
        """User clicked a column header: toggle sort direction and sort items logically."""
        current_order = self._sort_orders.get(logical_index, Qt.DescendingOrder)
        new_order = Qt.AscendingOrder if current_order == Qt.DescendingOrder else Qt.DescendingOrder
        self._sort_orders[logical_index] = new_order
        self.table.sortItems(logical_index, new_order)
        self.table.horizontalHeader().setSortIndicator(logical_index, new_order)
        self.table.horizontalHeader().setSortIndicatorShown(True)

    def _search_changed(self) -> None:
        self._sort_orders.clear()
        self.table.horizontalHeader().setSortIndicatorShown(False)
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
        year = self.year_combo.currentData()
        rows = catalog_search(
            self.lib.conn,
            self.search_box.text(),
            subject_id=subject_data if isinstance(subject_data, int) and subject_data > 0 else None,
            kind=self.kind_combo.currentData(),
            school_year=year,
            unclassified_only=(subject_data == -1),
            limit=2000)
        self.last_rows = rows
        # Perf audit F2.2–F2.3: this fill runs on every debounced keystroke,
        # so mid-fill repaints are off and only column 0 carries the file id
        # (selected_file_id reads selectedItems()[0]; selection is row-wide).
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        from ..core.normalize import persian_digits
        for i, row in enumerate(rows):
            date_str, size_str = self._display_strs_for(row)
            year_str = row["school_year"] or "—"
            values = [row["original_name"], row["subject_name"] or "—",
                      chapter_lesson_display(row["chapter"], row["lesson"]),
                      row["kind"] or "—", size_str,
                      persian_digits(date_str), persian_digits(year_str)]
            sort_keys = [
                row["original_name"].lower(),
                row["subject_name"] or "",
                (row["chapter"] or 0, row["lesson"] or 0),
                row["kind"] or "",
                row["size_bytes"] or 0,
                row["imported_at"] or "",
                row["school_year"] or "",
            ]
            for col, value in enumerate(values):
                item = TableSortItem(value)
                item.setData(TableSortItem.SORT_KEY_ROLE, sort_keys[col])
                if col == 0:
                    item.setData(Qt.UserRole, row["id"])
                    item.setIcon(self._file_icon_for(row["original_name"]))
                    item.setToolTip(row["original_name"])
                elif col == 1:
                    item.setToolTip(row["subject_name"] or "—")
                self.table.setItem(i, col, item)
        active_col = self.table.horizontalHeader().sortIndicatorSection()
        if self.table.horizontalHeader().isSortIndicatorShown() and active_col in self._sort_orders:
            self.table.sortItems(active_col, self._sort_orders[active_col])
        self.table.setUpdatesEnabled(True)
        self._update_empty_state(len(rows))
        self._update_action_states()
        unclassified = unclassified_count(self.lib.conn)   # F6: computed once
        self.count_label.setText(
            tr("status_files").format(i18n.num(len(rows))))
        self.unclassified_button.setText(
            tr("status_unclassified").format(i18n.num(unclassified)))
        self.unclassified_button.setVisible(bool(unclassified))

    def _update_action_states(self) -> None:
        """Edit/delete follow the table selection."""
        has_selection = bool(self.table.selectedItems())
        self.edit_action.setEnabled(has_selection)
        self.delete_action.setEnabled(has_selection)

    def _update_empty_state(self, shown: int) -> None:
        """E2: hide the hint when rows exist; otherwise pick the right
        message — a fresh library vs a search that found nothing. A fresh
        library also gets the «وارد کردن» CTA and the Guide CTA."""
        if shown:
            self.empty_label.hide()
            self.empty_button.hide()
            self.empty_guide_button.hide()
            return
        total = self.lib.conn.execute(
            "SELECT COUNT(*) c FROM files").fetchone()["c"]
        fresh = total == 0
        self.empty_label.setText(
            tr("empty_library") if fresh else tr("empty_search"))
        self.empty_button.setVisible(fresh)
        self.empty_guide_button.setVisible(fresh)
        self._center_empty_label()
        self.empty_label.show()

    def _center_empty_label(self) -> None:
        vp = self.table.viewport()
        self.empty_label.adjustSize()
        show_button = not self.empty_button.isHidden()
        show_guide = not self.empty_guide_button.isHidden()
        gap = 12 if show_button else 0
        guide_gap = 8 if show_guide else 0
        button_h = self.empty_button.sizeHint().height() if show_button else 0
        guide_h = self.empty_guide_button.sizeHint().height() if show_guide else 0
        block_h = self.empty_label.height() + gap + button_h + (guide_gap + guide_h if show_guide else 0)
        top = max(8, (vp.height() - block_h) // 2)
        center_x = (vp.width() - self.empty_label.width()) // 2
        self.empty_label.move(max(8, center_x), top)
        if show_button:
            btn_top = top + self.empty_label.height() + gap
            btn_x = (vp.width() - self.empty_button.width()) // 2
            self.empty_button.move(max(8, btn_x), btn_top)
            if show_guide:
                guide_x = (vp.width() - self.empty_guide_button.width()) // 2
                self.empty_guide_button.move(
                    max(8, guide_x),
                    btn_top + button_h + guide_gap)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self.empty_label.isHidden():
            self._center_empty_label()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_dark_titlebar()
        if not getattr(self, "_welcome_checked", False):
            self._welcome_checked = True
            if (self.settings.get("show_welcome", True) and
                os.environ.get("QT_QPA_PLATFORM") != "offscreen"):
                QTimer.singleShot(200, self.open_welcome_tour)

    def _apply_dark_titlebar(self) -> None:
        """The app is dark-only; a light Windows title bar would clash on
        a machine whose system theme is light. DwmSetWindowAttribute is
        the documented way to ask for the dark frame (attribute 20, with
        19 as the older Windows 10 fallback)."""
        if sys.platform != "win32" or getattr(self, "_dark_titlebar", False):
            return
        try:
            import ctypes
            value = ctypes.c_int(1)
            for attribute in (20, 19):
                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    int(self.winId()), attribute, ctypes.byref(value),
                    ctypes.sizeof(value))
                if result == 0:
                    self._dark_titlebar = True
                    break
        except Exception:
            pass                    # cosmetic only; never block startup

    def eventFilter(self, obj, event) -> bool:
        table = getattr(self, "table", None)
        if (table is not None
                and obj is table.viewport()
                and event.type() == QEvent.Resize
                and not self.empty_label.isHidden()):
            self._center_empty_label()
        elif (obj is self.search_box
              and event.type() in (QEvent.FocusIn, QEvent.FocusOut)):
            focused = event.type() == QEvent.FocusIn
            self.search_shell.setProperty("focused", focused)
            self.search_shell.style().unpolish(self.search_shell)
            self.search_shell.style().polish(self.search_shell)
        elif (table is not None and (obj is table or obj is table.viewport())
              and event.type() in (QEvent.DragEnter, QEvent.Drop)):
            if event.type() == QEvent.DragEnter:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Drop:
                self.dropEvent(event)
                return True
        elif (table is not None and obj is table.viewport()
              and event.type() == QEvent.ToolTip):
            index = table.indexAt(event.pos())
            if index.isValid() and self._cell_text_fits(index):
                QToolTip.hideText()
                return True
        return super().eventFilter(obj, event)

    def _cell_text_fits(self, index) -> bool:
        """True when the cell shows its text in full; tooltips then add
        nothing. The name column also reserves room for its file icon."""
        text = str(index.data(Qt.DisplayRole) or "")
        reserved = 44 if index.column() == 0 else 20
        available = self.table.visualRect(index).width() - reserved
        return self.table.fontMetrics().horizontalAdvance(text) <= available

    def selected_file_id(self) -> int | None:
        """The current row's id (the id lives on column 0 only — perf F2.2)."""
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        file_id = item.data(Qt.UserRole) if item is not None else None
        if file_id is None:
            self.statusBar().showMessage(tr("err_no_selection"), 3000)
            return None
        return file_id

    def open_selected_file(self) -> None:
        """Double-click: open the file with the OS default app (PDF viewer…)."""
        file_id = self.selected_file_id()
        if file_id is None:
            return
        row = self.lib.conn.execute(
            "SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        QDesktopServices.openUrl(QUrl.fromLocalFile(
            str(self.lib.stored_path(row))))

    def reveal_selected_file(self) -> None:
        """Reveal the selected file in the system file manager."""
        file_id = self.selected_file_id()
        if file_id is None:
            return
        row = self.lib.conn.execute(
            "SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        if not row:
            return
        path = self.lib.stored_path(row)
        if not path.exists():
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", f'/select,"{path}"'])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def copy_selected_names(self) -> None:
        """Copy original filenames of selected files to clipboard."""
        rows = self._selected_rows()
        if not rows:
            return
        QApplication.clipboard().setText("\n".join(r["original_name"] for r in rows))

    def copy_selected_paths(self) -> None:
        """Copy full stored filesystem paths of selected files to clipboard."""
        rows = self._selected_rows()
        if not rows:
            return
        paths = []
        for r in rows:
            rec = self.lib.conn.execute(
                "SELECT stored_name FROM files WHERE id=?", (r["id"],)).fetchone()
            if rec and rec["stored_name"]:
                paths.append(str(self.lib.files_dir / rec["stored_name"]))
        QApplication.clipboard().setText("\n".join(paths))

    def _show_search_context_menu(self, pos: QPoint) -> None:
        """Right-click on the search input box shows a localized, clean context menu."""
        menu = create_localized_line_edit_context_menu(
            self.search_box, parent=self, include_clear=True
        )
        menu.exec(self.search_box.mapToGlobal(pos))

    def _show_row_menu(self, pos) -> None:
        """Right-click anywhere on a row acts on the selection.

        The file id lives only on the name cell (perf F2.2), so the row
        is resolved from whatever cell was clicked and the id read from
        column 0. Clicking outside the current selection selects that row
        first (standard desktop behavior); clicking inside a multi-select
        applies the action to all selected rows.
        """
        item = self.table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        selected = {i.row() for i in
                    self.table.selectionModel().selectedRows()}
        if row not in selected:
            self.table.clearSelection()
            self.table.selectRow(row)
        rows = self._selected_rows()
        if not rows:
            return

        menu = QMenu(self)

        def add_item(text: str, icon_name: str | None = None, icon_color: str | None = None):
            act = menu.addAction(text)
            if icon_name and hasattr(act, "setIcon"):
                color = icon_color or theme.PALETTE["text"]
                act.setIcon(icons.icon(icon_name, color, 16))
            return act

        open_act = reveal_act = edit_act = copy_name_act = copy_path_act = bulk_act = None
        if len(rows) == 1:
            open_act = add_item(tr("menu_open"), "external-link")
            reveal_act = add_item(tr("menu_reveal"), "folder-open")
            edit_act = add_item(tr("btn_edit_meta"), "file-text")
            copy_name_act = add_item(tr("menu_copy_name"), "copy")
            copy_path_act = add_item(tr("menu_copy_path"), "copy")
        else:
            bulk_act = add_item(tr("bulk_edit_menu"), "file-text")
            copy_name_act = add_item(tr("menu_copy_name"), "copy")

        menu.addSeparator()
        delete_act = add_item(tr("delete_menu"), "trash-2", theme.PALETTE["danger"])
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        if chosen == delete_act:
            self.delete_selected_files()
        elif chosen == open_act:
            self.open_selected_file()
        elif chosen == reveal_act:
            self.reveal_selected_file()
        elif chosen == edit_act:
            self.edit_metadata()
        elif chosen == copy_name_act:
            self.copy_selected_names()
        elif chosen == copy_path_act:
            self.copy_selected_paths()
        elif chosen == bulk_act:
            self.bulk_edit_selected()

    def delete_selected_files(self) -> None:
        """Del key / «حذف» button / context menu — act on every selected row."""
        rows = self._selected_rows()
        if rows:
            self.delete_files([r["id"] for r in rows])

    def delete_files(self, file_ids: list) -> None:
        """E3 (design-approved 2026-10-24; bulk added 2026-10-29): a
        confirmed, explicit user action may remove files from the library.
        Each stored file is MOVED to files/.trash/ (never unlinked — the
        trash copy is the safety net) and its row leaves the catalog, so
        re-importing the same content works. files/.trash is a SUBFOLDER,
        and sweep_orphans only touches top-level files of files/ — the
        trash is exempt by construction.

        One file per transaction: a crash can leave a file in the trash
        with its row still present (the next open's health check flags
        it), but never a row pointing at an erased file.
        """
        rows = []
        for fid in file_ids:
            row = self.lib.conn.execute(
                """SELECT f.*, s.name AS subject_name FROM files f
                   LEFT JOIN subjects s ON s.id=f.subject_id WHERE f.id=?""",
                (fid,)).fetchone()
            if row is not None:
                rows.append(row)
        if not rows:
            return
        if len(rows) == 1:
            text = tr("delete_confirm").format(name=rows[0]["original_name"])
        else:
            text = tr("delete_confirm_many").format(
                count=i18n.num(len(rows)))
        answer = QMessageBox.question(
            self, tr("delete_title"), text,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        from ..core import db
        trash_dir = self.lib.files_dir / ".trash"
        trash_dir.mkdir(exist_ok=True)
        trash_meta_dir = self.lib.files_dir / ".trash_meta"
        trash_meta_dir.mkdir(exist_ok=True)
        for row in rows:
            stored_p = Path(row["stored_name"])
            dest = trash_dir / row["stored_name"]
            n = 0
            while dest.exists():    # a same-named file may already be in the trash
                n += 1
                dest = trash_dir / f"{stored_p.stem}~{n}{stored_p.suffix}"
            try:
                os.replace(self.lib.stored_path(row), dest)  # same volume → atomic
                tag_rows = self.lib.conn.execute(
                    "SELECT t.name FROM tags t JOIN file_tags ft ON ft.tag_id=t.id WHERE ft.file_id=?",
                    (row["id"],)
                ).fetchall()
                file_tags = [r[0] for r in tag_rows]
                meta = {
                    "original_name": row["original_name"],
                    "stored_name": row["stored_name"],
                    "subject_id": row["subject_id"],
                    "subject_name": row["subject_name"],
                    "chapter": row["chapter"],
                    "lesson": row["lesson"] if "lesson" in row.keys() else None,
                    "kind": row["kind"],
                    "school_year": row["school_year"],
                    "sha256": row["sha256"],
                    "size": row["size_bytes"],
                    "imported_at": row["imported_at"] if "imported_at" in row.keys() else None,
                    "deleted_at": _dt.datetime.now().isoformat(),
                    "note": row["note"] if "note" in row.keys() else "",
                    "tags": file_tags,
                }
                meta_dest = trash_meta_dir / f"{dest.name}.json"
                meta_dest.write_text(
                    json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            except FileNotFoundError:
                pass                 # already gone; the row still leaves
            with self.lib.conn:
                self.lib.conn.execute(
                    "DELETE FROM files WHERE id=?", (row["id"],))
                db.log(self.lib.conn, "delete", row["original_name"])
            self._display_strs.pop(row["id"], None)
        self.reload_filters()
        self.refresh()
        if len(rows) == 1:
            message = tr("delete_done").format(
                name=rows[0]["original_name"])
        else:
            message = tr("delete_done_many").format(
                count=i18n.num(len(rows)))
        self.statusBar().showMessage(message, 5000)

    def delete_file(self, file_id: int) -> None:
        """Single-file entry point (kept for callers and tests)."""
        self.delete_files([file_id])

    def bulk_edit_selected(self) -> None:
        """«ویرایش گروهی»: one metadata form applied to the selection."""
        rows = self._selected_rows()
        if not rows:
            return
        dialog = dialogs.BulkEditDialog(self, self.lib,
                                        [r["id"] for r in rows])
        if dialog.exec():
            self.reload_filters()
            self.refresh()
            self.statusBar().showMessage(
                tr("bulk_edit_done").format(count=i18n.num(len(rows))), 5000)

    # ---- actions ------------------------------------------------------

    def open_import_dialog(self) -> None:
        dialogs.ImportDialog(self).exec()

    def run_import_worker(self, paths: list, keep_duplicates: bool = False,
                          **kwargs) -> None:
        # Prevent re-entrant imports while an import is running or being reviewed
        if getattr(self, "_import_busy", False) or (
                getattr(self, "_worker", None) is not None and self._worker.isRunning()):
            self.statusBar().showMessage(tr("import_running_busy"), 3000)
            return
        self._import_busy = True
        # kwargs (A5): metas/meta_base/cleanup_dir for a ?????? import
        self._worker = ImportWorker(
            str(self.lib.root), paths, keep_duplicates, **kwargs)
        self._worker.progress.connect(
            lambda d, t, name: self.statusBar().showMessage(
                tr("import_running").format(d, t, name)))
        self._worker.done.connect(self._import_finished)
        self._worker.start()

    def _import_finished(self, imported, duplicates, errors, messages,
                         new_ids) -> None:
        try:
            self.reload_filters()
            self.refresh()
            # Categorizing is the app's main job ? ask for the new files' info
            # right away, pre-filled with the filename suggestions (and, for a
            # ?????? import, the manifest's subject/tags as pre-fill ? A5).
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
        finally:
            self._import_busy = False

    def open_trash_dialog(self) -> None:
        dialog = dialogs.TrashDialog(self, self.lib)
        dialog.exec()
        if dialog.restored_any:
            self.reload_filters()
            self.refresh()

    def open_exam_pack_dialog(self) -> None:
        dialogs.ExamPackDialog(self, self.lib).exec()

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

    def show_history(self) -> None:
        """E1: the activity log viewer + learned-rules transparency tab."""
        dialogs.ActivityDialog(self, self.lib).exec()

    def show_stats(self) -> None:
        """E5: files per subject/kind, total size, dedup bytes avoided.

        The numbers are computed in a background thread; a small progress
        dialog opens instantly (what is happening + a cancel button) and
        the results dialog appears only when the worker finishes. The UI
        thread never blocks on the queries.
        """
        from .workers import StatsWorker
        self._stats_worker = StatsWorker(str(self.lib.root))
        progress = dialogs.StatsProgressDialog(self)
        self._stats_worker.done.connect(
            lambda stats: self._stats_finished(progress, stats))
        self._stats_worker.start()
        progress.exec()          # modal; its cancel stops the worker

    def _stats_finished(self, progress, stats) -> None:
        progress.accept()        # closes the progress dialog either way
        if stats is None:        # user cancelled
            return
        dialogs.StatsDialog(self, stats).exec()

    def edit_metadata(self) -> None:
        """One row → the full metadata dialog; several rows → bulk edit."""
        if len(self._selected_rows()) > 1:
            self.bulk_edit_selected()
            return
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

    def open_help_dialog(self) -> None:
        dialogs.HelpDialog(self, self.settings, self.settings_path).exec()

    def open_welcome_tour(self) -> None:
        dialogs.WelcomeDialog(self, self.settings, self.settings_path).exec()

    # ---- LAN sharing ----------------------------------------------------

    def toggle_share(self) -> None:
        if self.share_server is None:
            # F4 (perf audit): the http/ssl/email import chain is only
            # needed when sharing actually starts
            from ..web.server import ShareServer
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