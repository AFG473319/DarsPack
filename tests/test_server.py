"""Tests for the LAN share server (PIN gate, search, download, upload)."""
import http.client
import json
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

import pytest

from darspack.core.importer import import_file
from darspack.core.library import Library
from darspack.core.search import unclassified_count
from darspack.web.server import ShareServer, _open_server_library, _parse_range, local_ips


@pytest.fixture()
def server(tmp_path):
    """A library with two files + a running ShareServer on a random port."""
    with Library(tmp_path / "lib") as lib:
        for i, name in enumerate(("نمونه سوال ریاضی فصل 3.pdf", "جزوه علوم.pdf")):
            p = tmp_path / name
            p.write_bytes(f"content-{i}".encode())
            import_file(lib, p)
        share = ShareServer(str(tmp_path / "lib"))
        share.start()
        yield share, lib
        share.stop()


@pytest.fixture(scope="module")
def ro_server(tmp_path_factory):
    """One read-only server shared by the GET-only tests of this module.

    Starting a server per test is the slowest part of a server test, so
    tests that never mutate the library (manifest, file-id validation,
    unknown route) share one instance. Anything that uploads, imports or
    deletes uses the function-scoped `server` fixture instead.
    """
    root = tmp_path_factory.mktemp("ro-lib")
    with Library(root / "lib") as lib:
        for i, name in enumerate(("نمونه سوال ریاضی فصل 3.pdf", "جزوه علوم.pdf")):
            p = root / name
            p.write_bytes(f"content-{i}".encode())
            import_file(lib, p)
        share = ShareServer(str(root / "lib"))
        share.start()
        yield share, lib
        share.stop()


def _exchange(url, data=None, headers=None):
    """One raw HTTP exchange with the server under test.

    Returns (status, body, response). http.client connects to the URL's
    host and port DIRECTLY, socket to socket — the request can only ever
    reach the loopback server under test, and nothing between the test
    and the server can alter the response. (The earlier urllib-based helpers
    were flaky here: they received responses and timeouts that
    this server provably never sends — so the tests now speak
    http.client directly.)

    http.client does NOT raise on error statuses; _get/_post return
    whatever arrives, which is exactly what the assertions need.
    """
    parts = urllib.parse.urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    conn = http.client.HTTPConnection(parts.hostname, parts.port or 80,
                                      timeout=5 if data is None else 10)
    try:
        conn.request("POST" if data is not None else "GET", path,
                     body=data, headers=headers or {})
        res = conn.getresponse()
        return res.status, res.read(), res
    finally:
        conn.close()


def _get(url):
    return _exchange(url)[:2]


def _get_error(url):
    """Readability alias: a 4xx reply is a normal return value here."""
    return _get(url)


def _post(url, data):
    status, body, _ = _exchange(url, data)
    return status, json.loads(body)


def _post_raw(url, data):
    return _exchange(url, data)[:2]


def _headers_for(share, file_id):
    res = _exchange(f"http://127.0.0.1:{share.port}/api/file/{file_id}"
                    f"?pin={share.pin}")[2]
    return res.headers["Content-Type"], res.headers["Content-Disposition"]


def test_favicon_is_served(ro_server):
    share, _ = ro_server
    status, body, res = _exchange(f"http://127.0.0.1:{share.port}/favicon.ico")
    assert status == 200
    assert res.headers["Content-Type"] == "image/x-icon"
    assert body[:4] == b"\x00\x00\x01\x00"


def test_pwa_assets_are_public(ro_server):
    """The browser fetches the manifest, install icons and font BEFORE
    the PIN is entered, so these routes must not require one."""
    share, _ = ro_server
    base = f"http://127.0.0.1:{share.port}"
    status, body, res = _exchange(f"{base}/manifest.webmanifest")
    assert status == 200
    assert res.headers["Content-Type"].startswith("application/manifest+json")
    manifest = json.loads(body)
    assert manifest["display"] == "standalone"
    assert {icon["sizes"] for icon in manifest["icons"]} == \
        {"192x192", "512x512"}

    for name, ctype in (("icon-192.png", "image/png"),
                        ("icon-512.png", "image/png")):
        status, body, res = _exchange(f"{base}/icons/{name}")
        assert status == 200 and body.startswith(b"\x89PNG")
        assert res.headers["Content-Type"] == ctype

    status, body, res = _exchange(f"{base}/fonts/Vazirmatn-Regular.ttf")
    assert status == 200 and body[:4] == b"\x00\x01\x00\x00"
    assert res.headers["Content-Type"] == "font/ttf"

    assert _get(f"{base}/icons/nope.png")[0] == 404
    assert _get(f"{base}/fonts/nope.ttf")[0] == 404


def test_api_requires_pin(ro_server):
    share, _ = ro_server
    base = f"http://127.0.0.1:{share.port}"
    status, body = _get(f"{base}/api/search?q=x")
    assert status == 403
    status, body = _get(f"{base}/api/search?q=x&pin={share.pin}")
    assert status == 200 and "files" in json.loads(body)


