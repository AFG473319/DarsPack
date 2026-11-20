"""Library statistics (آمار کتابخانه).

One definition of "the numbers" for every consumer: the desktop stats
dialog, the MCP `get_stats` tool and the benchmark scripts all read the
same dict, so they can never drift apart.
"""
from __future__ import annotations


def library_stats(conn) -> dict:
    """Counts and byte totals behind the stats views.

    Returns file_count, total_bytes, dedup_bytes (what duplicate imports
    saved), unclassified, per_subject and per_kind (sorted, biggest
    first). All queries are single indexed scans — the caller runs this
    off the UI thread.
    """
    per_subject = [(r["name"], r["c"]) for r in conn.execute(
        """SELECT s.name, COUNT(*) c FROM files f
           JOIN subjects s ON s.id=f.subject_id
           GROUP BY s.name ORDER BY c DESC""")]
    per_kind = [(r["kind"], r["c"]) for r in conn.execute(
        """SELECT kind, COUNT(*) c FROM files WHERE kind IS NOT NULL
           GROUP BY kind ORDER BY c DESC""")]
    total = conn.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(size_bytes),0) s FROM files"
    ).fetchone()
    dedup = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) saved FROM import_skips"
    ).fetchone()["saved"]
    unclassified = conn.execute(
        "SELECT COUNT(*) c FROM files WHERE subject_id IS NULL").fetchone()["c"]
    return {
        "file_count": total["c"],
        "total_bytes": total["s"],
        "dedup_bytes": dedup,
        "unclassified": unclassified,
        "per_subject": per_subject,
        "per_kind": per_kind,
    }
