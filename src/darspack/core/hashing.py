"""Streaming SHA-256 (هش فایل).

Reads the file in fixed-size chunks so a large PDF never loads fully
into RAM — the target laptop has 8 GB shared by the app, the browser
client and everything else. `progress(done, total)` lets the UI show a
bar without knowing any hashing details; without a callback the read
loop runs inside hashlib (C) instead.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_SIZE = 1024 * 1024  # 1 MB


def sha256_file(path, progress=None, size: int | None = None) -> str:
    """Return the hex SHA-256 of a file, read in chunks.

    `size` is optional: callers that already stat()ed the file (the
    importer needs the size for the catalog row anyway) pass it in so
    the file is not stat()ed twice.
    """
    path = Path(path)
    if progress is None:
        # hashlib.file_digest runs the read loop in C (same 1 MB buffer,
        # same constant memory) — the Python loop below exists only to
        # report progress, so it is skipped when nobody is watching.
        with open(path, "rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()
    if size is None:
        size = path.stat().st_size
    digest = hashlib.sha256()
    total = size
    done = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            done += len(chunk)
            progress(done, total)
    return digest.hexdigest()
