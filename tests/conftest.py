"""Make the src/ layout importable without installing the package.

The core modules (darspack.core.*) have no UI dependencies, so tests can
import them directly. This keeps `pytest` the only requirement for
running the test suite.
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
