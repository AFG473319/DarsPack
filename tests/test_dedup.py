"""Tests for duplicate/conflict detection (R1/R2/R3) against the labelled
synthetic test set — the same set the benchmark measures."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
from make_testset import make_testset  # noqa: E402

from darspack.core.dedup import duplicate_groups, rename_hints, version_conflicts  # noqa: E402
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
