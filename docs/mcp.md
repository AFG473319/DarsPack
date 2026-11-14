# DarsPack MCP (Model Context Protocol) Server

DarsPack includes a built-in, zero-dependency MCP server that lets AI agents
(**Claude Code**, **Claude Desktop**, **OpenCode**, **Cursor**, **Antigravity**,
**Hermes**, **OpenClaw**, and any other MCP client) read and organize the local
library: classify files, search, import, and build study packages.

The server speaks **JSON-RPC 2.0 over stdio** — one JSON object per line — and
is intentionally **headless**: nothing in `darspack/mcp/` imports Qt, so an
agent never opens the DarsPack window.

---

## 1. One-click setup inside the app (recommended)

1. In DarsPack press **F1** (or `راهنما`).
2. Open the tab **`اتصال به ایجنت‌های هوش مصنوعی`**.
3. Press **`کپی متن اتصال برای هوش مصنوعی`** and paste it into the agent's chat.

The prompt is generated on the spot with this machine's real paths, so the
command in it is already the one that works — there is nothing to edit.

If the agent can run shell commands, the two commands below are usually the
fastest path: the server prints its own configuration.

```bash
# exact mcpServers block for this machine
"DarsPack\DarsPackMcp.exe" --library "<library>" --print-config

# same thing in OpenCode v2's shape
"DarsPack\DarsPackMcp.exe" --library "<library>" --print-config --format opencode
```

---

## 2. The two executables (and why it matters)

| File | Kind | Purpose |
|---|---|---|
| `DarsPack.exe` | windowed | the Qt desktop app |
| `DarsPackMcp.exe` | **console** | the MCP server over stdio |

They share one `_internal` folder and one 105 MB install; `DarsPackMcp.exe`
adds only **2.26 MB** (measured 2026-11-14). Configs must point at
`DarsPackMcp.exe`:

- a windowed exe has **no usable stdin/stdout**, so stdio clients would wait
  forever;
- pointing a client at `DarsPack.exe` launches the GUI instead of a server.

Older builds printed `"<python>" -m darspack.mcp`, which failed twice: in a
source checkout the package is not installed (`ModuleNotFoundError`), and in
an installed build `sys.executable` *is* `DarsPack.exe`. Both cases are now
resolved by `src/darspack/mcp/launch.py`, which every generator (prompt, JSON
snippet, Help Center, `--print-config`) uses.

---

## 3. Verify before anything else

Every command below accepts `--selftest`, which is side-effect free (it never
creates or migrates a library) and exits `0` when the server is usable:

```bash
"DarsPack\DarsPackMcp.exe" --selftest
```

```json
{
  "ok": true,
  "server": "darspack-mcp",
  "version": "0.2.0",
  "protocol_versions": ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"],
  "launch_mode": "frozen",
  "command": "C:\\...\\DarsPack\\DarsPackMcp.exe --library C:\\...\\DarsPackLibrary",
  "library": "C:\\Users\\<user>\\Documents\\DarsPackLibrary",
  "library_exists": true,
  "tool_count": 16,
  "checks": [ ... ]
}
```

`"library_exists": false` is not an error — the app creates the library on
first run, and connecting first is fine.

---

## 4. Registering the server by client

### OpenCode (v2)

```bash
opencode.cmd mcp add darspack -- "C:\Program Files\DarsPack\DarsPackMcp.exe" --library "C:\Users\<user>\Documents\DarsPackLibrary"
```

Use `opencode.cmd` on Windows, not `opencode` from PowerShell: the
`opencode.ps1` shim drops the `--` separator and the CLI then answers
`Unrecognized flag: --library` (reproduced 2026-11-14, OpenCode 2.2.7).

