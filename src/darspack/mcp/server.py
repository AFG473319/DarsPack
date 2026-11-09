"""JSON-RPC 2.0 / Model Context Protocol (MCP) server implementation for DarsPack.

Zero third-party dependencies: runs over stdio using Python's standard library.
Compatible with OpenCode, Claude Desktop, Cursor, and any MCP client.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from ..core import db
from ..core.importer import import_file
from ..core.library import Library
from ..core.normalize import match_key
from ..core.search import search
from ..core.suggest import suggest, learn_hint, DEFAULT_SUBJECTS
from .extractor import extract_preview

DEFAULT_LIBRARY_PATH = Path.home() / "Documents" / "DarsPackLibrary"


class DarsPackMcpServer:
    """Core handler for MCP protocol methods."""

    PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, library_path: Path | str | None = None):
        self.library_path = Path(library_path) if library_path else self._resolve_library_path()
        self._lib: Library | None = None
        self.tools: dict[str, dict] = {}
        self._register_tools()

    def _resolve_library_path(self) -> Path:
        """Resolve library path from settings.json or fallback to default."""
        env_path = os.environ.get("DARSPACK_LIBRARY")
        if env_path:
            return Path(env_path)

        settings_file = DEFAULT_LIBRARY_PATH / "settings.json"
        if settings_file.exists():
            try:
                data = json.loads(settings_file.read_text(encoding="utf-8"))
                if "library" in data:
                    return Path(data["library"])
            except Exception:
                pass
        return DEFAULT_LIBRARY_PATH

    @property
    def lib(self) -> Library:
        if self._lib is None:
            self._lib = Library(self.library_path).open()
        return self._lib

    def close(self) -> None:
        if self._lib is not None:
            self._lib.close()
            self._lib = None

    def _register_tools(self) -> None:
        self.tools = {
            "darspack_list_subjects": {
                "description": "Get all school subjects (درس‌ها) currently registered in DarsPack.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
                "handler": self.tool_list_subjects,
            },
            "darspack_add_subject": {
                "description": "Add a new school subject to the catalog if it does not already exist.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Subject name in Persian (e.g. «هندسه», «فیزیک»)",
                        }
                    },
                    "required": ["name"],
                },
                "handler": self.tool_add_subject,
            },
            "darspack_get_unclassified_files": {
                "description": "List files in DarsPack that are still unclassified (missing subject) and need categorization.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of files to return (default 50)",
                            "default": 50,
                        }
                    },
                },
                "handler": self.tool_get_unclassified_files,
            },
            "darspack_search_files": {
                "description": "Search files in DarsPack catalog using Persian-normalized queries and optional filters.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query text"},
                        "subject": {"type": "string", "description": "Filter by subject name"},
                        "kind": {
                            "type": "string",
                            "enum": ["جزوه", "نمونه‌سوال", "کاربرگ", "تکلیف", "سایر"],
                            "description": "Material kind",
                        },
                        "limit": {"type": "integer", "default": 20},
                    },
                },
                "handler": self.tool_search_files,
            },
            "darspack_preview_file": {
                "description": "Extract text snippet and metadata preview from a stored DarsPack file to determine its subject/chapter/kind.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "integer", "description": "The file ID in DarsPack"},
                        "max_chars": {"type": "integer", "default": 1500},
                    },
                    "required": ["file_id"],
                },
                "handler": self.tool_preview_file,
            },
            "darspack_classify_file": {
                "description": "Classify or update metadata for a file in DarsPack (subject, chapter, lesson, kind, school_year, tags, note).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "integer", "description": "The file ID to classify"},
                        "subject": {"type": "string", "description": "Subject name in Persian (e.g. «ریاضی»)"},
                        "chapter": {"type": ["integer", "null"], "description": "Chapter number (فصل, 1..40)"},
                        "lesson": {"type": ["integer", "null"], "description": "Lesson number (درس, 1..40)"},
                        "kind": {
                            "type": "string",
                            "enum": ["جزوه", "نمونه‌سوال", "کاربرگ", "تکلیف", "سایر"],
                            "description": "Material type",
                        },
                        "school_year": {"type": ["string", "null"], "description": "Jalali school year, e.g. «1405-1406»"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags list (e.g. ['نوبت اول', 'نهایی'])",
                        },
                        "note": {"type": ["string", "null"], "description": "Additional note"},
                    },
                    "required": ["file_id", "subject"],
                },
                "handler": self.tool_classify_file,
            },
            "darspack_batch_classify": {
                "description": "Classify multiple files at once.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "file_id": {"type": "integer"},
                                    "subject": {"type": "string"},
                                    "chapter": {"type": ["integer", "null"]},
                                    "lesson": {"type": ["integer", "null"]},
                                    "kind": {"type": "string"},
                                    "school_year": {"type": ["string", "null"]},
                                    "tags": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["file_id", "subject"],
                            },
                        }
                    },
                    "required": ["items"],
                },
                "handler": self.tool_batch_classify,
            },
            "darspack_import_file": {
                "description": "Import an external file from disk into DarsPack's managed library.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute path to source file"},
                        "keep_duplicate": {
                            "type": "boolean",
                            "default": False,
                            "description": "If true, imports even if hash is duplicate",
                        },
                    },
                    "required": ["path"],
                },
                "handler": self.tool_import_file,
            },
        }

    # --- Tool handlers ---

    def tool_list_subjects(self, args: dict) -> dict:
        rows = self.lib.conn.execute("SELECT id, name FROM subjects ORDER BY name").fetchall()
        return {"subjects": [{"id": r["id"], "name": r["name"]} for r in rows]}

    def tool_add_subject(self, args: dict) -> dict:
        name = args.get("name", "").strip()
        if not name:
            return {"error": "Subject name cannot be empty"}
        with self.lib.conn:
            sid = db.get_or_create(self.lib.conn, "subjects", name)
        return {"id": sid, "name": name, "status": "ok"}

    def tool_get_unclassified_files(self, args: dict) -> dict:
        limit = int(args.get("limit", 50))
        rows = search(self.lib.conn, unclassified_only=True, limit=limit)
        items = []
        for r in rows:
            # Suggestion based on filename
            sug = suggest(Path(r["original_name"]).stem)
            items.append({
                "id": r["id"],
                "original_name": r["original_name"],
                "size_bytes": r["size_bytes"],
                "imported_at": r["imported_at"],
                "suggested_kind": sug.get("kind"),
                "suggested_chapter": sug.get("chapter"),
                "suggested_lesson": sug.get("lesson"),
                "suggested_subject": sug.get("subject"),
            })
        return {"count": len(items), "files": items}

    def tool_search_files(self, args: dict) -> dict:
        query = args.get("query", "")
        subject_name = args.get("subject")
        kind = args.get("kind")
        limit = int(args.get("limit", 20))

        subject_id = None
        if subject_name:
            s_row = self.lib.conn.execute(
                "SELECT id FROM subjects WHERE normalized=?", (match_key(subject_name),)
            ).fetchone()
            if s_row:
                subject_id = s_row["id"]

        rows = search(self.lib.conn, query=query, subject_id=subject_id, kind=kind, limit=limit)
        items = []
        for r in rows:
            items.append({
                "id": r["id"],
                "original_name": r["original_name"],
                "subject_name": r["subject_name"],
                "chapter": r["chapter"],
                "lesson": r["lesson"],
                "kind": r["kind"],
                "school_year": r["school_year"],
                "note": r["note"],
            })
        return {"results": items}

    def tool_preview_file(self, args: dict) -> dict:
        fid = int(args["file_id"])
        row = self.lib.conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
        if not row:
            return {"error": f"File with id {fid} not found"}

        stored_file = self.lib.stored_path(row)
        preview_text = extract_preview(stored_file, max_chars=args.get("max_chars", 1500))

        return {
            "id": fid,
            "original_name": row["original_name"],
            "stored_name": row["stored_name"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "preview": preview_text,
        }

    def tool_classify_file(self, args: dict) -> dict:
        fid = int(args["file_id"])
        subject = args["subject"].strip()
        chapter = args.get("chapter")
        lesson = args.get("lesson")
        kind = args.get("kind")
        school_year = args.get("school_year")
        tags = args.get("tags") or []
        note = args.get("note")

        conn = self.lib.conn
        with conn:
            subject_id = db.get_or_create(conn, "subjects", subject) if subject else None

            # Fetch existing to avoid overwriting unspecified fields
            cur_row = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
            if not cur_row:
                return {"error": f"File with id {fid} not found"}

            final_kind = kind or cur_row["kind"]
            final_year = school_year if school_year is not None else cur_row["school_year"]
            final_note = note if note is not None else cur_row["note"]

            conn.execute(
                """UPDATE files
                   SET subject_id=?, chapter=?, lesson=?, kind=?, school_year=?, note=?
                   WHERE id=?""",
                (subject_id, chapter, lesson, final_kind, final_year, final_note, fid),
            )

            # Update tags if provided
            if tags:
                conn.execute("DELETE FROM file_tags WHERE file_id=?", (fid,))
                for t in tags:
                    t = t.strip()
                    if t:
                        tag_id = db.get_or_create(conn, "tags", t)
                        conn.execute(
                            "INSERT OR IGNORE INTO file_tags(file_id, tag_id) VALUES (?,?)",
                            (fid, tag_id),
                        )

            # Learn hint tokens
            if subject:
                for token in match_key(Path(cur_row["original_name"]).stem).split():
                    if len(token) >= 3:
                        learn_hint(conn, token, subject)

            db.log(conn, "mcp_classify", f"file {fid} → {subject}")

        return {
            "status": "success",
            "file_id": fid,
            "subject": subject,
            "chapter": chapter,
            "lesson": lesson,
            "kind": final_kind,
        }

    def tool_batch_classify(self, args: dict) -> dict:
        items = args.get("items", [])
        results = []
        for it in items:
            res = self.tool_classify_file(it)
            results.append(res)
        return {"processed": len(results), "results": results}

    def tool_import_file(self, args: dict) -> dict:
        src_path = args.get("path")
        keep_dup = args.get("keep_duplicate", False)
        res = import_file(self.lib, src_path, keep_duplicate=keep_dup)
        return {
            "status": res.status,
            "message": res.message_fa,
            "file_id": res.file_id,
            "existing_id": res.existing_id,
        }

    # --- Dispatch JSON-RPC methods ---

    def handle_request(self, req: dict) -> dict | None:
        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        # Notifications (no id)
        if msg_id is None:
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": self.PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {},
                    },
                    "serverInfo": {
                        "name": "darspack-mcp",
                        "version": "0.1.0",
                    },
                },
            }

        elif method == "tools/list":
            tools_list = []
            for name, meta in self.tools.items():
                tools_list.append({
                    "name": name,
                    "description": meta["description"],
                    "inputSchema": meta["inputSchema"],
                })
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools_list}}

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            if tool_name not in self.tools:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                }
            try:
                result_data = self.tools[tool_name]["handler"](arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(result_data, ensure_ascii=False, indent=2)}
                        ]
                    },
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps({"error": str(e)}, ensure_ascii=False)}
                        ],
                        "isError": True,
                    },
                }

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }


def run_stdio_server(library_path: Path | str | None = None) -> None:
    """Run MCP server over standard input/output."""
    server = DarsPackMcpServer(library_path)
    # Binary stdio for clean UTF-8 JSON streaming
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    try:
        while True:
            line = stdin.readline()
            if not line:
                break
            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue

            try:
                req = json.loads(line_str)
            except Exception:
                continue

            resp = server.handle_request(req)
            if resp is not None:
                out_data = (json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8")
                stdout.write(out_data)
                stdout.flush()
    finally:
        server.close()