# --- F1: keep-alive + no per-request maintenance --------------------------

def test_protocol_is_http11(ro_server):
    share, _ = ro_server
    from darspack.web.server import _make_handler
    assert _make_handler(share).protocol_version == "HTTP/1.1"


def test_keepalive_reuses_one_connection(ro_server):
    """HTTP/1.1 keep-alive, end to end: TWO requests over ONE connection.

    With HTTP/1.0 the second request would be refused (the server closes
    after each response). Every response must carry Content-Length or the
    reused connection would desync — that invariant is what this pins.
    """
    import http.client
    share, _ = ro_server
    conn = http.client.HTTPConnection("127.0.0.1", share.port, timeout=5)
    try:
        conn.request("GET", "/")
        res = conn.getresponse()
        assert res.status == 200 and "درس‌پک" in res.read().decode("utf-8")
        conn.request("GET", f"/api/search?q=&pin={share.pin}")
        res = conn.getresponse()
        assert res.status == 200 and "files" in json.loads(res.read())
    finally:
        conn.close()


def test_no_sweep_in_server_threads(ro_server, monkeypatch):
    """Request threads never run maintenance (F1): no orphan sweep.

    The sweep used to run per library open on each new connection thread
    and could even delete an in-flight upload's file (the measured
    PermissionError race). The desktop app owns maintenance; the server
    threads only read.
    """
    share, _ = ro_server
    calls = []
    monkeypatch.setattr(Library, "sweep_orphans", lambda self: calls.append(1))
    _get(f"http://127.0.0.1:{share.port}/")
    _get(f"http://127.0.0.1:{share.port}/api/search?pin={share.pin}")
    assert calls == []


def test_search_endpoint_normalizes_digits(ro_server):
    share, _ = ro_server
    base = f"http://127.0.0.1:{share.port}"
    _, body = _get(f"{base}/api/search?q=" + urllib.parse.quote("فصل ۳")
                   + f"&pin={share.pin}")
    names = [f["name"] for f in json.loads(body)["files"]]
    assert names == ["نمونه سوال ریاضی فصل 3.pdf"]


def test_search_returns_chapter_and_lesson(server):
    """The phone client needs both book positions; the API used to omit
    lesson entirely, so a file with both showed only «فصل ۳»."""
    share, lib = server
    with lib.conn:
        lib.conn.execute(
            "UPDATE files SET chapter=3, lesson=7 WHERE original_name=?",
            ("نمونه سوال ریاضی فصل 3.pdf",))
    base = f"http://127.0.0.1:{share.port}"
    _, body = _get(f"{base}/api/search?q=&pin={share.pin}")
    target = next(f for f in json.loads(body)["files"]
                  if f["name"] == "نمونه سوال ریاضی فصل 3.pdf")
    assert target["chapter"] == 3
    assert target["lesson"] == 7


def test_download_endpoint(ro_server):
    share, _ = ro_server
    base = f"http://127.0.0.1:{share.port}"
    _, body = _get(f"{base}/api/search?q=" + urllib.parse.quote("جزوه")
                   + f"&pin={share.pin}")
    file_id = json.loads(body)["files"][0]["id"]
    status, data = _get(f"{base}/api/file/{file_id}?pin={share.pin}")
    assert status == 200 and data == b"content-1"


# --- D2: inline viewing for a small whitelist, download for the rest ------

def test_inline_viewing_whitelist(server):
    share, lib = server
    # a .pdf opens INSIDE the phone browser (files 1 and 2 are PDFs)
    ctype, disposition = _headers_for(share, 1)
    assert ctype == "application/pdf"
    assert disposition.startswith("inline")
    # an executable and an unknown extension download as octet-stream
    for name, content in (("prog.exe", b"MZfake"),
                          ("archive.xyz", b"???")):
        p = lib.root.parent / name
        p.write_bytes(content)
        import_file(lib, p)
    row = lib.conn.execute(
        "SELECT id FROM files WHERE original_name='prog.exe'").fetchone()
    ctype, disposition = _headers_for(share, row["id"])
    assert ctype == "application/octet-stream"
    assert disposition.startswith("attachment")
    row = lib.conn.execute(
        "SELECT id FROM files WHERE original_name='archive.xyz'").fetchone()
    ctype, disposition = _headers_for(share, row["id"])
    assert ctype == "application/octet-stream"
    assert disposition.startswith("attachment")


