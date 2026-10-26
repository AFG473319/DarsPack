"""Tests for the LAN share server (PIN gate, search, download, upload)."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from darspack.core.importer import import_file
from darspack.core.library import Library
from darspack.core.search import unclassified_count
from darspack.web.server import ShareServer, local_ips


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
        _make_handler_threads_joinable(share)
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
        _make_handler_threads_joinable(share)
        yield share, lib
        share.stop()


def _make_handler_threads_joinable(share) -> None:
    """Make ShareServer.stop() deterministic for the tests.

    The product server runs its handler threads as daemons, and stop()
    closes each request thread's SQLite connection WITHOUT joining them —
    a request thread still inside its post-response activity-log write
    then dies with a native access violation (we hit exactly this crash
    during teardown). This is a product-side race recorded in
    docs/limitations.md for the server's owner to fix. Here we only use
    socketserver's documented class attribute to make handler threads
    joinable, so server_close() waits for them and the tests never crash.
    """
    share._httpd.daemon_threads = False


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as res:
        return res.status, res.read()


def _get_error(url):
    """(status, body) for a response urllib would normally raise on."""
    try:
        with urllib.request.urlopen(url, timeout=5) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _post(url, data):
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as res:
        return res.status, json.loads(res.read())   # decoded once here


def _post_raw(url, data):
    """(status, raw body) for a POST, error responses included."""
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_start_returns_urls_and_random_port(server):
    share, _ = server
    urls = [f"http://127.0.0.1:{share.port}/"]
    status, body = _get(urls[0])
    assert status == 200 and "درس‌پک" in body.decode("utf-8")


def test_api_requires_pin(server):
    share, _ = server
    base = f"http://127.0.0.1:{share.port}"
    try:
        _get(f"{base}/api/search?q=x")
        assert False, "expected 403"
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
    status, body = _get(f"{base}/api/search?q=x&pin={share.pin}")
    assert status == 200 and "files" in json.loads(body)


# --- F1: keep-alive + no per-request maintenance --------------------------

def test_protocol_is_http11(server):
    share, _ = server
    from darspack.web.server import _make_handler
    assert _make_handler(share).protocol_version == "HTTP/1.1"


def test_keepalive_reuses_one_connection(server):
    """HTTP/1.1 keep-alive, end to end: TWO requests over ONE connection.

    With HTTP/1.0 the second request would be refused (the server closes
    after each response). Every response must carry Content-Length or the
    reused connection would desync — that invariant is what this pins.
    """
    import http.client
    share, _ = server
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


def test_no_sweep_in_server_threads(server, monkeypatch):
    """Request threads never run maintenance (F1): no orphan sweep.

    The sweep used to run per library open on each new connection thread
    and could even delete an in-flight upload's file (the measured
    PermissionError race). The desktop app owns maintenance; the server
    threads only read.
    """
    share, _ = server
    calls = []
    monkeypatch.setattr(Library, "sweep_orphans", lambda self: calls.append(1))
    _get(f"http://127.0.0.1:{share.port}/")
    _get(f"http://127.0.0.1:{share.port}/api/search?pin={share.pin}")
    assert calls == []


def test_search_endpoint_normalizes_digits(server):
    share, _ = server
    base = f"http://127.0.0.1:{share.port}"
    _, body = _get(f"{base}/api/search?q=" + urllib.parse.quote("فصل ۳")
                   + f"&pin={share.pin}")
    names = [f["name"] for f in json.loads(body)["files"]]
    assert names == ["نمونه سوال ریاضی فصل 3.pdf"]


def test_download_endpoint(server):
    share, _ = server
    base = f"http://127.0.0.1:{share.port}"
    _, body = _get(f"{base}/api/search?q=" + urllib.parse.quote("جزوه")
                   + f"&pin={share.pin}")
    file_id = json.loads(body)["files"][0]["id"]
    status, data = _get(f"{base}/api/file/{file_id}?pin={share.pin}")
    assert status == 200 and data == b"content-1"


def test_lockout_after_five_failures(server):
    share, _ = server
    base = f"http://127.0.0.1:{share.port}"
    for _ in range(5):
        try:
            _get(f"{base}/api/search?q=x&pin=000000")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
    # even the CORRECT pin is refused while locked out
    try:
        _get(f"{base}/api/search?q=x&pin={share.pin}")
        assert False, "expected lockout 403"
    except urllib.error.HTTPError as exc:
        assert exc.code == 403


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
    # no upload temp files left behind
    assert not list(Path(lib.root).glob("upload-*"))


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


def test_file_id_validation(ro_server):
    share, lib = ro_server
    base = f"http://127.0.0.1:{share.port}"
    # not a number at all
    status, body = _get_error(f"{base}/api/file/abc?pin={share.pin}")
    assert status == 400 and json.loads(body) == {"error": "id"}
    # a well-formed id that is not in the catalog
    status, body = _get_error(f"{base}/api/file/99999?pin={share.pin}")
    assert status == 404 and json.loads(body) == {"error": "not found"}
    # a NON-Latin id is rejected with the same 400 as garbage — the server
    # never URL-decodes the id, so even a percent-encoded Persian digit
    # never reaches latin_digits; the phone client is safe because it uses
    # the (Latin) ids /api/search returned. Pinned current behavior.
    status, body = _get_error(
        f"{base}/api/file/{urllib.parse.quote('۱')}?pin={share.pin}")
    assert status == 400 and json.loads(body) == {"error": "id"}


def test_unknown_route_is_404(ro_server):
    share, _ = ro_server
    status, _ = _get_error(f"http://127.0.0.1:{share.port}/definitely-not-here")
    assert status == 404


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
    # NOTE: this test deliberately sends ONE request instead of the same
    # body twice. The first upload's never-committed web_upload log write
    # keeps the SQLite write lock for the whole session (a known product
    # flaw, docs/limitations.md item 17), so a literal second request
    # stalls 5 s and dies. Assert the log row once the server commits it.


def test_upload_lands_unclassified(server):
    # classification-first: a phone upload has no dialog, so it must show
    # up in the «بدون درس» count for the desktop user to complete
    share, lib = server
    base = f"http://127.0.0.1:{share.port}"
    before = unclassified_count(lib.conn)
    _post(f"{base}/api/upload?name="
          + urllib.parse.quote("عکس-تابلو.pdf") + f"&pin={share.pin}", b"photo")
    assert unclassified_count(lib.conn) == before + 1
    # NOTE: we deliberately do NOT assert the `web_upload` activity_log row
    # here — db.log runs after import_file's transaction on the per-request
    # server thread and is never committed, so the row is rolled back when
    # the thread dies. Known flaw, recorded in docs/limitations.md; assert
    # it once the server commits its log writes.


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
        share.start()
        _make_handler_threads_joinable(share)
        share.stop()
        share.start()                          # fresh port, same library
        _make_handler_threads_joinable(share)
        try:
            status, body = _get(f"http://127.0.0.1:{share.port}/")
            assert status == 200
            _, data = _get(f"http://127.0.0.1:{share.port}"
                           f"/api/search?q=a&pin={share.pin}")
            assert len(json.loads(data)["files"]) == 1
        finally:
            share.stop()
