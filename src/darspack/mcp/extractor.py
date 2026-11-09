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


def extract_preview(file_path: Path | str, max_chars: int = 2000) -> str:
    """Extract a representative text snippet from a file for LLM classification."""
    path = Path(file_path)
    if not path.is_file():
        return f"[Error: File not found: {path}]"

    suffix = path.suffix.lower()

    if suffix in {".txt", ".md", ".csv", ".json", ".log"}:
        return _extract_plain_text(path, max_chars)
    elif suffix == ".pdf":
        return _extract_pdf_text(path, max_chars)
    else:
        # Fallback summary for images, docs, archives, etc.
        size_kb = round(path.stat().st_size / 1024, 1)
        return f"[File: {path.name}, Type: {suffix or 'unknown'}, Size: {size_kb} KB. Direct text extraction not supported without external parser.]"


def _extract_plain_text(path: Path, max_chars: int) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1256", "latin-1"):
        try:
            text = path.read_text(encoding=enc)
            snippet = text.strip()[:max_chars]
            if len(text) > max_chars:
                snippet += "\n... [truncated]"
            return snippet
        except UnicodeDecodeError:
            continue
    return "[Error: Unable to decode text file]"


def _extract_pdf_text(path: Path, max_chars: int) -> str:
    """Extract plain text from PDF streams using standard library."""
    try:
        data = path.read_bytes()
    except Exception as e:
        return f"[Error reading PDF: {e}]"

    # Search for all FlateDecode streams
    stream_re = re.compile(rb"stream[\r\n]+(.*?)[\r\n]+endstream", re.DOTALL)
    extracted_chunks = []
    total_len = 0

    for match in stream_re.finditer(data):
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
    size_kb = round(path.stat().st_size / 1024, 1)
    return f"[PDF: {path.name}, Size: {size_kb} KB. No plain text stream extracted - file may contain scanned images or custom font encodings.]"