def test_download_and_inline_query_params(server):
    share, lib = server
    # File 1 is PDF (normally inline)
    # ?download=1 forces attachment
    res = _exchange(f"http://127.0.0.1:{share.port}/api/file/1?download=1&pin={share.pin}")[2]
    assert res.headers["Content-Disposition"].startswith("attachment")

    # ?inline=1 forces inline
    res2 = _exchange(f"http://127.0.0.1:{share.port}/api/file/1?inline=1&pin={share.pin}")[2]
    assert res2.headers["Content-Disposition"].startswith("inline")

    # ?download=1&inline=1: download takes precedence
    res3 = _exchange(f"http://127.0.0.1:{share.port}/api/file/1?download=1&inline=1&pin={share.pin}")[2]
    assert res3.headers["Content-Disposition"].startswith("attachment")

    # Non-whitelisted binary file: ?inline=1 must NOT override D2 whitelist
    p = lib.root.parent / "test_bin.exe"
    p.write_bytes(b"MZfake")
    import_file(lib, p)
    bin_id = lib.conn.execute("SELECT id FROM files WHERE original_name='test_bin.exe'").fetchone()["id"]
    res_bin = _exchange(f"http://127.0.0.1:{share.port}/api/file/{bin_id}?inline=1&pin={share.pin}")[2]
    assert res_bin.headers["Content-Disposition"].startswith("attachment")


def test_lockout_after_five_failures(server):
    share, _ = server
    base = f"http://127.0.0.1:{share.port}"
    for _ in range(5):
        status, body = _get(f"{base}/api/search?q=x&pin=000000")
        assert status == 403
    # even the CORRECT pin is refused while locked out
    status, body = _get(f"{base}/api/search?q=x&pin={share.pin}")
    assert status == 403


def test_upload_imports_into_library(server, tmp_path):
    share, lib = server
    base = f"http://127.0.0.1:{share.port}"
    status, data = _post(
        f"{base}/api/upload?name="
        + urllib.parse.quote("کاربرگ علوم فصل ۲.pdf") + f"&pin={share.pin}",
        b"uploaded-content")
    assert data["status"] == "imported"
    row = lib.conn.execute(
        "SELECT original_name, stored_name FROM files "
        "WHERE original_name LIKE 'کاربرگ%'").fetchone()
    assert row["stored_name"] != ""
    # no upload temp files left behind — in the library root (B4 keeps
    # staging OUT of it) nor in the OS temp folder
    assert not list(Path(lib.root).glob("upload-*"))
    assert not list(Path(tempfile.gettempdir()).glob("darspack-upload-*"))


def test_upload_crash_leaves_nothing_in_library_root(server, monkeypatch):
    """B4: staging lives in the OS temp dir. If the importer dies between
    staging and import, the library root keeps exactly its own files —
    and the server's finally-block still removes the staged file."""
    share, lib = server
    import darspack.core.importer as importer_module

    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash mid-import")
    monkeypatch.setattr(importer_module, "import_file", boom)
    try:
        _post(f"http://127.0.0.1:{share.port}"
              f"/api/upload?name={urllib.parse.quote('کرش.pdf')}"
              f"&pin={share.pin}", b"half-written")
        assert False, "the simulated crash should surface as a dropped request"
    except (http.client.RemoteDisconnected, ConnectionError, OSError):
        pass
    staged = [p.name for p in Path(lib.root).iterdir()
              if p.name.startswith(("upload-", "darspack-upload-"))]
    assert staged == []            # nothing staged in the library root…
    # …and the OS-temp staging file was removed by the finally-block
    assert not list(Path(tempfile.gettempdir()).glob("darspack-upload-*"))


def test_busy_upload_returns_503_busy_json(server, monkeypatch):
    """H1: when the import fails because the database is locked, the
    phone gets a 503 JSON answer it can show ("try again in a moment")
    — not a dropped request. Only lock errors get this treatment; any
    other importer crash still drops the request (see the test above)."""
    import sqlite3
    share, lib = server
    import darspack.core.importer as importer_module

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(importer_module, "import_file", locked)
    status, body = _post(
        f"http://127.0.0.1:{share.port}"
        f"/api/upload?name={urllib.parse.quote('مشغول.pdf')}"
        f"&pin={share.pin}", b"content")
    assert status == 503
    assert body == {"error": "busy"}


def test_local_ips_are_valid():
    import ipaddress
    for ip in local_ips():
        ipaddress.ip_address(ip)     # raises if malformed


# --- the untested GET endpoints (shared read-only server) ----------------

def test_api_manifest_matches_catalog(ro_server):
    share, lib = ro_server
    base = f"http://127.0.0.1:{share.port}"
    from darspack.web.sync import catalog_manifest
    _, body = _get(f"{base}/api/manifest?pin={share.pin}")
    served = json.loads(body)
    assert served == catalog_manifest(lib.conn)
    assert set(next(iter(served.values()))) == {"name", "size"}


def test_unknown_route_is_404(ro_server):
    share, _ = ro_server
    status, _ = _get_error(f"http://127.0.0.1:{share.port}/definitely-not-here")
    assert status == 404


# --- D1/D4: subject chips endpoint + no caching of API answers ------------

