"""Tests for the LAN share server (PIN gate, search, download, upload)."""
import json
import urllib.request

import pytest

from darspack.core.importer import import_file
from darspack.core.library import Library
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
        yield share, lib
        share.stop()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as res:
        return res.status, res.read()


def _post(url, data):
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as res:
        return res.status, json.loads(res.read())   # decoded once here


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


from pathlib import Path  # noqa: E402  (used in the upload test)
import urllib.parse  # noqa: E402
import urllib.error  # noqa: E402