The config file is the most reliable route — and it is what the in-app button
copies — because it has no shell quoting at all. Note the shape: OpenCode uses
`mcp.servers` and a **single joined command array**, not `mcpServers`:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "darspack": {
        "type": "local",
        "command": [
          "C:\\Program Files\\DarsPack\\DarsPackMcp.exe",
          "--library",
          "C:\\Users\\<user>\\Documents\\DarsPackLibrary"
        ]
      }
    }
  }
}
```

The source-checkout variant needs `"environment": {"PYTHONPATH": "<repo>\\src"}`;
the app-generated block includes it automatically.

### Claude Code

```bash
claude mcp add darspack -- "C:\Program Files\DarsPack\DarsPackMcp.exe" --library "C:\Users\<user>\Documents\DarsPackLibrary"
```

### Claude Desktop

`%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "darspack": {
      "command": "C:\\Program Files\\DarsPack\\DarsPackMcp.exe",
      "args": ["--library", "C:\\Users\\<user>\\Documents\\DarsPackLibrary"]
    }
  }
}
```

### Cursor

`%USERPROFILE%\.cursor\mcp.json` (global) or `.cursor/mcp.json` (project) —
same `mcpServers` block as above.

### VS Code

`.vscode/mcp.json`, under `servers`, with `"type": "stdio"` added to the entry.

### Anything else

Merge the `mcpServers` block into whatever your client calls its server list.
Do not change the command, arguments or environment — that is the tuned part.

---

## 5. Running the server by hand

Frozen (installed) build:

```bash
"DarsPack\DarsPackMcp.exe" --library "D:\School\DarsPackLibrary"
```

Source checkout (the package is not installed, so `src/` must be on the path):

```bash
set PYTHONPATH=C:\path\to\DarsPack\src
python -m darspack.mcp --library "D:\School\DarsPackLibrary"
```

Library resolution order: `--library` flag → positional path →
`DARSPACK_LIBRARY` environment variable → `library` key in
`<default library>\settings.json` → `~/Documents/DarsPackLibrary`.

---

## 6. Available tools (16)

| Tool | Purpose |
|---|---|
| `darspack_get_stats` | File count, total size, dedup savings, per-subject/per-kind breakdown. Call first. |
| `darspack_list_subjects` | Registered subjects (`درس‌ها`) with counts |
| `darspack_add_subject` | Register a missing subject before classifying into it |
| `darspack_get_unclassified_files` | Files still missing a subject — the work queue |
| `darspack_search_files` | Persian-normalized search with subject/kind filters |
| `darspack_preview_file` | Text/metadata excerpt to deduce subject and chapter |
| `darspack_classify_file` | Set subject, chapter, lesson, kind, school year, tags, note |
| `darspack_batch_classify` | Same, for many files in one call |
| `darspack_import_file` | Copy a file from disk into the library and catalog it |
| `darspack_check_duplicates` | Exact duplicate groups (R1) and version conflicts (R2) |
| `darspack_trash_file` | Move a file to the reversible `.trash` |
| `darspack_list_trash` | List what is currently in the trash |
| `darspack_restore_trash_file` | Restore an item from the trash |
| `darspack_export_package` | Portable `.zip` study package with manifest + offline HTML index |
| `darspack_verify_package` | Verify manifest and SHA-256 hashes of a package |
| `darspack_backup_library` | Full-library backup ZIP with a catalog snapshot |

Read-only tools carry `"annotations": {"readOnlyHint": true}` so clients can
auto-approve them. `initialize` also returns `instructions`, which clients such
as OpenCode and Claude add to the system prompt; that is how an agent learns
the catalog rules without being told twice.

> **Safety:** "Flag, never touch" — duplicates and conflicts are reported, not
> merged; trash is reversible; permanent deletion (`empty_trash`) stays in the
> GUI, with the human. `darspack_delete_*` tools deliberately do not exist.

---

## 7. Protocol notes

- **Transport:** stdio, newline-delimited JSON-RPC 2.0. Batches are accepted.
- **Versions:** `initialize` echoes the client's revision when it is one of
  `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`; otherwise it answers
  with `2025-06-18`.
- **Capabilities:** `tools` only. `resources/list`, `resources/templates/list`
  and `prompts/list` still answer with empty lists instead of errors, because
  some clients probe them unconditionally.
- **stdout is reserved.** At startup the server redirects `sys.stdout` text
  writes to stderr, so a stray `print()` in the core code can never corrupt the
  protocol stream. Diagnostics go to stderr; the client shows them as logs.
- **No network.** The agent reaches the library directly; the LAN phone server
  is unrelated and still opt-in.

### Verified with a real client (2026-11-14)

- OpenCode 2.2.7: `opencode mcp list` reported **`✓ darspack connected`** with
  the config above, against the installed `DarsPackMcp.exe` and the real
  library.
- Manual stdio probe against the installed exe: `initialize` negotiated
  `2025-11-25`, `darspack_get_stats` returned the real catalog
  (`14` files, subjects `ریاضی`/`فیزیک`), `darspack_search_files` returned
  Persian filenames unchanged.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'darspack'` | source checkout without `PYTHONPATH` | use the generated block, or set `PYTHONPATH=<repo>\src` |
| `Unrecognized flag: --library` from `opencode mcp add` | the `opencode.ps1` shim dropped the `--` separator | use `opencode.cmd ...`, or paste the JSON block |
| `opencode.json` ends up with `"command": ["\"", "...\\ --library \\..."]` | the shell mangled the quotes around the arguments | delete the entry and paste the JSON block instead |
| Client connects, then immediately disconnects | command points at `DarsPack.exe` (windowed, no usable stdio) | point it at `DarsPackMcp.exe` |
| A DarsPack window opens when the agent starts | same cause as above | regenerate the config from the Help Center |
| `DarsPackMcp.exe` not found | build predates 2026-11-14, or a partial copy | rebuild `installer\build.bat` / reinstall |
| Config ignored silently in OpenCode | `mcpServers` pasted into `opencode.json` | use `mcp.servers` with a joined `command` array |
| Tool calls return `{"error": ...}` | wrong `file_id`, or the library is on a disconnected drive | call `darspack_get_stats`, re-check ids |

---

## 9. Measured footprint

On the demo laptop (i5-2450M, 8 GB RAM, Windows 11), 2026-11-14:

| Measurement | Value |
|---|---|
| `DarsPackMcp.exe` size | 2.26 MB (GUI exe: 2.65 MB, same `_internal`) |
| MCP process, idle after `initialize` | 31.9 MB working set, 16.9 MB private |
| Desktop app, idle (for comparison) | ~81 MB (`docs/limitations.md`) |
| Window opened | none |

So an agent working with MCP uses about a third of the desktop app's memory
and never shows a window.
