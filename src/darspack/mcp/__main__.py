"""CLI entrypoint to run the DarsPack MCP server.

    python -m darspack.mcp                 # serve over stdio
    python -m darspack.mcp --selftest      # health check, exit 0/1
    python -m darspack.mcp --library PATH  # explicit library folder

The same code path is used by the bundled ``DarsPackMcp.exe``.
"""
import sys

from .server import main

if __name__ == "__main__":
    sys.exit(main())
