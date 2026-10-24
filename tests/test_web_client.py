"""Guards for the phone web client (کلاینت گوشی).

The client JS once referenced a non-existent implicit global
(`pin_input` vs the input's real id `pin`), which made the PIN button
silently do nothing. These checks keep the page wired correctly:
every element the JS looks up must exist, the JS must parse, and the
page must be served by the server.
"""
import re
import urllib.request
from pathlib import Path

CLIENT = Path("src/darspack/web/client/index.html")


def test_js_syntax_is_valid():
    import subprocess
    html = CLIENT.read_text(encoding="utf-8")
    script = re.search(r"<script>(.*)</script>", html, re.S).group(1)
    js = Path("_client_check.js")
    js.write_text(script, encoding="utf-8")
    try:
        result = subprocess.run(
            ["node", "--check", str(js)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    finally:
        js.unlink(missing_ok=True)


def test_every_element_used_by_js_exists_in_html():
    html = CLIENT.read_text(encoding="utf-8")
    script = re.search(r"<script>(.*)</script>", html, re.S).group(1)
    ids_in_html = set(re.findall(r'id="([^"]+)"', html))
    ids_used = set(re.findall(r"\$\('([^']+)'\)", script))
    assert ids_used, "the JS must use explicit $() lookups"
    assert ids_used <= ids_in_html, f"missing ids: {ids_used - ids_in_html}"


def test_no_implicit_id_globals_in_js():
    script = re.search(r"<script>(.*)</script>",
                       CLIENT.read_text(encoding="utf-8"), re.S).group(1)
    for leaked in ("pin_input", "pinbox.style", "files.style", "list.innerHTML",
                   "upstatus.textContent"):
        assert leaked not in script, f"implicit global usage: {leaked}"


def test_client_page_is_rtl_and_has_pin_flow():
    html = CLIENT.read_text(encoding="utf-8")
    assert 'dir="rtl"' in html
    for required in ("savePin", "darspack-pin", "/api/search",
                     "/api/upload", "/api/file/"):
        assert required in html
