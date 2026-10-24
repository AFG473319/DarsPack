"""Search over the catalog (جست‌جو).

Both the query and the stored names go through match_key(), so
«فصل ۳» finds «فصل 3», and «رياضي» (Arabic ي) finds «ریاضی». Matching
covers the filename, the subject name and tags. Ranking: a prefix match
beats a contains match; ties break by recency.

Documented limitation: search covers names and metadata only — not the
text *inside* PDFs.
"""
from __future__ import annotations

from .normalize import match_key

_SQL = """
SELECT f.id, f.original_name, f.size_bytes, f.imported_at,
       f.chapter, f.kind, f.sha256,
       s.name AS subject_name,
       CASE WHEN f.name_norm LIKE :prefix THEN 0 ELSE 1 END AS rank
FROM files f
LEFT JOIN subjects s ON s.id = f.subject_id
WHERE (:q = '' OR f.name_norm LIKE :like
       OR s.normalized LIKE :like
       OR EXISTS (SELECT 1 FROM file_tags ft
                  JOIN tags t ON t.id = ft.tag_id
                  WHERE ft.file_id = f.id AND t.normalized LIKE :like))
  AND (:subject_id IS NULL OR f.subject_id = :subject_id)
  AND (:unclassified = 0 OR f.subject_id IS NULL)
  AND (:kind IS NULL OR f.kind = :kind)
ORDER BY rank, f.imported_at DESC
LIMIT :limit
"""


def search(conn, query: str = "", subject_id: int | None = None,
           kind: str | None = None, limit: int = 200,
           unclassified_only: bool = False) -> list:
    """Return catalog rows matching the query and optional filters.

    unclassified_only=True lists files still missing their subject —
    the "finish your catalog" view (categorizing is the app's main job).
    """
    key = match_key(query)
    return conn.execute(_SQL, {
        "q": key,
        "like": f"%{key}%",
        "prefix": f"{key}%",
        "subject_id": subject_id,
        "unclassified": 1 if unclassified_only else 0,
        "kind": kind,
        "limit": limit,
    }).fetchall()


def unclassified_count(conn) -> int:
    """How many files still have no subject (for the status bar nudge)."""
    return conn.execute(
        "SELECT COUNT(*) c FROM files WHERE subject_id IS NULL").fetchone()["c"]
