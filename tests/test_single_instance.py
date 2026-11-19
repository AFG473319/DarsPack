"""Single-instance guard (M20): two copies must not open one library.

The lock is a QLockFile in the library folder, so a second copy starting
on the same library sees it held and exits instead of the two processes
fighting over the same SQLite file (one writing while the other shows
stale rows — the M22 case).
"""
from darspack.ui.app import acquire_instance_lock


def test_second_lock_attempt_fails_while_first_is_held(tmp_path):
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    first = acquire_instance_lock(lib_dir)
    assert first is not None
    try:
        assert acquire_instance_lock(lib_dir) is None
    finally:
        first.unlock()


def test_lock_is_reacquirable_after_release(tmp_path):
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    first = acquire_instance_lock(lib_dir)
    assert first is not None
    first.unlock()
    second = acquire_instance_lock(lib_dir)
    assert second is not None
    second.unlock()
