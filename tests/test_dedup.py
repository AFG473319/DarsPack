"""Tests for duplicate/conflict detection (R1/R2/R3) against the labelled
synthetic test set — the same set the benchmark measures."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
from make_testset import make_testset  # noqa: E402

from darspack.core.dedup import (  # noqa: E402
    duplicate_groups, likely_versions, rename_hints, strip_version_noise,
    version_conflicts,
)
from darspack.core.normalize import match_key  # noqa: E402
from darspack.core.importer import import_paths  # noqa: E402
from darspack.core.library import Library  # noqa: E402


def _build(tmp_path, count=20, keep_duplicates=True):
    """Import a small labelled test set into a fresh (open) library."""
    labels = make_testset(tmp_path / "set", count=count, seed=42)
    lib = Library(tmp_path / "lib").open()
    import_paths(lib, [tmp_path / "set"], keep_duplicates=keep_duplicates)
    return lib, labels


def test_r1_finds_exactly_the_planted_duplicates(tmp_path):
    lib, labels = _build(tmp_path)
    planted = {tuple(sorted(pair)) for pair in labels["duplicates"]}
    found = set()
    for g in duplicate_groups(lib.conn):
        names = sorted(r["original_name"] for r in g.rows)
        found.add(tuple(names))
    assert found == planted                    # no false positives either


def test_r2_finds_exactly_the_planted_conflicts(tmp_path):
    lib, labels = _build(tmp_path)
    planted = {Path(pair[0]).name for pair in labels["conflicts"]}
    found = {Path(g.rows[0]["original_name"]).name
             for g in version_conflicts(lib.conn)}
    assert found == planted


def test_r3_rename_hints_are_duplicate_groups_with_distinct_names(tmp_path):
    lib, _ = _build(tmp_path)
    for g in rename_hints(lib.conn):
        names = {r["name_norm"] for r in g.rows}
        assert len(names) > 1


def test_default_import_leaves_no_duplicates(tmp_path):
    lib, labels = _build(tmp_path, keep_duplicates=False)
    planted = {tuple(sorted(pair)) for pair in labels["duplicates"]}
    assert planted                             # the set does contain plants
    assert duplicate_groups(lib.conn) == []    # …but import-time dedup removed them


# --- core-algorithm safety net: the empty case, spelling interaction,
# --- and the flag-only rule from both sides -----------------------------

def test_empty_library_has_no_groups(tmp_path):
    lib = Library(tmp_path / "lib").open()
    assert duplicate_groups(lib.conn) == []
    assert version_conflicts(lib.conn) == []
    assert rename_hints(lib.conn) == []


def test_r2_cross_spelling_names_are_one_conflict(tmp_path):
    # normalization × dedup interacting: the Arabic-ي spelling normalizes
    # to the same name_norm as the Persian one, so two DIFFERENT contents
    # under the two spellings are exactly one R2 group — the kind of thing
    # a rewrite can silently break
    lib = Library(tmp_path / "lib").open()
    a = tmp_path / "ریاضی نهم.pdf"
    a.write_bytes(b"persian-yeh version")
    b = tmp_path / "رياضي نهم.pdf"
    b.write_bytes(b"arabic-yeh version")
    import_paths(lib, [a, b])
    groups = version_conflicts(lib.conn)
    assert len(groups) == 1
    assert {r["original_name"] for r in groups[0].rows} == {
        "ریاضی نهم.pdf", "رياضي نهم.pdf"}


def test_r3_finds_exactly_the_planted_duplicates(tmp_path):
    # strengthen R3 like R1/R2 above: every rename hint is a planted
    # duplicate pair (same bytes, different names) and nothing else
    lib, labels = _build(tmp_path)
    planted = {tuple(sorted(pair)) for pair in labels["duplicates"]}
    found = {tuple(sorted(r["original_name"] for r in g.rows))
             for g in rename_hints(lib.conn)}
    assert found == planted


def test_default_import_keeps_version_conflicts(tmp_path):
    # the other half of the flag-only rule: import-time dedup removes only
    # EXACT copies — different-content versions stay stored and stay flagged
    lib, labels = _build(tmp_path, keep_duplicates=False)
    assert len(version_conflicts(lib.conn)) == len(labels["conflicts"])


# --- R4-lite: likely versions (re-download noise, different content) -------

@pytest.fixture()
def conn(tmp_path):
    import sqlite3
    from darspack.core import db
    c = db.connect(tmp_path / "catalog.db")
    db.init_schema(c)
    yield c
    c.close()


def _insert_file(conn, name, sha, ts="2026-10-25T10:00:00"):
    conn.execute(
        """INSERT INTO files(stored_name, original_name, name_norm,
           size_bytes, sha256, imported_at) VALUES ('', ?, ?, 3, ?, ?)""",
        (name, match_key(name), sha, ts))


def test_strip_version_noise_table():
    # every noise marker vanishes; everything else stays untouched
    assert strip_version_noise("جزوه ریاضی.pdf") == "جزوه ریاضی.pdf"
    for noisy, clean in [
        ("جزوه ریاضی (1).pdf", "جزوه ریاضی.pdf"),
        ("جزوه ریاضی نهایی.pdf", "جزوه ریاضی.pdf"),
        ("جزوه ریاضی نسخه 2.pdf", "جزوه ریاضی.pdf"),
        ("جزوه ریاضی final.pdf", "جزوه ریاضی.pdf"),
        ("جزوه ریاضی v2.pdf", "جزوه ریاضی.pdf"),
        ("جزوه ریاضی اصلاح شده.pdf", "جزوه ریاضی.pdf"),
    ]:
        assert strip_version_noise(noisy) == clean, noisy


def test_likely_versions_groups_redownload_pair(conn):
    _insert_file(conn, "کاربرگ ریاضی.pdf", "sha-a")
    _insert_file(conn, "کاربرگ ریاضی (1).pdf", "sha-b")
    groups = likely_versions(conn)
    assert len(groups) == 1
    assert {r["original_name"] for r in groups[0].rows} == {
        "کاربرگ ریاضی.pdf", "کاربرگ ریاضی (1).pdf"}


def test_likely_versions_groups_final_marker_pair(conn):
    _insert_file(conn, "جزوه علوم.pdf", "sha-a")
    _insert_file(conn, "جزوه علوم نهایی.pdf", "sha-b")
    assert len(likely_versions(conn)) == 1


def test_likely_versions_ignores_identical_content(conn):
    # same bytes under noisy names = R1's territory, not a version conflict
    _insert_file(conn, "جزوه علوم.pdf", "sha-a")
    _insert_file(conn, "جزوه علوم (1).pdf", "sha-a")
    assert likely_versions(conn) == []


def test_likely_versions_ignores_genuinely_different_files(conn):
    # different stripped keys never group, whatever the prefix overlap
    _insert_file(conn, "جزوه ریاضی.pdf", "sha-a")
    _insert_file(conn, "جزوه علوم.pdf", "sha-b")
    assert likely_versions(conn) == []


def test_likely_versions_ignores_single_name(conn):
    # >1 distinct NAME is required: one file under a noisy name alone
    # must not self-group
    _insert_file(conn, "جزوه علوم (1).pdf", "sha-a")
    assert likely_versions(conn) == []
