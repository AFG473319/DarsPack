# DarsPack MCP (Model Context Protocol) Server

DarsPack includes a built-in, zero-dependency MCP server that enables AI agents (such as **Claude Code**, **OpenCode**, **Antigravity**, **Cursor**, **Hermes**, **OpenClaw**, **Claude Desktop**) to connect directly to the local library.

The MCP server allows agents to:
1. List and create school subjects (`darspack_list_subjects`, `darspack_add_subject`).
2. Discover unclassified files needing organization (`darspack_get_unclassified_files`).
3. Search materials across the catalog (`darspack_search_files`).
4. Read text previews from stored documents (`darspack_preview_file`).
5. Classify files individually or in batches (`darspack_classify_file`, `darspack_batch_classify`).
6. Safely import new files from disk (`darspack_import_file`).

---

## 1. 1-Click In-App Agent Setup (Recommended)

DarsPack's in-app **Help Center (`F1`)** contains a dedicated **AI & MCP (هوش مصنوعی و MCP)** tab designed for effortless connection:
1. In DarsPack, click **راهنما (Help)** or press **F1**.
2. Select the **هوش مصنوعی و MCP** tab.
3. Click **«📋 کپی متن اتصال برای هوش مصنوعی»** (*Copy Connection Prompt for AI*).
4. Paste the copied text into your AI agent's chat (Claude Code, OpenCode, Antigravity, Cursor, Hermes, OpenClaw, etc.).

The prompt is generated dynamically using your system's current Python binary and your configured library path. The AI agent will read the prompt, self-locate its configuration format (JSON config or CLI command), connect to DarsPack, test the connection, and confirm readiness!

---

## 2. Running the MCP Server Manually

The server communicates using JSON-RPC 2.0 / MCP over standard input/output (`stdio`).

### Run via Python module:
```bash
python -m darspack.mcp
```

### Optional custom library path:
By default, the server opens the library at `~/Documents/DarsPackLibrary` (or the path defined in `settings.json`). You can also specify an explicit path:
```bash
python -m darspack.mcp "D:\School\DarsPackLibrary"
```
or set the environment variable:
```bash
set DARSPACK_LIBRARY=D:\School\DarsPackLibrary
```

---

## 3. Manual Configuration in AI Agents

### Claude Code CLI
```bash
claude mcp add darspack -- python -m darspack.mcp
```

### OpenCode / Claude Desktop / Cursor / Antigravity (`claude_desktop_config.json` or `mcp.json`)

```json
{
  "mcpServers": {
    "darspack": {
      "command": "python",
      "args": ["-m", "darspack.mcp"]
    }
  }
}
```

If you are using a virtual environment:
```json
{
  "mcpServers": {
    "darspack": {
      "command": "C:/path/to/.venv/Scripts/python.exe",
      "args": ["-m", "darspack.mcp"]
    }
  }
}
```

---

## 4. Available Tools

| Tool | Purpose |
|---|---|
| `darspack_list_subjects` | Get all subjects currently registered in the catalog |
| `darspack_add_subject` | Add a new subject (e.g. «هندسه») if missing |
| `darspack_get_unclassified_files` | List all files that are still missing their subject («بدون درس») |
| `darspack_preview_file` | Read text/metadata snippet of a file to determine its subject and chapter |
| `darspack_classify_file` | Set subject, chapter, lesson, kind, tags, and school year for a file |
| `darspack_batch_classify` | Classify multiple files in a single call |
| `darspack_search_files` | Search catalog with Persian-normalized queries and filters |
| `darspack_import_file` | Copy a new file from disk into the library and catalog it |
| `darspack_trash_file` | Move a file from the catalog into `.trash` (safe delete preserving metadata) |
| `darspack_list_trash` | List deleted files currently preserved in `.trash` with sidecar metadata |
| `darspack_restore_trash_file` | Restore a file from `.trash` back into active catalog with its tags and attributes |
| `darspack_check_duplicates` | Detect exact duplicate groups (R1) and version conflicts (R2) |
| `darspack_export_package` | Export selected files into a portable `.zip` درس‌پک package with manifest & offline HTML |
| `darspack_verify_package` | Verify integrity and SHA-256 hashes of a `.zip` درس‌پک package |
| `darspack_backup_library` | Full-library backup ZIP with point-in-time `catalog.db` snapshot |
| `darspack_get_stats` | Retrieve overall catalog stats, size, deduplication savings, and subject counts |

> **Note on Safety:** In line with DarsPack's core philosophy ("Flag, never touch"), permanent deletion from `.trash` (`empty_trash`) is intentionally restricted to the human user in the GUI to prevent accidental loss of student files.

---

## 5. Architecture & Safety

- **Local & Offline**: Zero network calls. Only accesses your local SQLite catalog and files directory.
- **Concurrent Safe**: Runs alongside the DarsPack desktop GUI using SQLite WAL mode.
- **Flag, Never Overwrite**: Reuses DarsPack's hash dedup and atomic copy-and-rename guarantees.
- **Zero Third-party Dependencies**: Built with Python standard library (`json`, `sys`, `pathlib`, `zlib`, `sqlite3`).
