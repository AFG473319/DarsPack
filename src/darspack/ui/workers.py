"""Background workers (نخ‌های پس‌زمینه).

Hashing and copying big files can take seconds — running them on the UI
thread would freeze the window. Each worker opens its OWN connection to
the catalog (one connection per thread, WAL mode), does the work, and
reports back via Qt signals. The UI thread only ever reads fresh rows
after the worker finishes.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..core.importer import import_file, iter_files
from ..core.library import Library


class ImportWorker(QThread):
    """Import a list of files/folders in the background."""

    progress = Signal(int, int, str)          # done, total, current name
    done = Signal(int, int, int, list)        # imported, duplicates, errors, messages

    def __init__(self, library_root, paths, keep_duplicates=False, parent=None):
        super().__init__(parent)
        self.library_root = library_root
        self.paths = list(paths)
        self.keep_duplicates = keep_duplicates

    def run(self) -> None:
        lib = Library(self.library_root).open()
        imported = duplicates = errors = 0
        messages: list[str] = []
        files = list(iter_files(self.paths))
        for i, path in enumerate(files, start=1):
            self.progress.emit(i, len(files), path.name)
            result = import_file(lib, path, keep_duplicate=self.keep_duplicates)
            if result.status == "imported":
                imported += 1
            elif result.status == "duplicate":
                duplicates += 1
            else:
                errors += 1
                messages.append(result.message_fa)
        lib.close()
        self.done.emit(imported, duplicates, errors, messages)
