"""Streaming SHA-256 (هش فایل).

Reads the file in 1 MB chunks so a large PDF never loads fully into
RAM — the target laptop has 8 GB shared by the app, the browser client
and everything else. `progress(done, total)` lets the UI show a bar
without knowing any hashing details.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_SIZE = 1024 * 1024  # 1 MB


def sha256_file(path, progress=None) -> str:
    """Return the hex SHA-256 of a file, read in chunks."""
    path = Path(path)
    digest = hashlib.sha256()
    total = path.stat().st_size
    done = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done, total)
    return digest.hexdigest()
