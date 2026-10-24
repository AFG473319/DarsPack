"""LAN sync manifest + diff (سنکرون — هسته‌ی بازنویسی تو).

One job: answer "what is different between my catalog and another
DarsPack's catalog / package manifest?" as a plain dict. Used by the
web server (/api/manifest) and reusable later for PC↔PC sync.

The diff is deliberately simple and explainable:
- their  = the other side's {sha256: name} map
- ours   = our {sha256: name} map
- missing_on_theirs : we have it, they don't (they can download)
- missing_on_ours   : they have it, we don't (we can request)
- same_content_different_name : R3 seen across devices
"""
from __future__ import annotations

import sqlite3


def catalog_manifest(conn: sqlite3.Connection) -> dict:
    """Our catalog as {sha256: display info} — the sync unit of exchange."""
    manifest: dict = {}
    for row in conn.execute(
            """SELECT sha256, original_name, size_bytes FROM files
               GROUP BY sha256"""):
        manifest[row["sha256"]] = {
            "name": row["original_name"], "size": row["size_bytes"]}
    return manifest


def diff(ours: dict, theirs: dict) -> dict:
    """Compare two {sha256: {...}} manifests. Pure function, no I/O."""
    our_shas, their_shas = set(ours), set(theirs)
    return {
        "missing_on_theirs": sorted(our_shas - their_shas),
        "missing_on_ours": sorted(their_shas - our_shas),
        "same_content_different_name": sorted(
            sha for sha in our_shas & their_shas
            if ours[sha].get("name") != theirs[sha].get("name")),
    }
