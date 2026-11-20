"""Windows 11 Fluent titlebar/backdrop helper: the no-HWND early exits."""
from types import SimpleNamespace

from darspack.ui.fluent_win32 import apply_fluent_window_effects


def test_zero_or_missing_hwnd_returns_false():
    # Offscreen windows have no real HWND — the helper's early-exit branch.
    assert apply_fluent_window_effects(SimpleNamespace(winId=lambda: 0)) is False
    assert apply_fluent_window_effects(None) is False
