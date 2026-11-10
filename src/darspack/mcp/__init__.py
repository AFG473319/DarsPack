"""DarsPack Model Context Protocol (MCP) server.

Enables AI agents (OpenCode, Claude, Cursor, Antigravity) to connect to
DarsPack to inspect files, query the catalog, and classify school materials.
"""
from .server import DarsPackMcpServer, run_stdio_server

__all__ = ["DarsPackMcpServer", "run_stdio_server"]