def test_api_subjects_lists_counts(server):
    share, lib = server
    base = f"http://127.0.0.1:{share.port}"
    sci = lib.conn.execute(
        "SELECT id FROM subjects WHERE name='علوم تجربی'").fetchone()["id"]
    lib.conn.execute(
        "UPDATE files SET subject_id=? WHERE original_name LIKE 'جزوه%'",
        (sci,))
    lib.conn.commit()
    _, body = _get(f"{base}/api/subjects?pin={share.pin}")
    data = json.loads(body)
    counts = {s["name"]: s["count"] for s in data["subjects"]}
    assert counts["علوم تجربی"] == 1        # the seeded subjects, with counts
    assert all(s["id"] for s in data["subjects"])
    assert data["unclassified"] == 1        # the «بدون درس» chip count


def test_api_responses_carry_no_store(ro_server):
    # the phone must never serve a stale catalog from a cache (D4)
    share, _ = ro_server
    _, _, res = _exchange(
        f"http://127.0.0.1:{share.port}/api/search?pin={share.pin}")
    assert res.headers["Cache-Control"] == "no-store"


# --- the upload path: guards, defaults, duplicates, classification -------

def test_upload_strips_path_parts(server, tmp_path):
    """A malicious or buggy client must not write outside the library."""
    share, lib = server
    base = f"http://127.0.0.1:{share.port}"
    status, data = _post(
        f"{base}/api/upload?name=..%2F..%2Fevil.pdf&pin={share.pin}",
        b"evil-content")
    assert data["status"] == "imported"
    row = lib.conn.execute(
        "SELECT original_name, stored_name FROM files "
        "WHERE original_name='evil.pdf'").fetchone()
    assert row is not None                     # catalogued under the bare name
    assert (lib.files_dir / row["stored_name"]).exists()
    assert not (tmp_path / "evil.pdf").exists()  # nothing landed outside


def test_upload_size_guard(server, monkeypatch):
    share, lib = server
    base = f"http://127.0.0.1:{share.port}"
    # an empty body fails the 0 < length check
    status, body = _post_raw(f"{base}/api/upload?pin={share.pin}", b"")
    assert status == 413 and json.loads(body) == {"error": "size"}
    # over-limit: shrink the limit instead of uploading 200 MB
    import darspack.web.server as server_module
    monkeypatch.setattr(server_module, "MAX_UPLOAD", 8)
    status, body = _post_raw(f"{base}/api/upload?pin={share.pin}", b"1234567890")
    assert status == 413 and json.loads(body) == {"error": "size"}


def test_upload_without_name_gets_default(server):
    share, lib = server
    base = f"http://127.0.0.1:{share.port}"
    _, data = _post(f"{base}/api/upload?pin={share.pin}", b"default-name")
    assert data["status"] == "imported"
    row = lib.conn.execute(
        "SELECT original_name FROM files WHERE original_name='upload.bin'"
    ).fetchone()
    assert row is not None


# --- C6: the search filters the API documents ----------------------------

def _fa_digits(number: int) -> str:
    return "".join("۰۱۲۳۴۵۶۷۸۹"[int(d)] if d.isdigit() else d
                   for d in str(number))


def test_search_filter_params_through_http(server):
    share, lib = server
    base = f"http://127.0.0.1:{share.port}"
    sci = lib.conn.execute(
        "SELECT id FROM subjects WHERE name='علوم تجربی'").fetchone()["id"]
    lib.conn.execute(
        "UPDATE files SET subject_id=? WHERE original_name LIKE 'جزوه%'",
        (sci,))
    lib.conn.commit()

    def names(qs):
        _, body = _get(f"{base}/api/search?{qs}&pin={share.pin}")
        return [f["name"] for f in json.loads(body)["files"]]

    assert names("subject_id=" + str(sci)) == ["جزوه علوم.pdf"]
    # Persian digits are accepted in the filter, like everywhere else
    assert names("subject_id=" + urllib.parse.quote(_fa_digits(sci))) == \
        ["جزوه علوم.pdf"]
    assert names("kind=" + urllib.parse.quote("نمونه‌سوال")) == \
        ["نمونه سوال ریاضی فصل 3.pdf"]
    # only the file still missing its subject
    assert names("unclassified=1") == ["نمونه سوال ریاضی فصل 3.pdf"]
    # a malformed value is ignored, never a crash
    assert len(names("subject_id=not-a-number")) == 2


def test_upload_hints_stored_and_prefill(server):
    """G4: kind/lesson hints from the uploader's phone are explicit
    choices and are stored; the subject hint is NEVER stored (only the
    desktop classify dialog may set a subject) — it comes back on the
    response as `prefill`, and the file lands in «بدون درس»."""
    share, lib = server
    base = f"http://127.0.0.1:{share.port}"
    before = unclassified_count(lib.conn)
    _, data = _post(
        f"{base}/api/upload?name="
        + urllib.parse.quote("کاربرگ جدید.pdf")
        + "&kind=" + urllib.parse.quote("کاربرگ")
        + "&lesson=3&subject=" + urllib.parse.quote("ریاضی")
        + f"&pin={share.pin}", b"hinted")
    assert data["status"] == "imported"
    assert data["prefill"] == {"subject": "ریاضی", "tags": []}
    row = lib.conn.execute(
        "SELECT kind, lesson, subject_id FROM files "
        "WHERE original_name='کاربرگ جدید.pdf'").fetchone()
    assert row["kind"] == "کاربرگ" and row["lesson"] == 3
    assert row["subject_id"] is None
    assert unclassified_count(lib.conn) == before + 1


