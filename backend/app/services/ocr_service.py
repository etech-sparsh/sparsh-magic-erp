"""OCR for scanned / image-only PDF pages.

Tiered and best-effort so accuracy is maximised on whatever the host provides:

  1. **Tesseract** (free, local, fast) via PyMuPDF's built-in OCR — used when a
     Tesseract engine is installed and discoverable by MuPDF.
  2. **OpenAI vision OCR** (gpt-4o-mini) — a per-page fallback that needs NO
     system binary, only the existing OpenAI key. Slower and metered, but it
     means scanned PDFs are fully transcribed even on a server without Tesseract.

Pages are rendered with PyMuPDF (already a dependency). Blocking work (render +
Tesseract) is pushed to threads so the event loop isn't stalled. Vision calls run
with bounded concurrency. Nothing here ever raises — on total failure it returns
an empty dict and the caller keeps its existing behaviour.
"""
from __future__ import annotations

import asyncio
import base64
from typing import Dict, List, Optional

from app.config.settings import settings

# Tunables (overridable via settings if those attributes exist).
MAX_OCR_PAGES: int = int(getattr(settings, "MAX_OCR_PAGES", 600))   # safety cap per file
OCR_DPI: int = int(getattr(settings, "OCR_DPI", 200))               # render resolution
OCR_VISION_CONCURRENCY: int = int(getattr(settings, "OCR_VISION_CONCURRENCY", 8))
OCR_VISION_MODEL: str = str(getattr(settings, "OCR_VISION_MODEL", "gpt-4o-mini"))

_client: Optional["object"] = None


def _get_client():
    global _client
    if _client is None:
        from openai import AsyncOpenAI
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _tesseract_ok() -> bool:
    """Whether MuPDF can OCR (i.e. a Tesseract engine is installed/discoverable).

    Probed once by attempting a tiny OCR; failures (no engine, no tessdata) mean
    we fall back to vision OCR.
    """
    global _TESS_OK
    if _TESS_OK is not None:
        return _TESS_OK
    try:
        import fitz  # PyMuPDF
        doc = fitz.open()  # empty in-memory doc
        page = doc.new_page()
        page.insert_text((72, 72), "ocr probe")
        page.get_textpage_ocr(full=True)  # raises if no Tesseract
        doc.close()
        _TESS_OK = True
    except Exception:
        _TESS_OK = False
    return _TESS_OK


_TESS_OK: Optional[bool] = None


def _ocr_pages_tesseract(path: str, page_indices: List[int], dpi: int) -> Dict[int, str]:
    """Blocking: OCR the given page indices with Tesseract via MuPDF."""
    import fitz  # PyMuPDF
    out: Dict[int, str] = {}
    doc = fitz.open(path)
    try:
        for i in page_indices:
            if i < 0 or i >= doc.page_count:
                continue
            page = doc[i]
            try:
                tp = page.get_textpage_ocr(flags=0, dpi=dpi, full=True)
                txt = page.get_text("text", textpage=tp) or ""
            except Exception:
                txt = ""
            if txt.strip():
                out[i] = txt
    finally:
        doc.close()
    return out


def _render_page_png(path: str, i: int, dpi: int) -> Optional[bytes]:
    """Blocking: render one PDF page to PNG bytes."""
    import fitz  # PyMuPDF
    doc = fitz.open(path)
    try:
        if i < 0 or i >= doc.page_count:
            return None
        pix = doc[i].get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    except Exception:
        return None
    finally:
        doc.close()


async def _ocr_page_vision(path: str, i: int, dpi: int, sem: asyncio.Semaphore) -> Optional[str]:
    """OCR one page through the multimodal model (no system binary needed)."""
    png = await asyncio.to_thread(_render_page_png, path, i, dpi)
    if not png:
        return None
    b64 = base64.b64encode(png).decode("utf-8")
    data_uri = f"data:image/png;base64,{b64}"
    async with sem:
        try:
            resp = await _get_client().chat.completions.create(
                model=OCR_VISION_MODEL,
                temperature=0,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": (
                            "Transcribe ALL text from this document page exactly as it "
                            "appears, preserving reading order, headings, lists and table "
                            "rows. Output ONLY the transcribed text, with no commentary. "
                            "If the page has no readable text, output nothing."
                        )},
                        {"type": "image_url", "image_url": {"url": data_uri, "detail": "high"}},
                    ],
                }],
            )
            return (resp.choices[0].message.content or "").strip() or None
        except Exception as e:  # noqa: BLE001
            print(f"[ocr] vision OCR failed on page {i}: {e}")
            return None


async def ocr_pdf_pages(path: str, page_indices: List[int], dpi: int = OCR_DPI) -> Dict[int, str]:
    """OCR the requested PDF page indices → {page_index: text}.

    Uses Tesseract when available (fast/free), otherwise OpenAI vision OCR.
    Capped at MAX_OCR_PAGES to bound time/cost on very large files.
    """
    if not page_indices:
        return {}
    pages = sorted(set(page_indices))[:MAX_OCR_PAGES]

    # Preferred: local Tesseract (no API cost).
    if _tesseract_ok():
        return await asyncio.to_thread(_ocr_pages_tesseract, path, pages, dpi)

    # Fallback: vision OCR. Requires an OpenAI key.
    if not getattr(settings, "OPENAI_API_KEY", None):
        return {}
    sem = asyncio.Semaphore(max(1, OCR_VISION_CONCURRENCY))
    results = await asyncio.gather(*[_ocr_page_vision(path, i, dpi, sem) for i in pages])
    return {i: t for i, t in zip(pages, results) if t}


def ocr_engine_name() -> str:
    """Human-readable name of the active OCR engine (for logs/diagnostics)."""
    if _tesseract_ok():
        return "tesseract"
    if getattr(settings, "OPENAI_API_KEY", None):
        return f"openai-vision:{OCR_VISION_MODEL}"
    return "none"
