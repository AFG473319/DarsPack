"""Integration prompt generation for AI agents.

Produces a ready-to-paste prompt plus config snippets that let an agent
register the DarsPack MCP server without guessing.  The command itself is
resolved by :mod:`darspack.mcp.launch`, so the prompt describes a command
that is known to work on this machine (bundled exe when installed, Python
module + ``PYTHONPATH`` in a source checkout).
"""
from __future__ import annotations

import sys
from pathlib import Path

from ..paths import app_exe_name, opencode_command
from .launch import (
    SERVER_EXE_NAME,
    McpLaunch,
    build_mcp_config,
    build_opencode_config,
    config_json,
    resolve_launch,
    resolve_library_path,
)

__all__ = [
    "build_mcp_config",
    "build_opencode_config",
    "build_agent_prompt",
    "resolve_launch",
    "resolve_library_path",
]

#: One line per tool: agents pick tools by name, so keep this list exact.
_TOOL_SUMMARY = (
    ("darspack_get_stats", "library size, file counts, dedup savings - call this first"),
    ("darspack_list_subjects", "registered subjects (درس‌ها) with file counts"),
    ("darspack_add_subject", "register a missing subject before classifying into it"),
    ("darspack_get_unclassified_files", "files still missing a subject (the work queue)"),
    ("darspack_search_files", "search the catalog; Persian-normalized, filterable"),
    ("darspack_preview_file", "read a text/metadata excerpt to guess subject and chapter"),
    ("darspack_classify_file", "set subject, chapter, lesson, kind, year, tags, note"),
    ("darspack_batch_classify", "same as above for many files in one call"),
    ("darspack_import_file", "copy a file from disk into the library and catalog it"),
    ("darspack_check_duplicates", "exact duplicate groups (R1) and version conflicts (R2)"),
    ("darspack_trash_file", "move a file to the reversible trash (never a hard delete)"),
    ("darspack_list_trash", "list what currently sits in the trash"),
    ("darspack_restore_trash_file", "restore an item from the trash"),
    ("darspack_export_package", "build a portable .zip study package with an offline index"),
    ("darspack_verify_package", "check hashes and manifest of a .zip package"),
    ("darspack_backup_library", "full library backup ZIP incl. catalog snapshot"),
)


def _format_lines(launch: McpLaunch) -> list[str]:
    lines = [f"Executable : {launch.command}"]
    lines.append(f"Arguments  : {' '.join(launch.args)}")
    lines.append(f"Full line  : {launch.command_line()}")
    if launch.env:
        env_pairs = ", ".join(f"{k}={v}" for k, v in launch.env.items())
        lines.append(f"Environment: {env_pairs}")
    else:
        lines.append("Environment: none needed")
    return lines