def test_duplicate_upload_reported_once(server):
    """An upload whose content is already catalogued is reported, not
    re-stored — through the full HTTP path (one request)."""
    share, lib = server
    base = f"http://127.0.0.1:{share.port}"
    # b"content-0" is file 1's exact bytes, already in the catalog
    url = (f"{base}/api/upload?name="
           + urllib.parse.quote("دوباره.pdf") + f"&pin={share.pin}")
    _, data = _post(url, b"content-0")
    assert data["status"] == "duplicate"
    count = lib.conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    assert count == 2                          # nothing re-stored


def test_web_upload_log_row_is_committed(server):
    """The web_upload activity-log row used to be written after the import
    transaction, on the request thread's own connection, and never
    committed — the log under-reported phone uploads (limitations #17).
    The server now commits it explicitly."""
    share, lib = server
    base = f"http://127.0.0.1:{share.port}"
    _post(f"{base}/api/upload?name="
          + urllib.parse.quote("ثبت‌شده.pdf") + f"&pin={share.pin}", b"logged")
    # the log write happens after the response is sent (deliberate: a log
    # failure must never fail an upload), so poll briefly for it
    deadline = time.time() + 2
    details: list = []
    while time.time() < deadline:
        details = [r["detail"] for r in lib.conn.execute(
            "SELECT detail FROM activity_log WHERE action='web_upload'")]
        if details:
            break
        time.sleep(0.05)
    assert "ثبت‌شده.pdf" in details


def test_second_distinct_upload_succeeds(server):
    """The old flaw (limitations #17), end to end: the first upload's
    uncommitted log write held SQLite's write lock for the whole session,
    so the SECOND upload with new content stalled ~5 s and died with the
    file never catalogued. Both uploads must now land."""
    share, lib = server
    base = f"http://127.0.0.1:{share.port}"
    _, d1 = _post(f"{base}/api/upload?name=a.pdf&pin={share.pin}",
                  b"first-bytes")
    _, d2 = _post(f"{base}/api/upload?name=b.pdf&pin={share.pin}",
                  b"second-bytes")
    assert d1["status"] == "imported" and d2["status"] == "imported"
    count = lib.conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    assert count == 4                          # 2 fixture files + 2 uploads


def test_upload_lands_unclassified(server):
    # classification-first: a phone upload has no dialog, so it must show
    # up in the «بدون درس» count for the desktop user to complete
    share, lib = server
    base = f"http://127.0.0.1:{share.port}"
    before = unclassified_count(lib.conn)
    _post(f"{base}/api/upload?name="
          + urllib.parse.quote("عکس-تابلو.pdf") + f"&pin={share.pin}", b"photo")
    assert unclassified_count(lib.conn) == before + 1


def test_missing_stored_file_served_gracefully(server):
    # the catalog row exists but files/ was emptied (USB moved, folder
    # cleaned by hand) — the phone gets a Persian 404, not a crash
    share, lib = server
    base = f"http://127.0.0.1:{share.port}"
    (lib.files_dir / "000001.pdf").unlink()
    status, body = _get_error(f"{base}/api/file/1?pin={share.pin}")
    assert status == 404 and json.loads(body) == {"error": "file missing"}


# --- the PIN lockout, as unit tests: no HTTP, no sleeping ----------------

def test_check_pin_lockout_is_per_ip(tmp_path):
    share = ShareServer(str(tmp_path / "lib"))
    for _ in range(5):
        assert not share.check_pin("10.0.0.1", "000000")
    # the CORRECT pin is now refused for the attacker's IP…
    assert not share.check_pin("10.0.0.1", share.pin)
    # …but another device on the LAN is unaffected
    assert share.check_pin("10.0.0.2", share.pin)


def test_check_pin_lockout_expires(tmp_path):
    share = ShareServer(str(tmp_path / "lib"))
    # forge the timestamps instead of sleeping 30 s: the last failure was
    # 31 s ago, outside the 30-second lockout window
    share._fails["10.0.0.1"] = [time.time() - 31]
    assert share.check_pin("10.0.0.1", share.pin)


def test_check_pin_with_none_is_just_a_failure(tmp_path):
    # a client that sends no pin at all must not crash the server
    share = ShareServer(str(tmp_path / "lib"))
    assert share.check_pin("10.0.0.9", None) is False
    assert share._fails["10.0.0.9"]            # counted like any wrong pin


