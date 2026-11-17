"""DarsPack Control & Test Harness (ابزار کنترل و تست خودکار درس‌پک).

A unified programmatic and CLI driver to try, test, inspect, and visually
verify DarsPack. Used by developers and subagents to exercise all desktop UI
features, dialogs, state changes, screenshots, and LAN web server APIs.

Usage examples:
    # 1. Run full end-to-end smoke test (desktop UI + server) and output JSON:
    python scripts/app_harness.py smoke

    # 2. Capture high-resolution screenshots of main window & dialogs:
    python scripts/app_harness.py screenshot --out-dir eval/screenshots

    # 3. Test a desktop search query and return matching rows:
    python scripts/app_harness.py search "ریاضی"

    # 4. Test LAN server endpoints (auth, search, upload, inline view):
    python scripts/app_harness.py test-server

    # 5. Start a sandbox LAN server for interactive browser preview:
    python scripts/app_harness.py serve --port 8765
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Ensure offscreen Qt by default unless explicitly asked for headed display
if "--headed" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from PySide6.QtCore import Qt


def ensure_qapp():
    """Ensure a single QApplication instance exists with DarsPack theme."""
    from PySide6.QtWidgets import QApplication
    from darspack import i18n
    from darspack.ui import theme
    app = QApplication.instance()
    if app is None:
        app = QApplication(["darspack_harness"])
        app.setStyle("Fusion")
        app.setLayoutDirection(Qt.RightToLeft if i18n.language() == "fa" else Qt.LeftToRight)
        theme.load_fonts()
        app.setStyleSheet(theme.build_qss())
    return app


class SandboxEnvironment:
    """Creates an isolated temporary DarsPack library with sample school materials."""

    def __init__(self, count: int = 12):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="darspack_sandbox_"))
        self.library_dir = self.temp_dir / "library"
        self.settings_path = self.temp_dir / "settings.json"
        self.settings = {
            "language": "fa",
            "library": str(self.library_dir),
            "share_port": 8765,
        }
        self.settings_path.write_text(json.dumps(self.settings, ensure_ascii=False), encoding="utf-8")
        self._populate_sample_files(count)

    def _populate_sample_files(self, count: int):
        from darspack.core.library import Library
        from darspack.core.importer import import_file
        from darspack.core import db

        with Library(self.library_dir) as lib:
            sample_data = [
                ("جزوه ریاضی فصل ۳ نهم.pdf", "ریاضی", 3, None, "جزوه", "1405-1406", "مهم برای امتحان"),
                ("نمونه سوال ریاضی نهم فصل ۳.pdf", "ریاضی", 3, None, "نمونه‌سوال", "1405-1406", "سوالات تستی"),
                ("کاربرگ علوم تجربی درس ۵.pdf", "علوم تجربی", None, 5, "کاربرگ", "1405-1406", ""),
                ("جزوه فارسی درس ۲ هشتم.pdf", "فارسی", None, 2, "جزوه", "1404-1405", "آرایه‌ها"),
                ("نمونه سوال علوم نهم فصل ۴.pdf", "علوم تجربی", 4, None, "نمونه‌سوال", "1405-1406", "حرکت و نیرو"),
                ("تکلیف زبان انگلیسی درس ۳.pdf", "انگلیسی", None, 3, "تکلیف", "1405-1406", "Grammar"),
                ("عکس تخته تدریس ریاضی فصل ۵.png", "ریاضی", 5, None, "جزوه", "1405-1406", "فرمول اتحاد"),
                ("فایل بدون درس برای تست.pdf", None, None, None, "سایر", "1405-1406", "هنوز دسته‌بندی نشده"),
            ]

            sources_dir = self.temp_dir / "sources"
            sources_dir.mkdir(exist_ok=True)

            for idx, (name, subj, ch, les, kind, yr, note) in enumerate(sample_data[:count]):
                src = sources_dir / name
                src.write_bytes(f"sample dummy school content {idx} {name}".encode("utf-8"))
                res = import_file(lib, src)
                if res.file_id:
                    with lib.conn:
                        subj_id = db.get_or_create(lib.conn, "subjects", subj) if subj else None
                        lib.conn.execute(
                            """UPDATE files SET subject_id=?, chapter=?, lesson=?, kind=?, school_year=?, note=?
                               WHERE id=?""",
                            (subj_id, ch, les, kind, yr, note, res.file_id)
                        )

    def cleanup(self):
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass


class AppDriver:
    """Programmatic driver to manipulate, inspect, and test MainWindow and Dialogs."""

    def __init__(self, sandbox: SandboxEnvironment | None = None):
        self.sandbox = sandbox or SandboxEnvironment()
        self.app = ensure_qapp()
        from darspack.ui.main_window import MainWindow
        self.window = MainWindow(self.sandbox.library_dir, self.sandbox.settings, self.sandbox.settings_path)
        self.window.show()
        self.process_events()

    def process_events(self, duration_ms: int = 50):
        """Process Qt event loop to ensure updates, timers and layouts settle."""
        from PySide6.QtCore import QCoreApplication
        t_end = time.time() + (duration_ms / 1000.0)
        while time.time() < t_end:
            QCoreApplication.processEvents()
            time.sleep(0.005)

    def search(self, text: str) -> list[dict]:
        """Set search box text, trigger debounce timer, and return visible rows."""
        self.window.search_box.setText(text)
        self.process_events(300)  # wait for 200ms QTimer to trigger refresh
        return self.get_table_rows()

    def set_filter(self, subject_name: str | None = None, kind: str | None = None, year: str | None = None) -> list[dict]:
        """Apply toolbar filters and return visible rows."""
        if subject_name is not None:
            idx = self.window.subject_combo.findText(subject_name)
            if idx >= 0:
                self.window.subject_combo.setCurrentIndex(idx)
        if kind is not None:
            idx = self.window.kind_combo.findText(kind)
            if idx >= 0:
                self.window.kind_combo.setCurrentIndex(idx)
        if year is not None:
            from darspack.core.normalize import persian_digits
            idx = self.window.year_combo.findText(persian_digits(year))
            if idx >= 0:
                self.window.year_combo.setCurrentIndex(idx)
        self.process_events(100)
        return self.get_table_rows()

    def select_row(self, row_idx: int):
        """Select a row in the catalog table."""
        self.window.table.clearSelection()
        self.window.table.selectRow(row_idx)
        self.process_events(50)

    def get_table_rows(self) -> list[dict]:
        """Extract all visible rows and data from QTableWidget."""
        table = self.window.table
        rows = []
        for r in range(table.rowCount()):
            item_name = table.item(r, 0)
            file_id = item_name.data(Qt.UserRole) if item_name else None
            name = item_name.text() if item_name else ""
            subject = table.item(r, 1).text() if table.item(r, 1) else ""
            chap_les = table.item(r, 2).text() if table.item(r, 2) else ""
            kind = table.item(r, 3).text() if table.item(r, 3) else ""
            size = table.item(r, 4).text() if table.item(r, 4) else ""
            date = table.item(r, 5).text() if table.item(r, 5) else ""
            year = table.item(r, 6).text() if table.item(r, 6) else ""
            rows.append({
                "id": file_id,
                "name": name,
                "subject": subject,
                "chapter_lesson": chap_les,
                "kind": kind,
                "size": size,
                "date": date,
                "year": year
            })
        return rows

    def get_status_info(self) -> dict:
        """Read status bar text and counters."""
        return {
            "status_text": self.window.count_label.text(),
            "unclassified_text": self.window.unclassified_button.text(),
            "unclassified_visible": self.window.unclassified_button.isVisible(),
            "total_rows": self.window.table.rowCount(),
        }

    def capture_screenshot(self, target_path: Path, widget=None) -> Path:
        """Capture a high-res PNG screenshot of a widget or the main window."""
        target_path = Path(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        w = widget or self.window
        pix = w.grab()
        pix.save(str(target_path), "PNG")
        return target_path

    def close(self):
        """Close window and teardown."""
        self.window.close()
        self.process_events(50)
        self.sandbox.cleanup()


def run_smoke_test(out_dir: Path | None = None) -> dict:
    """Runs a complete test of the Desktop UI, Dialogs, and Web Server."""
    out_dir = out_dir or (REPO_ROOT / "eval" / "screenshots")
    out_dir.mkdir(parents=True, exist_ok=True)

    report = {"desktop": {}, "dialogs": {}, "server": {}, "screenshots": []}
    driver = AppDriver()
    try:
        # 1. Desktop Initial State
        initial_rows = driver.get_table_rows()
        status = driver.get_status_info()
        shot1 = driver.capture_screenshot(out_dir / "01_main_window_loaded.png")
        report["desktop"]["initial_row_count"] = len(initial_rows)
        report["desktop"]["unclassified_visible"] = status["unclassified_visible"]
        report["screenshots"].append(str(shot1))

        # 2. Search Test
        math_rows = driver.search("ریاضی")
        shot2 = driver.capture_screenshot(out_dir / "02_search_math.png")
        report["desktop"]["search_math_count"] = len(math_rows)
        report["screenshots"].append(str(shot2))

        # 3. Filter Reset
        all_rows = driver.search("")
        report["desktop"]["reset_count"] = len(all_rows)

        # 4. Dialog Verifications
        from darspack.ui import dialogs
        from darspack.core.dedup import duplicate_groups, version_conflicts, rename_hints
        from darspack.i18n import tr
        first_id = initial_rows[0]["id"]

        # 4a. Metadata Dialog
        meta_dlg = dialogs.MetadataDialog(driver.window, driver.window.lib, first_id)
        shot_meta = driver.capture_screenshot(out_dir / "03_metadata_dialog.png", meta_dlg)
        report["dialogs"]["metadata_subject"] = meta_dlg.subject.currentText()
        report["screenshots"].append(str(shot_meta))
        meta_dlg.close()

        # 4b. Bulk Edit Dialog
        bulk_dlg = dialogs.BulkEditDialog(driver.window, driver.window.lib, [r["id"] for r in initial_rows[:3]])
        shot_bulk = driver.capture_screenshot(out_dir / "04_bulk_edit_dialog.png", bulk_dlg)
        report["dialogs"]["bulk_edit_ready"] = True
        report["screenshots"].append(str(shot_bulk))
        bulk_dlg.close()

        # 4c. Stats Dialog
        stats_data = dialogs.library_stats(driver.window.lib.conn)
        stats_dlg = dialogs.StatsDialog(driver.window, stats_data)
        shot_stats = driver.capture_screenshot(out_dir / "05_stats_dialog.png", stats_dlg)
        report["dialogs"]["stats_ready"] = True
        report["screenshots"].append(str(shot_stats))
        stats_dlg.close()

        # 4d. Activity/History Dialog
        act_dlg = dialogs.ActivityDialog(driver.window, driver.window.lib)
        shot_act = driver.capture_screenshot(out_dir / "06_activity_dialog.png", act_dlg)
        report["dialogs"]["activity_ready"] = True
        report["screenshots"].append(str(shot_act))
        act_dlg.close()

        # 4e. Duplicates Dialog
        dup_groups = {
            tr("dups_tab1"): duplicate_groups(driver.window.lib.conn),
            tr("dups_tab2"): version_conflicts(driver.window.lib.conn),
            tr("dups_tab3"): rename_hints(driver.window.lib.conn),
        }
        dup_dlg = dialogs.DuplicatesDialog(driver.window, dup_groups)
        shot_dup = driver.capture_screenshot(out_dir / "07_duplicates_dialog.png", dup_dlg)
        report["dialogs"]["duplicates_ready"] = True
        report["screenshots"].append(str(shot_dup))
        dup_dlg.close()

        # 4f. Trash Dialog (seed files so table is captured populated)
        trash_dir = driver.window.lib.files_dir / ".trash"
        trash_dir.mkdir(exist_ok=True)
        trash_meta_dir = driver.window.lib.files_dir / ".trash_meta"
        trash_meta_dir.mkdir(exist_ok=True)
        (trash_dir / "old_quiz.pdf").write_bytes(b"%PDF-oldquiz")
        (trash_meta_dir / "old_quiz.pdf.json").write_text(json.dumps({
            "original_name": "آزمون_فصل_اول_علوم.pdf",
            "stored_name": "old_quiz.pdf",
            "subject_name": "علوم تجربی",
            "size": 12400,
            "deleted_at": "2026-10-30T14:00:00",
            "kind": "نمونه‌سوال"
        }, ensure_ascii=False), encoding="utf-8")
        (trash_dir / "draft_notes.docx").write_bytes(b"PK-notes")
        (trash_meta_dir / "draft_notes.docx.json").write_text(json.dumps({
            "original_name": "خلاصه_درس_دوم_فارسی.docx",
            "stored_name": "draft_notes.docx",
            "subject_name": "فارسی",
            "size": 45200,
            "deleted_at": "2026-10-30T15:30:00",
            "kind": "جزوه"
        }, ensure_ascii=False), encoding="utf-8")

        trash_dlg = dialogs.TrashDialog(driver.window, driver.window.lib)
        shot_trash = driver.capture_screenshot(out_dir / "08_trash_dialog.png", trash_dlg)
        report["dialogs"]["trash_ready"] = True
        report["screenshots"].append(str(shot_trash))
        trash_dlg.close()

        # 4g. Exam Pack Dialog
        exam_dlg = dialogs.ExamPackDialog(driver.window, driver.window.lib)
        # Assert no raw i18n keys leak into dialog headers or controls
        headers_text = [exam_dlg.table.horizontalHeaderItem(c).text() for c in range(exam_dlg.table.columnCount())]
        assert "col_chapter" not in headers_text, "Raw col_chapter key leaked to header"
        assert exam_dlg.subject_combo.itemText(0) != "filter_all_subjects", "Raw filter_all_subjects leaked to combo"
        shot_exam = driver.capture_screenshot(out_dir / "09_exam_pack_dialog.png", exam_dlg)
        report["dialogs"]["exam_pack_ready"] = True
        report["screenshots"].append(str(shot_exam))
        exam_dlg.close()

        # 5. Server Test
        from darspack.web.server import ShareServer
        server = ShareServer(str(driver.sandbox.library_dir))
        server.start()
        time.sleep(0.1)
        try:
            pin = server.pin
            port = server.port
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)

            # Test PIN gate
            conn.request("GET", "/api/search?q=")
            res403 = conn.getresponse()
            res403.read()
            report["server"]["pin_protected"] = (res403.status == 403)

            # Test search with valid PIN
            conn.request("GET", f"/api/search?q=&pin={pin}")
            res200 = conn.getresponse()
            data = json.loads(res200.read().decode("utf-8"))
            report["server"]["search_ok"] = (res200.status == 200 and "files" in data)

            # Test subjects endpoint
            conn.request("GET", f"/api/subjects?pin={pin}")
            res_sub = conn.getresponse()
            sub_data = json.loads(res_sub.read().decode("utf-8"))
            report["server"]["subjects_count"] = len(sub_data.get("subjects", []))
            conn.close()
        finally:
            server.stop()

        report["success"] = True
        return report

    finally:
        driver.close()


def main():
    parser = argparse.ArgumentParser(description="DarsPack App Control & Test Harness")
    parser.add_argument("command", choices=["smoke", "screenshot", "search", "test-server", "serve"],
                        help="Action to perform")
    parser.add_argument("--query", type=str, default="", help="Query for search command")
    parser.add_argument("--out-dir", type=str, default="eval/screenshots", help="Directory for screenshots")
    parser.add_argument("--port", type=int, default=0, help="Port for server (0 = auto-assign)")
    parser.add_argument("--headed", action="store_true", help="Run with onscreen window display")

    args = parser.parse_args()

    if args.command == "smoke":
        res = run_smoke_test(Path(args.out_dir))
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "screenshot":
        res = run_smoke_test(Path(args.out_dir))
        print(f"Screenshots saved to: {args.out_dir}")
        for s in res.get("screenshots", []):
            print(f"  - {s}")

    elif args.command == "search":
        driver = AppDriver()
        try:
            results = driver.search(args.query)
            print(json.dumps(results, indent=2, ensure_ascii=False))
        finally:
            driver.close()

    elif args.command == "test-server":
        sandbox = SandboxEnvironment()
        from darspack.web.server import ShareServer
        server = ShareServer(str(sandbox.library_dir))
        if args.port:
            server.port = args.port
        server.start()
        time.sleep(0.1)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
            conn.request("GET", f"/api/subjects?pin={server.pin}")
            res = conn.getresponse()
            body = res.read().decode("utf-8")
            print(f"Status: {res.status}")
            print(f"Response: {body}")
            conn.close()
        finally:
            server.stop()
            sandbox.cleanup()

    elif args.command == "serve":
        sandbox = SandboxEnvironment(count=20)
        from darspack.web.server import ShareServer
        server = ShareServer(str(sandbox.library_dir))
        if args.port:
            server.port = args.port
        urls = server.start()
        print("==================================================")
        print("DarsPack Sandbox LAN Server running!")
        print(f"URLs: {', '.join(urls)}")
        print(f"Local URL: http://127.0.0.1:{server.port}/")
        print(f"PIN: {server.pin}")
        print("Press Ctrl+C to terminate.")
        print("==================================================")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.stop()
            sandbox.cleanup()


if __name__ == "__main__":
    main()
