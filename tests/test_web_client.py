"""Guards for the phone web client (کلاینت گوشی).

The client JS once referenced a non-existent implicit global
(`pin_input` vs the input's real id `pin`), which made the PIN button
silently do nothing. These checks keep the page wired correctly:
every element the JS looks up must exist, the JS must parse, and the
page must be served by the server.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# anchored to the repo root, so the suite runs from any working directory
CLIENT = Path(__file__).resolve().parent.parent / "src" / "darspack" / "web" / "client" / "index.html"


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node not installed — JS syntax check skipped")
def test_js_syntax_is_valid(tmp_path):
    js = tmp_path / "_client_check.js"    # temp folder: no litter in the repo
    js.write_text(
        re.search(r"<script>(.*)</script>",
                  CLIENT.read_text(encoding="utf-8"), re.S).group(1),
        encoding="utf-8")
    result = subprocess.run(
        ["node", "--check", str(js)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


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


def test_client_filters_subjects_through_the_chips():
    """D1: the chips row reads /api/subjects and filters /api/search with
    subject_id / unclassified — the filters the server documents."""
    html = CLIENT.read_text(encoding="utf-8")
    for required in ("/api/subjects", "subject_id=", "unclassified=1",
                     "renderChips", "بدون درس"):
        assert required in html


def test_client_shows_persian_digits_and_sizes():
    """Counts and file sizes must render with Persian digits (۰-۹)."""
    html = CLIENT.read_text(encoding="utf-8")
    assert "faNum" in html
    assert "'۰۱۲۳۴۵۶۷۸۹'" in html          # the digit table itself
    assert "humanSize" in html


def test_client_renders_chapter_with_persian_digits():
    """Chapter and lesson numbers arrive from the API as ints; both must
    pass through faNum — «فصل ۳ / درس ۵», not Latin digits."""
    html = CLIENT.read_text(encoding="utf-8")
    assert "faNum(f.chapter" in html
    assert "faNum(f.lesson" in html


def test_client_upload_is_styled_and_accepts_multiple():
    """The native file input shows English «No file chosen / Choose File»
    and takes one file; the client now hides it behind a Persian label
    and accepts a multi-file selection."""
    html = CLIENT.read_text(encoding="utf-8")
    assert re.search(r'<input[^>]*id="up"[^>]*multiple', html)
    assert 'class="upload-btn"' in html
    assert 'for="up"' in html


def test_client_declares_a_pwa_and_the_bundled_font():
    """The phone page is installable (manifest + theme colour + icons)
    and uses the same Vazirmatn font as the desktop app."""
    html = CLIENT.read_text(encoding="utf-8")
    for required in (
            'rel="manifest"', "manifest.webmanifest", 'name="theme-color"',
            "/icons/icon-192.png", "@font-face",
            "/fonts/Vazirmatn-Regular.ttf"):
        assert required in html


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node not installed — boot check skipped")
def test_returning_user_with_a_saved_pin_sees_the_library(tmp_path):
    """Bug (2026-10-29): on a reload with a stored PIN the client filled
    the DOM but never un-hid #files — both containers stayed display:none,
    so every returning visitor got a blank page."""
    state = _boot_state(tmp_path, stored_pin="123456")
    assert state["files"] == "block"
    assert state["pinbox"] == "none"


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node not installed — boot check skipped")
def test_first_visit_without_a_pin_sees_the_pin_screen(tmp_path):
    state = _boot_state(tmp_path, stored_pin="")
    assert state["files"] == "none"
    assert state["pinbox"] == "block"


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node not installed — boot check skipped")
def test_client_shows_chapter_and_lesson_together(tmp_path):
    """A file with both book positions must render both, with Persian
    digits — the old meta line had no lesson field at all."""
    state = _boot_state(
        tmp_path, stored_pin="123456",
        files=[{"id": 1, "name": "x.pdf", "subject": "ریاضی",
                "chapter": 3, "lesson": 5, "kind": "جزوه", "size": 1024}])
    assert "فصل ۳" in state["list"]
    assert "درس ۵" in state["list"]


def test_client_normalizes_persian_pin_and_includes_font_medium():
    html = CLIENT.read_text(encoding="utf-8")
    assert "latinDigits" in html
    assert "/fonts/Vazirmatn-Medium.ttf" in html
    assert "logoutPin" in html
    assert "clearSearch" in html
    assert "<bdi dir=\"auto\">" in html


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node not installed — Persian PIN check skipped")
def test_client_persian_digits_in_save_pin(tmp_path):
    html = CLIENT.read_text(encoding="utf-8")
    source = re.search(r"<script>([\s\S]*)</script>", html).group(1)
    harness = tmp_path / "pin_harness.js"
    harness.write_text(f"""
