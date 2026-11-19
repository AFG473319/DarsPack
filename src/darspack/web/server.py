"""Opt-in LAN web server (سرور شبکه‌ی محلی).

Runs ONLY while the user keeps sharing enabled, guarded by a random
per-session PIN. Bound to all interfaces so a phone on the same Wi-Fi
can reach it; it never initiates any connection and nothing leaves the
LAN. Every /api call must carry ?pin=; wrong PIN 5 times → 30 s lockout
for that IP (hmac.compare_digest, not ==, so timing cannot leak the
PIN). Uploads arrive as a raw body (no multipart) and go through the
normal importer — hash, duplicate check, suggestions, activity log.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import asset_path
from ..core.library import Library

_ICON_TYPES = {
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
}
_FONT_FILES = {
    "Vazirmatn-Regular.ttf",
    "Vazirmatn-Medium.ttf",
    "Vazirmatn-SemiBold.ttf",
    "Vazirmatn-Bold.ttf",
}


def _open_server_library(root: str) -> Library:
    """Open a library for a server thread WITHOUT the maintenance passes (F1).

    Every phone request used to pay a fresh Library.open() — schema init,
    orphan sweep, health check — ~120–150 ms each, and the orphan sweep
    even raced in-flight uploads (it could delete a temp file another
    thread was still importing). The desktop app always opened this
    library first, so the schema already exists and the server threads
    only need to read/query.
    """
    return Library(root, maintain=False).open()

CLIENT_DIR: Path
if getattr(sys, "frozen", False):
    # PyInstaller build: data files unpack under sys._MEIPASS
    CLIENT_DIR = Path(sys._MEIPASS) / "darspack" / "web" / "client"
else:
    CLIENT_DIR = Path(__file__).parent / "client"
MAX_UPLOAD = 200 * 1024 * 1024          # 200 MB — bigger files via USB
LOCKOUT_SECONDS = 30
MAX_FAILS = 5
SEARCH_LIMIT = 300          # phone search page (M30: the API also reports
                            # the total, so the cap is never shown as "all")
SHARE_TTL_SECONDS = 30 * 60  # H2: sharing stops by itself after 30 min —
                            # a PIN left alive overnight is a PIN left on
                            # the school network
_DISK_RESERVE = 10 * 1024 * 1024   # M10: keep 10 MB free besides the
                            # upload itself (temp staging + catalog growth).
                            # Deliberately small: a big reserve would refuse
                            # every upload on a nearly-full scratch disk
                            # (the test tmpfs is only 512 MB) even for a
                            # tiny file — the check must catch a *full*
                            # disk, not a merely busy one.

# M10: never let a phone upload an executable or script into the library —
# a classmate taps "download" once and runs it. School files are documents,
# images and archives; code has no business here. Checked on the suffix
# only (a double extension like "notes.pdf.exe" is still .exe).
_BLOCKED_UPLOAD_EXTS = frozenset({
    ".exe", ".dll", ".sys", ".drv", ".com", ".scr", ".cpl", ".ocx",
    ".bat", ".cmd", ".ps1", ".psm1", ".psd1", ".vbs", ".vbe", ".js",
    ".jse", ".wsf", ".wsh", ".hta", ".msi", ".msp", ".msm", ".apk",
    ".appx", ".appxbundle", ".msix", ".msixbundle", ".gadget", ".jar",
    ".py", ".pyw", ".pyc", ".sh", ".bash", ".zsh", ".pl", ".rb", ".php",
    ".reg", ".inf", ".lnk", ".pif", ".application", ".scf", ".sct",
})


_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    """Parse a single-byte-range header (M11: download resume).

    Returns (start, end) inclusive, or None when the range is
    unsatisfiable or not a single range. Suffix ranges ("bytes=-500",
    the last 500 bytes) and open ranges ("bytes=500-") are supported;
    multi-range requests are not — the caller answers 416 for them.
    """
    if "," in header:
        return None
    m = _RANGE_RE.match(header.strip())
    if m is None or size <= 0:
        return None
    first, last = m.group(1), m.group(2)
    if first == "" and last == "":
        return None
    if first == "":
        n = int(last)
        if n <= 0:
            return None
        start, end = max(0, size - n), size - 1
    elif last == "":
        start, end = int(first), size - 1
    else:
        start, end = int(first), int(last)
        if end < start:
            return None
    if start >= size:
        return None
    return start, min(end, size - 1)

# D2: extensions served inline (the phone browser shows them instead of
# forcing a download), with a FIXED Content-Type. mimetypes.guess_type is
# deliberately not used: on Windows it consults the registry, which
# differs per machine — a literal table is predictable and testable.
_INLINE_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".txt": "text/plain; charset=utf-8",
}


def _int_param(query: dict, key: str) -> int | None:
    """Read an integer query parameter, Persian or Latin digits allowed.

    Anything non-numeric is ignored (the filter just doesn't apply) —
    a malformed value must never crash a request.
    """
    from ..core.normalize import latin_digits
    raw = latin_digits((query.get(key) or [""])[0])
    return int(raw) if raw.isdigit() else None


def _flag_param(query: dict, key: str) -> bool:
    return (query.get(key) or ["0"])[0].lower() in ("1", "true")


def local_ips() -> list[str]:
    """Best-effort list of this machine's LAN addresses for the QR/URL box."""
    ips = {"127.0.0.1"}
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = ipaddress.ip_address(info[4][0])
            if not ip.is_loopback:
                ips.add(str(ip))
    except OSError:
        pass
    return sorted(ips)


class ShareServer:
    """Owns the HTTPServer thread and the PIN; start()/stop() from the UI."""

    def __init__(self, library_root: str):
        self.library_root = library_root
        self.pin = f"{secrets.randbelow(1_000_000):06d}"
        self.port = 0                       # assigned by bind()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._fails: dict[str, list] = {}   # ip → [timestamps]
        self._fails_lock = threading.Lock()
        self._stop_lock = threading.Lock()  # stop() runs from the UI thread
        # AND the TTL timer — both must not interleave server_close()
        self._ttl_timer: threading.Timer | None = None

    def rotate_pin(self) -> str:
        """H2: a fresh random PIN — every link carrying the old one stops
        working at once. Also clears the per-IP lockout counters, so a
        classmate locked out by typos is not stuck behind the old PIN."""
        self.pin = f"{secrets.randbelow(1_000_000):06d}"
        with self._fails_lock:
            self._fails.clear()
        return self.pin

    def is_running(self) -> bool:
        return self._httpd is not None

    def start(self, ttl_seconds: float | None = None) -> list[str]:
        self._stopping = False
        handler = _make_handler(self)
        self._httpd = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
        # Non-daemon handler threads (fixes limitations #18): daemon
        # threads are never tracked by ThreadingMixIn, so server_close()
        # returned while a request thread was still inside its SQLite
        # write — then stop() closed that connection under it (native
        # access violation). Joinable threads make stop() deterministic.
        self._httpd.daemon_threads = False
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            # poll_interval 0.05 (default 0.5): shutdown() waits for the
            # serve loop to notice the stop flag, and a 0.5 s wait on
            # every stop made the UI's «قطع اشتراک» feel sluggish
            target=self._httpd.serve_forever,
            kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()
        # H2: sharing ends by itself. A timer (not the UI) fires stop();
        # the share dialog's poll notices the server is gone and closes.
        ttl = SHARE_TTL_SECONDS if ttl_seconds is None else ttl_seconds
        if ttl and ttl > 0:
            self._ttl_timer = threading.Timer(ttl, self._auto_stop)
            self._ttl_timer.daemon = True
            self._ttl_timer.start()
        return [f"http://{ip}:{self.port}/" for ip in local_ips()]

    def _auto_stop(self) -> None:
        """H2: the TTL firing — stop() is idempotent, so the UI path that
        also stops on dialog close stays safe."""
        self.stop()

    def stop(self) -> None:
        with self._stop_lock:
            if self._httpd is None:
                return
            if self._ttl_timer is not None:
                self._ttl_timer.cancel()
                self._ttl_timer = None
            self._stopping = True
            self._httpd.shutdown()
            # M12: shut down every live connection — idle ones AND the
            # ones mid-transfer — so a blocked read/write unblocks now
            # instead of server_close() waiting out the whole transfer.
            # (The old code only closed idle connections, which is why
            # stopping mid-download still froze the UI.)
            closer = getattr(self, "_close_all_connections", None)
            if closer is not None:
                closer()
            self._httpd.server_close()
            self._httpd = None
            closer = getattr(self, "_close_libraries", None)
            if closer is not None:
                closer()

    # --- helpers used by the handler ---------------------------------

    def check_pin(self, ip: str, given: str) -> bool:
        if self._locked_out(ip):
            return False
        ok = hmac.compare_digest(str(given or ""), self.pin)
        if ok:
            self._clear_fails(ip)
        else:
            self._record_fail(ip)
        return ok

    def _locked_out(self, ip: str) -> bool:
        with self._fails_lock:
            fails = self._fails.get(ip, [])
            recent = [t for t in fails if time.time() - t < LOCKOUT_SECONDS]
            self._fails[ip] = recent
            return len(recent) >= MAX_FAILS

    def _record_fail(self, ip: str) -> None:
        with self._fails_lock:
            self._fails.setdefault(ip, []).append(time.time())

    def _clear_fails(self, ip: str) -> None:
        with self._fails_lock:
            self._fails.pop(ip, None)


def _make_handler(server: ShareServer):
    # SQLite connections must stay on the thread that created them, so each
    # HTTP worker thread gets its own Library. They are closed in stop().
    local = threading.local()
    registry: list[Library] = []
    registry_lock = threading.Lock()
    idle_conns: set[socket.socket] = set()
    all_conns: set[socket.socket] = set()   # M12: every live connection,
    # idle or mid-transfer — stop() shuts them all down at once

    def _library() -> Library:
        lib = getattr(local, "library", None)
        if lib is None:
            lib = _open_server_library(server.library_root)
            local.library = lib
            with registry_lock:
                registry.append(lib)
        return lib

    def _close_idle() -> None:
        with registry_lock:
            conns = list(idle_conns)
        for conn in conns:
            try:
                conn.shutdown(socket.SHUT_RD)
            except OSError:
                pass

    def _close_all_conns() -> None:
        # M12: unblock in-flight reads/writes too — a download whose phone
        # stopped reading, or an upload waiting for the next chunk, would
        # otherwise keep server_close() (and the UI) waiting for the
        # socket timeout. A shut-down socket makes the handler's read /
        # write fail at once; the handler treats that as "client gone".
        with registry_lock:
            conns = list(all_conns)
        for conn in conns:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _close_all_libs() -> None:
        import sqlite3 as _sq
        with registry_lock:
            for lib in registry:
                try:
                    lib.close()
                except _sq.Error:
                    pass   # thread already gone — nothing to save
            registry.clear()

    server._close_idle_connections = _close_idle
    server._close_all_connections = _close_all_conns
    server._close_libraries = _close_all_libs

    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.1 keep-alive (F1): a phone reuses one connection for its
        # browse-download-upload round instead of paying a fresh TCP +
        # library-open per request. This only works because EVERY response
        # carries an exact Content-Length — _send, _json and _serve_file
        # must keep that invariant.
        protocol_version = "HTTP/1.1"
        timeout = 5.0

        def log_message(self, *args) -> None:   # silence per-request noise
            pass

        def handle_one_request(self) -> None:
            if server._stopping:
                # M12: a request that arrived after stop() began must not
                # start new work (an upload, a download) that stop() then
                # has to wait out — the socket just closes.
                self.close_connection = True
                return
            with registry_lock:
                idle_conns.add(self.connection)
                all_conns.add(self.connection)
            try:
                super().handle_one_request()
            except (TimeoutError, ConnectionError, OSError):
                self.close_connection = True
            finally:
                with registry_lock:
                    idle_conns.discard(self.connection)
                    all_conns.discard(self.connection)
            if server._stopping:
                self.close_connection = True

        # ---- helpers --------------------------------------------------

        def _send(self, code: int, body: bytes, ctype: str,
                  no_store: bool = False,
                  cache_seconds: int | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if no_store:
                # D4 (server side): API answers are never cached — a phone
                # must always see the library as it is right now
                self.send_header("Cache-Control", "no-store")
            elif cache_seconds is not None:
                self.send_header(
                    "Cache-Control", f"public, max-age={cache_seconds}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(
                obj, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8", no_store=True)

        def _pin_ok(self) -> bool:
            query = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            given = (query.get("pin") or [""])[0]
            ip = self.client_address[0]
            if server.check_pin(ip, given):
                return True
            err = "lockout" if server._locked_out(ip) else "pin"
            self._json({"error": err}, 403)
            return False

        # ---- routes ---------------------------------------------------

        def do_GET(self) -> None:
            with registry_lock:
                idle_conns.discard(self.connection)
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path
            query = urllib.parse.parse_qs(parsed.query)
            if route == "/" or route == "/index.html":
                self._serve_client()
            elif route == "/favicon.ico":
                self._serve_favicon()
            elif route == "/manifest.webmanifest":
                self._serve_manifest()
            elif route.startswith("/icons/"):
                self._serve_icon(route)
            elif route.startswith("/fonts/"):
                self._serve_font(route)
            elif route == "/api/manifest":
                if self._pin_ok():
                    from ..web.sync import catalog_manifest
                    self._json(catalog_manifest(_library().conn))
            elif route == "/api/search":
                if self._pin_ok():
                    from ..core.search import search, search_total
                    # C6: the API honors the filters it documents —
                    # subject_id / kind / unclassified pass straight
                    # through to search()
                    q = (query.get("q") or [""])[0]
                    subject_id = _int_param(query, "subject_id")
                    kind = (query.get("kind") or [None])[0] or None
                    unclassified = _flag_param(query, "unclassified")
                    rows = search(
                        _library().conn, q,
                        subject_id=subject_id, kind=kind,
                        unclassified_only=unclassified,
                        limit=SEARCH_LIMIT)
                    # M30: the page is capped at SEARCH_LIMIT rows — also
                    # report the real total, so the phone says "showing
                    # 300 of 1,240" instead of "300 files" as if that
                    # were the whole library.
                    total = search_total(
                        _library().conn, q,
                        subject_id=subject_id, kind=kind,
                        unclassified_only=unclassified)
                    self._json({"files": [
                        {"id": r["id"], "name": r["original_name"],
                         "subject": r["subject_name"],
                         "chapter": r["chapter"], "lesson": r["lesson"],
                         "kind": r["kind"],
                         "size": r["size_bytes"],
                         "available": bool(r["available"])} for r in rows],
                        "total": total,
                        "truncated": total > len(rows)})
            elif route == "/api/subjects":
                if self._pin_ok():
                    # D1: the phone's filter chips — one SQL for every
                    # subject WITH its file count, plus the «بدون درس»
                    # count, so the client needs no per-chip requests
                    rows = _library().conn.execute(
                        "SELECT s.id, s.name, COUNT(f.id) AS n "
                        "FROM subjects s LEFT JOIN files f "
                        "ON f.subject_id = s.id "
                        "GROUP BY s.id ORDER BY s.name").fetchall()
                    from ..core.search import unclassified_count
                    self._json({
                        "subjects": [{"id": r["id"], "name": r["name"],
                                      "count": r["n"]} for r in rows],
                        "unclassified": unclassified_count(_library().conn)})
            elif route.startswith("/api/file/"):
                if self._pin_ok():
                    self._serve_file(route.rsplit("/", 1)[-1], query)
            else:
                self._send(404, "not found".encode(), "text/plain")

        def do_POST(self) -> None:
            with registry_lock:
                idle_conns.discard(self.connection)
            route = urllib.parse.urlparse(self.path).path
            if route != "/api/upload":
                self.close_connection = True   # body unread: don't reuse
                self._send(404, "not found".encode(), "text/plain")
                return
            if not self._pin_ok():
                # the request body was never read — with HTTP/1.1 an
                # unread body would be misparsed as the next request,
                # so this connection must not be reused
                self.close_connection = True
                return
            query = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            name = (query.get("name") or ["upload.bin"])[0]
            name = Path(name).name or "upload.bin"       # strip any path part
            # M10: executables and scripts never reach the library — a
            # classmate taps "download" once and runs it. Checked before
            # the body is read, so the rejected bytes never arrive.
            if Path(name).suffix.lower() in _BLOCKED_UPLOAD_EXTS:
                self.close_connection = True   # body (partly) unread
                self._json({"error": "type"}, 415)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 < length <= MAX_UPLOAD:
                self.close_connection = True   # body (partly) unread
                self._json({"error": "size"}, 413)
                return
            # M10: a full disk must fail fast with a clear error, not
            # halfway through the copy — the staging temp plus the final
            # copy both need room, on top of a reserve for the catalog.
            free = shutil.disk_usage(server.library_root).free
            if free < length + _DISK_RESERVE:
                self.close_connection = True   # body (partly) unread
                self._json({"error": "space"}, 507)
                return
            # B4: the upload is staged in the OS temp folder, never in the
            # library root — a crash between create and import leaves at
            # worst a stray temp file nobody sees, and nothing that the
            # orphan sweep or a library listing can mistake for library data.
            # G4: optional pre-fill hints on the upload URL. kind/lesson
            # are the uploader's explicit choice, so they are stored the
            # same way a درس‌پک import stores them. subject is NEVER
            # stored (classification-first: only the desktop classify
            # dialog may set it) — it travels back on the response as
            # `prefill`, and the file lands in «بدون درس».
            meta: dict = {}
            kind_hint = (query.get("kind") or [None])[0]
            lesson_hint = _int_param(query, "lesson")
            subject_hint = (query.get("subject") or [None])[0]
            if kind_hint:
                meta["kind"] = kind_hint
            if lesson_hint is not None:
                meta["lesson"] = lesson_hint
            if subject_hint:
                meta["subject"] = subject_hint
            safe_suffix = re.sub(r"[^A-Za-z0-9._-]", "", Path(name).suffix)[:16]
            fd, tmp_name = tempfile.mkstemp(prefix="darspack-upload-",
                                            suffix=safe_suffix or ".bin")
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "wb") as f:
                    remaining = length
                    while remaining:
                        if server._stopping:
                            # M12: sharing was stopped mid-upload — stop
                            # reading now; the partial temp file is removed
                            # by the finally below, nothing is imported.
                            break
                        chunk = self.rfile.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        f.write(chunk)
                if remaining > 0:
                    self.close_connection = True
                    self._json({"error": "incomplete"}, 400)
                    return
                from ..core.importer import import_file
                result = import_file(_library(), tmp, display_name=name,
                                     meta=meta or None)
            finally:
                tmp.unlink(missing_ok=True)
            reply = {"status": result.status, "message": result.message_fa}
            if result.prefill:
                reply["prefill"] = result.prefill
            self._json(reply)
            from ..core import db
            # Committed NOW (fixes limitations #17): this request thread's
            # connection outlives the request, and an uncommitted write
            # used to hold SQLite's write lock for the whole share session
            # — the second distinct upload then stalled and failed.
            with _library().conn:
                db.log(_library().conn, "web_upload", name)

        # ---- file routes ----------------------------------------------

        def _serve_client(self) -> None:
            index = CLIENT_DIR / "index.html"
            if index.exists():
                self._send(200, index.read_bytes(), "text/html; charset=utf-8",
                           no_store=True)
            else:
                self._send(500, "client missing".encode(), "text/plain")

        def _serve_favicon(self) -> None:
            icon = CLIENT_DIR / "favicon.ico"
            if icon.is_file():
                self._send(200, icon.read_bytes(), "image/x-icon")
            else:
                self._send(404, b"not found", "text/plain")

        def _serve_static(self, path: Path, ctype: str,
                          cache_seconds: int | None = 86400) -> None:
            if path.is_file():
                self._send(200, path.read_bytes(), ctype,
                           cache_seconds=cache_seconds)
            else:
                self._send(404, b"not found", "text/plain")

        def _serve_manifest(self) -> None:
            # PWA metadata is public: the browser fetches it before the PIN
            self._serve_static(CLIENT_DIR / "manifest.webmanifest",
                               "application/manifest+json", 3600)

        def _serve_icon(self, route: str) -> None:
            name = route.removeprefix("/icons/")
            ctype = _ICON_TYPES.get(name)
            if ctype is None:
                self._send(404, b"not found", "text/plain")
                return
            self._serve_static(CLIENT_DIR / "icons" / name, ctype)

        def _serve_font(self, route: str) -> None:
            name = route.removeprefix("/fonts/")
            if name not in _FONT_FILES:
                self._send(404, b"not found", "text/plain")
                return
            self._serve_static(asset_path(f"fonts/{name}"), "font/ttf")

        def _serve_file(self, file_id: str, query: dict | None = None) -> None:
            from ..core.normalize import latin_digits
            if not latin_digits(file_id).isdigit():
                self._json({"error": "id"}, 400)
                return
            row = _library().conn.execute(
                "SELECT * FROM files WHERE id=?", (int(file_id),)).fetchone()
            if row is None:
                self._json({"error": "not found"}, 404)
                return
            path = _library().stored_path(row)
            if not path.is_file():
                self._json({"error": "file missing"}, 404)
                return
            size = path.stat().st_size
            # M11: a phone on flaky school Wi-Fi resumes a failed download
            # instead of restarting from zero. Single ranges only — a
            # multi-range or out-of-range request gets 416, per RFC 9110.
            start, end = 0, size - 1
            status = 200
            range_header = self.headers.get("Range")
            if range_header is not None:
                parsed = _parse_range(range_header, size)
                if parsed is None:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                start, end = parsed
                status = 206
            length = end - start + 1
            self.send_response(status)
            name = urllib.parse.quote(row["original_name"])
            # D2: whitelist extensions open INSIDE the phone browser (a
            # classmate checks a جزوه without leaving the app); everything
            # else — executables, archives, unknown types — downloads.
            ctype = _INLINE_TYPES.get(
                Path(row["original_name"]).suffix.lower(),
                "application/octet-stream")
            is_whitelisted = ctype in _INLINE_TYPES.values()
            q = query or {}
            force_download = _flag_param(q, "download")
            force_inline = _flag_param(q, "inline")
            if force_download:
                disposition = "attachment"
            elif force_inline and is_whitelisted:
                disposition = "inline"
            else:
                disposition = "inline" if is_whitelisted else "attachment"
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Disposition",
                             f"{disposition}; filename*=UTF-8''{name}")
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range",
                                 f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(length))
            self.end_headers()
            try:
                with open(path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        if server._stopping:
                            # M12: sharing was stopped mid-download — stop
                            # sending; the client just sees a cut-off
                            # download it can resume with Range.
                            break
                        chunk = f.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                # M11: the phone went away mid-download (walked out of
                # Wi-Fi range, closed the tab) — that is normal here, not
                # a crash: swallow it and let the handler close quietly.
                pass
            if server._stopping:
                self.close_connection = True

    return Handler