# --- lifecycle: sharing can be turned off and back on --------------------

def test_start_stop_start_serves_again(tmp_path):
    with Library(tmp_path / "lib") as lib:
        p = tmp_path / "a.pdf"
        p.write_bytes(b"once")
        import_file(lib, p)
        share = ShareServer(str(tmp_path / "lib"))
        urls = share.start()
        assert urls and share.port != 0        # a random port was assigned
        status, body = _get(f"http://127.0.0.1:{share.port}/")
        assert status == 200 and "درس‌پک" in body.decode("utf-8")
        share.stop()
        share.start()                          # fresh port, same library
        try:
            status, body = _get(f"http://127.0.0.1:{share.port}/")
            assert status == 200
            _, data = _get(f"http://127.0.0.1:{share.port}"
                           f"/api/search?q=a&pin={share.pin}")
            assert len(json.loads(data)["files"]) == 1
        finally:
            share.stop()


def test_download_nonexistent_file_returns_404(ro_server):
    share, _ = ro_server
    base = f"http://127.0.0.1:{share.port}"
    status, _ = _get(f"{base}/api/file/999999?pin={share.pin}")
    assert status == 404
    status_bad_id, _ = _get(f"{base}/api/file/not-a-number?pin={share.pin}")
    assert status_bad_id == 400
    # the id is never URL-decoded: a percent-encoded Persian digit is
    # rejected with the same 400 as garbage (pinned current behavior)
    status_fa, _ = _get(f"{base}/api/file/{urllib.parse.quote('۱')}?pin={share.pin}")
    assert status_fa == 400


def test_search_empty_query_lists_all(ro_server):
    share, _ = ro_server
    base = f"http://127.0.0.1:{share.port}"
    status, body = _get(f"{base}/api/search?q=&pin={share.pin}")
    assert status == 200
    files = json.loads(body)["files"]
    assert len(files) == 2


def test_check_pin_whitespace_and_invalid(tmp_path):
    share = ShareServer(str(tmp_path / "lib"))
    # Pin with spaces should be stripped or fail cleanly
    assert not share.check_pin("10.0.0.3", " ")
    assert not share.check_pin("10.0.0.3", "")
    assert not share.check_pin("10.0.0.3", "abcdef")


# ---------------------------------------------------------------------------
# Phone-sharing fixes (2026-11-19 review: H2, M10, M11, M12, M30)
# ---------------------------------------------------------------------------


def test_rotate_pin_invalidates_old_pin(server):
    """H2: a rotated PIN kills the old one at once — a forwarded link dies."""
    share, _ = server
    base = f"http://127.0.0.1:{share.port}"
    status, _ = _get(f"{base}/api/search?q=x&pin={share.pin}")
    assert status == 200
    old_pin = share.pin
    new_pin = share.rotate_pin()
    assert new_pin != old_pin
    assert new_pin == share.pin
    status, _ = _get(f"{base}/api/search?q=x&pin={old_pin}")
    assert status == 403
    status, _ = _get(f"{base}/api/search?q=x&pin={new_pin}")
    assert status == 200


def test_rotate_pin_clears_lockout(server):
    """H2: rotating the PIN also resets a tripped lockout — the owner is
    never locked out of their own share by a classmate's guessing."""
    share, _ = server
    base = f"http://127.0.0.1:{share.port}"
    wrong = "000000" if share.pin != "000000" else "111111"
    for _ in range(5):
        status, _ = _get(f"{base}/api/search?q=x&pin={wrong}")
        assert status == 403
    # even the CORRECT pin is refused while locked out
    status, _ = _get(f"{base}/api/search?q=x&pin={share.pin}")
    assert status == 403
    share.rotate_pin()
    status, _ = _get(f"{base}/api/search?q=x&pin={share.pin}")
    assert status == 200


def test_share_auto_stops_after_ttl(tmp_path):
    """H2: sharing stops by itself after the TTL, and the same server
    object can be started again afterwards."""
    with Library(tmp_path / "lib"):
        share = ShareServer(str(tmp_path / "lib"))
        share.start(ttl_seconds=0.2)
        assert share.is_running()
        try:
            time.sleep(0.8)
            assert not share.is_running()
            conn = http.client.HTTPConnection(
                "127.0.0.1", share.port, timeout=2)
            with pytest.raises(OSError):
                conn.request("GET", "/")
                conn.getresponse()
            conn.close()
            # sharing can start again on the same object
            share.start()
            assert share.is_running()
            status, _ = _get(
                f"http://127.0.0.1:{share.port}/?pin={share.pin}")
            assert status == 200
        finally:
            share.stop()


@pytest.mark.parametrize("name", [
    "notes.exe", "run.bat", "script.ps1", "tool.py",
    "notes.PDF.exe", "app.msi", "macro.vbs",
])
def test_upload_rejects_executable_extensions(server, name):
    """M10: executables and scripts never reach the library."""
    share, _ = server
    status, body = _post(
        f"http://127.0.0.1:{share.port}/api/upload?name={name}"
        f"&pin={share.pin}",
        b"fake-binary")
    assert status == 415
    assert body["error"] == "type"


