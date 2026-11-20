"""Tests for normalized search (جست‌جو)."""
import pytest

from darspack.core import db
from darspack.core.library import Library
from darspack.core.normalize import match_key
from darspack.core.search import search


@pytest.fixture()
def lib(tmp_path):
    library = Library(tmp_path / "lib", maintain=False).open()
    db.init_schema(library.conn)
    library.seed_subjects()
    seed_files = [
        ("نمونه سوال ریاضی فصل 3.pdf", 3, None, "نمونه‌سوال", "sha-1"),
        ("کاربرگ ریاضی فصل دو.pdf", 2, None, "کاربرگ", "sha-2"),
        ("جزوه علوم تجربی.pdf", None, None, "جزوه", "sha-3"),
        ("summary.PDF", None, None, None, "sha-4"),
    ]
    with library.conn:
        for name, ch, les, kind, sha in seed_files:
            library.conn.execute(
                """INSERT INTO files(stored_name, original_name, name_norm,
                   size_bytes, sha256, imported_at, chapter, lesson, kind, available)
                   VALUES (?, ?, ?, 100, ?, '2026-10-24T12:00:00', ?, ?, ?, 1)""",
                (name, name, match_key(name), sha, ch, les, kind))
    yield library
    library.close()


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


# --- the metadata half of the promise: names, subjects AND tags ----------

def _classify(lib, file_id, subject_name, tags=()):
    """Give a file a subject and tags the way the dialogs do."""
    sid = db.get_or_create(lib.conn, "subjects", subject_name)
    lib.conn.execute("UPDATE files SET subject_id=? WHERE id=?", (sid, file_id))
    for tag in tags:
        tid = db.get_or_create(lib.conn, "tags", tag)
        lib.conn.execute(
            "INSERT OR IGNORE INTO file_tags(file_id, tag_id) VALUES (?,?)",
            (file_id, tid))
    lib.conn.commit()


def test_tag_matches_even_when_name_does_not(lib):
    file_id = lib.conn.execute(
        "SELECT id FROM files WHERE original_name LIKE 'summary%'"
    ).fetchone()["id"]
    _classify(lib, file_id, "انگلیسی", tags=("امتحان",))
    rows = search(lib.conn, "امتحان")
    assert [r["original_name"] for r in rows] == ["summary.PDF"]


def test_subject_name_matches_files_classified_under_it(lib):
    # the documented promise: matching covers the filename AND the subject
    file_id = lib.conn.execute(
        "SELECT id FROM files WHERE original_name LIKE 'summary%'"
    ).fetchone()["id"]
    _classify(lib, file_id, "ریاضی")           # name has no ریاضی at all
    got = names(search(lib.conn, "ریاضی"))
    assert "summary.PDF" in got                # found through the subject


def test_subject_id_filter(lib):
    fid = lib.conn.execute(
        "SELECT id FROM files WHERE original_name LIKE 'summary%'"
    ).fetchone()["id"]
    _classify(lib, fid, "علوم")
    sid = lib.conn.execute(
        "SELECT id FROM subjects WHERE name='علوم'").fetchone()["id"]
    rows = search(lib.conn, "", subject_id=sid)
    assert [r["original_name"] for r in rows] == ["summary.PDF"]


def test_kind_filter(lib):
    rows = search(lib.conn, "", kind="نمونه‌سوال")
    assert [r["original_name"] for r in rows] == ["نمونه سوال ریاضی فصل 3.pdf"]


def test_query_combined_with_subject_filter(lib):
    # classify one of the two ریاضی-named files, then filter: the query
    # alone matches both, the filter narrows the result to the classified one
    fid = lib.conn.execute(
        "SELECT id FROM files WHERE original_name LIKE 'نمونه سوال%'"
    ).fetchone()["id"]
    _classify(lib, fid, "ریاضی")
    sid = lib.conn.execute(
        "SELECT id FROM subjects WHERE name='ریاضی'").fetchone()["id"]
    assert len(search(lib.conn, "ریاضی")) == 2
    rows = search(lib.conn, "ریاضی", subject_id=sid)
    assert [r["original_name"] for r in rows] == ["نمونه سوال ریاضی فصل 3.pdf"]


def test_limit_caps_results(lib):
    assert len(search(lib.conn, "", limit=2)) == 2


def test_zwnj_query_finds_spaced_name(lib):
    # a query typed with the half-space (نمونه‌سوال) must find files stored
    # as «نمونه سوال» — both sides go through match_key
    rows = search(lib.conn, "نمونه‌سوال")
    assert [r["original_name"] for r in rows] == ["نمونه سوال ریاضی فصل 3.pdf"]


