"""Duplicate grouping and conflict detection (تشخیص تکراری و تضاد).

Four rules — and the rule of rules: *flag only*. Nothing here deletes
or overwrites; the UI shows these groups and the user decides.

  R1 exact duplicate  : same sha256 (محتوای یکسان)
  R2 version conflict : same normalized name, different sha256
                        (نسخه‌های متفاوت با نام یکسان)
  R3 rename hint      : same sha256, different normalized names
                        (یک محتوا با نام‌های مختلف)
  R4-lite (likely_versions): names differing only by re-download noise
                        («x (1).pdf», «نسخه نهایی», «final») with
                        different content — a WEAK hint, flag-only
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Group:
    label_fa: str
    rows: list = field(default_factory=list)   # catalog rows in the group
    detail_fa: str = ""


def duplicate_groups(conn) -> list[Group]:
    """R1 — every sha256 owned by more than one row."""
    shas = [r["sha256"] for r in conn.execute(
        "SELECT sha256 FROM files GROUP BY sha256 HAVING COUNT(*) > 1")]
    groups = []
    for sha in shas:
        rows = conn.execute(
            "SELECT * FROM files WHERE sha256=? ORDER BY imported_at",
            (sha,)).fetchall()
        wasted = (len(rows) - 1) * (rows[0]["size_bytes"] or 0)
        groups.append(Group(
            "تکراری کامل", list(rows),
            f"{len(rows)} نسخه‌ی یکسان — فضای اشغال‌شده‌ی تکراری: {wasted} بایت"))
    return groups


def version_conflicts(conn) -> list[Group]:
    """R2 — same normalized name saved with different content."""
    names = [r["name_norm"] for r in conn.execute(
        """SELECT name_norm FROM files
           GROUP BY name_norm HAVING COUNT(DISTINCT sha256) > 1""")]
    groups = []
    for name in names:
        rows = conn.execute(
            "SELECT * FROM files WHERE name_norm=? ORDER BY imported_at",
            (name,)).fetchall()
        groups.append(Group(
            "نسخه‌های متفاوت با نام یکسان", list(rows),
            "احتمالاً نسخه‌های مختلف یک فایل‌اند — قبل از استفاده مقایسه کن"))
    return groups


def rename_hints(conn) -> list[Group]:
    """R3 — identical content saved under different names."""
    hints = []
    for g in duplicate_groups(conn):
        if len({r["name_norm"] for r in g.rows}) > 1:
            hints.append(Group(
                "یک محتوا با نام‌های مختلف", g.rows,
                "محتوای یکسان با نام‌های متفاوت ذخیره شده"))
    return hints


# --- R4-lite: likely different versions of the same file --------------------
# Kept INSIDE dedup.py on purpose: the noise patterns below are the
# core-algorithm material, so they must not leak into normalize.py.

_NOISE_RE = re.compile(
    r"(\(\d+\))"          # the browser's re-download suffix: «x (1).pdf»
    r"|(نسخه ?\d+)"       # «نسخه ۲»
    r"|(نهایی|اصلاح ?شده|جدید|کپی|کپی شده)"
    r"|(final|copy|v\d+)"  # Latin twins of the same habits
)

_SPACE_BEFORE_EXT_RE = re.compile(r"\s+(\.\w+)$")  # «x (1) .pdf» → «x.pdf»


def strip_version_noise(name_norm: str) -> str:
    """Drop re-download/version noise from a match key (key only — the
    stored original_name is never touched). Pure helper, unit-testable."""
    cleaned = _NOISE_RE.sub(" ", name_norm)
    cleaned = _SPACE_BEFORE_EXT_RE.sub(r"\1", cleaned)
    return " ".join(cleaned.split())       # collapse the leftover spaces


def likely_versions(conn) -> list[Group]:
    """R4-lite — names differing only by version noise, different content.

    R2 only fires on EXACT normalized-name equality, so the most common
    real pattern escapes it: the teacher's corrected worksheet re-downloaded
    as «x (1).pdf» sits beside the outdated twin. Group rows whose
    noise-stripped key matches when the group holds >1 distinct sha256
    AND >1 distinct name (otherwise every single file would self-group).
    Weak hint by design: false positives are acceptable because nothing
    ever acts on this group automatically.
    """
    rows = conn.execute(
        "SELECT * FROM files ORDER BY imported_at").fetchall()
    buckets: dict[str, list] = {}
    for row in rows:
        key = strip_version_noise(row["name_norm"])
        if not key:
            key = row["name_norm"]        # a name made only of noise stays itself
        buckets.setdefault(key, []).append(row)
    groups = []
    for key, group_rows in sorted(buckets.items()):
        if (len({r["sha256"] for r in group_rows}) > 1
                and len({r["name_norm"] for r in group_rows}) > 1):
            groups.append(Group(
                "نسخه‌های احتمالی", group_rows,
                "احتمالاً نسخه‌های مختلف یک فایل‌اند — قبل از استفاده مقایسه کن"))
    return groups
