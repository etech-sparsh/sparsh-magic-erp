"""Paragraph-aware text chunking for retrieval.

Produces smaller, semantically-coherent chunks than a flat word-window split,
which materially improves embedding-retrieval precision on long documents: a
question about page 250 of a 400-page PDF retrieves the right passage instead of
an 800-word slab that buries the answer.

Strategy: split on blank lines into paragraph-ish blocks, pack blocks up to a
word target, carry an overlap of trailing words into the next chunk (so context
isn't severed at a boundary), and hard-split any single oversized block
(e.g. a giant table dumped as one line). Falls back gracefully on pathological
input — never raises.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

DEFAULT_TARGET_WORDS = 320
DEFAULT_OVERLAP_WORDS = 60
_PAGE_MARKER_RE = re.compile(r"^\s*\[Page\s+(\d+)\]\s*$", re.IGNORECASE | re.MULTILINE)


def _tail(words: List[str], n: int) -> List[str]:
    """Last `n` words (for overlap continuity), or [] when no overlap wanted."""
    if n <= 0:
        return []
    return list(words[-n:])


def smart_chunk(
    text: str,
    target_words: int = DEFAULT_TARGET_WORDS,
    overlap_words: int = DEFAULT_OVERLAP_WORDS,
) -> List[str]:
    """Split `text` into overlapping, paragraph-aware chunks of ~`target_words`."""
    if not text or not text.strip():
        return []

    target_words = max(50, int(target_words))
    overlap_words = max(0, min(int(overlap_words), target_words // 2))
    step = max(1, target_words - overlap_words)

    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if not blocks:
        blocks = [text.strip()]

    chunks: List[str] = []
    buf: List[str] = []  # accumulating words for the current chunk

    for block in blocks:
        words = block.split()

        # A single oversized paragraph (or a one-line table) is hard-split into
        # target-sized, overlapping windows.
        if len(words) > target_words:
            if buf:
                chunks.append(" ".join(buf))
                buf = _tail(buf, overlap_words)
            start = 0
            while start < len(words):
                chunks.append(" ".join(words[start:start + target_words]))
                start += step
            buf = _tail(words, overlap_words)
            continue

        # Would appending this block overflow the target? Flush, then seed the
        # next chunk with the overlap tail plus this block.
        if buf and len(buf) + len(words) > target_words:
            chunks.append(" ".join(buf))
            buf = _tail(buf, overlap_words) + words
        else:
            buf.extend(words)

    if buf:
        chunks.append(" ".join(buf))

    # Drop empties and any accidental exact-duplicate neighbours from overlap.
    out: List[str] = []
    for c in (s.strip() for s in chunks):
        if c and (not out or out[-1] != c):
            out.append(c)
    return out


def _page_for_offset(markers: List[tuple], offset: int) -> Optional[int]:
    """Return the most recent page marker at or before ``offset``."""
    page = None
    for pos, marker_page in markers:
        if pos > offset:
            break
        page = marker_page
    return page


def smart_chunk_records(
    text: str,
    target_words: int = DEFAULT_TARGET_WORDS,
    overlap_words: int = DEFAULT_OVERLAP_WORDS,
) -> List[Dict]:
    """Return chunk docs with lightweight metadata.

    The public ``smart_chunk`` stays as a list[str] for compatibility. This
    richer variant is used by retrieval indexes so large PDFs can preserve page
    hints, making answers and debugging much more precise.
    """
    chunks = smart_chunk(text, target_words=target_words, overlap_words=overlap_words)
    if not chunks:
        return []

    markers = [(m.start(), int(m.group(1))) for m in _PAGE_MARKER_RE.finditer(text or "")]
    records: List[Dict] = []
    search_from = 0
    for i, content in enumerate(chunks):
        start = (text or "").find(content[: min(len(content), 120)], search_from)
        if start < 0:
            start = search_from
        end = start + len(content)
        page_start = _page_for_offset(markers, start)
        page_end = _page_for_offset(markers, end)
        metadata = {"chunk_index": i, "char_start": start, "char_end": end}
        if page_start is not None:
            metadata["page_start"] = page_start
        if page_end is not None:
            metadata["page_end"] = page_end
        records.append({"content": content, **metadata})
        search_from = max(search_from, start + max(1, len(content) // 2))
    return records
