"""Tests for streaming SHA-256 and filename suggestions."""
import hashlib

from darspack.core.hashing import sha256_file
from darspack.core.suggest import suggest

ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_sha256_known_vector(tmp_path):
    p = tmp_path / "abc.bin"
    p.write_bytes(b"abc")
    assert sha256_file(p) == ABC_SHA256


def test_sha256_large_file_chunked(tmp_path):
    data = b"x" * (3 * 1024 * 1024)          # forces several 1 MB chunks
    p = tmp_path / "big.bin"
    p.write_bytes(data)
    seen = []
    sha256_file(p, progress=lambda done, total: seen.append((done, total)))
    assert sha256_file(p) == hashlib.sha256(data).hexdigest()
    assert seen[-1] == (len(data), len(data))  # progress reached the end


def test_suggest_full_case():
    out = suggest("نمونه سوال ریاضی نهم فصل 3")
    assert out == {"subject": "ریاضی", "chapter": 3, "kind": "نمونه‌سوال"}


def test_suggest_word_number_and_zwnj():
    out = suggest("جزوه علوم فصل پنج")
    assert out["chapter"] == 5 and out["kind"] == "جزوه" and out["subject"] == "علوم"
    out = suggest("نمونه‌سوال عربی فصل ۷")     # ZWNJ + Persian digit
    assert out["kind"] == "نمونه‌سوال" and out["subject"] == "عربی"
    assert out["chapter"] == 7


def test_suggest_no_match_returns_none():
    assert suggest("IMG_20260101_1234") == {
        "subject": None, "chapter": None, "kind": None}


def test_suggest_arabic_letters_still_match():
    out = suggest("كاربرگ فارسي")              # Arabic ك and ي
    assert out["kind"] == "کاربرگ" and out["subject"] == "فارسی"
