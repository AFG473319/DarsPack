"""Shared test setup for the whole suite.

- Puts src/ on sys.path so the package imports without installation
  (pytest stays the only requirement for running the tests).
- Sets Qt's offscreen platform BEFORE any test module can import
  PySide6 or create a QApplication — a widget test without a display
  would otherwise crash Qt silently, with no error message anywhere
  (that exact failure mode cost a debugging session on 2026-10-24).
- One session-scoped QApplication shared by every Qt test: creating a
  second QApplication in the same process is a classic source of
  order-dependent crashes.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from darspack.core.library import Library


@pytest.fixture(scope="session")
def qapp():
    """The one QApplication for the whole test run (offscreen)."""
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def library(tmp_path):
    """One open Library under tmp_path/lib, closed automatically.

    The common setup of most core tests, factored out so new tests
    stay short. Existing tests keep their own setups (additive only).
    """
    with Library(tmp_path / "lib") as lib:
        yield lib
