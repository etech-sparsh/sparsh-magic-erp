"""Text → vector embeddings (OpenAI) for semantic retrieval.

Resilient by design: if vector RAG is disabled, the API key is missing, or the
call errors, every function returns None so callers fall back to keyword search.
The OpenAI client is imported lazily so importing this module never fails on a
host without the SDK.
"""
from __future__ import annotations

from typing import List, Optional

from app.assistant.config import config
from app.config.settings import settings

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import AsyncOpenAI  # lazy import
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def enabled() -> bool:
    return bool(config.RAG_VECTOR_ENABLED and settings.OPENAI_API_KEY)


async def embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    """Embed a list of texts → list of vectors (same order/length).

    Returns None if embeddings are unavailable (disabled / no key / error), so
    the caller can fall back. Empty strings are replaced with a single space so
    the API never rejects the batch and the output stays index-aligned.
    """
    if not enabled() or not texts:
        return None
    cleaned = [((t or "").strip()[: config.EMBED_MAX_CHARS] or " ") for t in texts]
    try:
        client = _get_client()
        out: List[List[float]] = []
        step = max(1, int(config.EMBED_BATCH))
        for i in range(0, len(cleaned), step):
            batch = cleaned[i : i + step]
            resp = await client.embeddings.create(model=config.EMBED_MODEL, input=batch)
            # resp.data preserves input order.
            out.extend([d.embedding for d in resp.data])
        return out
    except Exception as e:  # noqa: BLE001 — degrade to keyword search
        print(f"[rag] embed_texts failed ({len(cleaned)} texts): {e}")
        return None


async def embed_query(text: str) -> Optional[List[float]]:
    """Embed a single query string → vector, or None on failure."""
    vecs = await embed_texts([text or ""])
    return vecs[0] if vecs else None


async def attach_embeddings(docs: List[dict], text_key: str = "content") -> List[dict]:
    """Best-effort: add an `embedding` field to each chunk doc before insert.

    On any failure the docs are returned unchanged (no embedding field) — they
    still get inserted and remain findable by keyword search, and can be
    embedded later by the backfill script. So write paths never break.
    """
    if not docs:
        return docs
    vecs = await embed_texts([d.get(text_key, "") or "" for d in docs])
    if vecs and len(vecs) == len(docs):
        for d, v in zip(docs, vecs):
            d["embedding"] = v
    return docs
