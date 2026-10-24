"""PyInstaller entry point (نقطه‌ی ورود بسته‌بندی).

A tiny script whose only job is to call the real app entry. Kept
separate from the package so the build never drags test/dev modules in.
"""
import sys
from pathlib import Path

# When frozen, src/darspack is bundled as a package; from source we add src/.
SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(SRC))

from darspack.ui.app import run  # noqa: E402

if __name__ == "__main__":
    run()
