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

import shutil
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

    A5 (package import): `metas` maps a path relative to `meta_base` to
    a درس‌پک manifest entry; matching files are imported with
    meta={kind, chapter, lesson, school_year} applied like filename
    suggestions, and the manifest's subject/tags come back (pre-fill
    only, never stored) as `result_prefills` for the classify dialog.
    `cleanup_dir` (the extracted package's temp folder) is removed by
    the worker after `done` — the dialog that extracted it returns
    immediately, so someone who outlives it must own the cleanup.
    """

    progress = Signal(int, int, str)          # done, total, current name
    done = Signal(int, int, int, list, list)  # imported, dups, errors, messages, new ids

    def __init__(self, library_root, paths, keep_duplicates=False, parent=None,
                 metas=None, meta_base=None, cleanup_dir=None):
        super().__init__(parent)
        self.library_root = library_root
        self.paths = list(paths)
        self.keep_duplicates = keep_duplicates
        self.metas = metas
        self.meta_base = Path(meta_base) if meta_base else None
        self.cleanup_dir = Path(cleanup_dir) if cleanup_dir else None
        self.result_prefills: dict = {}      # file_id → {"subject", "tags"}

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
                                         meta=self._meta_for(path),
                                         keep_duplicate=self.keep_duplicates)
                except Exception as exc:      # one bad file ≠ a dead batch
                    errors += 1
                    messages.append(f"{path.name}: {exc.__class__.__name__}")
                    continue
                if result.status == "imported":
                    imported += 1
                    new_ids.append(result.file_id)
                    if result.prefill:
                        self.result_prefills[result.file_id] = result.prefill
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
            if self.cleanup_dir is not None:
                shutil.rmtree(self.cleanup_dir, ignore_errors=True)

    def _meta_for(self, path: Path) -> dict | None:
        """The manifest entry for this extracted file, keyed by its path
        relative to the extracted files/ folder (A5)."""
        if self.metas is None:
            return None
        try:
            key = str(path.relative_to(self.meta_base))
        except (ValueError, TypeError):
            key = path.name
        return self.metas.get(key)

    def _write_error_log(self) -> None:
        """The windowed exe has no console — keep the traceback somewhere."""
        try:
            with open(Path(self.library_root) / "error.log", "a",
                      encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat(timespec='seconds')} "
                        f"import crashed\n{traceback.format_exc()}\n")
        except OSError:
            pass


class StatsWorker(QThread):
    """Compute library stats off the UI thread (the «آمار» dialog).

    Opens its OWN Library (one connection per thread), runs the indexed
    stats queries, emits the dict — or None if the user cancelled.
    """

    done = Signal(object)                     # stats dict, or None on cancel

    def __init__(self, library_root, parent=None):
        super().__init__(parent)
        self.library_root = library_root
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        stats = None
        lib = None
        try:
            lib = Library(self.library_root).open()
            if not self._cancelled:
                from ..ui.dialogs import library_stats
                stats = library_stats(lib.conn)
        except Exception:
            stats = None                      # cancelled or failed: no dialog
        finally:
            if lib is not None:
                try:
                    lib.close()
                except Exception:
                    pass
            self.done.emit(stats if not self._cancelled else None)


class FeedbackPoster(QThread):
    """POST one feedback payload to the configured endpoint (background).

    Network must never run on the UI thread. done(ok: bool) — True only
    on a 2xx answer within the timeout. The payload is saved locally
    BEFORE this thread starts, so a failure never loses feedback.
    """

    done = Signal(bool)

    def __init__(self, endpoint: str, payload: dict, parent=None, timeout: float = 5.0):
        super().__init__(parent)
        self.endpoint = endpoint
        self.payload = payload
        self.timeout = timeout

    def run(self) -> None:
        import json as _json
        import urllib.request
        try:
            req = urllib.request.Request(
                self.endpoint,
                data=_json.dumps(self.payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                ok = 200 <= res.status < 300
        except Exception:
            ok = False
        self.done.emit(ok)
