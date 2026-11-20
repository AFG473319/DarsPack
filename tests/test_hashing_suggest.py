"""Tests for streaming SHA-256 and filename suggestions."""
import hashlib

from darspack.core.hashing import sha256_file
from darspack.core.suggest import suggest

ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_sha256_known_vector(tmp_path):
    p = tmp_path / "abc.bin"
    p.write_bytes(b"abc")
    assert sha256_file(p) == ABC_SHA256


def test_suggest_full_case():
    out = suggest("نمونه سوال ریاضی نهم فصل 3")
    assert out == {"subject": "ریاضی", "chapter": 3, "lesson": None,
                   "kind": "نمونه‌سوال", "grade": "نهم"}


def test_suggest_word_number_and_zwnj():
    # «علوم» alone is no longer a subject (canonical «علوم تجربی» only,
    # design decision 2026-10-24) — a bare «علوم» filename gets None
    out = suggest("جزوه علوم فصل پنج")
    assert out["chapter"] == 5 and out["kind"] == "جزوه"
    assert out["subject"] is None
    out = suggest("نمونه‌سوال عربی فصل ۷")     # ZWNJ + Persian digit
    assert out["kind"] == "نمونه‌سوال" and out["subject"] == "عربی"
    assert out["chapter"] == 7


def test_suggest_no_match_returns_none():
    assert suggest("IMG_20260101_1234") == {
        "subject": None, "chapter": None, "lesson": None,
        "kind": None, "grade": None}


def test_suggest_arabic_letters_still_match():
    out = suggest("كاربرگ فارسي")              # Arabic ك and ي
    assert out["kind"] == "کاربرگ" and out["subject"] == "فارسی"


# --- uncovered branches and boundaries ----------------------------------

def test_suggest_honors_a_custom_subject_list():
    out = suggest("جزوه فیزیک فصل 2", subjects=["فیزیک"])
    assert out["subject"] == "فیزیک"       # the passed list, not the defaults
    out = suggest("جزوه ریاضی فصل 2", subjects=["فیزیک"])
    assert out["subject"] is None          # a subject outside the list never matches


def test_suggest_chapter_boundaries():
    assert suggest("تکلیف ریاضی فصل 40")["chapter"] == 40    # MAX_CHAPTER edge
    assert suggest("تکلیف ریاضی فصل 41")["chapter"] is None  # above the bound
    assert suggest("جزوه علوم فصل یازده")["chapter"] == 11   # two-digit word number


def test_suggest_first_kind_hint_wins():
    # «نمونه سوال» and «جزوه» both appear in the name — dict order decides:
    # the kind list is checked top to bottom, and نمونه سوال comes first
    assert suggest("نمونه سوال جزوه ریاضی")["kind"] == "نمونه‌سوال"


# --- pinned current behavior still open for a ruling (later review) ---
# Each test below locks a verified behavior that a reasonable person might
# call a bug. Do NOT change the behavior silently: change it together with
# its test, on purpose.

def test_quirk_chapter_123_becomes_12():
    # known quirk (⚖️): the chapter regex takes the first TWO digits, so
    # «فصل 123» silently means chapter 12 instead of no-chapter
    assert suggest("جزوه ریاضی فصل 123")["chapter"] == 12


def test_quirk_chapter_zero_stays_zero():
    # known quirk (⚖️): 0 doubles as "no chapter" in the UI (the dialogs
    # store `value() or None`), but suggest itself still returns 0 here
    assert suggest("جزوه ریاضی فصل 0")["chapter"] == 0


def test_quirk_word_number_matches_inside_longer_words():
    # known quirk (⚖️): word numbers match by substring and are tried in
    # dict order — «فصل دوازده» hits «فصل دو» first, so it suggests chapter
    # 2 and can never mean 12; likewise «فصل یکم» contains «یک» → chapter 1
    assert suggest("جزوه علوم فصل دوازده")["chapter"] == 2
    assert suggest("جزوه ریاضی فصل یکم")["chapter"] == 1


def test_quirk_subject_matches_inside_a_word():
    # known quirk (⚖️): subjects match by substring, so «هنرستان»
    # suggests «هنر» — word-boundary matching is the planned improvement
    assert suggest("برنامه هنرستان")["subject"] == "هنر"


def test_aloom_tajrobi_now_wins():
    # FIXED by a 2026-10-24 design decision: the bare «علوم» entry
    # was removed from DEFAULT_SUBJECTS and matching is longest-first,
    # so «علوم تجربی» — the official textbook name — is what suggests
    assert suggest("جزوه علوم تجربی فصل 3")["subject"] == "علوم تجربی"


# --- the A6 precision pack ------------------------------------------------

