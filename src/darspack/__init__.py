"""DarsPack (درس‌پک) — offline-first organizer for school materials."""

import sys
from pathlib import Path

APP_NAME = "DarsPack"
APP_NAME_FA = "درس‌پک"
__version__ = "0.2.3"


def asset_path(relative: str) -> Path:
    """Locate a bundled asset in a source checkout or a frozen build."""
    if getattr(sys, "_MEIPASS", None):
        base = Path(sys._MEIPASS) / "darspack" / "assets"
    else:
        base = Path(__file__).resolve().parent / "assets"
    return base / relative
