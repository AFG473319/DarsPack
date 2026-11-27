"""Main window (پنجره‌ی اصلی): search, filters, catalog table, actions.

Layout mirrors how a student thinks: a search box + subject/kind filters
on top, the file table in the middle, and action buttons below. The
whole catalog is read through core.search(), so the window never builds
SQL itself. Heavy work (import, package import) runs in workers.
"""
from __future__ import annotations

import datetime as _dt
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import (QEvent, QObject, QPoint, QSize, Qt, QThread,
                            QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QApplication,
    QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QStatusBar, QTableWidget, QTableWidgetItem,
    QToolButton, QToolTip, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__, asset_path, i18n
from ..core.search import search as catalog_search
from ..i18n import tr
from . import dialogs, icons, theme
from .delegates import FileNameDelegate, FileNameLabel, KindBadgeDelegate
from .smooth_scroll import enable_smooth_scroll
from .workers import ImportWorker, start_worker

if TYPE_CHECKING:      # F4 (perf audit): ShareServer pulls http/ssl/email —
    from ..web.server import ShareServer   # only needed when sharing starts

KINDS = ["جزوه", "نمونه‌سوال", "کاربرگ", "تکلیف", "سایر"]


def human_size(n: int | None, lang: str | None = None) -> str:
    """Bytes → a human size in the UI language («۱٫۵ کیلوبایت», «1.5 KB»)."""
    if n is None or not isinstance(n, (int, float)) or n < 0:
        return "—"          # missing/corrupt size never crashes the table
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


def jalali_date(iso: str | None) -> str:
    if not iso or not isinstance(iso, str):
        return "—"          # missing date (old/partial rows) never crashes the table
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
    except (ValueError, TypeError, OverflowError):
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
            return self.text() < other.text()
        return False


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
        # Preserve Qt.Popup window flags so reparenting does not turn the
        # context menu into an embedded non-dismissible child widget.
        menu.setParent(parent, menu.windowFlags())

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
        clear_act.setIcon(icons.icon("x", theme.PALETTE["text"], 16))
        clear_act.triggered.connect(edit.clear)

    theme.apply_menu_style(menu)
    return menu


class _StopShareWorker(QObject):
    """M12: server.stop() can block while a transfer is in flight — run it
    off the UI thread so «قطع اشتراک» never freezes the window. A plain
    QObject moved onto a QThread (see workers.start_worker); `done`
    carries the result back to the UI thread."""

    done = Signal()

    def __init__(self, server):
        super().__init__()
        self._server = server

    @Slot()
    def run(self) -> None:
        try:
            self._server.stop()
        except Exception:
            pass
        finally:
            self.done.emit()


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
        # _display_stamps tracks (imported_at, size_bytes) so SQLite id
        # reuse after an external delete still refreshes cached labels.
        self._display_strs: dict = {}
        self._display_stamps: dict = {}

        self.setWindowTitle(tr("app_title"))
        self.resize(1150, 720)
        self.setMinimumSize(1000, 600)
        self._file_icon = icons.icon("file-text", theme.PALETTE["muted"], 16)
        self._pdf_icon = icons.icon("file-text", "#8ca8d9", 16)
        self._image_icon = icons.icon("image", "#8fd0b8", 16)
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
        shell.setContentsMargins(10, 0, 12, 0)
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
        for combo, width in ((self.subject_combo, 140),
                             (self.kind_combo, 118),
                             (self.year_combo, 128)):
            combo.setFixedWidth(width)
            combo.setFixedHeight(30)
            theme.setup_combobox(combo)
        self.subject_combo.currentIndexChanged.connect(self._on_filter_combo_changed)
        self.kind_combo.currentIndexChanged.connect(self._on_filter_combo_changed)
        self.year_combo.currentIndexChanged.connect(self._on_filter_combo_changed)

        self.import_button = QPushButton(tr("btn_import"))
        self.import_button.setObjectName("Primary")
        self.import_button.setIcon(
            icons.icon("plus", theme.PALETTE["on_accent"], 18))
        self.import_button.setIconSize(QSize(18, 18))
        self.import_button.setFixedHeight(38)
        self.import_button.clicked.connect(self.open_import_dialog)

        filter_bar = QWidget()
        filter_bar.setObjectName("FilterBar")
        toolbar = QHBoxLayout(filter_bar)
        toolbar.setContentsMargins(10, 6, 10, 6)
        toolbar.setSpacing(8)

        self.packages_menu = QMenu(self)
        self._menu_action(self.packages_menu, tr("btn_export"), "upload",
                          self.export_package)
        self._menu_action(self.packages_menu, tr("btn_exam_pack"), "package",
                          self.open_exam_pack_dialog)
        self._menu_action(self.packages_menu, tr("btn_verify"), "circle-check",
                          self.verify_package)
        self._menu_action(self.packages_menu, tr("btn_import_pkg"),
                          "folder-open", self.import_package)
        self.packages_button = self._tool_button(tr("btn_packages"),
                          "package")
        self.packages_button.setProperty("hasDropdown", True)
        self.packages_button.setPopupMode(QToolButton.InstantPopup)
        self.packages_button.setMenu(self.packages_menu)
        pkg_overlay = QHBoxLayout(self.packages_button)
        pkg_overlay.setContentsMargins(8, 0, 8, 0)
        pkg_overlay.addStretch(1)
        pkg_chev = QLabel()
        pkg_chev.setFixedSize(12, 12)
        pkg_chev.setPixmap(icons.tinted_pixmap("chevron-down", theme.PALETTE["muted"], 12))
        pkg_chev.setAttribute(Qt.WA_TransparentForMouseEvents)
        pkg_overlay.addWidget(pkg_chev, 0, Qt.AlignVCenter)
        toolbar.addWidget(self.packages_button)

        self.duplicates_button = self._tool_button(tr("btn_dups"), "copy")
        self.duplicates_button.clicked.connect(self.show_duplicates)
        toolbar.addWidget(self.duplicates_button)

        self.share_button = self._tool_button(tr("btn_share"), "share-2")
        self.share_button.clicked.connect(self.toggle_share)
        toolbar.addWidget(self.share_button)

        self.more_menu = QMenu(self)
        self.more_menu.setMinimumWidth(220)
        self.edit_action = self._menu_action(
            self.more_menu, tr("btn_edit_meta"), "file-text", self._on_shortcut_edit)
        self.delete_action = self._menu_action(
            self.more_menu, tr("btn_delete"), "trash-2",
            self.delete_selected_files, icon_color=theme.PALETTE["danger"])
        self.edit_action.setEnabled(False)
        self.delete_action.setEnabled(False)
        self.more_menu.addSeparator()
        self._menu_action(self.more_menu, tr("btn_trash_bin"), "archive",
                          self.open_trash_dialog)
        self._menu_action(self.more_menu, tr("btn_history"), "history",
                          self.show_history)
        self._menu_action(self.more_menu, tr("btn_stats"), "chart-column",
                          self.show_stats)
        self.more_menu.addSeparator()
        self._menu_action(
            self.more_menu, tr("btn_feedback"), "message-square",
            lambda: dialogs.FeedbackDialog(self, self.settings).exec())
        self._menu_action(self.more_menu, tr("btn_tour"), "compass",
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
            icons.icon("ellipsis-vertical", theme.PALETTE["muted"], 16))
        self.more_button.setIconSize(QSize(16, 16))
        self.more_button.setToolTip(tr("more_actions"))
        self.more_button.setFixedSize(30, 30)
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
        hdr_text_align = Qt.AlignLeading | Qt.AlignVCenter
        for col in range(len(columns)):
            hdr_item = self.table.horizontalHeaderItem(col)
            if hdr_item is not None:
                hdr_item.setTextAlignment(
                    Qt.AlignCenter if col == 3 else hdr_text_align
                )
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
            0, FileNameDelegate(self.table))
        self.table.setItemDelegateForColumn(
            3, KindBadgeDelegate(self.table))
        # Stretch the NAME column. setStretchLastSection stretched
        # «سال» (the last logical column in RTL), which squeezed «درس» into
        # «مطالعات ...» while the name stayed fixed at 420 px.
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(80)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 140), (2, 140), (3, 100),
                           (4, 84), (5, 118), (6, 86)):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            self.table.setColumnWidth(col, width)
        self._sort_orders: dict[int, Qt.SortOrder] = {}
        header.setSortIndicator(5, Qt.DescendingOrder)
        header.setSortIndicatorShown(True)
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
        self.empty_clear_button = QPushButton(tr("empty_search_clear"),
                                              self.table.viewport())
        self.empty_clear_button.setObjectName("Secondary")
        self.empty_clear_button.setFixedSize(170, 36)
        self.empty_clear_button.clicked.connect(self._clear_all_filters)
        self.empty_clear_button.hide()
        # The viewport's final geometry arrives after the first layout, so
        # centering at refresh() time is stale — re-center on every
        # viewport resize (first show, scrollbars, window resizes).
        self.table.viewport().installEventFilter(self)

        # --- assembly: Windows 11 Fluent Layout ----------------------
        # Top-level container: Horizontal layout with NavRail on side and Canvas on main
        central = QWidget()
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Navigation Rail (سایدبار ناوبری روان)
        self.nav_rail = QWidget()
        self.nav_rail.setObjectName("NavRail")
        self.nav_rail.setFixedWidth(210)
        nav_vbox = QVBoxLayout(self.nav_rail)
        nav_vbox.setContentsMargins(8, 12, 8, 12)
        nav_vbox.setSpacing(4)

        # Brand header in rail
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(6, 4, 6, 12)
        brand_row.setSpacing(8)
        brand = QSvgWidget(str(asset_path("icon/darspack.svg")))
        brand.setFixedSize(28, 28)
        brand_row.addWidget(brand)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel(tr("app_title"))
        title.setObjectName("BrandTitle")
        subtitle = QLabel(tr("app_subtitle"))
        subtitle.setObjectName("BrandSub")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        brand_row.addLayout(titles)
        brand_row.addStretch(1)
        nav_vbox.addLayout(brand_row)

        self._nav_items = {}

        def _add_nav_item(key: str, label: str, icon_name: str, slot, count_badge=None) -> QToolButton:
            btn = QToolButton()
            btn.setObjectName("NavItem")
            btn.setText(label)
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            btn._icon_name = icon_name
            btn.setIcon(icons.icon(icon_name, theme.PALETTE["muted"], 16))
            btn.setIconSize(QSize(16, 16))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(slot)

            btn._base_label = label
            btn._badge_count = 0
            btn._badge = None
            overlay = QHBoxLayout(btn)
            overlay.setContentsMargins(6, 0, 6, 0)
            overlay.setSpacing(0)

            indicator = QFrame()
            indicator.setObjectName("NavIndicator")
            indicator.setFixedSize(3, 16)
            indicator.setAttribute(Qt.WA_TransparentForMouseEvents)
            indicator.hide()
            btn._indicator = indicator
            overlay.addWidget(indicator, 0, Qt.AlignVCenter)
            overlay.addStretch(1)

            if count_badge:
                btn.setProperty("hasBadge", True)
                badge = QLabel("")
                badge.setObjectName("NavBadge")
                badge.setAlignment(Qt.AlignCenter)
                badge.setFixedHeight(18)
                badge.setMinimumWidth(20)
                badge.setAttribute(Qt.WA_TransparentForMouseEvents)
                badge.hide()
                overlay.addWidget(badge, 0, Qt.AlignVCenter)
                btn._badge = badge

            nav_vbox.addWidget(btn)
            self._nav_items[key] = btn
            return btn

        # Section 1: Library (کتابخانه)
        sec_lib = QLabel(tr("nav_sec_library"))
        sec_lib.setObjectName("NavSectionHeader")
        nav_vbox.addWidget(sec_lib)

        self.nav_all = _add_nav_item("all", tr("nav_all_files"), "folder-open",
                                     lambda: self._select_nav_filter(None, None))
        self.nav_all.setProperty("active", True)
        self.nav_all._indicator.show()
        self.nav_all.setIcon(icons.icon("folder-open", theme.PALETTE["accent"], 16))

        self.nav_unclassified = _add_nav_item(
            "unclass", tr("nav_unclassified"), "triangle-alert",
            lambda: self._select_nav_filter(-1, None), count_badge=True)

        self.nav_trash = _add_nav_item(
            "trash", tr("nav_trash"), "archive", self.open_trash_dialog)

        nav_vbox.addStretch(1)

        div2 = QFrame()
        div2.setObjectName("NavDivider")
        div2.setFrameShape(QFrame.HLine)
        nav_vbox.addWidget(div2)

        # Bottom section: Stats & Settings
        _add_nav_item("stats", tr("nav_stats"), "chart-column", self.show_stats)
        _add_nav_item("history", tr("nav_history"), "history", self.show_history)
        _add_nav_item("help", tr("btn_help"), "circle-help", self.open_help_dialog)
        _add_nav_item("settings", tr("nav_settings"), "settings", self.open_settings)

        root_layout.addWidget(self.nav_rail)

        # 2. Main Content Canvas
        canvas = QWidget()
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)

        # Fluent CommandBar (Top Header with Search + Primary CTA + View Switcher)
        command_bar = QWidget()
        command_bar.setObjectName("CommandBar")
        cmd_layout = QHBoxLayout(command_bar)
        cmd_layout.setContentsMargins(10, 8, 10, 8)
        cmd_layout.setSpacing(12)

        # Search Bar
        cmd_layout.addWidget(self.search_shell)
        cmd_layout.addStretch(1)

        # View Switcher (Table View vs Card Grid View)
        view_group = QFrame()
        view_group.setObjectName("SegmentGroup")
        vg_layout = QHBoxLayout(view_group)
        vg_layout.setContentsMargins(2, 2, 2, 2)
        vg_layout.setSpacing(2)

        self.btn_view_table = QToolButton()
        self.btn_view_table.setObjectName("SegmentBtn")
        self.btn_view_table.setIcon(icons.icon("list", "#ffffff", 16))
        self.btn_view_table.setIconSize(QSize(16, 16))
        self.btn_view_table.setFixedSize(32, 32)
        self.btn_view_table.setToolTip(tr("view_table"))
        self.btn_view_table.setProperty("active", True)
        self.btn_view_table.clicked.connect(lambda: self._set_view_mode("table"))
        vg_layout.addWidget(self.btn_view_table)

        self.btn_view_cards = QToolButton()
        self.btn_view_cards.setObjectName("SegmentBtn")
        self.btn_view_cards.setIcon(icons.icon("grid", theme.PALETTE["muted"], 16))
        self.btn_view_cards.setIconSize(QSize(16, 16))
        self.btn_view_cards.setFixedSize(32, 32)
        self.btn_view_cards.setToolTip(tr("view_cards"))
        self.btn_view_cards.setProperty("active", False)
        self.btn_view_cards.clicked.connect(lambda: self._set_view_mode("cards"))
        vg_layout.addWidget(self.btn_view_cards)

        cmd_layout.addWidget(view_group)

        # Primary Import Action
        cmd_layout.addWidget(self.import_button)

        canvas_layout.addWidget(command_bar)

        # Sub-header / FilterBar (Quick Subject, Kind & Year dropdowns + More menu)
        canvas_layout.addWidget(filter_bar)

        # Fluent InfoBar (Status notification banner for active Wi-Fi sharing or notices)
        self.info_bar = QFrame()
        self.info_bar.setObjectName("InfoBar")
        info_layout = QHBoxLayout(self.info_bar)
        info_layout.setContentsMargins(14, 6, 14, 6)
        info_layout.setSpacing(10)
        self.info_bar_icon = QLabel()
        self.info_bar_icon.setFixedSize(18, 18)
        info_layout.addWidget(self.info_bar_icon)
        self.info_bar_label = QLabel()
        self.info_bar_label.setObjectName("InfoBarText")
        info_layout.addWidget(self.info_bar_label, 1)
        self.info_bar_action = QPushButton(tr("infobar_share_view"))
        self.info_bar_action.setObjectName("InfoBarAction")
        self.info_bar_action.setCursor(Qt.PointingHandCursor)
        self.info_bar_action.clicked.connect(self.toggle_share)
        info_layout.addWidget(self.info_bar_action)
        self.info_bar_close = QToolButton()
        self.info_bar_close.setObjectName("InfoBarClose")
        self.info_bar_close.setIcon(icons.icon("x", theme.PALETTE["muted"], 14))
        self.info_bar_close.setCursor(Qt.PointingHandCursor)
        self.info_bar_close.clicked.connect(self.info_bar.hide)
        info_layout.addWidget(self.info_bar_close)
        self.info_bar.hide()

        # Content area with Stacked Views: Table and Card Grid
        self.content_stack = QWidget()
        content_vbox = QVBoxLayout(self.content_stack)
        content_vbox.setContentsMargins(10, 6, 10, 10)
        content_vbox.setSpacing(8)
        content_vbox.addWidget(self.info_bar)

        # Table View
        content_vbox.addWidget(self.table, 1)

        # Card Grid View
        self.card_scroll = QScrollArea()
        self.card_scroll.setObjectName("CardGridScroll")
        self.card_scroll.setWidgetResizable(True)
        self.card_container = QWidget()
        self.card_container.setObjectName("CardGridContainer")
        self.card_grid = QGridLayout(self.card_container)
        self.card_grid.setContentsMargins(4, 4, 4, 4)
        self.card_grid.setSpacing(12)
        self.card_scroll.setWidget(self.card_container)
        self.card_scroll.hide()
        enable_smooth_scroll(self.card_scroll)
        content_vbox.addWidget(self.card_scroll, 1)

        canvas_layout.addWidget(self.content_stack, 1)

        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)
        self._status_bar.setContentsMargins(10, 2, 10, 3)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        self.count_label.setContentsMargins(10, 0, 10, 0)
        self._status_bar.addWidget(self.count_label)
        self.unclassified_button = QPushButton("")
        self.unclassified_button.setObjectName("WarnPill")
        self.unclassified_button.setIcon(
            icons.icon("triangle-alert", theme.PALETTE["accent"], 13))
        self.unclassified_button.setIconSize(QSize(13, 13))
        self.unclassified_button.setCursor(Qt.PointingHandCursor)
        self.unclassified_button.clicked.connect(self._show_unclassified)
        self._status_bar.addPermanentWidget(self.unclassified_button)
        canvas_layout.addWidget(self._status_bar)

        root_layout.addWidget(canvas, 1)
        self.setCentralWidget(central)

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

    def statusBar(self) -> QStatusBar:
        """Keep the status bar scoped to the canvas so the NavRail runs full height."""
        return self._status_bar

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
        button.setIcon(icons.icon(icon_name, theme.PALETTE["text"], 15))
        button.setIconSize(QSize(15, 15))
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(30)
        return button

    def _menu_action(self, menu: QMenu, text: str, icon_name: str,
                     slot, icon_color: str | None = None) -> QAction:
        color = icon_color or theme.PALETTE["text"]
        action = menu.addAction(
            icons.icon(icon_name, color, 16), text)
        action.triggered.connect(slot)
        return action

    def _sync_nav_to_filters(self) -> None:
        """Keep the NavRail highlight synchronized with combo-box filter state."""
        subj = self.subject_combo.currentData()
        has_extra = (
            (self.kind_combo.currentData() is not None)
            or (self.year_combo.currentData() is not None)
        )
        if subj == -1 and not has_extra:
            active_key = "unclass"
        elif subj is None and not has_extra:
            active_key = "all"
        else:
            active_key = ""
        for key, btn in getattr(self, "_nav_items", {}).items():
            is_act = (key == active_key)
            btn.setProperty("active", is_act)
            ind = getattr(btn, "_indicator", None)
            if ind is not None:
                ind.setVisible(is_act)
            if hasattr(btn, "_icon_name"):
                btn.setIcon(icons.icon(
                    btn._icon_name,
                    theme.PALETTE["accent"] if is_act else theme.PALETTE["muted"],
                    16,
                ))
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _on_filter_combo_changed(self) -> None:
        self._sync_nav_to_filters()
        self.refresh()

    def _clear_all_filters(self) -> None:
        self.search_box.blockSignals(True)
        self.subject_combo.blockSignals(True)
        self.kind_combo.blockSignals(True)
        self.year_combo.blockSignals(True)
        self.search_box.clear()
        self.subject_combo.setCurrentIndex(0)
        self.kind_combo.setCurrentIndex(0)
        self.year_combo.setCurrentIndex(0)
        self.search_box.blockSignals(False)
        self.subject_combo.blockSignals(False)
        self.kind_combo.blockSignals(False)
        self.year_combo.blockSignals(False)
        self._update_clear_button("")
        self._sync_nav_to_filters()
        self.refresh()

    def _select_nav_filter(self, subject_id, kind) -> None:
        """Handle clicks on the Fluent Navigation Rail."""
        self.subject_combo.blockSignals(True)
        self.kind_combo.blockSignals(True)
        self.year_combo.blockSignals(True)
        if subject_id == -1:
            idx = self.subject_combo.findData(-1)
            if idx >= 0:
                self.subject_combo.setCurrentIndex(idx)
            self.kind_combo.setCurrentIndex(0)
            self.year_combo.setCurrentIndex(0)
        else:
            self.subject_combo.setCurrentIndex(0)
            self.kind_combo.setCurrentIndex(0)
            self.year_combo.setCurrentIndex(0)
        self.subject_combo.blockSignals(False)
        self.kind_combo.blockSignals(False)
        self.year_combo.blockSignals(False)
        self._sync_nav_to_filters()
        self.refresh()

    def _set_view_mode(self, mode: str) -> None:
        """Switch between detailed Windows table view and modern Fluent card grid."""
        is_cards = (mode == "cards")
        self.btn_view_table.setProperty("active", not is_cards)
        self.btn_view_cards.setProperty("active", is_cards)
        self.btn_view_table.setIcon(icons.icon(
            "list", theme.PALETTE["muted"] if is_cards else "#ffffff", 16))
        self.btn_view_cards.setIcon(icons.icon(
            "grid", "#ffffff" if is_cards else theme.PALETTE["muted"], 16))
        self.btn_view_table.style().unpolish(self.btn_view_table)
        self.btn_view_table.style().polish(self.btn_view_table)
        self.btn_view_cards.style().unpolish(self.btn_view_cards)
        self.btn_view_cards.style().polish(self.btn_view_cards)

        if is_cards:
            self.table.hide()
            self._populate_card_grid()
            self.card_scroll.show()
        else:
            self.card_scroll.hide()
            self.table.show()

    def _populate_card_grid(self) -> None:
        """Fill the Fluent card grid with visual tiles of the current result rows."""
        # Clear existing card widgets
        while self.card_grid.count():
            item = self.card_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        from .delegates import KIND_BADGES

        cols = 3  # 3 responsive columns
        for idx, row in enumerate(self.last_rows):
            card = QFrame()
            card.setObjectName("FileCard")
            card.setCursor(Qt.PointingHandCursor)
            c_layout = QVBoxLayout(card)
            c_layout.setContentsMargins(12, 10, 12, 10)
            c_layout.setSpacing(6)

            # Top row: File Icon + File Name
            header_row = QHBoxLayout()
            header_row.setSpacing(8)
            f_icon = QLabel()
            f_icon.setFixedSize(24, 24)
            f_icon.setPixmap(self._file_icon_for(row["original_name"]).pixmap(24, 24))
            header_row.addWidget(f_icon)

            lbl_name = FileNameLabel(row["original_name"])
            lbl_name.setObjectName("CardTitle")
            lbl_name.setToolTip(row["original_name"])
            header_row.addWidget(lbl_name, 1)
            c_layout.addLayout(header_row)

            # Meta row: Subject badge + Kind badge
            chips_row = QHBoxLayout()
            chips_row.setSpacing(6)
            if row["subject_name"]:
                s_chip = QLabel(row["subject_name"])
                s_chip.setObjectName("CardSubjChip")
                chips_row.addWidget(s_chip)

            kind_text = row["kind"] or "سایر"
            k_chip = QLabel(kind_text)
            k_chip.setObjectName("CardKindChip")
            bg, fg = KIND_BADGES.get(kind_text, KIND_BADGES["سایر"])
            k_chip.setStyleSheet(f"background: {bg}; color: {fg};")
            chips_row.addWidget(k_chip)
            chips_row.addStretch(1)
            c_layout.addLayout(chips_row)

            # Footer row: Chapter/Lesson & Size
            foot_row = QHBoxLayout()
            ch_les = chapter_lesson_display(row["chapter"], row["lesson"])
            foot_lbl = QLabel(f"{ch_les}  ·  {human_size(row['size_bytes'])}")
            foot_lbl.setObjectName("CardMeta")
            foot_row.addWidget(foot_lbl)
            foot_row.addStretch(1)
            c_layout.addLayout(foot_row)

            # Double-click to open
            card.mouseDoubleClickEvent = lambda e, r=row: self._open_card_file(r)

            r_idx = idx // cols
            c_idx = idx % cols
            self.card_grid.addWidget(card, r_idx, c_idx)

    def _open_card_file(self, row) -> None:
        stored = row["stored_name"] if "stored_name" in row.keys() else ""
        if not stored:
            self.statusBar().showMessage(tr("err_file_gone"), 3000)
            return
        p = self.lib.stored_path(row)
        if not p.is_file():
            self.statusBar().showMessage(tr("err_file_gone"), 3000)
            self.refresh()
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _update_clear_button(self, text: str) -> None:
        self.clear_search_button.setVisible(bool(text))

    def _show_unclassified(self) -> None:
        self._select_nav_filter(-1, None)

    # ---- catalog view -------------------------------------------------

    def reload_filters(self) -> None:
        prev_subject = self.subject_combo.currentData()
        prev_kind = self.kind_combo.currentData()
        prev_year = self.year_combo.currentData()

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

        for combo, prev in (
            (self.subject_combo, prev_subject),
            (self.kind_combo, prev_kind),
            (self.year_combo, prev_year),
        ):
            idx = combo.findData(prev)
            combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.subject_combo.blockSignals(False)
        self.kind_combo.blockSignals(False)
        self.year_combo.blockSignals(False)
        self._sync_nav_to_filters()

    def _file_icon_for(self, name: str):
        ext = Path(name).suffix.lower()
        if ext in (".zip", ".rar", ".7z", ".tar", ".gz"):
            return self._archive_icon
        if ext == ".darspack":
            return self._package_icon
        if ext == ".pdf":
            return self._pdf_icon
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"):
            return self._image_icon
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
        fid = row["id"]
        stamp = (row["imported_at"], row["size_bytes"])
        cached = self._display_strs.get(fid)
        if cached is None or self._display_stamps.get(fid) != stamp:
            cached = (jalali_date(row["imported_at"]),
                      human_size(row["size_bytes"]))
            self._display_strs[fid] = cached
            self._display_stamps[fid] = stamp
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
        # try/finally: one bad row must never leave the table frozen with
        # repaints disabled for the rest of the session.
        try:
            self.table.setRowCount(len(rows))
            from ..core.normalize import persian_digits
            for i, row in enumerate(rows):
                date_str, size_str = self._display_strs_for(row)
                name = row["original_name"] or "—"
                year_str = str(row["school_year"] or "—")
                values = [name,
                          row["subject_name"] or "—",
                          chapter_lesson_display(row["chapter"], row["lesson"]),
                          row["kind"] or "—", size_str or "—",
                          persian_digits(str(date_str or "—")),
                          persian_digits(year_str)]
                sort_keys = [
                    name.lower(),
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
                        item.setIcon(self._file_icon_for(name))
                        item.setToolTip(name)
                    elif col == 1:
                        item.setToolTip(row["subject_name"] or "—")
                    self.table.setItem(i, col, item)
            active_col = self.table.horizontalHeader().sortIndicatorSection()
            if self.table.horizontalHeader().isSortIndicatorShown() and active_col in self._sort_orders:
                self.table.sortItems(active_col, self._sort_orders[active_col])
        finally:
            self.table.setUpdatesEnabled(True)
        self._update_empty_state(len(rows))
        self._update_action_states()
        # One query for both numbers (B10): the status bar wants the total
        # and the unclassified nudge, and COUNT over the same table twice
        # is a second full scan for a value it already has.
        total_files, unclassified = self.lib.conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(subject_id IS NULL), 0) u "
            "FROM files").fetchone()
        is_filtered = bool(
            self.search_box.text().strip()
            or subject_data is not None
            or self.kind_combo.currentData() is not None
            or year is not None
        )
        if is_filtered and total_files > 0:
            self.count_label.setText(
                tr("status_files_filtered").format(
                    i18n.num(len(rows)), i18n.num(total_files)))
        else:
            self.count_label.setText(
                tr("status_files").format(i18n.num(len(rows))))
        self.unclassified_button.setText(
            tr("status_unclassified").format(i18n.num(unclassified)))
        self.unclassified_button.setVisible(bool(unclassified))

        # Update Navigation Rail unclassified count badge
        if hasattr(self, "nav_unclassified"):
            badge = getattr(self.nav_unclassified, "_badge", None)
            if isinstance(badge, QLabel):
                badge.setText(i18n.num(unclassified))
                badge.setVisible(unclassified > 0)
            else:
                base = getattr(self.nav_unclassified, "_base_label", tr("nav_unclassified"))
                self.nav_unclassified.setText(
                    f"{base} ({i18n.num(unclassified)})" if unclassified > 0 else base
                )

        # If card view is currently active, re-populate cards
        if hasattr(self, "card_scroll") and self.card_scroll.isVisible():
            self._populate_card_grid()

    def _update_action_states(self) -> None:
        """Edit/delete follow the table selection."""
        selected_rows = {i.row() for i in self.table.selectedItems()}
        has_selection = bool(selected_rows)
        self.edit_action.setText(
            tr("bulk_edit_menu") if len(selected_rows) > 1 else tr("btn_edit_meta")
        )
        self.edit_action.setEnabled(has_selection)
        self.delete_action.setEnabled(has_selection)

    def _update_empty_state(self, shown: int) -> None:
        """E2: hide the hint when rows exist; otherwise pick the right
        message — a fresh library vs a search that found nothing. A fresh
        library gets Import + Guide CTAs; a filtered empty state gets Clear."""
        if shown:
            self.empty_label.hide()
            self.empty_button.hide()
            self.empty_guide_button.hide()
            self.empty_clear_button.hide()
            return
        total = self.lib.conn.execute(
            "SELECT COUNT(*) c FROM files").fetchone()["c"]
        fresh = total == 0
        self.empty_label.setText(
            tr("empty_library") if fresh else tr("empty_search"))
        self.empty_button.setVisible(fresh)
        self.empty_guide_button.setVisible(fresh)
        self.empty_clear_button.setVisible(not fresh)
        self._center_empty_label()
        self.empty_label.show()

    def _center_empty_label(self) -> None:
        vp = self.table.viewport()
        self.empty_label.adjustSize()
        show_button = not self.empty_button.isHidden()
        show_guide = not self.empty_guide_button.isHidden()
        show_clear = not self.empty_clear_button.isHidden()
        cta_btn = self.empty_button if show_button else (self.empty_clear_button if show_clear else None)
        gap = 12 if cta_btn is not None else 0
        guide_gap = 8 if (show_button and show_guide) else 0
        button_h = cta_btn.sizeHint().height() if cta_btn is not None else 0
        guide_h = self.empty_guide_button.sizeHint().height() if (show_button and show_guide) else 0
        block_h = self.empty_label.height() + gap + button_h + (guide_gap + guide_h if show_guide and show_button else 0)
        top = max(8, (vp.height() - block_h) // 2)
        center_x = (vp.width() - self.empty_label.width()) // 2
        self.empty_label.move(max(8, center_x), top)
        if cta_btn is not None:
            btn_top = top + self.empty_label.height() + gap
            btn_x = (vp.width() - cta_btn.width()) // 2
            cta_btn.move(max(8, btn_x), btn_top)
            if show_button and show_guide:
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
                # Pass the window as the timer's context object so the
                # timer is cancelled if the window is destroyed first.
                QTimer.singleShot(200, self, self.open_welcome_tour)

    def _apply_dark_titlebar(self) -> None:
        """Apply native Windows 11 Immersive Dark Mode and Mica backdrop."""
        if getattr(self, "_dark_titlebar", False):
            return
        from . import fluent_win32
        if fluent_win32.apply_fluent_window_effects(self):
            self._dark_titlebar = True

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
        nothing. The name column reserves room for icon and ext pill."""
        text = str(index.data(Qt.DisplayRole) or "")
        reserved = 56 if index.column() == 0 else 20
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
        if row is None:
            # M22: the row vanished between the table fill and the click
            # (second instance, or a phone delete while sharing) — say so
            # and refresh instead of crashing on a None row.
            self.statusBar().showMessage(tr("err_file_gone"), 3000)
            self.refresh()
            return
        path = self.lib.stored_path(row)
        if not row["stored_name"] or not path.is_file():
            self.statusBar().showMessage(tr("err_file_gone"), 3000)
            self.refresh()
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

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
            try:
                import ctypes
                from ctypes import wintypes
                ole32 = ctypes.windll.ole32
                ole32.CoInitialize(None)
                shell32 = ctypes.windll.shell32
                shell32.ILCreateFromPathW.restype = ctypes.c_void_p
                shell32.ILCreateFromPathW.argtypes = [wintypes.LPCWSTR]
                shell32.ILFree.argtypes = [ctypes.c_void_p]
                shell32.SHOpenFolderAndSelectItems.argtypes = [
                    ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, wintypes.DWORD]
                abs_str = os.path.abspath(str(path))
                pidl = shell32.ILCreateFromPathW(abs_str)
                if pidl:
                    hr = shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
                    shell32.ILFree(pidl)
                    if hr == 0:
                        return
            except Exception:
                pass
            norm_path = os.path.normpath(str(path))
            try:
                subprocess.Popen(f'explorer.exe /select,"{norm_path}"')
            except (OSError, ValueError):
                # Policy limits / out of resources: open the folder at least.
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
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
        # One query for the whole selection (B14) instead of one per row.
        ids = [r["id"] for r in rows]
        marks = ",".join("?" * len(ids))
        stored = {r["id"]: r["stored_name"] for r in self.lib.conn.execute(
            f"SELECT id, stored_name FROM files WHERE id IN ({marks})", ids)}
        paths = [str(self.lib.files_dir / stored[r["id"]])
                 for r in rows if stored.get(r["id"])]
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

        menu, actions = self.create_row_menu(rows)
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return

        if chosen == actions.get("delete"):
            self.delete_selected_files()
        elif chosen == actions.get("open"):
            self.open_selected_file()
        elif chosen == actions.get("reveal"):
            self.reveal_selected_file()
        elif chosen == actions.get("edit"):
            self.edit_metadata()
        elif chosen == actions.get("copy_name"):
            self.copy_selected_names()
        elif chosen == actions.get("copy_path"):
            self.copy_selected_paths()
        elif chosen == actions.get("bulk"):
            self.bulk_edit_selected()

    def create_row_menu(self, rows: list) -> tuple[QMenu, dict]:
        """Build the localized context menu for the given selected rows."""
        menu = QMenu(self)
        actions = {}

        def add_item(key: str, text: str, icon_name: str | None = None, icon_color: str | None = None):
            act = menu.addAction(text)
            if icon_name and hasattr(act, "setIcon"):
                color = icon_color or theme.PALETTE["text"]
                act.setIcon(icons.icon(icon_name, color, 16))
            actions[key] = act
            return act

        if len(rows) == 1:
            add_item("open", f"{tr('menu_open')}\tEnter", "external-link")
            add_item("reveal", tr("menu_reveal"), "folder-open")
            add_item("edit", f"{tr('btn_edit_meta')}\tCtrl+E", "file-text")
            add_item("copy_name", tr("menu_copy_name"), "copy")
            add_item("copy_path", tr("menu_copy_path"), "link")
        else:
            add_item("bulk", f"{tr('bulk_edit_menu')}\tCtrl+E", "file-text")
            add_item("copy_name", tr("menu_copy_names"), "copy")

        menu.addSeparator()
        add_item("delete", f"{tr('delete_menu')}\tDel", "trash-2", theme.PALETTE["danger"])
        return menu, actions

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
        ids = list(file_ids)
        if ids:
            # One query for the batch (B14) — the delete loop below needs
            # the full row of every file anyway.
            marks = ",".join("?" * len(ids))
            rows_by_id = {row["id"]: row for row in self.lib.conn.execute(
                f"""SELECT f.*, s.name AS subject_name FROM files f
                    LEFT JOIN subjects s ON s.id=f.subject_id
                    WHERE f.id IN ({marks})""", ids)}
            rows = [rows_by_id[fid] for fid in ids if fid in rows_by_id]
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
        # M27: one file locked by another program (a PDF open in a
        # reader is the classic case) used to abort the whole delete
        # with a crash dialog, leaving some files moved and some not
        # with no message about which. Move each file on its own and
        # report the split at the end.
        moved, failed = [], []
        for row in rows:
            try:
                self.lib.move_to_trash(row["id"])
            except (OSError, KeyError, sqlite3.OperationalError):
                failed.append(row["original_name"])
                continue
            moved.append(row)
            self._display_strs.pop(row["id"], None)
            self._display_stamps.pop(row["id"], None)
        self.reload_filters()
        self.refresh()
        if failed and moved:
            message = tr("delete_partial").format(
                moved=i18n.num(len(moved)), failed=i18n.num(len(failed)))
        elif failed:
            message = tr("delete_none_moved")
        elif len(moved) == 1:
            message = tr("delete_done").format(
                name=moved[0]["original_name"])
        else:
            message = tr("delete_done_many").format(
                count=i18n.num(len(moved)))
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
                getattr(self, "_worker_thread", None) is not None
                and self._worker_thread.isRunning()):
            self.statusBar().showMessage(tr("import_running_busy"), 3000)
            return
        self._import_busy = True
        # kwargs (A5): metas/meta_base/cleanup_dir for a ?????? import
        self._worker = ImportWorker(
            str(self.lib.root), paths, keep_duplicates, **kwargs)
        # Bound methods, not lambdas: a lambda connected to a worker
        # signal runs in the WORKER's thread (PySide6 routes a bare
        # callable to the sender object's thread), so a lambda would
        # touch the status bar off the UI thread. A bound method of
        # this window is queued back to the UI thread.
        self._worker.progress.connect(self._import_progress)
        self._worker.done.connect(self._import_finished)
        self._worker_thread = start_worker(self._worker, parent=self)

    def _import_progress(self, done: int, total: int, name: str) -> None:
        self.statusBar().showMessage(
            tr("import_running").format(done, total, name))

    def _import_finished(self, imported, duplicates, errors, messages,
                         new_ids) -> None:
        try:
            # `_import_progress` used a message with no timeout, so it stayed
            # on the status bar forever. Clear it as soon as the worker is
            # done — before the review dialog — so «در حال وارد کردن 1/1» can
            # never outlive the import it describes.
            self.statusBar().clearMessage()
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
            self.statusBar().showMessage(
                tr("import_done_status").format(i18n.num(imported)), 5000)
        finally:
            # The worker deletes itself when its thread finishes — drop
            # the references now, while the object is still alive, so
            # nothing later touches a deleted wrapper.
            self._worker = None
            self._worker_thread = None
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
        # M24: hashing every file in the package used to freeze the
        # whole window with no progress and no cancel.
        self._run_package_worker(
            "verify", path, label=tr("pkg_verifying"),
            on_done=lambda result: dialogs.VerifyReportDialog(
                self, path, result["report"], library=self.lib).exec())

    def import_package(self) -> None:
        """Open a درس‌پک, verify it, offer to import its contents."""
        path, _ = QFileDialog.getOpenFileName(
            self, tr("verify_pick"), "", "ZIP (*.zip)")
        if not path:
            return
        self._run_package_worker(
            "verify", path, label=tr("pkg_verifying"),
            on_done=lambda result: dialogs.VerifyReportDialog(
                self, path, result["report"], library=self.lib,
                offer_import=True).exec())

    def _run_package_worker(self, kind: str, path: str, file_ids=None,
                            label: str = "", on_done=None) -> None:
        """Run a PackageWorker behind a progress dialog (M24).

        `on_done(result)` runs on the UI thread with the worker's
        result dict. Modelled on show_stats / StatsProgressDialog.
        """
        old_thread = getattr(self, "_pkg_thread", None)
        if old_thread is not None and old_thread.isRunning():
            return
        from .workers import PackageWorker
        self._pkg_worker = PackageWorker(str(self.lib.root), kind, path,
                                         file_ids)
        progress = dialogs.PackageProgressDialog(
            self, tr("btn_verify") if kind == "verify" else tr("export_title"),
            label)
        # Kept on self so the bound-method done handler below can find
        # them (see _import_progress for why no lambda is used here).
        self._pkg_progress = progress
        self._pkg_on_done = on_done
        self._pkg_worker.progress.connect(progress.set_progress)
        self._pkg_worker.done.connect(self._package_finished)
        self._pkg_thread = start_worker(self._pkg_worker, parent=self)
        progress.exec()

    def _package_finished(self, result: dict) -> None:
        progress = self._pkg_progress
        on_done = self._pkg_on_done
        if progress is not None:  # Esc may have closed it already
            progress.accept()
        # The worker deletes itself when its thread finishes — drop the
        # references now, while the object is still alive.
        self._pkg_worker = None
        self._pkg_thread = None
        self._pkg_progress = None
        self._pkg_on_done = None
        if result.get("cancelled"):
            self.statusBar().showMessage(tr("pkg_cancelled"), 4000)
            return
        if "error" in result:
            QMessageBox.critical(self, APP_NAME, result["error"])
            return
        if on_done is not None:
            on_done(result)

    def show_duplicates(self) -> None:
        """Duplicates/conflicts/rename hints — three full-library scans.

        They run in a background worker (B17): on a large catalog the
        scans blocked the window long enough to look frozen. The progress
        dialog opens instantly and offers a real cancel, exactly like
        «آمار» (show_stats).
        """
        old_thread = getattr(self, "_dups_thread", None)
        if old_thread is not None and old_thread.isRunning():
            return
        from .workers import DuplicatesWorker
        self._dups_worker = DuplicatesWorker(str(self.lib.root))
        progress = dialogs.StatsProgressDialog(
            self, title_key="dups_title", label_key="dups_computing",
            worker_attr="_dups_worker")
        # Kept on self so the bound-method done handler below can find it
        # (see _import_progress for why no lambda is used here).
        self._dups_progress = progress
        self._dups_worker.done.connect(self._duplicates_finished)
        self._dups_thread = start_worker(self._dups_worker, parent=self)
        progress.exec()          # modal; its cancel stops the worker

    def _duplicates_finished(self, report) -> None:
        progress = self._dups_progress
        if progress is not None:  # Esc may have closed it already
            progress.accept()
        # The worker deletes itself when its thread finishes — drop the
        # references now, while the object is still alive.
        self._dups_worker = None
        self._dups_thread = None
        self._dups_progress = None
        if report is None:       # user cancelled
            return
        dialogs.DuplicatesDialog(self, {
            tr("dups_tab1"): report["groups"],
            tr("dups_tab2"): report["conflicts"],
            tr("dups_tab3"): report["renames"],
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
        old_thread = getattr(self, "_stats_thread", None)
        if old_thread is not None and old_thread.isRunning():
            return
        from .workers import StatsWorker
        self._stats_worker = StatsWorker(str(self.lib.root))
        progress = dialogs.StatsProgressDialog(self)
        # Kept on self so the bound-method done handler below can find
        # it (see _import_progress for why no lambda is used here).
        self._stats_progress = progress
        self._stats_worker.done.connect(self._stats_finished)
        self._stats_thread = start_worker(self._stats_worker, parent=self)
        progress.exec()          # modal; its cancel stops the worker

    def _stats_finished(self, stats) -> None:
        progress = self._stats_progress
        if progress is not None:  # Esc may have closed it already
            progress.accept()
        # The worker deletes itself when its thread finishes — drop the
        # references now, while the object is still alive.
        self._stats_worker = None
        self._stats_thread = None
        self._stats_progress = None
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
        # M22: the row may have vanished since the table was filled —
        # check before building the dialog (it dereferences the row).
        row = self.lib.conn.execute(
            "SELECT id FROM files WHERE id=?", (file_id,)).fetchone()
        if row is None:
            self.statusBar().showMessage(tr("err_file_gone"), 3000)
            self.refresh()
            return
        if dialogs.MetadataDialog(self, self.lib, file_id).exec():
            self.reload_filters()
            self.refresh()

    def open_settings(self) -> None:
        old_library = self.settings.get("library")
        if dialogs.SettingsDialog(self, self.settings,
                                  self.settings_path).exec():
            from .app import apply_font_size
            apply_font_size(self.settings)
            if self.settings.get("library") != old_library:
                self._offer_restart_for_library_change()

    def _offer_restart_for_library_change(self) -> None:
        """The library folder only takes effect after a restart (H6):
        offer to restart now instead of leaving the user wondering why
        nothing changed."""
        answer = QMessageBox.question(
            self, APP_NAME, tr("settings_restart_now"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            from PySide6.QtCore import QProcess
            # From source (`python -m darspack`), sys.argv[0] points directly at
            # __main__.py whose relative imports fail unless invoked with -m.
            launch_args = (sys.argv[1:] if getattr(sys, "frozen", False)
                           else ["-m", "darspack", *sys.argv[1:]])
            QProcess.startDetached(sys.executable, launch_args)
            self.close()
            QApplication.quit()

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
            try:
                with self.lib.conn:
                    db.log(self.lib.conn, "share_start",
                           f"port={self.share_server.port}")
            except sqlite3.OperationalError:
                pass
            # Update Fluent InfoBar banner
            if hasattr(self, "info_bar"):
                self.info_bar_icon.setPixmap(
                    icons.tinted_pixmap("share-2", theme.PALETTE["accent"], 18))
                self.info_bar_label.setText(
                    tr("infobar_share_active").format(pin=i18n.num(self.share_server.pin)))
                self.info_bar.show()
            # The dialog stays open while sharing; whatever closes it
            # (stop button, X) ends the server right after.
            dialogs.ShareDialog(self, self.share_server, urls,
                                on_close=self.stop_share).exec()
            self.stop_share()
        else:
            self.stop_share()

    def stop_share(self, sync: bool = False) -> None:
        """End sharing. Async by default (M12): server.stop() waits out
        in-flight transfers, so it runs on a worker thread while the
        banner shows a "stopping…" state. sync=True is for closeEvent —
        at shutdown the window is already going away, and the worker
        must not outlive the window it belongs to."""
        server = self.share_server
        if server is None:
            return
        self.share_server = None
        from ..core import db
        try:
            with self.lib.conn:
                db.log(self.lib.conn, "share_stop", "")
        except sqlite3.OperationalError:
            pass
        if sync:
            server.stop()
            if hasattr(self, "info_bar"):
                self.info_bar.hide()
            self.refresh()
            return
        if hasattr(self, "info_bar"):
            self.info_bar_label.setText(tr("infobar_share_stopping"))
            self.info_bar.show()
        worker = _StopShareWorker(server)
        # `done` is wired to the slot below (queued to the UI thread);
        # start_worker wires done → thread.quit and deletes both
        # objects when the thread finishes.
        worker.done.connect(self._on_share_stopped)
        self._stop_worker = worker
        self._stop_thread = start_worker(worker, parent=self)

    @Slot()
    def _on_share_stopped(self) -> None:
        # sender() is the _StopShareWorker whose done just fired.
        worker = self.sender()
        if getattr(self, "_stop_worker", None) is worker:
            self._stop_worker = None
            self._stop_thread = None
        # The user may have started sharing again while the old server
        # was still stopping — only hide the banner when nothing is live.
        if self.share_server is None and hasattr(self, "info_bar"):
            self.info_bar.hide()
        self.refresh()

    def closeEvent(self, event) -> None:
        # M12: never destroy a running stop worker with its window —
        # wait for it (the server-side abort bounds this to well under
        # a second in practice), then stop synchronously for a clean exit.
        thread = getattr(self, "_stop_thread", None)
        if thread is not None and thread.isRunning():
            thread.quit()   # thread-safe; lets wait() return once run() ends
            thread.wait()
        self.stop_share(sync=True)   # never leave the server thread running
        self._stop_background_workers()   # never destroy a running QThread
        self.lib.close()
        super().closeEvent(event)

    def _stop_background_workers(self) -> None:
        """Stop every worker thread before the window is destroyed (M21).

        Destroying a QThread while it runs aborts the whole process
        ("QThread: Destroyed while thread is still running"), so the
        window must outlive its workers. Each worker is asked to stop
        and waited on: cancellable workers (import, stats, package)
        stop between steps, so 3 s is plenty; the feedback poster has
        no cancel point and its request times out after 8 s, so it gets
        9 s. The `done` handlers are disconnected first — a worker
        finishing during close must not pop dialogs onto a window that
        is already going away. Workers are plain QObjects on their own
        QThreads (see workers.start_worker); the pairs below are
        (worker, thread).
        """
        pairs = []
        for worker_attr, thread_attr in (("_worker", "_worker_thread"),
                                         ("_stats_worker", "_stats_thread"),
                                         ("_dups_worker", "_dups_thread"),
                                         ("_pkg_worker", "_pkg_thread")):
            worker = getattr(self, worker_attr, None)
            thread = getattr(self, thread_attr, None)
            if thread is not None and thread.isRunning():
                pairs.append((worker, thread))
        # FeedbackPoster threads are parented to the window, not kept
        # in an attribute — find them among the window's QThread children.
        known = {thread for _, thread in pairs}
        for thread in self.findChildren(QThread):
            if thread.isRunning() and thread not in known:
                pairs.append((None, thread))
        for worker, _thread in pairs:
            if worker is None:
                continue
            handler = {"_worker": "_import_finished",
                       "_stats_worker": "_stats_finished",
                       "_dups_worker": "_duplicates_finished",
                       "_pkg_worker": "_package_finished"}
            for attr, slot in handler.items():
                if getattr(self, attr, None) is worker:
                    try:
                        worker.done.disconnect(getattr(self, slot))
                    except (TypeError, RuntimeError):
                        pass
        for worker, _thread in pairs:
            if worker is not None:
                cancel = getattr(worker, "cancel", None)
                if callable(cancel):
                    try:
                        cancel()
                    except Exception:
                        pass
        for worker, thread in pairs:
            # Ask the thread's event loop to exit as soon as the
            # worker's run() returns (quit is thread-safe). Without
            # this, wait() below can time out: the done->quit wiring in
            # start_worker only fires once run() returns, and a worker
            # still mid-file has not emitted done yet.
            thread.quit()
            thread.wait(5000 if worker is not None
                        and hasattr(worker, "cancel") else 10000)