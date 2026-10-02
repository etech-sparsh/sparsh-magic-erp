"""Serves files held by the TEMPORARY local upload fallback.

This route is the read half of `services/local_upload_store.py`: when S3 was unavailable and
the fallback was switched on, uploads landed on this server's disk under a `local/` key, and
`get_signed_url` hands out links pointing here instead of at a presigned S3 URL.

-- Why it is unauthenticated ----------------------------------------------------------------
It is not, in the sense that matters. It carries exactly the authorisation an S3 presigned
URL carries: a link that expires and cannot be altered without the signing key. Every caller
that used to hand a browser a presigned URL is doing the same thing here, and the checks that
decide WHO may obtain a link still happen upstream, in the handler that calls
`get_signed_url` behind its own capability gate.

Requiring a session here instead would break the case presigned URLs exist for -- a browser
following a link, an <img> tag, a PDF viewer -- and would not add a check that upstream has
not already made.

-- Deleting this ------------------------------------------------------------------------------
Once `scripts/migrate_local_uploads_to_s3.py --report` shows nothing outstanding, this file,
`services/local_upload_store.py`, the two settings keys and the `include_router` line in
main.py can all go, in any order.
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.services import local_upload_store as local_store

router = APIRouter(prefix="/files", tags=["Local file fallback"])

# Served as an attachment, and never as a type the browser will execute in our origin. The
# store accepts only documents and images, but the header is set from what is actually about
# to be sent rather than from what was promised at upload time.
_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get("/local")
async def get_local_file(
    key: str = Query(...),
    expires: str = Query(...),
    signature: str = Query(...),
):
    """Return one locally-stored file, if the link is signed and unexpired."""
    ok, reason = local_store.verify(key, expires, signature)
    if not ok:
        # One status and one sentence for every rejection. Distinguishing "expired" from
        # "bad signature" in the response would tell somebody guessing at links which half
        # they got right; the specific reason goes to the log instead.
        print(f"[WARN] rejected local file request ({reason}): {key}")
        raise HTTPException(status_code=403, detail="This link is not valid or has expired.")

    if not local_store.exists(key):
        raise HTTPException(status_code=404, detail="That file is no longer available.")

    import os
    name = key.split("/", 1)[-1]
    # Strip the uuid prefix the store added, so a download arrives under the name the
    # person originally uploaded.
    original = name.split("_", 1)[-1] if "_" in name else name
    extension = os.path.splitext(original)[1].lower()

    try:
        data = local_store.read(key)
    except Exception as e:
        print(f"[WARN] could not read local upload {key}: {e}")
        raise HTTPException(status_code=404, detail="That file is no longer available.")

    return Response(
        content=data,
        media_type=_CONTENT_TYPES.get(extension, "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="{original}"',
            # These bytes are personal data behind an expiring link; no shared cache should
            # keep a copy that outlives the signature.
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
