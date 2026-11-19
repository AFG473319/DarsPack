"""Search over the catalog (جست‌وجو).

Both the query and the stored names go through match_key(), so
«فصل ۳» finds «فصل 3», and «رياضي» (Arabic ي) finds «ریاضی». Matching
covers the filename, the subject name, tags, the note and the kind —
and a «فصل ۵»/«درس ۳» phrase also matches the structured chapter/lesson
columns, so classified files are found even when their filename never
mentions the word.

Multi-token (C1): the query's words are AND-ed together — every token
must match *somewhere*. «ریاضی نمونه سوال فصل ۵» finds files whose name
orders the same words differently. Ranking: a prefix match on the first
token beats a contains match; ties break by recency.

Documented limitations: the note is matched as stored (no note_norm
column yet — typing-style differences inside a note won't match), and
search covers names and metadata only — not the text *inside* PDFs.
"""
from __future__ import annotations

import re

from .normalize import match_key
from .suggest import WORD_NUMBERS

_BASE_SQL = """
SELECT f.id, f.original_name, f.size_bytes, f.imported_at,
       f.chapter, f.lesson, f.kind, f.school_year, f.note, f.sha256, f.available,
       s.name AS subject_name,
       {rank} AS rank
FROM files f
LEFT JOIN subjects s ON s.id = f.subject_id
WHERE {where}
ORDER BY rank, f.imported_at DESC
LIMIT :limit
"""


def _escape_like(text: str) -> str:
    """Escape %, _, and / in text for SQL LIKE queries with ESCAPE '/'."""
    return text.replace("/", "//").replace("%", "/%").replace("_", "/_")


# One token's match clause: every token must match somewhere (AND across
# tokens). The EXISTS finds the token among the file's tags; it names its
# aliases ftg/tgt so it can never collide with the outer aliases.
_TOKEN_CLAUSE = """(f.name_norm LIKE :like{i} ESCAPE '/'
       OR s.normalized LIKE :like{i} ESCAPE '/'
       OR f.note LIKE :like{i} ESCAPE '/'
       OR f.kind LIKE :like{i} ESCAPE '/'
       OR EXISTS (SELECT 1 FROM file_tags ftg
                  JOIN tags tgt ON tgt.id = ftg.tag_id
                  WHERE ftg.file_id = f.id AND tgt.normalized LIKE :like{i} ESCAPE '/')"""

# «فصل ۵» / «درس سه» become structured tokens: the number is matched
# against the chapter/lesson columns in addition to the text surfaces.
# Word numbers are tried longest-first so «دوازده» is never read as «دو».
_PHRASE_RE = re.compile(
    r"(فصل|درس)\s*(\d{1,2}|دوازده|یازده|ده|نه|هشت|هفت|شش|پنج|چهار|سه|دو|یک)"
    r"(?![\u0600-\u06FF])")

MAX_TOKENS = 8       # a real query never has more; pasting never hangs it
MAX_TOKEN_LEN = 64   # a pasted paragraph is not a search term


def _tokens(key: str) -> list[dict]:
    """Split a normalized query into search tokens.

    Each token is {'text': str, 'num': int|None, 'field': 'chapter'|'lesson'}
    — text is always present (used for the LIKE surfaces); num/field are
    set only for «فصل/درس N» phrases. Empty tokens are dropped, phrases
    stay atomic («فصل 5» is one token, not two), and the list is capped.
    """
    out: list[dict] = []
    pos = 0

    def add_plain(text: str) -> None:
        for word in text.split():
            out.append({"text": word[:MAX_TOKEN_LEN], "num": None,
                        "field": None})

    for m in _PHRASE_RE.finditer(key):
        add_plain(key[pos:m.start()])
        number = m.group(2)
        num = int(number) if number.isdigit() else WORD_NUMBERS[number]
        field = "chapter" if m.group(1) == "فصل" else "lesson"
        out.append({"text": m.group(0).strip()[:MAX_TOKEN_LEN],
                    "num": num, "field": field})
        pos = m.end()
    add_plain(key[pos:])
    return out[:MAX_TOKENS]


def _build_where(query: str = "", subject_id: int | None = None,
                 kind: str | None = None, school_year: str | None = None,
                 unclassified_only: bool = False):
    """Shared WHERE builder for search() and search_total().

    Returns (where_sql, params, tokens). The params carry no :limit or
    :prefix — the row query adds those itself — so the same WHERE can
    feed both the paged SELECT and the COUNT(*).
    """
    tokens = _tokens(match_key(query))
    params = {
        "subject_id": subject_id,
        "kind": kind,
        "school_year": school_year,
    }

    where_parts = []
    for i, tok in enumerate(tokens):
        params[f"like{i}"] = f"%{_escape_like(tok['text'])}%"
        clause = _TOKEN_CLAUSE.format(i=i)
        if tok["num"] is not None:
            params[f"num{i}"] = tok["num"]
            clause += f"\n       OR f.{tok['field']} = :num{i}"
        clause += ")"
        where_parts.append(clause)
    if subject_id is not None:
        where_parts.append("f.subject_id = :subject_id")
    if unclassified_only:
        where_parts.append("f.subject_id IS NULL")
    if kind is not None:
        where_parts.append("f.kind = :kind")
    if school_year is not None:
        where_parts.append("f.school_year = :school_year")

    if not where_parts:     # also covers the fresh-catalog case
        where_parts = ["1"]
    return "\n  AND ".join(where_parts), params, tokens


def search(conn, query: str = "", subject_id: int | None = None,
           kind: str | None = None, school_year: str | None = None,
           limit: int = 200, unclassified_only: bool = False) -> list:
    """Return catalog rows matching the query and optional filters.

    unclassified_only=True lists files still missing their subject —
    the "finish your catalog" view (categorizing is the app's main job).
    """
    where, params, tokens = _build_where(
        query, subject_id, kind, school_year, unclassified_only)
    params["limit"] = limit

    if tokens:
        # Prefix rank on the FIRST token only — later tokens are filters,
        # not ranking signals (same rule as before multi-token search).
        params["prefix"] = f"{_escape_like(tokens[0]['text'])}%"
        rank = "CASE WHEN f.name_norm LIKE :prefix ESCAPE '/' THEN 0 ELSE 1 END"
    else:
        rank = "0"          # empty query lists everything, newest first

    sql = _BASE_SQL.format(rank=rank, where=where)
    return conn.execute(sql, params).fetchall()


def search_total(conn, query: str = "", subject_id: int | None = None,
                 kind: str | None = None, school_year: str | None = None,
                 unclassified_only: bool = False) -> int:
    """How many catalog rows match the same filters search() would apply.

    M30: the phone client caps its page at SEARCH_LIMIT rows, so it needs
    the real total to say "showing X of Y" instead of presenting the cap
    as the whole library.
    """
    where, params, _tokens = _build_where(
        query, subject_id, kind, school_year, unclassified_only)
    sql = ("SELECT COUNT(*) c FROM files f "
           "LEFT JOIN subjects s ON s.id = f.subject_id "
           f"WHERE {where}")
    return conn.execute(sql, params).fetchone()["c"]


def unclassified_count(conn) -> int:
    """How many files still have no subject (for the status bar nudge)."""
    return conn.execute(
        "SELECT COUNT(*) c FROM files WHERE subject_id IS NULL").fetchone()["c"]
