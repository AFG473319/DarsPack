"""Tests for normalized search (جست‌جو)."""
import pytest

from darspack.core.importer import import_file
from darspack.core.library import Library
from darspack.core.search import search


@pytest.fixture()
def lib(tmp_path):
    with Library(tmp_path / "lib") as library:
        for name in ("نمونه سوال ریاضی فصل 3.pdf",
                     "کاربرگ ریاضی فصل دو.pdf",
                     "جزوه علوم تجربی.pdf",
                     "summary.PDF"):
            p = tmp_path / name
            p.write_bytes(f"data-{name}".encode("utf-8"))
            import_file(library, p)
        yield library


def names(rows):
    return [r["original_name"] for r in rows]


def test_persian_and_latin_digits_match_equally(lib):
    assert names(search(lib.conn, "فصل 3")) == names(search(lib.conn, "فصل ۳"))
    assert names(search(lib.conn, "فصل 3")) == ["نمونه سوال ریاضی فصل 3.pdf"]


def test_subject_word_matches_multiple_files(lib):
    got = names(search(lib.conn, "ریاضی"))
    assert set(got) == {"نمونه سوال ریاضی فصل 3.pdf", "کاربرگ ریاضی فصل دو.pdf"}


def test_word_number_chapter_found(lib):
    assert names(search(lib.conn, "فصل دو")) == ["کاربرگ ریاضی فصل دو.pdf"]


def test_arabic_yeh_matches_persian_yeh(lib):
    assert search(lib.conn, "رياضي")           # Arabic ي
    assert names(search(lib.conn, "رياضي")) == names(search(lib.conn, "ریاضی"))


def test_casefolded_latin(lib):
    assert names(search(lib.conn, "SUMMARY")) == ["summary.PDF"]


def test_prefix_ranks_before_contains(lib):
    rows = search(lib.conn, "جزوه")
    assert rows[0]["original_name"] == "جزوه علوم تجربی.pdf"


def test_empty_query_lists_everything(lib):
    assert len(search(lib.conn, "")) == 4