const elements = {{}};
const make = () => ({{ style: {{}}, textContent: '', innerHTML: '', value: '' }});
const document = {{ getElementById: id => (elements[id] ||= make()) }};
const store = {{}};
const localStorage = {{
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => {{ store[k] = String(v); }},
  removeItem: k => {{ delete store[k]; }},
}};
let seenUrl = '';
const fetch = async (url) => {{
  seenUrl = url;
  return {{ status: 200, json: async () => ({{ files: [], subjects: [], unclassified: 0 }}) }};
}};
const vm = require('vm');
const context = {{ document, localStorage, fetch, setTimeout, clearTimeout,
                   console, encodeURIComponent, JSON }};
vm.createContext(context);
vm.runInContext({json.dumps(source)}, context);
document.getElementById('pin').value = '۱۲۳۴۵۶';
Promise.resolve(context.savePin()).then(() => {{
  console.log(JSON.stringify({{ stored: store['darspack-pin'], url: seenUrl }}));
}});
""", encoding="utf-8")
    res = subprocess.run(["node", str(harness)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out["stored"] == "123456"
    assert "pin=123456" in out["url"]


def _boot_state(tmp_path, stored_pin: str, files: list | None = None) -> dict:
    """Run the page boot in Node with a stub DOM and report which panel
    the boot path made visible plus the rendered list. Real behavior, no
    browser dependency."""
    harness = tmp_path / "boot_harness.js"
    pin_line = (f'store["darspack-pin"] = {json.dumps(stored_pin)};'
                if stored_pin else "")
    payload = json.dumps(files or [], ensure_ascii=False)
    harness.write_text(f"""
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync(process.argv[2], 'utf8');
const source = html.match(/<script>([\\s\\S]*)<\\/script>/)[1];
const elements = {{}};
const make = () => ({{ style: {{}}, textContent: '', innerHTML: '', value: '' }});
const document = {{ getElementById: id => (elements[id] ||= make()) }};
const store = {{}};
{pin_line}
const localStorage = {{
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => {{ store[k] = String(v); }},
  removeItem: k => {{ delete store[k]; }},
}};
const fetch = async () => ({{ status: 200,
  json: async () => ({{ files: {payload}, subjects: [], unclassified: 0 }}) }});
const context = {{ document, localStorage, fetch, setTimeout, clearTimeout,
                   console, encodeURIComponent, JSON }};
vm.createContext(context);
vm.runInContext(source, context);
setTimeout(() => {{
  const display = id => (elements[id] ? elements[id].style.display : '(missing)');
  console.log(JSON.stringify({{ files: display('files'),
                                pinbox: display('pinbox'),
                                list: elements['list'] ? elements['list'].innerHTML : '' }}));
  process.exit(0);
}}, 50);
""", encoding="utf-8")
    result = subprocess.run(
        ["node", str(harness), str(CLIENT)],
        capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])

def test_client_shows_try_again_message_when_server_is_busy():
    """H1: a 503 {"error": "busy"} upload answer must reach the user as
    a 'try again in a moment' message, not the generic failure text."""
    html = CLIENT.read_text(encoding="utf-8")
    assert "error === 'busy'" in html
    assert "سرور مشغول است" in html
