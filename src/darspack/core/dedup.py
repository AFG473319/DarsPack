"""Duplicate grouping and conflict detection (تشخیص تکراری و تضاد).

Three rules — and the rule of rules: *flag only*. Nothing here deletes
or overwrites; the UI shows these groups and the user decides.

  R1 exact duplicate  : same sha256 (محتوای یکسان)
  R2 version conflict : same normalized name, different sha256
                        (نسخه‌های متفاوت با نام یکسان)
  R3 rename hint      : same sha256, different normalized names
                        (یک محتوا با نام‌های مختلف)
"""
from __future__ import annotations

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
        wasted = (len(rows) - 1) * rows[0]["size_bytes"]
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
