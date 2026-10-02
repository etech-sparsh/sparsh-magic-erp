"""Media Library content indexing.

Makes the shared Media Library answerable by the assistant: extracts the
SEARCHABLE TEXT from each uploaded file — document text for PDFs/Word/Excel/etc.
and the speech transcript for audio/video — and saves it on the media_library
document (`content_text`). The assistant's `search_media_library` tool searches
that field, so the chatbot can answer questions about what is INSIDE the files,
not just their names.

Runs as a background task after upload (the file is already in S3, so we
download it to a temp path, extract, then clean up). Failures are recorded on
the document (`content_status`) and never break the upload response.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime

from bson import ObjectId

from app.assistant.config import config
from app.db.mongodb import get_collection
from app.services.s3_service import download_file_from_s3

# File types we can turn into searchable text. Images/"other" are skipped
# (no reliable text to keyword-search).
INDEXABLE_TYPES = {"audio", "video", "pdf", "document"}

# Cap stored text so a huge spreadsheet can't bloat the document or, later, the
# model prompt. ~120k chars is plenty for retrieval excerpts.
MAX_CONTENT_CHARS = 120_000


async def _reindex_media_chunks(media_doc: dict, text: str) -> None:
    """Chunk a file's extracted text and (re)write embedded vector chunks to the
    media_chunks collection, so the assistant can semantically search inside
    Media Library files. Best-effort: keyword search on content_text still works
    if this fails. Always clears the file's old chunks first (idempotent re-index).
    """
    media_id = str(media_doc["_id"])
    chunk_col = get_collection(config.MEDIA_CHUNK_COLLECTION)
    await chunk_col.delete_many({"media_id": media_id})
    if not text:
        return

    from app.services.gpt_service import chunk_text
    from app.assistant.rag.embeddings import attach_embeddings

    # Smaller chunks than the Support Engine default → better retrieval precision.
    pieces = chunk_text(text, chunk_size=250, overlap=40)
    docs = [
        {
            "media_id": media_id,
            "name": media_doc.get("name"),
            "file_name": media_doc.get("file_name"),
            "media_type": media_doc.get("media_type"),
            "content": p,
            "created_at": datetime.utcnow(),
        }
        for p in pieces
    ]
    docs = await attach_embeddings(docs)
    if docs:
        await chunk_col.insert_many(docs)
    print(f"[media:{media_id}] wrote {len(docs)} vector chunk(s)")


async def index_media_library_item(media_id: str, s3_key: str, filename: str, media_type: str) -> None:
    """Extract searchable text from a Media Library file and store it.

    audio/video → transcript (Whisper/ffmpeg pipeline); everything else →
    document text extraction (reuses the GPT knowledge extractor)."""
    col = get_collection("media_library")
    local_path = None
    try:
        tmp_dir = tempfile.gettempdir()
        local_path = os.path.join(tmp_dir, f"medialib_{media_id}_{os.path.basename(filename)}")
        loop = asyncio.get_event_loop()
        downloaded = await loop.run_in_executor(None, download_file_from_s3, s3_key, local_path)
        if not downloaded:
            raise RuntimeError("Could not download file from S3 for indexing")

        if media_type in ("audio", "video"):
            from app.services.transcription_service import transcribe_media_file
            text = await transcribe_media_file(local_path)
            empty_status = "no_speech"
        else:
            # PDFs, Word, Excel, txt, csv — same extractor the Support Engine uses.
            from app.services.gpt_service import extract_text_from_file
            result = await extract_text_from_file(local_path, filename)
            text = (result or {}).get("text", "") or ""
            empty_status = "no_text"

        text = (text or "").strip()[:MAX_CONTENT_CHARS]
        await col.update_one(
            {"_id": ObjectId(media_id)},
            {"$set": {
                "content_text": text,
                "content_status": "completed" if text else empty_status,
                "indexed_at": datetime.utcnow(),
            }},
        )
        print(f"[media:{media_id}] indexed {len(text)} chars from {filename}")

        # Vector chunks for semantic search inside the file.
        media_doc = await col.find_one({"_id": ObjectId(media_id)})
        if media_doc:
            await _reindex_media_chunks(media_doc, text)
    except Exception as e:  # noqa: BLE001 — record and move on; never fail silently
        print(f"[media:{media_id}] indexing error: {e}")
        await col.update_one(
            {"_id": ObjectId(media_id)},
            {"$set": {"content_status": "failed", "content_error": str(e)}},
        )
    finally:
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception:
                pass
