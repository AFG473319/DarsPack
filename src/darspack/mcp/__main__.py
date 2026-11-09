"""CLI entrypoint to run the DarsPack MCP server:

python -m darspack.mcp
"""
import sys
from .server import run_stdio_server

if __name__ == "__main__":
    library_path = sys.argv[1] if len(sys.argv) > 1 else None
    run_stdio_server(library_path)
