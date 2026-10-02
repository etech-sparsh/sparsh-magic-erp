"""Move files written by the local upload fallback into S3, and repoint the records at them.

While `LOCAL_UPLOAD_FALLBACK` was on, uploads that S3 refused were written to this server's
disk under keys beginning `local/`. Those files are personal data on an unreplicated box.
This script is how they stop being that.

For every record still holding a `local/` key: read the file from disk, put it in S3, write
the new key back to the record, and (with --delete-local) remove the disk copy.

-- --report first ---------------------------------------------------------------------------
`--report` counts what is outstanding and touches nothing. Run it to see whether the fallback
was ever used at all -- on a system where S3 never failed, the answer is zero and there is
nothing to do.

-- Nothing moves until S3 is actually working -------------------------------------------------
The script uploads one probe object before it touches any record. If that fails, it stops,
because a run that "migrates" a hundred records into a bucket that is still rejecting writes
would repoint them at keys holding nothing.

-- Order of operations ---------------------------------------------------------------------
Upload, then repoint, then (optionally) delete. A crash between steps leaves the record
pointing at a file that still exists -- the safe direction. Re-running is harmless: a record
already carrying an S3 key is not selected.

Usage (from backend/):
    python scripts/migrate_local_uploads_to_s3.py --report
    python scripts/migrate_local_uploads_to_s3.py --apply
    python scripts/migrate_local_uploads_to_s3.py --apply --delete-local
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# (collection, dotted field holding the key). Every place an upload key comes to rest.
# `hrms_candidates` holds three, because the public application form accepts three files.
TARGETS = [
    ("hrms_candidates",  "resume.key"),
    ("hrms_candidates",  "photo.key"),
    ("hrms_documents",   "s3_key"),
    ("hrms_assessments", "response_attachments.key"),
    ("hrms_onboarding",  "kyc_documents.key"),
    ("media",            "s3_key"),
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate locally-stored uploads into S3.")
    parser.add_argument("--report", action="store_true",
                        help="Count what is outstanding and exit. Writes nothing.")
    parser.add_argument("--apply", action="store_true",
                        help="Upload to S3 and repoint the records.")
    parser.add_argument("--delete-local", action="store_true",
                        help="With --apply, delete each disk copy once S3 holds it.")
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()
    if not args.report and not args.apply:
        print("Nothing to do: pass --report to look, or --apply to migrate.")
        return 0

    from app.db.mongodb import connect_to_mongo, close_mongo_connection, get_collection
    from app.services import local_upload_store as local_store
    from app.services.s3_service import upload_file_to_s3_with_key

    await connect_to_mongo()
    try:
        found = []
        for collection, field in TARGETS:
            rows = await get_collection(collection).find(
                {field: {"$regex": f"^{local_store.LOCAL_KEY_PREFIX}"}}
            ).to_list(10000)
            for row in rows:
                found.append((collection, field, row))

        print()
        print("=" * 72)
        print("  Local uploads awaiting migration to S3")
        print("=" * 72)
        if not found:
            print("  Nothing outstanding. The local fallback holds no live records.")
            print()
            print("  You can now switch LOCAL_UPLOAD_FALLBACK off and delete")
            print("  app/routes/local_files.py, app/services/local_upload_store.py")
            print("  and this script.")
            return 0

        by_collection = {}
        for collection, field, _row in found:
            by_collection[f"{collection}.{field}"] = by_collection.get(
                f"{collection}.{field}", 0) + 1
        for where in sorted(by_collection):
            print(f"  {where:<40} {by_collection[where]}")
        print(f"\n  total: {len(found)}")
        print(f"  disk : {local_store.storage_root()}")
        print()

        if args.report:
            print("REPORT ONLY — nothing was written.")
            return 0

        # Prove S3 accepts writes before repointing anything at it.
        try:
            upload_file_to_s3_with_key(io.BytesIO(b"probe"), "migration_probe.txt",
                                       "text/plain")
        except Exception as e:
            print(f"ABORTED: S3 is still not accepting uploads ({type(e).__name__}: {e}).")
            print("Fix the credentials first — migrating now would repoint records at "
                  "keys holding nothing.")
            return 2

        migrated, missing, failed = 0, 0, 0
        for collection, field, row in found:
            key = row
            for part in field.split("."):
                key = (key or {}).get(part) if isinstance(key, dict) else None
            if not isinstance(key, str) or not local_store.is_local_key(key):
                continue

            if not local_store.exists(key):
                print(f"  MISSING ON DISK  {collection} {row.get('_id')}  {key}")
                missing += 1
                continue

            original = key.split("/", 1)[-1]
            original = original.split("_", 1)[-1] if "_" in original else original
            try:
                data = local_store.read(key)
                result = upload_file_to_s3_with_key(
                    io.BytesIO(data), original, "application/octet-stream")
                new_key = result.get("key")
                if not new_key or local_store.is_local_key(new_key):
                    raise RuntimeError("upload did not return an S3 key")
                await get_collection(collection).update_one(
                    {"_id": row["_id"]}, {"$set": {field: new_key}})
                migrated += 1
                if args.delete_local:
                    local_store.delete(key)
            except Exception as e:
                print(f"  FAILED  {collection} {row.get('_id')}  {key}: {e}")
                failed += 1

        print()
        print(f"  migrated : {migrated}")
        if missing:
            print(f"  missing  : {missing}  (record kept its local key — investigate)")
        if failed:
            print(f"  failed   : {failed}  (re-run to retry)")
        if migrated and not args.delete_local:
            print("\n  Disk copies were kept. Re-run with --delete-local once you have "
                  "confirmed the files open from S3.")
        return 0 if not failed else 1
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
