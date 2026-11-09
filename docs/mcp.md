# DarsPack MCP (Model Context Protocol) Server

DarsPack includes a built-in, zero-dependency MCP server that enables AI agents (such as **OpenCode**, **Claude Desktop**, **Antigravity**, **Cursor**) to connect directly to the local library.

The MCP server allows agents to:
1. List and create school subjects (`darspack_list_subjects`, `darspack_add_subject`).
2. Discover unclassified files needing organization (`darspack_get_unclassified_files`).
3. Search materials across the catalog (`darspack_search_files`).
4. Read text previews from stored documents (`darspack_preview_file`).
5. Classify files individually or in batches (`darspack_classify_file`, `darspack_batch_classify`).
6. Safely import new files from disk (`darspack_import_file`).

---

## 1. Running the MCP Server

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

## 2. Configuring in AI Agents

### OpenCode / Claude Desktop / Cursor (`claude_desktop_config.json` or `mcp.json`)

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

## 3. Available Tools

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

---

## 4. Architecture & Safety

- **Local & Offline**: Zero network calls. Only accesses your local SQLite catalog and files directory.
- **Concurrent Safe**: Runs alongside the DarsPack desktop GUI using SQLite WAL mode.
- **Flag, Never Overwrite**: Reuses DarsPack's hash dedup and atomic copy-and-rename guarantees.
- **Zero Third-party Dependencies**: Built with Python standard library (`json`, `sys`, `pathlib`, `zlib`, `sqlite3`).
