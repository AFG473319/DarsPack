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

from .. import __version__          # for the FeedbackPoster User-Agent
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
        self._cancelled = False

    def cancel(self) -> None:
        """Ask the worker to stop after the file it is currently on.

        Closing the window while an import runs must never destroy a
        running QThread (Qt aborts the process). The flag is checked
        between files; `done` still fires, so the UI never hangs.
        """
        self._cancelled = True

    def run(self) -> None:
        imported = duplicates = errors = 0
        messages: list[str] = []
        new_ids: list[int] = []
        lib = None
        try:
            lib = Library(self.library_root).open()
            files = list(iter_files(self.paths))
            for i, path in enumerate(files, start=1):
                if self._cancelled:
                    break
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


class _PackageCancelled(Exception):
    """Raised from the progress callback to stop verify/export cleanly."""


class PackageWorker(QThread):
    """Verify or export a درس‌پک off the UI thread (M24).

    manifest's verify/export already accept a `progress` callback —
    this worker drives it from the callback, so Cancel works without
    terminating the thread: the callback raises _PackageCancelled, the
    ZIP context manager closes cleanly, and a partial export ZIP is
    deleted before `done` fires. `done` carries one dict:
    {"kind", "report"} for a verify, {"kind", "info"} for an export,
    {"cancelled": True}, or {"error": str}.
    """

    progress = Signal(int, int, str)   # done, total, current file name
    done = Signal(object)

    def __init__(self, library_root, kind: str, path, file_ids=None,
                 parent=None):
        super().__init__(parent)
        self.library_root = library_root
        self.kind = kind
        self.path = str(path)
        self.file_ids = list(file_ids or [])
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _check_cancelled(self) -> None:
        if self._cancelled:
            raise _PackageCancelled()

    def _verify_progress(self, name: str, _arc: str = "") -> None:
        # verify_package calls progress(name, arc) per manifest entry
        self._check_cancelled()
        self.progress.emit(0, 0, name)   # total unknown → indeterminate bar

    def _export_progress(self, done: int, total: int) -> None:
        self._check_cancelled()
        self.progress.emit(done, total, "")

    def run(self) -> None:
        from ..core import manifest as manifest_core

        lib = None
        try:
            if self.kind == "verify":
                report = manifest_core.verify_package(
                    self.path, progress=self._verify_progress)
                self.done.emit({"kind": "verify", "report": report})
            else:
                lib = Library(self.library_root).open()
                info = manifest_core.export_package(
                    lib.conn, lib.files_dir, self.file_ids, self.path,
                    progress=self._export_progress)
                self.done.emit({"kind": "export", "info": info})
        except _PackageCancelled:
            self._discard_partial()
            self.done.emit({"cancelled": True})
        except Exception as exc:
            self._discard_partial()
            self.done.emit({"error": f"{exc.__class__.__name__}: {exc}"})
        finally:
            if lib is not None:
                try:
                    lib.close()
                except Exception:
                    pass

    def _discard_partial(self) -> None:
        """A cancelled/failed export must not leave a half-written ZIP
        that looks like a real package."""
        if self.kind == "export":
            try:
                Path(self.path).unlink(missing_ok=True)
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
    on a 2xx answer within the timeout; anything else (dead Wi-Fi, a
    captive portal, a 4xx/5xx answer, a too-large body) is the same
    False the dialog turns into a «ارسال دوباره» prompt on the UI
    thread. The payload is queued on the device BEFORE this thread
    starts, so a failure never loses feedback — the dialog (not this
    class) drives re-sending. A firmer timeout than a desktop would
    need, because students often are on phone hotspots. The dialog
    parents this thread to the main window, so closing the form never
    deletes a running thread.
    """

    done = Signal(bool)

    def __init__(self, endpoint: str, payload: dict, parent=None,
                 timeout: float = 8):
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
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "User-Agent": "DarsPack/" + __version__,
                },
                method="POST")
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                ok = 200 <= res.status < 300
        except Exception:
            ok = False
        self.done.emit(ok)
