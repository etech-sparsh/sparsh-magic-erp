"""
TPMS ▸ task uploads (proof-of-work files).

Port of uploadTaskFile / getTaskUploads (`copy_of calender/code.js:606 / 592`).

Storage moves from Google Drive to the ERP's existing S3 service. We persist the S3 KEY
and mint a fresh signed URL on every read — signed URLs expire, so storing one (as the
older learner-upload path does) leaves dead links behind.

Uploads are only meaningful for activities flagged `upload_required` in the catalogue.
The file is tagged with the activity's scope so the Implementation Tracker can group
company-wise vs HOD-wise proof correctly.
"""
import io
import logging
import re
from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException, UploadFile

from app.db.mongodb import get_collection
from app.models.tpms import COLL_TASK_UPLOADS, UPLOAD_MAX_BYTES, period_from_date
from app.services.s3_service import get_signed_url, upload_file_to_s3_with_key

logger = logging.getLogger(__name__)

CLIENT_ROLES = {"clientadmin", "clientuser"}


def _sanitize_name(name: str) -> str:
    """Strip path separators and anything else that could break a storage key, collapse
    whitespace, and keep the result to a sane length (spec §12)."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "")).strip("-.")
    return (cleaned or "file")[:180]


def _display_name(user: dict) -> str:
    return (user.get("full_name")
            or " ".join(filter(None, [user.get("first_name"), user.get("last_name")])).strip()
            or user.get("email") or "Unknown")


async def upload_task_file(user: dict, event_id: str, file: UploadFile) -> dict:
    from app.services.tpms_lifecycle_service import find_tpms_event
    doc, _coll = await find_tpms_event(event_id)

    # Client-side users may only attach to their own company's activities.
    if (user.get("role") or "").lower() in CLIENT_ROLES:
        if str(doc.get("company_id") or "") != str(user.get("company_id") or ""):
            raise HTTPException(status_code=403, detail="Not your company activity.")

    # Uploads are only accepted for activities flagged `upload_required` in the catalogue.
    meta = doc.get("activity_meta") or {}
    if not meta.get("upload_required"):
        raise HTTPException(status_code=400,
                            detail="This activity does not require a file upload.")

    payload = await file.read()
    if len(payload) > UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Max file size 25 MB")
    if not payload:
        raise HTTPException(status_code=400, detail="Choose a file first")

    day = str(doc.get("start") or "")[:10]
    period = period_from_date(day)
    # Spec §12 — {Activity}_{CompanyID}_{Month}_{timestamp}_{originalName}, sanitised of
    # path-breaking characters. The timestamp is what stops a second upload of the same
    # filename to the same activity from overwriting the first.
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    stored_name = _sanitize_name(
        f"{doc.get('activity') or 'Activity'}_{doc.get('company_id') or ''}"
        f"_{period or 'na'}_{stamp}_{file.filename or 'file'}"
    )
    try:
        stored = upload_file_to_s3_with_key(
            io.BytesIO(payload),
            f"tpms/{event_id}/{stored_name}",
            file.content_type or "application/octet-stream",
        )
    except Exception as e:
        logger.error(f"TPMS upload to S3 failed for event {event_id}: {e}")
        raise HTTPException(status_code=502, detail="Upload failed. Please try again.")

    record = {
        "event_id": str(event_id),
        "company_id": str(doc.get("company_id") or ""),
        "company_name": doc.get("company_name"),
        "activity": doc.get("activity"),
        "scope": meta.get("scope"),
        "period": period_from_date(day),
        "member_id": str(user.get("_id")),
        "member_name": _display_name(user),
        "file_name": file.filename,
        "size": len(payload),
        "s3_key": stored["key"],
        "uploaded_by": str(user.get("_id")),
        "uploaded_by_name": _display_name(user),
        "uploaded_at": datetime.utcnow(),
    }
    res = await get_collection(COLL_TASK_UPLOADS).insert_one(record)
    record["_id"] = str(res.inserted_id)
    record["url"] = stored["url"]
    return record


async def list_task_uploads(user: dict, event_id: Optional[str] = None,
                            company_id: Optional[str] = None,
                            period: Optional[str] = None) -> List[dict]:
    """Files for one activity, or for a company+period (the Implementation Tracker view).
    Signed URLs are regenerated on every read."""
    query: dict = {}
    if event_id:
        query["event_id"] = str(event_id)
    if company_id:
        query["company_id"] = str(company_id)
    if period:
        query["period"] = period
    if (user.get("role") or "").lower() in CLIENT_ROLES:
        query["company_id"] = str(user.get("company_id") or "")
    if not query:
        raise HTTPException(status_code=400, detail="event_id or company_id is required")

    docs = await get_collection(COLL_TASK_UPLOADS).find(query).to_list(1000)
    docs.sort(key=lambda d: d.get("uploaded_at") or datetime.min, reverse=True)
    for d in docs:
        d["_id"] = str(d["_id"])
        try:
            d["url"] = get_signed_url(d["s3_key"]) if d.get("s3_key") else None
        except Exception:
            d["url"] = None
    return docs
