"""Background workers (نخ‌های پس‌زمینه).

Hashing and copying big files can take seconds — running them on the UI
thread would freeze the window. Each worker opens its OWN connection to
the catalog (one connection per thread, WAL mode), does the work, and
reports back via Qt signals.

Error rule: a bad file (locked by another program, unreadable, deleted
mid-import) is counted and reported — it must never kill the worker
thread, because a dead worker means the UI waits for a `done` signal
that never comes (the "stuck on importing" bug, 2026-10-24).
"""
from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.importer import import_file, iter_files
from ..core.library import Library


class ImportWorker(QThread):
    """Import a list of files/folders in the background.

    `done` also carries the ids of the freshly imported files so the UI
    can open the classification review dialog — entering the file info
    is the app's main job, not a side effect.
    """

    progress = Signal(int, int, str)          # done, total, current name
    done = Signal(int, int, int, list, list)  # imported, dups, errors, messages, new ids

    def __init__(self, library_root, paths, keep_duplicates=False, parent=None):
        super().__init__(parent)
        self.library_root = library_root
        self.paths = list(paths)
        self.keep_duplicates = keep_duplicates

    def run(self) -> None:
        imported = duplicates = errors = 0
        messages: list[str] = []
        new_ids: list[int] = []
        lib = None
        try:
            lib = Library(self.library_root).open()
            files = list(iter_files(self.paths))
            for i, path in enumerate(files, start=1):
                self.progress.emit(i, len(files), path.name)
                try:
                    result = import_file(lib, path,
                                         keep_duplicate=self.keep_duplicates)
                except Exception as exc:      # one bad file ≠ a dead batch
                    errors += 1
                    messages.append(f"{path.name}: {exc.__class__.__name__}")
                    continue
                if result.status == "imported":
                    imported += 1
                    new_ids.append(result.file_id)
                elif result.status == "duplicate":
                    duplicates += 1
                else:
                    errors += 1
                    messages.append(result.message_fa)
        except Exception as exc:              # catastrophic — still report
            errors += 1
            messages.append(f"خطای غیرمنتظره: {exc.__class__.__name__}")
            self._write_error_log()
        finally:
            if lib is not None:
                try:
                    lib.close()
                except Exception:
                    pass
            self.done.emit(imported, duplicates, errors, messages, new_ids)

    def _write_error_log(self) -> None:
        """The windowed exe has no console — keep the traceback somewhere."""
        try:
            with open(Path(self.library_root) / "error.log", "a",
                      encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat(timespec='seconds')} "
                        f"import crashed\n{traceback.format_exc()}\n")
        except OSError:
            pass
