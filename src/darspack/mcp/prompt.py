"""Integration prompt generation for AI agents (Claude Code, OpenCode, Antigravity, Cursor, Hermes, OpenClaw).

Produces ready-to-use natural language prompts and JSON configuration snippets
that empower AI agents to auto-configure DarsPack MCP connections with 1 click.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

from .server import DEFAULT_LIBRARY_PATH


def get_resolved_library_path(library_path: Path | str | None = None) -> Path:
    """Return resolved library path or fallback to default."""
    if library_path:
        return Path(library_path).resolve()
    return DEFAULT_LIBRARY_PATH.resolve()


def get_resolved_python_path(python_path: str | None = None) -> str:
    """Return python executable path normalized for command execution."""
    if python_path:
        return python_path
    return sys.executable or "python"


def build_mcp_config(
    library_path: Path | str | None = None,
    python_path: str | None = None,
) -> dict:
    """Generate standard MCP server configuration dictionary."""
    py_path = get_resolved_python_path(python_path).replace("\\", "/")
    lib = get_resolved_library_path(library_path)
    lib_str = str(lib).replace("\\", "/")

    args = ["-m", "darspack.mcp"]
    if lib != DEFAULT_LIBRARY_PATH.resolve():
        args.append(lib_str)

    return {
        "mcpServers": {
            "darspack": {
                "command": py_path,
                "args": args,
            }
        }
    }


def build_agent_prompt(
    library_path: Path | str | None = None,
    python_path: str | None = None,
) -> str:
    """Generate a comprehensive, structured prompt for any AI coding agent.

    The prompt guides agents (Claude Code, OpenCode, Antigravity, Cursor, Hermes, OpenClaw, etc.)
    to self-configure the DarsPack MCP server based on their respective architecture.
    """
    py_path = get_resolved_python_path(python_path).replace("\\", "/")
    lib = get_resolved_library_path(library_path)
    lib_str = str(lib).replace("\\", "/")

    config = build_mcp_config(library_path=lib, python_path=py_path)
    config_json = json.dumps(config, indent=2, ensure_ascii=False)

    args_list = config["mcpServers"]["darspack"]["args"]
    cmd_cli_args = " ".join(args_list)

    prompt = f"""# Connect to DarsPack MCP Server

You are an AI assistant connecting to DarsPack, an offline Persian-first educational file manager and catalog, via the Model Context Protocol (MCP).
Please automatically register and enable the DarsPack MCP server in your local environment / MCP configuration.

## System & Environment Details:
- Python Executable: "{py_path}"
- Server Module: darspack.mcp
- Command: "{py_path}" {cmd_cli_args}
- DarsPack Library Path: "{lib_str}"
- Protocol: JSON-RPC 2.0 over standard I/O (stdio)
- Dependencies: None (pure Python standard library, zero third-party packages)

## Integration Instructions by Agent / Client:

1. Claude Code (CLI):
   Run the following terminal command:
   claude mcp add darspack -- "{py_path}" {cmd_cli_args}

2. OpenCode / Antigravity / Cursor / Claude Desktop / OpenClaw / Hermes:
   Add the following block to your MCP configuration file (e.g. `claude_desktop_config.json`, `.cursor/mcp.json`, `mcp.json`, or your agent's tool/server config):
{config_json}

3. If you have file editing or shell execution capabilities:
   - Identify your configuration file location.
   - Insert or merge the "darspack" MCP server entry.
   - Test connectivity by calling `darspack_get_stats` or `darspack_list_subjects`.

## Available DarsPack Tools:
- `darspack_list_subjects`: List registered school subjects (ریاضی, زیست, etc.)
- `darspack_add_subject`: Add a missing subject
- `darspack_get_unclassified_files`: Retrieve files needing subject/chapter classification
- `darspack_preview_file`: Read document text/metadata excerpt to deduce subject & chapter
- `darspack_classify_file` & `darspack_batch_classify`: Categorize files with subject, chapter, lesson, kind, tags
- `darspack_search_files`: Search catalog with Persian-normalized queries and filters
- `darspack_import_file`: Safely import new files from disk
- `darspack_check_duplicates`: Detect exact duplicates and version conflicts
- `darspack_export_package`: Create exam packages (.zip) with offline HTML index
- `darspack_get_stats`: Retrieve catalog statistics and size

## Safety Invariant:
- DarsPack follows "Flag, never touch". It never deletes or overwrites files without human GUI confirmation.

## Next Steps for You:
1. Configure and enable the MCP server.
2. Verify the connection by calling `darspack_get_stats` or `darspack_list_subjects`.
3. Inform the user in Persian that you are connected and ready to organize their study materials!
"""
    return prompt
