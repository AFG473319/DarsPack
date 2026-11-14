"""DarsPack Model Context Protocol (MCP) server.

Enables AI agents (OpenCode, Claude, Cursor, Antigravity) to connect to
DarsPack to inspect files, query the catalog, and classify school materials.

Importing this package pulls in no GUI code: it is safe to run inside a
headless stdio process started by an agent.
"""
from .server import DarsPackMcpServer, build_selftest_report, main, run_stdio_server
from .launch import McpLaunch, build_mcp_config, build_opencode_config, resolve_launch
from .prompt import build_agent_prompt

__all__ = [
    "DarsPackMcpServer",
    "run_stdio_server",
    "main",
    "build_selftest_report",
    "McpLaunch",
    "resolve_launch",
    "build_mcp_config",
    "build_opencode_config",
    "build_agent_prompt",
]
