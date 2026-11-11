"""DarsPack Model Context Protocol (MCP) server.

Enables AI agents (OpenCode, Claude, Cursor, Antigravity) to connect to
DarsPack to inspect files, query the catalog, and classify school materials.
"""
from .server import DarsPackMcpServer, run_stdio_server
from .prompt import build_agent_prompt, build_mcp_config

__all__ = ["DarsPackMcpServer", "run_stdio_server", "build_agent_prompt", "build_mcp_config"]
