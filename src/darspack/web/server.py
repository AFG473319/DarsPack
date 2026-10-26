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
import secrets
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..core.library import Library

def _open_server_library(root: str) -> Library:
    """Open a library for a server thread WITHOUT the maintenance passes (F1).

    Every phone request used to pay a fresh Library.open() — schema init,
    orphan sweep, health check — ~120–150 ms each, and the orphan sweep
    even raced in-flight uploads (it could delete a temp file another
    thread was still importing). The desktop app always opened this
    library first, so the schema already exists and the server threads
    only need to read/query.

    Contract with core (decision recorded 2026-10-26):
        Library(root, maintain=False).open() skips init_schema and
        sweep_orphans. When core lands that flag we use it; until then a
        local subclass achieves the same and the try/except disappears.
    """
    try:
        return Library(root, maintain=False).open()
    except TypeError:                      # core hasn't landed the flag yet
        from ..core import db

        class _ServerLibrary(Library):
            def open(self) -> "Library":
                self.root.mkdir(parents=True, exist_ok=True)
                self.files_dir.mkdir(exist_ok=True)
                self.conn = db.connect(self.db_path)
                return self

        return _ServerLibrary(root).open()

CLIENT_DIR: Path
if getattr(sys, "frozen", False):
    # PyInstaller build: data files unpack under sys._MEIPASS
    CLIENT_DIR = Path(sys._MEIPASS) / "darspack" / "web" / "client"
else:
    CLIENT_DIR = Path(__file__).parent / "client"
MAX_UPLOAD = 200 * 1024 * 1024          # 200 MB — bigger files via USB
LOCKOUT_SECONDS = 30
MAX_FAILS = 5

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
        self._fails: dict[str, list] = {}   # ip → [timestamps]
        self._fails_lock = threading.Lock()

    def start(self) -> list[str]:
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
            target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return [f"http://{ip}:{self.port}/" for ip in local_ips()]

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
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

    def _library() -> Library:
        lib = getattr(local, "library", None)
        if lib is None:
            lib = _open_server_library(server.library_root)
            local.library = lib
            with registry_lock:
                registry.append(lib)
        return lib

    def _close_all() -> None:
        import sqlite3 as _sq
        with registry_lock:
            for lib in registry:
                try:
                    lib.close()
                except _sq.Error:
                    pass   # thread already gone — nothing to save
            registry.clear()

    server._close_libraries = _close_all

    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.1 keep-alive (F1): a phone reuses one connection for its
        # browse-download-upload round instead of paying a fresh TCP +
        # library-open per request. This only works because EVERY response
        # carries an exact Content-Length — _send, _json and _serve_file
        # must keep that invariant.
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:   # silence per-request noise
            pass

        # ---- helpers --------------------------------------------------

        def _send(self, code: int, body: bytes, ctype: str,
                  no_store: bool = False) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if no_store:
                # D4 (server side): API answers are never cached — a phone
                # must always see the library as it is right now
                self.send_header("Cache-Control", "no-store")
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
            if server.check_pin(self.client_address[0], given):
                return True
            self._json({"error": "pin"}, 403)
            return False

        # ---- routes ---------------------------------------------------

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path
            if route == "/" or route == "/index.html":
                self._serve_client()
            elif route == "/api/manifest":
                if self._pin_ok():
                    from ..web.sync import catalog_manifest
                    self._json(catalog_manifest(_library().conn))
            elif route == "/api/search":
                if self._pin_ok():
                    query = urllib.parse.parse_qs(parsed.query)
                    from ..core.search import search
                    # C6: the API honors the filters it documents —
                    # subject_id / kind / unclassified pass straight
                    # through to search()
                    rows = search(
                        _library().conn, (query.get("q") or [""])[0],
                        subject_id=_int_param(query, "subject_id"),
                        kind=(query.get("kind") or [None])[0] or None,
                        unclassified_only=_flag_param(query, "unclassified"),
                        limit=300)
                    self._json({"files": [
                        {"id": r["id"], "name": r["original_name"],
                         "subject": r["subject_name"],
                         "chapter": r["chapter"], "kind": r["kind"],
                         "size": r["size_bytes"]} for r in rows]})
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
                    self._serve_file(route.rsplit("/", 1)[-1])
            else:
                self._send(404, "not found".encode(), "text/plain")

        def do_POST(self) -> None:
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
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_UPLOAD:
                self.close_connection = True   # body (partly) unread
                self._json({"error": "size"}, 413)
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
            fd, tmp_name = tempfile.mkstemp(prefix="darspack-upload-",
                                            suffix="-" + name)
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "wb") as f:
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        f.write(chunk)
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
                self._send(200, index.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(500, "client missing".encode(), "text/plain")

        def _serve_file(self, file_id: str) -> None:
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
            self.send_response(200)
            name = urllib.parse.quote(row["original_name"])
            # D2: whitelist extensions open INSIDE the phone browser (a
            # classmate checks a جزوه without leaving the app); everything
            # else — executables, archives, unknown types — downloads.
            ctype = _INLINE_TYPES.get(
                Path(row["original_name"]).suffix.lower(),
                "application/octet-stream")
            disposition = ("attachment" if ctype == "application/octet-stream"
                           else "inline")
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Disposition",
                             f"{disposition}; filename*=UTF-8''{name}")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    self.wfile.write(chunk)

    return Handler
