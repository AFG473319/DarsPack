"""Fast, zero-dependency text & snippet extraction from school materials.

Supports:
- Plain text / markdown (.txt, .md, .csv)
- PDF (.pdf) - Extracts text streams from PDF objects without requiring PyPDF/fitz
- Fallback binary/preview info
"""
from __future__ import annotations

import re
import zlib
from pathlib import Path


#: Never read more than this of a PDF into memory for a preview.  The
#: preview only needs a text snippet, and a huge scanned PDF is mostly
#: image streams anyway — without a cap, previewing one big file can
#: spike RAM on an 8 GB laptop.
MAX_PDF_BYTES = 8 * 1024 * 1024

#: Cap plain-text reads for the same reason — a huge .log/.csv never loads whole.
MAX_TEXT_BYTES = 1024 * 1024

# PDF content streams: `stream` … `endstream`. Compiled once at import —
# this pattern is re-used for every PDF that gets previewed.
_STREAM_RE = re.compile(rb"stream[\r\n]+(.*?)[\r\n]+endstream", re.DOTALL)


def extract_preview(file_path: Path | str, max_chars: int = 2000) -> str:
    """Extract a representative text snippet from a file for LLM classification."""
    path = Path(file_path)
    try:
        if not path.is_file():
            return f"[Error: File not found: {path}]"
    except OSError as e:
        return f"[Error reading file: {e}]"

    suffix = path.suffix.lower()

    if suffix in {".txt", ".md", ".csv", ".json", ".log"}:
        return _extract_plain_text(path, max_chars)
    elif suffix == ".pdf":
        return _extract_pdf_text(path, max_chars)
    else:
        # Fallback summary for images, docs, archives, etc.
        try:
            size_kb = round(path.stat().st_size / 1024, 1)
        except OSError as e:
            return f"[Error reading file: {e}]"
        return f"[File: {path.name}, Type: {suffix or 'unknown'}, Size: {size_kb} KB. Direct text extraction not supported without external parser.]"


def _extract_plain_text(path: Path, max_chars: int) -> str:
    try:
        with path.open("rb") as fh:
            raw = fh.read(MAX_TEXT_BYTES)
    except OSError as e:
        return f"[Error reading text file: {e}]"
    byte_capped = len(raw) == MAX_TEXT_BYTES
    # Try utf-8-sig before utf-8 so UTF-8 BOMs strip cleanly.
    for enc in ("utf-8-sig", "utf-8", "cp1256", "latin-1"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError as e:
            # If the 1 MB read cap split a multi-byte UTF-8 sequence at the
            # very end of the buffer, decode everything before that tail.
            if byte_capped and e.start >= len(raw) - 3:
                try:
                    text = raw[:e.start].decode(enc)
                except UnicodeDecodeError:
                    continue
            else:
                continue
        snippet = text.strip()[:max_chars]
        if len(text) > max_chars or byte_capped:
            snippet += "\n... [truncated]"
        return snippet
    return "[Error: Unable to decode text file]"


def _extract_pdf_text(path: Path, max_chars: int) -> str:
    """Extract plain text from PDF streams using standard library."""
    try:
        with path.open("rb") as fh:
            data = fh.read(MAX_PDF_BYTES)
    except Exception as e:
        return f"[Error reading PDF: {e}]"

    # Search for all FlateDecode streams
    extracted_chunks = []
    total_len = 0

    for match in _STREAM_RE.finditer(data):
        raw_stream = match.group(1)
        try:
            decompressed = zlib.decompress(raw_stream)
        except Exception:
            # Might be uncompressed or use different filter
            decompressed = raw_stream

        # Extract text in parentheses (Tj / TJ operators in PDF syntax)
        # e.g. (Hello) Tj or [(Hello) 10 (World)] TJ
        tj_matches = re.findall(rb"\((.*?)\)\s*Tj", decompressed)
        tj_array_matches = re.findall(rb"\[(.*?)\]\s*TJ", decompressed)

        for item in tj_matches:
            try:
                # Basic PDF string decoding
                text_part = item.decode("utf-8", errors="ignore")
                text_part = text_part.strip()
                if text_part:
                    extracted_chunks.append(text_part)
                    total_len += len(text_part)
            except Exception:
                pass

        for array_item in tj_array_matches:
            nested = re.findall(rb"\((.*?)\)", array_item)
            for part in nested:
                try:
                    text_part = part.decode("utf-8", errors="ignore").strip()
                    if text_part:
                        extracted_chunks.append(text_part)
                        total_len += len(text_part)
                except Exception:
                    pass

        if total_len >= max_chars * 2:
            break

    if extracted_chunks:
        full_text = " ".join(extracted_chunks)
        # Clean extra whitespace
        full_text = re.sub(r"\s+", " ", full_text).strip()
        if len(full_text) > max_chars:
            return full_text[:max_chars] + "\n... [truncated]"
        return full_text

    # If stream decoding yielded no UTF-8 readable text (e.g. encrypted or CIDFont without ToUnicode map)
    try:
        size_kb = round(path.stat().st_size / 1024, 1)
    except OSError as e:
        return f"[Error reading PDF: {e}]"
    return f"[PDF: {path.name}, Size: {size_kb} KB. No plain text stream extracted - file may contain scanned images or custom font encodings.]"
