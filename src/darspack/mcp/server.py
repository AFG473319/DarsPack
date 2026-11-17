"""JSON-RPC 2.0 / Model Context Protocol (MCP) server implementation for DarsPack.

Zero third-party dependencies: runs over stdio using Python's standard library.
Compatible with OpenCode, Claude Desktop, Cursor, and any MCP client.

The process is deliberately headless: nothing here imports Qt or the UI
package, so an agent gets a small stdio process instead of a desktop window.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ..core import db
from ..core.backup import backup_library, backup_filename
from ..core.dedup import duplicate_groups, version_conflicts
from ..core.importer import import_file
from ..core.library import Library
from ..core.manifest import export_package, verify_package
from ..core.normalize import match_key
from ..core.search import search
from ..core.suggest import suggest, learn_hint
from .extractor import extract_preview

DEFAULT_LIBRARY_PATH = Path.home() / "Documents" / "DarsPackLibrary"

#: Protocol revisions this server understands, newest first.  During
#: ``initialize`` we echo the client's revision when we support it and
#: answer with :attr:`DarsPackMcpServer.PROTOCOL_VERSION` otherwise.
SUPPORTED_PROTOCOL_VERSIONS = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)

#: Tools that only read.  Advertised as ``readOnlyHint`` so clients can
#: auto-approve them and so agents know they are safe to call freely.
READ_ONLY_TOOLS = frozenset({
    "darspack_list_subjects",
    "darspack_get_unclassified_files",
    "darspack_search_files",
    "darspack_preview_file",
    "darspack_list_trash",
    "darspack_check_duplicates",
    "darspack_verify_package",
    "darspack_get_stats",
})


class DarsPackMcpServer:
    """Core handler for MCP protocol methods."""

    PROTOCOL_VERSION = "2025-06-18"

    #: Sent to the client during ``initialize``; most clients (OpenCode,
    #: Claude) inject this into the system prompt, which is the cheapest way
    #: to stop an agent from guessing how the catalog works.
    INSTRUCTIONS = (
        "DarsPack is the user's local, offline Persian library of school materials. "
        "Start with darspack_get_stats, then use darspack_get_unclassified_files as the "
        "work queue. Read darspack_preview_file before choosing a subject; never invent "
        "one, and call darspack_add_subject first if it is missing. Duplicates and "
        "conflicts are flagged, never merged or deleted; trash is reversible and "
        "permanent deletion stays in the GUI. Persian text is normalized "
        "automatically (ي/ی, ك/ک, ZWNJ, Persian and Latin digits). Reply in Persian."
    )

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
            "darspack_trash_file": {
                "description": "Move a file from active catalog to .trash (safe delete, preserves original and sidecar metadata).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "integer", "description": "The file ID in DarsPack"}
                    },
                    "required": ["file_id"],
                },
                "handler": self.tool_trash_file,
            },
            "darspack_list_trash": {
                "description": "List all files currently in the .trash folder with their preserved metadata.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
                "handler": self.tool_list_trash,
            },
            "darspack_restore_trash_file": {
                "description": "Restore a deleted file from .trash back into the active catalog with its tags and metadata.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "trash_name": {"type": "string", "description": "The trash filename (from darspack_list_trash)"}
                    },
                    "required": ["trash_name"],
                },
                "handler": self.tool_restore_trash_file,
            },
            "darspack_check_duplicates": {
                "description": "Detect exact duplicate groups (R1) and version conflicts (R2: same name, different content).",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
                "handler": self.tool_check_duplicates,
            },
            "darspack_export_package": {
                "description": "Export selected files as a portable, standalone .zip درس‌پک package with manifest.json and offline index.html.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "List of file IDs to include in the package",
                        },
                        "output_path": {
                            "type": "string",
                            "description": "Absolute output path for the .zip file",
                        },
                    },
                    "required": ["file_ids", "output_path"],
                },
                "handler": self.tool_export_package,
            },
            "darspack_verify_package": {
                "description": "Verify integrity and completeness of a .zip درس‌پک package against its manifest.json.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "package_path": {
                            "type": "string",
                            "description": "Absolute path to the .zip package",
                        }
                    },
                    "required": ["package_path"],
                },
                "handler": self.tool_verify_package,
            },
            "darspack_backup_library": {
                "description": "Create a full library backup ZIP containing the database snapshot (catalog.db) and all stored files.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "output_dir": {
                            "type": "string",
                            "description": "Directory to save the backup ZIP. If omitted, uses Desktop/user home.",
                        }
                    },
                },
                "handler": self.tool_backup_library,
            },
            "darspack_get_stats": {
                "description": "Get overall library statistics: file counts, total size, dedup bytes saved, breakdown by subject and kind.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
                "handler": self.tool_get_stats,
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

    def tool_trash_file(self, args: dict) -> dict:
        file_id = int(args["file_id"])
        res = self.lib.move_to_trash(file_id)
        return {
            "status": "success",
            "message": f"File {res['original_name']} moved to trash",
            "trash_name": res["trash_name"],
        }

    def tool_list_trash(self, args: dict) -> dict:
        items = self.lib.list_trash()
        return {"count": len(items), "items": items}

    def tool_restore_trash_file(self, args: dict) -> dict:
        trash_name = args["trash_name"].strip()
        res = self.lib.restore_trash_file(trash_name)
        return {
            "status": "success",
            "message": f"File {res['original_name']} restored to catalog",
            "file_id": res["id"],
        }

    def tool_check_duplicates(self, args: dict) -> dict:
        conn = self.lib.conn
        r1_groups = duplicate_groups(conn)
        r2_groups = version_conflicts(conn)

        def serialize_group(g):
            return {
                "label": g.label_fa,
                "detail": g.detail_fa,
                "files": [
                    {
                        "id": r["id"],
                        "original_name": r["original_name"],
                        "size_bytes": r["size_bytes"],
                        "sha256": r["sha256"],
                        "imported_at": r["imported_at"],
                    }
                    for r in g.rows
                ],
            }

        return {
            "exact_duplicates": [serialize_group(g) for g in r1_groups],
            "version_conflicts": [serialize_group(g) for g in r2_groups],
        }

    def tool_export_package(self, args: dict) -> dict:
        file_ids = [int(fid) for fid in args.get("file_ids", [])]
        out_path = Path(args["output_path"])
        if not file_ids:
            return {"error": "file_ids cannot be empty"}

        out_path.parent.mkdir(parents=True, exist_ok=True)
        info = export_package(self.lib.conn, self.lib.files_dir, file_ids, out_path)
        with self.lib.conn:
            db.log(self.lib.conn, "mcp_export", f"{info['count']} files -> {out_path.name}")
        return {
            "status": "success",
            "path": info["path"],
            "count": info["count"],
            "manifest_sha256": info["manifest_sha256"],
        }

    def tool_verify_package(self, args: dict) -> dict:
        pkg_path = Path(args["package_path"])
        if not pkg_path.is_file():
            return {"error": f"Package file not found: {pkg_path}"}
        report = verify_package(pkg_path)
        return {
            "ok": report.ok,
            "problems": report.problems,
        }

    def tool_backup_library(self, args: dict) -> dict:
        out_dir = Path(args.get("output_dir") or (Path.home() / "Documents"))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / backup_filename()
        info = backup_library(self.lib, out_file)
        with self.lib.conn:
            db.log(self.lib.conn, "mcp_backup", f"snapshot saved to {out_file.name}")
        return {
            "status": "success",
            "path": str(out_file),
            "file_count": info["count"],
        }

    def tool_get_stats(self, args: dict) -> dict:
        conn = self.lib.conn
        total = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(size_bytes),0) s FROM files"
        ).fetchone()
        dedup = conn.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) saved FROM import_skips"
        ).fetchone()["saved"]
        unclassified = conn.execute(
            "SELECT COUNT(*) c FROM files WHERE subject_id IS NULL"
        ).fetchone()["c"]

        per_subject = [
            {"subject": r["name"], "count": r["c"]}
            for r in conn.execute(
                """SELECT s.name, COUNT(*) c FROM files f
                   JOIN subjects s ON s.id=f.subject_id
                   GROUP BY s.name ORDER BY c DESC"""
            )
        ]
        per_kind = [
            {"kind": r["kind"], "count": r["c"]}
            for r in conn.execute(
                """SELECT kind, COUNT(*) c FROM files WHERE kind IS NOT NULL
                   GROUP BY kind ORDER BY c DESC"""
            )
        ]
        return {
            "file_count": total["c"],
            "total_bytes": total["s"],
            "dedup_bytes_saved": dedup,
            "unclassified_count": unclassified,
            "per_subject": per_subject,
            "per_kind": per_kind,
        }

    # --- Dispatch JSON-RPC methods ---

    def handle_request(self, req: dict | list) -> dict | list | None:
        """Handle one JSON-RPC message (or a batch array) and return a reply."""
        if isinstance(req, list):
            # JSON-RPC 2.0 batches are rare but legal; answer them in order.
            replies = [self.handle_request(item) for item in req]
            non_null = [r for r in replies if r is not None]
            return non_null or None

        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        # Notifications (no id) never get a reply.
        if msg_id is None:
            return None

        if method == "initialize":
            requested = params.get("protocolVersion")
            version = (
                requested
                if requested in SUPPORTED_PROTOCOL_VERSIONS
                else self.PROTOCOL_VERSION
            )
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": version,
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": "darspack-mcp",
                        "version": _server_version(),
                    },
                    "instructions": self.INSTRUCTIONS,
                },
            }

        elif method == "tools/list":
            tools_list = []
            for name, meta in self.tools.items():
                entry = {
                    "name": name,
                    "description": meta["description"],
                    "inputSchema": meta["inputSchema"],
                }
                if name in READ_ONLY_TOOLS:
                    entry["annotations"] = {"readOnlyHint": True}
                tools_list.append(entry)
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools_list}}

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
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

        elif method == "resources/list":
            # We declare no resources; an empty list is friendlier than an
            # error because some clients probe this unconditionally.
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"resources": []}}

        elif method == "resources/templates/list":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"resourceTemplates": []}}

        elif method == "prompts/list":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"prompts": []}}

        elif method == "logging/setLevel":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }


def _server_version() -> str:
    """Report the app version so logs match the installed build."""
    try:
        from .. import __version__

        return __version__
    except Exception:
        return "0.0.0"


class _StderrOnlyStream:
    """Stand-in for ``sys.stdout`` that sends text to stderr.

    Only ``sys.stdout.buffer`` carries JSON-RPC.  A stray ``print()``
    anywhere in the core code would otherwise land in that stream, and a
    single non-JSON line makes most clients drop the connection.  Routing
    text to stderr keeps the protocol stream clean and still lets the agent
    (and the user) see the message as a log line.
    """

    encoding = "utf-8"
    errors = "replace"

    def __init__(self, target) -> None:
        self._target = target

    def write(self, text: str) -> int:
        try:
            self._target.write(text)
        except Exception:
            pass
        return len(text)

    def flush(self) -> None:
        try:
            self._target.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False


def build_selftest_report(library_path: Path | str | None = None) -> tuple[dict, int]:
    """Answer "does this command work?" without opening the library.

    Agents are told to run this before writing any configuration, so it must
    be side-effect free: it reports the library it *would* open, but never
    creates or migrates anything.
    """
    from .launch import resolve_launch

    launch = resolve_launch(library_path)
    library = Path(launch.args[-1]) if launch.args else DEFAULT_LIBRARY_PATH

    server = DarsPackMcpServer(library)
    listed = server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )
    tool_names = [tool["name"] for tool in listed["result"]["tools"]]
    pinged = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    server.close()

    checks = [
        {"check": "json_rpc", "ok": pinged.get("result") == {}},
        {"check": "tools_registered", "ok": len(tool_names) > 0},
        {"check": "launch_mode", "ok": launch.available, "mode": launch.mode},
        {
            "check": "library_present",
            "ok": library.is_dir(),
            "path": str(library),
            "note": "not required for connecting; the app creates it on first run",
        },
    ]
    ok = all(item["ok"] for item in checks if item["check"] != "library_present")

    report = {
        "ok": ok,
        "server": "darspack-mcp",
        "version": _server_version(),
        "protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
        "launch_mode": launch.mode,
        "command": launch.command_line(),
        "library": str(library),
        "library_exists": library.is_dir(),
        "tool_count": len(tool_names),
        "tools": tool_names,
        "checks": checks,
        "note": launch.note,
    }
    return report, (0 if ok else 1)


def _write_json_line(payload: dict) -> None:
    """Write one UTF-8 JSON line to the real stdout (used by --selftest)."""
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8", "replace"
    )
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
    else:  # pragma: no cover - only when stdout was replaced by a test harness
        sys.stdout.write(data.decode("utf-8", "replace"))
        sys.stdout.flush()


def run_stdio_server(library_path: Path | str | None = None) -> None:
    """Run MCP server over standard input/output (line-delimited JSON-RPC)."""
    server = DarsPackMcpServer(library_path)
    # Binary stdio for clean UTF-8 JSON streaming.  Grab the real streams
    # *before* guarding sys.stdout.
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    sys.stdout = _StderrOnlyStream(sys.stderr)

    try:
        while True:
            line = stdin.readline()
            if not line:
                break
            line_str = line.decode("utf-8", "replace").strip()
            if not line_str:
                continue

            try:
                req = json.loads(line_str)
            except Exception:
                continue

            resp = server.handle_request(req)
            if resp is None:
                continue
            out_data = (json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8")
            stdout.write(out_data)
            stdout.flush()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        server.close()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: run the server, or ``--selftest`` and exit."""
    parser = argparse.ArgumentParser(
        prog="darspack.mcp",
        description=(
            "DarsPack MCP server (JSON-RPC 2.0 over stdio). "
            "Headless: it never opens the DarsPack window."
        ),
    )
    parser.add_argument(
        "library",
        nargs="?",
        help="DarsPack library folder (defaults to settings.json or ~/Documents/DarsPackLibrary)",
    )
    parser.add_argument(
        "--library",
        dest="library_flag",
        metavar="PATH",
        help="DarsPack library folder (preferred over the positional form)",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="print a JSON health report and exit 0 when the server is usable",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="print a ready-to-paste MCP config block for this machine and exit",
    )
    parser.add_argument(
        "--format",
        choices=("mcp", "opencode"),
        default="mcp",
        help="config flavour for --print-config (default: mcp -> mcpServers block)",
    )
    parser.add_argument(
        "--version", action="version", version=f"darspack-mcp {_server_version()}"
    )
    args = parser.parse_args(argv)

    library = args.library_flag or args.library
    if args.print_config:
        from .launch import build_mcp_config, build_opencode_config

        config = (
            build_opencode_config(library)
            if args.format == "opencode"
            else build_mcp_config(library)
        )
        _write_json_line(config)
        return 0

    if args.selftest:
        report, code = build_selftest_report(library)
        _write_json_line(report)
        return code

    run_stdio_server(library)
    return 0