def test_suggest_lesson_parsed_separately_from_chapter():
    # «درس N» fills the NEW lesson field (design decision 2026-10-24:
    # درس and فصل are separate columns); «فارسی درس ۳» has no فصل at all
    out = suggest("فارسی درس 3")
    assert out["lesson"] == 3 and out["chapter"] is None
    out = suggest("جزوه ریاضی درس دو فصل 5")
    assert out["lesson"] == 2 and out["chapter"] == 5


def test_suggest_lesson_word_number_and_quirk():
    assert suggest("کاربرگ عربی درس سه")["lesson"] == 3
    # same substring quirk as فصل (pinned above): «درس دوازده» hits
    # «درس دو» first → 2, never 12
    assert suggest("کاربرگ عربی درس دوازده")["lesson"] == 2


def test_suggest_new_kind_keywords():
    for name in ("تست ریاضی", "بانک سوال فیزیک", "سوالات فصل 2"):
        assert suggest(name)["kind"] == "نمونه‌سوال", name
    for name in ("مرور فصل 3", "جمع بندی علوم تجربی", "فرمول های ریاضی"):
        assert suggest(name)["kind"] == "جزوه", name


def test_suggest_grade_hint():
    assert suggest("نمونه سوال ریاضی هشتم")["grade"] == "هشتم"
    assert suggest("کاربرگ هفتم")["grade"] == "هفتم"
    assert suggest("جزوه بدون پایه")["grade"] is None


def test_suggest_longest_match_first_custom_list():
    # longest-match-first also protects a custom list that still holds
    # both spellings: the longer subject wins
    out = suggest("جزوه علوم تجربی فصل 2", subjects=["علوم", "علوم تجربی"])
    assert out["subject"] == "علوم تجربی"


# --- hashing edges --------------------------------------------------------

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_sha256_of_empty_file(tmp_path):
    # a 0-byte upload is a real phone-client scenario; the digest is the
    # well-known empty-input one, and progress is never called (the loop
    # body never runs)
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    seen = []
    assert sha256_file(p, progress=lambda d, t: seen.append((d, t))) == EMPTY_SHA256
    assert seen == []


def test_sha256_exact_at_chunk_boundaries(tmp_path):
    # 1 MB is exactly one chunk; +1 byte forces a second (1-byte) chunk —
    # both must equal the plain hashlib digest, not a padded approximation
    for size in (1024 * 1024, 1024 * 1024 + 1):
        data = b"y" * size
        p = tmp_path / f"edge-{size}.bin"
        p.write_bytes(data)
        assert sha256_file(p) == hashlib.sha256(data).hexdigest()


def test_sha256_progress_never_goes_backwards(tmp_path):
    # a progress bar needs a non-decreasing done counter — pin the sequence
    data = b"x" * (3 * 1024 * 1024)
    p = tmp_path / "big.bin"
    p.write_bytes(data)
    seen = []
    sha256_file(p, progress=lambda done, total: seen.append(done))
    assert seen == sorted(seen)


# --- A4: learned token→subject hints (pre-fill only) ------------------------

def test_learned_hint_fires_only_at_two_hits_and_only_when_list_misses():
    learned = {"رضایی": {"subject": "ریاضی", "hits": 2}}
    # the fixed list missed → the learned rule pre-fills
    assert suggest("جزوه رضایی فصل 2", learned=learned)["subject"] == "ریاضی"
    # one confirmed hit is not enough to fire
    assert suggest("جزوه رضایی فصل 2",
                   learned={"رضایی": {"subject": "ریاضی", "hits": 1}}
                   )["subject"] is None
    # the fixed list always wins when it matches
    assert suggest("جزوه ریاضی رضایی", learned=learned)["subject"] == "ریاضی"


def test_learn_hint_round_trip_through_the_table(tmp_path):
    from darspack.core import db
    from darspack.core.suggest import forget_hint, learn_hint, load_hints, suggest
    conn = db.connect(tmp_path / "h.db")
    try:
        db.init_schema(conn)
        learn_hint(conn, "رضایی", "ریاضی")
        learn_hint(conn, "رضایی", "ریاضی")     # second save → hits = 2
        learn_hint(conn, "ahmadi", "انگلیسی")  # gets normalized/match-keyed
        hints = load_hints(conn)
        assert hints["رضایی"] == {"subject": "ریاضی", "hits": 2}
        assert suggest("جزوه رضایی", learned=hints)["subject"] == "ریاضی"
        forget_hint(conn, "رضایی")
        assert "رضایی" not in load_hints(conn)
        # tiny tokens (filenames like «آ» …) never become rules
        learn_hint(conn, "ab", "ریاضی")
        assert "ab" not in load_hints(conn)
    finally:
        conn.close()
