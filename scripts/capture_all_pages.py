# -*- coding: utf-8 -*-
"""Generate high-resolution screenshots of every page, dialog, and tab in DarsPack."""
import json
import os
import sys
import time
from pathlib import Path

# Run in offscreen mode
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTabWidget

from darspack import i18n
from darspack.core import db
from darspack.core.dedup import duplicate_groups, version_conflicts, rename_hints
from darspack.core.library import Library
from darspack.core.importer import import_file
from darspack.core.manifest import VerifyReport
from darspack.ui import dialogs, theme
from darspack.ui.dialogs import library_stats
from scripts.app_harness import AppDriver, SandboxEnvironment, ensure_qapp


class DummyServer:
    def __init__(self, pin=481920):
        self.pin = pin


def generate_all_screenshots(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    app = ensure_qapp()

    sandbox = SandboxEnvironment(count=8)
    driver = AppDriver(sandbox)

    try:
        lib = driver.window.lib
        # Seed extra rich data for the dialogs
        with lib.conn:
            # Seed activity log rows
            db.log(lib.conn, "import", "۳ فایل جدید وارد شد")
            db.log(lib.conn, "classify", "دسته‌بندی خودکار انجام شد")
            db.log(lib.conn, "export", "بسته شب امتحان ریاضی خروجی گرفته شد")
            db.log(lib.conn, "share_start", "سرور اشتراک شبکه روشن شد")

            # Seed learned hint rules (for ActivityDialog Tab 2)
            lib.conn.execute(
                "INSERT OR REPLACE INTO hint_rules (token, subject_id, hits, last_used) VALUES (?, ?, ?, ?)",
                ("حسابان", 1, 5, "2026-10-30T10:00:00")
            )
            lib.conn.execute(
                "INSERT OR REPLACE INTO hint_rules (token, subject_id, hits, last_used) VALUES (?, ?, ?, ?)",
                ("هندسه", 1, 3, "2026-10-30T11:00:00")
            )
            lib.conn.execute(
                "INSERT OR REPLACE INTO hint_rules (token, subject_id, hits, last_used) VALUES (?, ?, ?, ?)",
                ("زیست", 2, 4, "2026-10-30T12:00:00")
            )

        # Seed trash files with sidecars
        trash_dir = lib.files_dir / ".trash"
        trash_dir.mkdir(exist_ok=True)
        trash_meta_dir = lib.files_dir / ".trash_meta"
        trash_meta_dir.mkdir(exist_ok=True)
        (trash_dir / "quiz1.pdf").write_bytes(b"%PDF-quiz1")
        (trash_meta_dir / "quiz1.pdf.json").write_text(json.dumps({
            "original_name": "آزمون_مستمر_علوم_تجربی.pdf",
            "stored_name": "quiz1.pdf",
            "subject_name": "علوم تجربی",
            "size": 24500,
            "deleted_at": "2026-10-30T14:20:00",
            "kind": "نمونه‌سوال",
            "tags": ["امتحان", "مهم"]
        }, ensure_ascii=False), encoding="utf-8")
        (trash_dir / "notes_fa.docx").write_bytes(b"PK-notesfa")
        (trash_meta_dir / "notes_fa.docx.json").write_text(json.dumps({
            "original_name": "نکات_کلیدی_ادبیات_درس۳.docx",
            "stored_name": "notes_fa.docx",
            "subject_name": "فارسی",
            "size": 58900,
            "deleted_at": "2026-10-30T16:15:00",
            "kind": "جزوه",
            "tags": ["نکات", "درس۳"]
        }, ensure_ascii=False), encoding="utf-8")

        # Refresh main window
        driver.window.refresh()
        driver.process_events(100)

        results = []

        def snap(filename: str, widget, title: str):
            p = out_dir / filename
            driver.process_events(50)
            driver.capture_screenshot(p, widget)
            results.append((filename, str(p.resolve()), title))
            print(f"Captured: {filename} - {title}")

        # 1. Main Window - Catalog View
        snap("01_main_window_catalog.png", driver.window, "Main Window - Catalog View")

        # 2. Main Window - Search View
        driver.search("ریاضی")
        snap("02_main_window_search.png", driver.window, "Main Window - Search Filtered View")
        driver.window.search_box.clear()
        driver.process_events(250)

        # 3. Import Dialog
        imp_dlg = dialogs.ImportDialog(driver.window)
        imp_dlg.show()
        snap("03_import_dialog.png", imp_dlg, "Import Dialog")
        imp_dlg.close()

        # 4. Classify Dialog
        file_ids = [r["id"] for r in lib.conn.execute("SELECT id FROM files LIMIT 3")]
        classify_dlg = dialogs.ClassifyDialog(driver.window, lib, file_ids)
        classify_dlg.show()
        snap("04_classify_dialog.png", classify_dlg, "Classify Review Dialog")
        classify_dlg.close()

        # 5. Metadata Dialog (Single File)
        if file_ids:
            meta_dlg = dialogs.MetadataDialog(driver.window, lib, file_ids[0])
            meta_dlg.show()
            snap("05_metadata_dialog.png", meta_dlg, "Metadata Edit Dialog (Single File)")
            meta_dlg.close()

        # 6. Bulk Edit Dialog (Multiple Files)
        if len(file_ids) >= 2:
            bulk_dlg = dialogs.BulkEditDialog(driver.window, lib, file_ids)
            bulk_dlg.show()
            snap("06_bulk_edit_dialog.png", bulk_dlg, "Bulk Edit Dialog (Multiple Files)")
            bulk_dlg.close()

        # 7. Stats Dialog
        stats_data = library_stats(lib.conn)
        stats_dlg = dialogs.StatsDialog(driver.window, stats_data)
        stats_dlg.show()
        snap("07_stats_dialog.png", stats_dlg, "Library Stats Dialog")
        stats_dlg.close()

        # 8 & 9. Activity & History Dialog - Tab 1 and Tab 2
        act_dlg = dialogs.ActivityDialog(driver.window, lib)
        act_dlg.show()
        act_tabs = act_dlg.findChild(QTabWidget)
        if act_tabs:
            act_tabs.setCurrentIndex(0)
            driver.process_events(50)
            snap("08_activity_tab1_history.png", act_dlg, "Activity Dialog - Tab 1: Activity History (تاریخچه‌ی فعالیت‌ها)")
            act_tabs.setCurrentIndex(1)
            driver.process_events(50)
            snap("09_activity_tab2_rules.png", act_dlg, "Activity Dialog - Tab 2: Learned Rules (قانون‌های یادگرفته‌شده)")
        act_dlg.close()

        # 10, 11, 12. Duplicates & Conflicts Dialog - Tab 1, 2, 3
        dup_groups = {
            i18n.tr("dups_tab1"): duplicate_groups(lib.conn),
            i18n.tr("dups_tab2"): version_conflicts(lib.conn),
            i18n.tr("dups_tab3"): rename_hints(lib.conn),
        }
        dup_dlg = dialogs.DuplicatesDialog(driver.window, dup_groups)
        dup_dlg.show()
        dup_tabs = dup_dlg.findChild(QTabWidget)
        if dup_tabs:
            dup_tabs.setCurrentIndex(0)
            driver.process_events(50)
            snap("10_duplicates_tab1_exact.png", dup_dlg, "Duplicates Dialog - Tab 1: Exact Duplicates (تکراری کامل)")
            dup_tabs.setCurrentIndex(1)
            driver.process_events(50)
            snap("11_duplicates_tab2_conflicts.png", dup_dlg, "Duplicates Dialog - Tab 2: Version Conflicts (نسخه‌های متفاوت، نام یکسان)")
            dup_tabs.setCurrentIndex(2)
            driver.process_events(50)
            snap("12_duplicates_tab3_renames.png", dup_dlg, "Duplicates Dialog - Tab 3: Rename Hints (یک محتوا، نام‌های مختلف)")
        dup_dlg.close()

        # 13. Network Share Dialog
        dummy_server = DummyServer(pin=481920)
        share_dlg = dialogs.ShareDialog(
            driver.window, dummy_server, ["http://192.168.1.105:8765", "http://127.0.0.1:8765"], lambda: None)
        share_dlg.show()
        snap("13_share_dialog.png", share_dlg, "Network Share Dialog (Pairing PIN & QR Code)")
        share_dlg.close()

        # 14 & 15. Settings Dialog - General & Advanced
        settings_dlg = dialogs.SettingsDialog(driver.window, sandbox.settings, sandbox.settings_path)
        settings_dlg.show()
        snap("14_settings_dialog_general.png", settings_dlg, "Settings Dialog - General View")
        settings_dlg.advanced.setChecked(True)
        driver.process_events(50)
        snap("15_settings_dialog_advanced.png", settings_dlg, "Settings Dialog - Advanced Settings (API Endpoints Expanded)")
        settings_dlg.close()

        # 16. Feedback Dialog
        fb_dlg = dialogs.FeedbackDialog(driver.window, sandbox.settings)
        fb_dlg.show()
        fb_dlg._set_stars(4)
        snap("16_feedback_dialog.png", fb_dlg, "Feedback Dialog")
        fb_dlg.close()

        # 17. Package Export Dialog
        export_dlg = dialogs.ExportDialog(driver.window, file_ids[:2])
        export_dlg.show()
        snap("17_export_dialog.png", export_dlg, "Package Export Dialog")
        export_dlg.close()

        # 18. Package Verify Report Dialog
        verify_report = VerifyReport(ok=True)
        verify_dlg = dialogs.VerifyReportDialog(
            driver.window, "sample_package.zip", verify_report, lib, offer_import=True)
        verify_dlg.show()
        snap("18_verify_report_dialog.png", verify_dlg, "Package Verify Report Dialog")
        verify_dlg.close()

        # 19. Trash Bin Dialog
        trash_dlg = dialogs.TrashDialog(driver.window, lib)
        trash_dlg.show()
        snap("19_trash_dialog.png", trash_dlg, "Trash Bin Viewer (Safe Restore)")
        trash_dlg.close()

        # 20. Exam Revision Pack Builder
        exam_dlg = dialogs.ExamPackDialog(driver.window, lib)
        exam_dlg.show()
        snap("20_exam_pack_dialog.png", exam_dlg, "Exam Revision Pack Builder")
        exam_dlg.close()

        # 21. Welcome/Onboarding Dialog - All 3 slides
        welcome_dlg = dialogs.WelcomeDialog(driver.window, sandbox.settings, sandbox.settings_path)
        welcome_dlg.show()
        driver.process_events(50)
        snap("21_welcome_slide1.png", welcome_dlg, "Welcome Dialog - Slide 1: Safe Local Library")
        welcome_dlg.stack.setCurrentIndex(1)
        driver.process_events(50)
        snap("22_welcome_slide2.png", welcome_dlg, "Welcome Dialog - Slide 2: Smart Classification")
        welcome_dlg.stack.setCurrentIndex(2)
        driver.process_events(50)
        snap("23_welcome_slide3.png", welcome_dlg, "Welcome Dialog - Slide 3: Offline & Phone Sharing")
        welcome_dlg.close()

        # 24-28. Help Center Dialog - All 5 tabs
        help_dlg = dialogs.HelpDialog(driver.window, sandbox.settings, sandbox.settings_path)
        help_dlg.show()
        driver.process_events(50)
        help_tabs = help_dlg.tabs
        help_tabs.setCurrentIndex(0)
        driver.process_events(50)
        snap("24_help_tab1_quick.png", help_dlg, "Help Center - Tab 1: Quick Guide")
        help_tabs.setCurrentIndex(1)
        driver.process_events(50)
        snap("25_help_tab2_shortcuts.png", help_dlg, "Help Center - Tab 2: Keyboard Shortcuts")
        help_tabs.setCurrentIndex(2)
        driver.process_events(50)
        snap("26_help_tab3_phone.png", help_dlg, "Help Center - Tab 3: Phone Sharing Guide")
        help_tabs.setCurrentIndex(3)
        driver.process_events(50)
        snap("27_help_tab4_mcp.png", help_dlg, "Help Center - Tab 4: AI & MCP Integration Guide")
        help_tabs.setCurrentIndex(4)
        driver.process_events(50)
        snap("28_help_tab5_faq.png", help_dlg, "Help Center - Tab 5: FAQ")
        help_dlg.close()

        # 29-33. Context and Dropdown Menus
        # Single row table context menu
        table_rows = driver.get_table_rows()
        if table_rows:
            menu_single, _ = driver.window.create_row_menu([table_rows[0]])
            menu_single.adjustSize()
            menu_single.show()
            driver.process_events(50)
            snap("29_menu_table_single.png", menu_single, "Context Menu - Single File Selected")
            menu_single.close()

            if len(table_rows) >= 2:
                menu_multi, _ = driver.window.create_row_menu(table_rows[:2])
                menu_multi.adjustSize()
                menu_multi.show()
                driver.process_events(50)
                snap("30_menu_table_multi.png", menu_multi, "Context Menu - Multiple Files Selected")
                menu_multi.close()

        # Search box context menu
        from darspack.ui.main_window import create_localized_line_edit_context_menu
        driver.window.search_box.setText("ریاضی")
        search_menu = create_localized_line_edit_context_menu(
            driver.window.search_box, driver.window, include_clear=True
        )
        search_menu.adjustSize()
        search_menu.show()
        driver.process_events(50)
        snap("31_menu_search_box.png", search_menu, "Context Menu - Search Box")
        search_menu.close()
        driver.window.search_box.clear()

        # Packages dropdown menu
        driver.window.packages_menu.adjustSize()
        driver.window.packages_menu.show()
        driver.process_events(50)
        snap("32_menu_packages.png", driver.window.packages_menu, "Dropdown Menu - Packages")
        driver.window.packages_menu.close()

        # More actions dropdown menu
        driver.window.more_menu.adjustSize()
        driver.window.more_menu.show()
        driver.process_events(50)
        snap("33_menu_more_actions.png", driver.window.more_menu, "Dropdown Menu - More Actions")
        driver.window.more_menu.close()

        return results

    finally:
        driver.close()


if __name__ == "__main__":
    out = REPO_ROOT / "eval" / "screenshots" / "all_pages"
    res = generate_all_screenshots(out)
    print(f"\nAll {len(res)} screenshots successfully captured in {out}")