def test_same_rank_orders_newest_first(tmp_path):
    # deterministic-ordering guard: _now() has second resolution, so two
    # real imports can tie — here rows are inserted with explicit
    # imported_at values to pin the newest-first rule within one rank
    with Library(tmp_path / "lib") as lib:
        for i, ts in enumerate(("2026-10-24T10:00:00", "2026-10-25T10:00:00")):
            name = f"فایل {i}.pdf"
            lib.conn.execute(
                """INSERT INTO files(stored_name, original_name, name_norm,
                   size_bytes, sha256, imported_at)
                   VALUES ('', ?, ?, 3, ?, ?)""",
                (name, match_key(name), f"sha-{i}", ts))
        lib.conn.commit()
        rows = search(lib.conn, "فایل")
        assert [r["original_name"] for r in rows] == ["فایل 1.pdf", "فایل 0.pdf"]


# --- C1: multi-token (AND) search ------------------------------------------

def test_reordered_tokens_find_the_same_files(lib):
    # the canonical query «ریاضی نمونه سوال» — real filenames order the
    # same words differently («نمونه سوال ریاضی …»); contiguous LIKE missed them
    assert names(search(lib.conn, "ریاضی نمونه سوال")) == \
        names(search(lib.conn, "نمونه سوال ریاضی"))
    assert set(names(search(lib.conn, "ریاضی نمونه سوال"))) == {
        "نمونه سوال ریاضی فصل 3.pdf"}


def test_every_token_must_match_somewhere(lib):
    # AND semantics: one non-matching token filters everything out
    assert names(search(lib.conn, "ریاضی ناموجود")) == []
    assert names(search(lib.conn, "ریاضی فصل 3")) == \
        ["نمونه سوال ریاضی فصل 3.pdf"]


def test_multitoken_query_still_finds_by_subject_and_tag(lib):
    # each token may match a DIFFERENT surface: name, subject, tag
    fid = lib.conn.execute(
        "SELECT id FROM files WHERE original_name LIKE 'summary%'"
    ).fetchone()["id"]
    _classify(lib, fid, "ریاضی", tags=("امتحان",))
    rows = search(lib.conn, "ریاضی امتحان")
    assert [r["original_name"] for r in rows] == ["summary.PDF"]


def test_pasted_garbage_never_crashes(lib):
    long_text = ("کلمه " * 50).strip()          # 50 tokens — over the cap
    assert isinstance(search(lib.conn, long_text), list)
    assert isinstance(search(lib.conn, "ریاضی " * 20), list)
    assert search(lib.conn, "   ") == search(lib.conn, "")


# --- C2: structured metadata participates in search -------------------------

def test_note_is_searchable(lib):
    fid = lib.conn.execute(
        "SELECT id FROM files WHERE original_name LIKE 'summary%'"
    ).fetchone()["id"]
    lib.conn.execute("UPDATE files SET note='از امتحان میانترم میاد' WHERE id=?",
                     (fid,))
    lib.conn.commit()
    assert [r["original_name"] for r in search(lib.conn, "میانترم")] == \
        ["summary.PDF"]


def test_kind_word_matches_classified_files(lib):
    # «کاربرگ» is the stored kind of one file whose name contains it — but
    # the match must ALSO work through the kind column for files whose
    # name never says it
    fid = lib.conn.execute(
        "SELECT id FROM files WHERE original_name LIKE 'summary%'"
    ).fetchone()["id"]
    lib.conn.execute("UPDATE files SET kind='کاربرگ' WHERE id=?", (fid,))
    lib.conn.commit()
    got = names(search(lib.conn, "کاربرگ"))
    assert got == ["کاربرگ ریاضی فصل دو.pdf", "summary.PDF"]


def test_chapter_number_finds_files_whose_name_lacks_fasl(lib):
    # «فصل ۵» must find a classified file even when the filename never
    # mentions the word — that is what the chapter COLUMN is for
    fid = lib.conn.execute(
        "SELECT id FROM files WHERE original_name LIKE 'summary%'"
    ).fetchone()["id"]
    lib.conn.execute("UPDATE files SET chapter=5 WHERE id=?", (fid,))
    lib.conn.commit()
    got = set(names(search(lib.conn, "فصل 5")))
    # the summary row comes from its chapter COLUMN (name has no فصل);
    # the ریاضی file is فصل 3, so the number must NOT drag it in
    assert got == {"summary.PDF"}
    # and the Persian-digit twin behaves identically
    assert set(names(search(lib.conn, "فصل ۵"))) == got


def test_lesson_number_finds_files_whose_name_lacks_dars(lib):
    fid = lib.conn.execute(
        "SELECT id FROM files WHERE original_name LIKE 'summary%'"
    ).fetchone()["id"]
    lib.conn.execute("UPDATE files SET lesson=3 WHERE id=?", (fid,))
    lib.conn.commit()
    assert names(search(lib.conn, "درس 3")) == ["summary.PDF"]