@pytest.mark.parametrize("name", ["notes.pdf", "pack.zip", "photo.png", "noext"])
def test_upload_accepts_documents_and_archives(server, name):
    """M10 control: documents, archives and extensionless files still
    upload — the block list is narrow, not a whitelist."""
    share, _ = server
    status, body = _post(
        f"http://127.0.0.1:{share.port}/api/upload?name={name}"
        f"&pin={share.pin}",
        b"content")
    assert status == 200, (name, body)
    assert body["status"] == "imported"


def test_upload_rejects_when_disk_full(server, monkeypatch):
    """M10: a full disk fails fast with 507, before a single byte of the
    file is read or staged."""
    from collections import namedtuple
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("shutil.disk_usage",
                        lambda path: usage(10 ** 9, 10 ** 9, 0))
    share, _ = server
    status, body = _post(
        f"http://127.0.0.1:{share.port}/api/upload?name=notes.pdf"
        f"&pin={share.pin}",
        b"content")
    assert status == 507
    assert body["error"] == "space"


def test_concurrent_uploads_all_succeed(server):
    """M10/M12: five phones uploading at once all land in the library —
    the import lock is per-import, not per-request."""
    share, lib = server
    results = []

    def _up(i):
        status, body = _post(
            f"http://127.0.0.1:{share.port}/api/upload?name=parallel-{i}.pdf"
            f"&pin={share.pin}",
            f"parallel-content-{i}".encode())
        results.append((i, status, body))

    threads = [threading.Thread(target=_up, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert len(results) == 5
    assert all(status == 200 for _, status, _ in results), results
    n = lib.conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    assert n == 2 + 5
    names = {r["original_name"] for r in lib.conn.execute(
        "SELECT original_name FROM files").fetchall()}
    assert {f"parallel-{i}.pdf" for i in range(5)} <= names


def test_download_range_requests(ro_server):
    """M11: a phone resumes a failed download with Range instead of
    restarting it — single ranges, suffix and open-ended ranges, and a
    416 for anything unsatisfiable or multi-range."""
    share, lib = ro_server
    fid = lib.conn.execute(
        "SELECT id FROM files ORDER BY id").fetchone()["id"]
    base = f"http://127.0.0.1:{share.port}/api/file/{fid}?pin={share.pin}"
    # a plain download still works and advertises resume support
    status, body, res = _exchange(base)
    assert status == 200 and body == b"content-0"
    assert res.headers["Accept-Ranges"] == "bytes"
    # first four bytes
    status, body, res = _exchange(base, headers={"Range": "bytes=0-3"})
    assert status == 206
    assert res.headers["Content-Range"] == "bytes 0-3/9"
    assert body == b"cont"
    # open-ended range runs to the end
    status, body, res = _exchange(base, headers={"Range": "bytes=5-"})
    assert status == 206
    assert res.headers["Content-Range"] == "bytes 5-8/9"
    assert body == b"nt-0"
    # suffix range takes the last three bytes
    status, body, res = _exchange(base, headers={"Range": "bytes=-3"})
    assert status == 206
    assert res.headers["Content-Range"] == "bytes 6-8/9"
    assert body == b"t-0"
    # past the end of the file
    status, body, res = _exchange(base, headers={"Range": "bytes=9-20"})
    assert status == 416
    assert res.headers["Content-Range"] == "bytes */9"
    # multi-range is not supported — 416, per the single-range contract
    status, body, res = _exchange(
        base, headers={"Range": "bytes=0-3, 5-8"})
    assert status == 416


def test_stop_returns_quickly_during_download(tmp_path):
    """M12: stopping sharing during a big download returns at once
    instead of waiting out the whole transfer (the old behaviour hung
    until the socket timeout, ~5 s, per chunk)."""
    with Library(tmp_path / "lib") as lib:
        big = tmp_path / "big.pdf"
        big.write_bytes(b"x" * (20 * 1024 * 1024))
        import_file(lib, big)
        fid = lib.conn.execute(
            "SELECT id FROM files").fetchone()["id"]
        share = ShareServer(str(tmp_path / "lib"))
        share.start()
        started = threading.Event()

        def _download():
            try:
                conn = http.client.HTTPConnection(
                    "127.0.0.1", share.port, timeout=10)
                conn.request("GET", f"/api/file/{fid}?pin={share.pin}")
                res = conn.getresponse()
                res.read(1024)  # first chunk, then stop reading entirely
                started.set()
                time.sleep(10)  # hold the connection open, unread
                conn.close()
            except Exception:  # noqa: BLE001 - the server may cut us off
                pass

        t = threading.Thread(target=_download, daemon=True)
        try:
            t.start()
            assert started.wait(timeout=5), "download never started"
            time.sleep(0.5)  # let the server reach the blocked write
            t0 = time.monotonic()
            share.stop()
            elapsed = time.monotonic() - t0
            assert elapsed < 3.0, f"stop() took {elapsed:.2f}s mid-download"
            assert not share.is_running()
        finally:
            if share.is_running():
                share.stop()
            t.join(timeout=2)


def test_search_reports_total_and_truncated(server, tmp_path, monkeypatch):
    """M30: /api/search reports the true total and whether the page was
    capped, instead of silently presenting 300 rows as the library."""
    from darspack.web import server as server_module
    share, lib = server
    for i in range(3):
        p = tmp_path / f"extra-{i}.pdf"
        p.write_bytes(f"extra-content-{i}".encode())  # distinct bytes:
        # identical content would be deduplicated by content hash
        import_file(lib, p)
    monkeypatch.setattr(server_module, "SEARCH_LIMIT", 3)
    status, body = _get(
        f"http://127.0.0.1:{share.port}/api/search?pin={share.pin}")
    assert status == 200
    data = json.loads(body)
    assert len(data["files"]) == 3
    assert data["total"] == 5
    assert data["truncated"] is True
    monkeypatch.setattr(server_module, "SEARCH_LIMIT", 300)
    status, body = _get(
        f"http://127.0.0.1:{share.port}/api/search?pin={share.pin}")
    data = json.loads(body)
    assert len(data["files"]) == 5
    assert data["total"] == 5
    assert data["truncated"] is False


# --- server helpers: range parsing (download resume) + server-thread opens ---

@pytest.mark.parametrize("header,size,expected", [
    ("bytes=0-99", 100, (0, 99)),
    ("bytes=5-10", 100, (5, 10)),
    ("bytes=50-", 100, (50, 99)),
    ("bytes=-50", 100, (50, 99)),
    ("bytes=-500", 100, (0, 99)),  # suffix longer than the file → the whole file
    ("bytes=0-", 100, (0, 99)),
    ("bytes=99-99", 100, (99, 99)),
    ("bytes=-5", 5, (0, 4)),
    # unsatisfiable or invalid ranges → None (the route answers 416)
    ("bytes=100-", 100, None),          # start >= size
    ("bytes=2-1", 100, None),           # end < start
    ("bytes=-0", 100, None),            # zero-length suffix
    ("bytes=0-99,100-199", 200, None),  # multi-range
    ("items=0-9", 100, None),           # wrong unit
    ("bytes=a-b", 100, None),
    ("bytes=0-99", 0, None),            # empty file
])
def test_parse_range(header, size, expected):
    assert _parse_range(header, size) == expected


def test_open_server_library_opens_a_connection_without_maintenance(tmp_path):
    # The server's per-thread opens skip schema init / orphan sweep / health
    # check (the desktop opens the library first); the connection must still
    # answer queries for the phone path.
    with Library(tmp_path / "srv-lib") as lib:
        p = tmp_path / "ریاضی.pdf"
        p.write_bytes(b"data")
        import_file(lib, p)
    srv = _open_server_library(str(tmp_path / "srv-lib"))
    try:
        assert [r["original_name"] for r in
                srv.conn.execute("SELECT original_name FROM files")] == ["ریاضی.pdf"]
    finally:
        srv.close()


def test_malformed_query_params_file_ids_and_kind_do_not_drop_connection(ro_server):
    share, _ = ro_server
    base = f"http://127.0.0.1:{share.port}"

    # Superscript digit '²' passes str.isdigit() in Python, and >64-bit ints
    # overflow SQLite — neither should drop the socket or return 500.
    for path in (
        f"/api/search?pin={share.pin}&subject_id=%C2%B2",
        f"/api/search?pin={share.pin}&subject_id=99999999999999999999999",
    ):
        status, body = _get(base + path)
        assert status == 200
        assert "files" in json.loads(body)

    for bad_id in (urllib.parse.quote("²"), "99999999999999999999999"):
        status, body = _get_error(f"{base}/api/file/{bad_id}?pin={share.pin}")
        assert status == 400
        assert json.loads(body)["error"] == "id"

    status, reply = _post(
        f"{base}/api/upload?pin={share.pin}&name=x.pdf&kind=badkind",
        b"payload",
    )
    assert status == 400
    assert reply == {"error": "kind"}


def test_empty_trash_before_upload_does_not_busy_lock_server(server):
    share, lib = server
    p = Path(lib.root).parent / "gone.pdf"
    p.write_bytes(b"to-delete")
    res = import_file(lib, p)
    lib.move_to_trash(res.file_id)
    lib.empty_trash()

    status, reply = _post(
        f"http://127.0.0.1:{share.port}/api/upload?pin={share.pin}&name=fresh.pdf",
        b"fresh-phone-bytes",
    )
    assert status == 200
    assert reply["status"] == "imported"
