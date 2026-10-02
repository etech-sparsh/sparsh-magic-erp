"""Backfill embeddings for content that existed before RAG.

For each retrieval collection, embeds the chunks that don't yet have an
`embedding` field. For the Media Library it first builds `media_chunks` from
each file's stored `content_text` (chunked), then embeds them.

Safe + resumable: it only touches docs missing an embedding, so re-running just
finishes whatever was left. Run from backend/:
    python -m scripts.backfill_embeddings           # all collections
    python -m scripts.backfill_embeddings knowledge # one: knowledge|attachments|media
"""
import asyncio
import sys
from datetime import datetime

from bson import ObjectId

from app.assistant.config import config
from app.assistant.rag.embeddings import embed_texts, enabled
from app.db.mongodb import connect_to_mongo, close_mongo_connection, get_collection

BATCH = 100

async def _embed_existing(collection: str, label: str) -> None:
    col = get_collection(collection)
    total = await col.count_documents({"embedding": {"$exists": False}, "content": {"$exists": True}})
    print(f"[{label}] {total} chunk(s) need embeddings...")
    done = 0
    while True:
        docs = await col.find(
            {"embedding": {"$exists": False}, "content": {"$exists": True}}
        ).limit(BATCH).to_list(BATCH)
        if not docs:
            break
        vecs = await embed_texts([d.get("content", "") or "" for d in docs])
        if not vecs or len(vecs) != len(docs):
            print(f"[{label}] embedding batch failed — stopping (re-run to resume).")
            return
        for d, v in zip(docs, vecs):
            await col.update_one({"_id": d["_id"]}, {"$set": {"embedding": v}})
        done += len(docs)
        print(f"[{label}] {done}/{total}", flush=True)
    print(f"[{label}] done.")


async def _build_media_chunks() -> None:
    """Chunk + embed media_library.content_text into media_chunks (for files
    that have extracted text but no chunks yet)."""
    from app.services.gpt_service import chunk_text

    media_col = get_collection("media_library")
    chunk_col = get_collection(config.MEDIA_CHUNK_COLLECTION)
    files = await media_col.find(
        {"content_text": {"$exists": True, "$ne": ""}}
    ).to_list(10000)
    print(f"[media] {len(files)} file(s) with text...")
    for f in files:
        mid = str(f["_id"])
        if await chunk_col.count_documents({"media_id": mid}, limit=1):
            continue  # already chunked
        pieces = chunk_text(f.get("content_text") or "", chunk_size=250, overlap=40)
        if not pieces:
            continue
        vecs = await embed_texts(pieces)
        docs = []
        for i, p in enumerate(pieces):
            doc = {
                "media_id": mid, "name": f.get("name"), "file_name": f.get("file_name"),
                "media_type": f.get("media_type"), "content": p, "created_at": datetime.utcnow(),
            }
            if vecs and len(vecs) == len(pieces):
                doc["embedding"] = vecs[i]
            docs.append(doc)
        await chunk_col.insert_many(docs)
        print(f"[media] {f.get('file_name')}: {len(docs)} chunk(s)", flush=True)
    print("[media] done.")


async def _connect_with_retry(attempts: int = 20, delay: int = 6) -> bool:
    """Retry the DB connect through flaky/no-primary windows (resumable run)."""
    from app.db.mongodb import db_connection
    for i in range(attempts):
        await connect_to_mongo()
        if db_connection.db is not None:
            return True
        print(f"  DB not ready (attempt {i + 1}/{attempts}) — cluster has no "
              f"primary; retrying in {delay}s...", flush=True)
        await asyncio.sleep(delay)
    return False


async def main() -> None:
    if not enabled():
        print("RAG_VECTOR_ENABLED is off or OPENAI_API_KEY missing — nothing to do.")
        return
    which = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    if not await _connect_with_retry():
        print("Could not reach a writable primary after retries. The Atlas "
              "cluster is still down/electing — fix cluster health, then re-run.")
        return
    try:
        if which in ("all", "knowledge"):
            await _embed_existing("KnowledgeBase", "knowledge")
        if which in ("all", "attachments"):
            await _embed_existing(config.ATTACHMENT_CHUNK_COLLECTION, "attachments")
        if which in ("all", "media"):
            await _build_media_chunks()
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