def test_fasl_and_dars_target_their_own_columns(lib):
    fid = lib.conn.execute(
        "SELECT id FROM files WHERE original_name LIKE 'summary%'"
    ).fetchone()["id"]
    lib.conn.execute("UPDATE files SET lesson=3 WHERE id=?", (fid,))
    lib.conn.commit()
    # «فصل 3» must NOT match a file whose LESSON is 3 — separate columns
    # (design decision 2026-10-24), so the summary row is not in «فصل 3»
    assert "summary.PDF" not in names(search(lib.conn, "فصل 3"))


# --- B1: the available flag rides along with every result ------------------

def test_school_year_filter(lib):
    rows = search(lib.conn, "")
    fid = rows[0]["id"]
    lib.conn.execute("UPDATE files SET school_year='1404-1405' WHERE id=?", (fid,))
    lib.conn.commit()
    matched = search(lib.conn, "", school_year="1404-1405")
    assert len(matched) == 1
    assert matched[0]["id"] == fid
    assert matched[0]["school_year"] == "1404-1405"
    assert search(lib.conn, "", school_year="1406-1407") == []


def test_school_year_combined_with_query_and_note(lib):
    rows = search(lib.conn, "ریاضی")
    assert len(rows) > 0
    fid = rows[0]["id"]
    lib.conn.execute(
        "UPDATE files SET school_year='1404-1405', note='یادداشت مهم' WHERE id=?",
        (fid,))
    lib.conn.commit()

    matched = search(lib.conn, "ریاضی", school_year="1404-1405")
    assert any(r["id"] == fid for r in matched)
    target = next(r for r in matched if r["id"] == fid)
    assert target["note"] == "یادداشت مهم"
    assert target["school_year"] == "1404-1405"

    unmatched = search(lib.conn, "ریاضی", school_year="1399-1400")
    assert not any(r["id"] == fid for r in unmatched)


def test_like_wildcard_escaping(lib):
    name = "100%_sample.pdf"
    fid = lib.conn.execute(
        """INSERT INTO files(stored_name, original_name, name_norm,
           size_bytes, sha256, imported_at)
           VALUES ('', ?, ?, 3, 'sha-like', '2026-10-30T10:00:00')""",
        (name, match_key(name))).lastrowid
    lib.conn.commit()
    res = search(lib.conn, "100%")
    assert [r["id"] for r in res] == [fid]


def test_search_simultaneous_chapter_and_lesson(lib):
    # Insert a file with both chapter 3 and lesson 5
    name = "آزمون دوره ای.pdf"
    fid = lib.conn.execute(
        """INSERT INTO files(stored_name, original_name, name_norm,
           size_bytes, sha256, imported_at, chapter, lesson)
           VALUES ('', ?, ?, 10, 'sha-dual', '2026-10-30T10:00:00', 3, 5)""",
        (name, match_key(name))).lastrowid
    lib.conn.commit()
    res = search(lib.conn, "فصل 3 درس 5")
    assert any(r["id"] == fid for r in res)
    # Searching with Persian numerals also matches
    res_fa = search(lib.conn, "فصل ۳ درس ۵")
    assert any(r["id"] == fid for r in res_fa)


def test_search_unclassified_only_filter(lib):
    # All 4 default seed files in lib have subject_id=None
    assert len(search(lib.conn, "", unclassified_only=True)) == 4
    # Classify one file
    fid = lib.conn.execute("SELECT id FROM files LIMIT 1").fetchone()["id"]
    _classify(lib, fid, "ریاضی")
    # Now unclassified_only should return exactly 3
    assert len(search(lib.conn, "", unclassified_only=True)) == 3
    # Normal search still returns all 4
    assert len(search(lib.conn, "")) == 4


def test_search_with_brackets_and_punctuation(lib):
    # Files with parens and brackets in their names are found when searched
    name = "جزوه ریاضی (نهم) [ویژه].pdf"
    fid = lib.conn.execute(
        """INSERT INTO files(stored_name, original_name, name_norm,
           size_bytes, sha256, imported_at)
           VALUES ('', ?, ?, 10, 'sha-paren', '2026-10-30T10:00:00')""",
        (name, match_key(name))).lastrowid
    lib.conn.commit()
    res = search(lib.conn, "ریاضی (نهم)")
    assert any(r["id"] == fid for r in res)
    res_bracket = search(lib.conn, "[ویژه]")
    assert any(r["id"] == fid for r in res_bracket)


def test_search_total_counts_match_search_rows(lib):
    """M30: search_total counts exactly the rows search() would return,
    ignoring the page limit — the API's total/truncated flag rests on it."""
    from darspack.core.search import search_total
    assert search_total(lib.conn, "") == 4
    assert search_total(lib.conn, "ریاضی") == 2
    assert search_total(lib.conn, "ریاضی") == len(search(lib.conn, "ریاضی"))
    assert search_total(lib.conn, "ریاضی", kind="جزوه") == 0
    assert search_total(lib.conn, "", unclassified_only=True) == 4
    assert search_total(lib.conn, "علوم") == 1
    assert search_total(lib.conn, "نیم‌فاصله‌ای که نیست") == 0
