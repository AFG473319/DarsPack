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
import secrets
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..core.library import Library

CLIENT_DIR: Path
if getattr(sys, "frozen", False):
    # PyInstaller build: data files unpack under sys._MEIPASS
    CLIENT_DIR = Path(sys._MEIPASS) / "darspack" / "web" / "client"
else:
    CLIENT_DIR = Path(__file__).parent / "client"
MAX_UPLOAD = 200 * 1024 * 1024          # 200 MB — bigger files via USB
LOCKOUT_SECONDS = 30
MAX_FAILS = 5


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
            lib = Library(server.library_root).open()
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
        def log_message(self, *args) -> None:   # silence per-request noise
            pass

        # ---- helpers --------------------------------------------------

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(
                obj, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8")

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
                    rows = search(_library().conn, (query.get("q") or [""])[0],
                                  limit=300)
                    self._json({"files": [
                        {"id": r["id"], "name": r["original_name"],
                         "subject": r["subject_name"],
                         "chapter": r["chapter"], "kind": r["kind"],
                         "size": r["size_bytes"]} for r in rows]})
            elif route.startswith("/api/file/"):
                if self._pin_ok():
                    self._serve_file(route.rsplit("/", 1)[-1])
            else:
                self._send(404, "not found".encode(), "text/plain")

        def do_POST(self) -> None:
            route = urllib.parse.urlparse(self.path).path
            if route != "/api/upload":
                self._send(404, "not found".encode(), "text/plain")
                return
            if not self._pin_ok():
                return
            query = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            name = (query.get("name") or ["upload.bin"])[0]
            name = Path(name).name or "upload.bin"       # strip any path part
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_UPLOAD:
                self._json({"error": "size"}, 413)
                return
            tmp = Path(_library().root) / f"upload-{secrets.token_hex(4)}-{name}"
            try:
                with open(tmp, "wb") as f:
                    remaining = length
                    while remaining:
                        chunk = self.rfile.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        f.write(chunk)
                from ..core.importer import import_file
                result = import_file(_library(), tmp, display_name=name)
            finally:
                tmp.unlink(missing_ok=True)
            self._json({"status": result.status,
                        "message": result.message_fa})
            from ..core import db
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
            self.send_header("Content-Type",
                             "application/octet-stream")
            self.send_header("Content-Disposition",
                             f"attachment; filename*=UTF-8''{name}")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    self.wfile.write(chunk)

    return Handler
