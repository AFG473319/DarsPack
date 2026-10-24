"""Tests for the sync manifest + diff (سنکرون)."""
from darspack.core.importer import import_file
from darspack.core.library import Library
from darspack.web.sync import catalog_manifest, diff


def test_manifest_groups_by_content(tmp_path):
    with Library(tmp_path / "lib") as lib:
        for i, name in enumerate(("a.pdf", "b.pdf")):
            p = tmp_path / name
            p.write_bytes(b"same-bytes")
            import_file(lib, p)
        manifest = catalog_manifest(lib.conn)
        assert len(manifest) == 1              # one sha256, not two rows
        assert next(iter(manifest.values()))["size"] == len(b"same-bytes")


def test_diff_symmetry_and_rename_detection():
    ours = {"S1": {"name": "a.pdf"}, "S2": {"name": "b.pdf"}}
    theirs = {"S1": {"name": "a-old.pdf"}, "S3": {"name": "c.pdf"}}
    d = diff(ours, theirs)
    assert d["missing_on_theirs"] == ["S2"]    # they can fetch it from us
    assert d["missing_on_ours"] == ["S3"]      # we can fetch it from them
    assert d["same_content_different_name"] == ["S1"]


def test_diff_identical_manifests_is_empty():
    m = {"S1": {"name": "a.pdf"}}
    assert diff(m, m) == {"missing_on_theirs": [], "missing_on_ours": [],
                          "same_content_different_name": []}
