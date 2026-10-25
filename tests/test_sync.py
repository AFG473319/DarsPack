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


# --- core-algorithm safety net: entry contents, degenerate diffs, and the
# --- whole-module path the server actually uses --------------------------

def test_manifest_entries_carry_name_and_size(tmp_path):
    with Library(tmp_path / "lib") as lib:
        for i, name in enumerate(("a.pdf", "b.pdf")):
            p = tmp_path / name
            p.write_bytes(f"bytes-{i}".encode())
            import_file(lib, p)
        m = catalog_manifest(lib.conn)
        assert len(m) == 2                     # one entry per distinct content
        assert {e["name"] for e in m.values()} == {"a.pdf", "b.pdf"}
        assert {e["size"] for e in m.values()} == {len("bytes-0"), len("bytes-1")}


def test_manifest_picks_one_name_per_content(tmp_path):
    # known quirk (⚖️): with two names for the same bytes, catalog_manifest
    # keeps ONE entry per sha256 and its name is whichever row the GROUP BY
    # returns — deliberately not pinned to a specific name. Fine for diff
    # semantics; the rewrite should make the choice deterministic.
    with Library(tmp_path / "lib") as lib:
        for name in ("first.pdf", "second.pdf"):
            p = tmp_path / name
            p.write_bytes(b"same")
            import_file(lib, p)
        m = catalog_manifest(lib.conn)
        assert len(m) == 1
        assert next(iter(m.values()))["name"] in {"first.pdf", "second.pdf"}


def test_diff_with_empty_sides():
    m = {"S1": {"name": "a.pdf"}, "S2": {"name": "b.pdf"}}
    assert diff({}, {}) == {"missing_on_theirs": [], "missing_on_ours": [],
                            "same_content_different_name": []}
    d = diff(m, {})                            # they have nothing at all
    assert d["missing_on_theirs"] == ["S1", "S2"]   # sorted shas
    assert d["missing_on_ours"] == []
    assert d["same_content_different_name"] == []


def test_diff_between_two_real_libraries(tmp_path):
    # the end-to-end guard: build two libraries the way two students would
    # have them, then diff their catalogs. B has one file we lack, one we
    # have that they lack, and one renamed copy of ours.
    with Library(tmp_path / "a") as lib_a, Library(tmp_path / "b") as lib_b:
        x = tmp_path / "a.pdf"
        x.write_bytes(b"content-x")
        y = tmp_path / "b.pdf"
        y.write_bytes(b"content-y")
        import_file(lib_a, x)
        import_file(lib_a, y)
        z = tmp_path / "c.pdf"
        z.write_bytes(b"content-z")
        y2 = tmp_path / "b-renamed.pdf"
        y2.write_bytes(b"content-y")
        import_file(lib_b, z)
        import_file(lib_b, y2)

        d = diff(catalog_manifest(lib_a.conn), catalog_manifest(lib_b.conn))
        assert len(d["missing_on_theirs"]) == 1      # a.pdf
        assert len(d["missing_on_ours"]) == 1        # c.pdf
        assert len(d["same_content_different_name"]) == 1   # b.pdf = b-renamed.pdf
