"""PyInstaller entry point for the headless MCP server (``DarsPackMcp.exe``).

Deliberately separate from ``launcher.py``: it imports only
``darspack.mcp``, so the frozen executable loads no Qt, opens no window and
stays small.  AI agents start it over stdio while the user keeps working
(or keeps DarsPack closed).
"""
import sys
from pathlib import Path

# When frozen, src/darspack is bundled as a package; from source we add src/.
SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(SRC))

from darspack.mcp.server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
