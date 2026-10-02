"""One-time backfill: extract searchable text for Media Library files that were
uploaded before content indexing existed.

For every media_library doc of an indexable type (audio/video/pdf/document) that
has no `content_text` yet, download it from S3, extract its text/transcript, and
save it — so the assistant can answer questions about already-uploaded files too.

Safe to re-run: it skips anything already indexed (content_status == completed).
Run from backend/:  python -m scripts.backfill_media_index
"""
import asyncio

from app.db.mongodb import connect_to_mongo, close_mongo_connection, get_collection
from app.services.media_index_service import index_media_library_item, INDEXABLE_TYPES


async def _connect_with_retry(attempts: int = 20, delay: int = 6) -> bool:
    """Retry the DB connect through flaky/no-primary windows. Returns True once
    a connection is established. The backfill itself is resumable, so even if the
    cluster drops mid-run, re-running continues where it left off."""
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
    if not await _connect_with_retry():
        print("Could not reach a writable primary after retries. The Atlas "
              "cluster is still down/electing — fix cluster health, then re-run.")
        return
    try:
        col = get_collection("media_library")
        query = {
            "media_type": {"$in": list(INDEXABLE_TYPES)},
            "s3_key": {"$exists": True, "$ne": None},
            "content_status": {"$ne": "completed"},
        }
        docs = await col.find(query).to_list(10000)
        print(f"Found {len(docs)} media file(s) needing indexing.")

        done = 0
        for d in docs:
            mid = str(d["_id"])
            name = d.get("file_name") or d.get("name") or "media"
            print(f"  [{done + 1}/{len(docs)}] {name} ({d.get('media_type')}) ...", flush=True)
            # Survive a mid-run cluster flap: on any error (usually a no-primary
            # window), reconnect and retry the SAME file instead of crashing.
            # The file's writes are idempotent (re-index clears its old chunks),
            # so retrying can't duplicate data.
            for attempt in range(4):
                try:
                    await index_media_library_item(mid, d["s3_key"], name, d.get("media_type"))
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"    file errored ({str(e)[:80]}); reconnecting & retrying "
                          f"({attempt + 1}/4)...", flush=True)
                    await _connect_with_retry()
            done += 1

        print(f"Done. Indexed {done} file(s).")
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
