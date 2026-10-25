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


def test_quirk_aloom_tajrobi_entry_unreachable():
    # known quirk (⚖️): «علوم» precedes «علوم تجربی» in DEFAULT_SUBJECTS
    # and matches first, so the «علوم تجربی» entry can never win. The
    # planned fix is longest-match-first — until then this pins reality.
    assert suggest("جزوه علوم تجربی فصل 3")["subject"] == "علوم"


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