def build_agent_prompt(
    library_path: Path | str | None = None,
    python_path: str | None = None,
) -> str:
    """Prompt an agent can execute end to end: register, verify, then use."""
    launch = resolve_launch(library_path, python_path)
    library = resolve_library_path(library_path)

    # Paths and binary names that differ between Windows and Linux.
    opencode_bin = opencode_command()
    if sys.platform == "win32":
        claude_config = "%APPDATA%\\Claude\\claude_desktop_config.json"
        cursor_config = "%USERPROFILE%\\.cursor\\mcp.json"
        claude_label = "Claude Desktop (Windows)"
        opencode_note = (
            "Use `opencode.cmd` on Windows: the `opencode.ps1` shim drops the `--`\n"
            "separator, and the CLI then answers \"Unrecognized flag: --library\"."
        )
        denied = '"Access is denied"'
    else:
        claude_config = "~/.config/Claude/claude_desktop_config.json"
        cursor_config = "~/.cursor/mcp.json"
        claude_label = "Claude Desktop (Linux)"
        opencode_note = "On Linux the binary is plain `opencode`."
        denied = '"Permission denied"'

    if not launch.available:
        build_script = (
            "installer\\build.bat"
            if sys.platform == "win32"
            else "installer/build-linux.sh"
        )
        return f"""# Connect to DarsPack MCP Server

This DarsPack build cannot expose MCP yet: {launch.note}

Tell the user, in Persian, that the app must be rebuilt or reinstalled
(``{build_script}`` produces ``{SERVER_EXE_NAME}`` next to
``{app_exe_name()}``).  Do not invent a configuration - a config pointing at
``{app_exe_name()}`` would only launch the desktop window.
"""

    mcp_json = config_json(build_mcp_config(library_path, python_path))
    opencode_json = config_json(build_opencode_config(library_path, python_path))
    tools_block = "\n".join(f"- `{name}` - {desc}" for name, desc in _TOOL_SUMMARY)

    return f"""# Connect to DarsPack MCP Server

DarsPack (درس‌پک) is a local, offline Persian library of school materials.
It ships a Model Context Protocol server that speaks JSON-RPC 2.0 over
stdio. Register it, verify it, then use it.

## 1. The command (already resolved for this machine)

{chr(10).join(_format_lines(launch))}
Library    : {library}

The server is a standalone stdio process:
- it does **not** open the DarsPack window and does not need the app running;
- it loads no GUI toolkit, so it stays small in RAM;
- it makes no network calls and exits when you close the connection;
- it writes only through the tools below, and never hard-deletes a file.

If you can run shell commands, let the server print its own configuration
instead of retyping it (paths are already absolute and quoted when they
contain spaces):

```bash
{launch.command_line()} --print-config
{launch.command_line()} --print-config --format opencode
```

## 2. Register it

OpenCode (v2) - pick one:
```bash
{opencode_bin} mcp add darspack -- {launch.command_line()}
```
{opencode_note}

The most reliable route is the config file - merge this into
`opencode.json` / `opencode.jsonc` (note: OpenCode uses `mcp.servers`, **not**
`mcpServers`):
```json
{opencode_json}
```

Claude Code (CLI):
```bash
claude mcp add darspack -- {launch.command_line()}
```
If your shell reports an unrecognized flag, it mangled the `--` separator;
write the JSON block below into the client config instead.

{claude_label}, merge into `{claude_config}`:
```json
{mcp_json}
```

Cursor: merge the same `mcpServers` block into
`{cursor_config}` (global) or `.cursor/mcp.json` (project).

VS Code: put the same entry under `servers` in `.vscode/mcp.json` and add
`"type": "stdio"` to it.

Antigravity / Hermes / OpenClaw / any other client: merge the `mcpServers`
block into whatever your configuration calls its server list. Do not change
the command, the arguments or the environment - that is the part that was
tuned for this machine.

## 3. Verify before you rely on it

Run this once and read the JSON it prints:
```bash
{launch.selftest_line()}
```
Expected: `"ok": true` plus `"tool_count": 16`. If it fails, report the exact
stderr instead of guessing - a `ModuleNotFoundError` means the environment
was dropped, and {denied} on a locked file means DarsPack was
built without `{SERVER_EXE_NAME}`.

## 4. Confirm the connection

Call `darspack_get_stats`, then `darspack_list_subjects`. Both return JSON.
Then tell the user in Persian that you are connected and can organize their
study files.

## 5. Tools (16)

{tools_block}

## 6. Working rules

- Call `darspack_get_stats` before bulk work: it tells you the real size.
- Classify only after reading `darspack_preview_file` or the filename; never
  invent a subject. Unclassified files are a valid state, not an error.
- Use `darspack_add_subject` first if a subject is missing.
- Safety invariant "Flag, never touch": duplicates and conflicts are
  reported, never auto-merged or auto-deleted. Trash is reversible;
  permanent deletion stays in the GUI, with the human.
- Persian input is normalized for you (ي/ی, ك/ک, ZWNJ, Persian and Latin
  digits), so search with whatever spelling the user gives.
- Answer the user in Persian, keep numbers as they come back from the tools.
"""


def build_minimal_prompt(
    library_path: Path | str | None = None,
    python_path: str | None = None,
) -> str:
    """Shorter variant for agents that only need the registration block."""
    launch = resolve_launch(library_path, python_path)
    if not launch.available:
        return launch.note
    return (
        "Register this local MCP server (stdio, no GUI, no network) as "
        '"darspack", then verify it with the second command:\n'
        f"{launch.command_line()}\n"
        f"{launch.selftest_line()}\n"
    )
