from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from typing import List, Optional
from datetime import datetime
from bson import ObjectId
import functools
import asyncio
import os

from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user
from app.services.s3_service import (
    upload_file_to_s3_with_key,
    get_signed_url,
    delete_file_from_s3,
)

router = APIRouter(prefix="/media", tags=["Media Library"])

# Roles allowed to manage the shared media library (the "staff side").
STAFF_ROLES = ["superadmin", "admin", "coach", "staff"]

ALLOWED_TYPES = ["video", "audio", "pdf", "document", "image", "other"]

MEDIA_TYPE_FILE_RULES = {
    "image": {
        "extensions": {"jpg", "jpeg", "png", "gif", "webp"},
        "mime_types": {"image/jpeg", "image/png", "image/gif", "image/webp"},
        "mime_prefix": "image/",
    },
    "video": {
        "extensions": {"mp4", "mov", "avi", "mkv", "webm"},
        "mime_types": {
            "video/mp4",
            "video/quicktime",
            "video/x-msvideo",
            "video/avi",
            "video/msvideo",
            "video/x-matroska",
            "application/x-matroska",
            "video/webm",
        },
        "mime_prefix": "video/",
    },
    "audio": {
        "extensions": {"mp3", "wav", "aac", "ogg", "m4a", "flac"},
        "mime_types": {
            "audio/mpeg",
            "audio/mp3",
            "audio/wav",
            "audio/x-wav",
            "audio/aac",
            "audio/aacp",
            "audio/x-aac",
            "audio/ogg",
            "application/ogg",
            # .m4a — browsers report it inconsistently across these three:
            "audio/x-m4a",
            "audio/m4a",
            "audio/mp4",
            "audio/flac",
            "audio/x-flac",
        },
        "mime_prefix": "audio/",
    },
    "document": {
        "extensions": {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt"},
        "mime_types": {
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "text/plain",
        },
    },
    "pdf": {
        "extensions": {"pdf"},
        "mime_types": {"application/pdf"},
    },
}


def validate_media_file_type(media_type: str, filename: str, content_type: str) -> None:
    normalized_type = (media_type or "").lower().strip()
    if normalized_type == "other":
        return

    rules = MEDIA_TYPE_FILE_RULES.get(normalized_type)
    if not rules:
        raise HTTPException(
            status_code=400,
            detail="Please select Image, Video, Audio, or Document before uploading.",
        )

    extension = os.path.splitext(filename or "")[1].lower().lstrip(".")
    normalized_mime = (content_type or "").lower().strip()

    # The extension is authoritative. The MIME type only blocks when the browser
    # actually sent a meaningful one that contradicts the category — browsers
    # report types like .m4a inconsistently (audio/x-m4a, audio/mp4, or nothing
    # at all on Windows), so requiring an exact MIME match rejects valid files.
    mime_ok = (
        not normalized_mime
        or normalized_mime == "application/octet-stream"
        or normalized_mime in rules["mime_types"]
        or (rules.get("mime_prefix") and normalized_mime.startswith(rules["mime_prefix"]))
    )

    if extension not in rules["extensions"] or not mime_ok:
        allowed = ", ".join(sorted(rules["extensions"]))
        raise HTTPException(
            status_code=400,
            detail=f"{filename} is not a valid {normalized_type} file. Allowed extensions: {allowed}.",
        )


def _serialize(doc: dict, with_url: bool = True) -> dict:
    doc["_id"] = str(doc["_id"])
    if with_url and doc.get("s3_key"):
        # Signed URLs expire, so generate a fresh one each time we hand a record out.
        doc["url"] = get_signed_url(doc["s3_key"])
    return doc


@router.post("")
async def upload_media(
    background_tasks: BackgroundTasks,
    media_type: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    folder: Optional[str] = Form("/"),
    tags: Optional[str] = Form(""),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    if current_user.get("role") not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to upload media")

    media_type = (media_type or "other").lower().strip()
    validate_media_file_type(media_type, file.filename, file.content_type or "")

    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    # Stream the upload to S3 off the event loop (boto3 is blocking).
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            functools.partial(
                upload_file_to_s3_with_key,
                file.file,
                file.filename,
                file.content_type or "application/octet-stream",
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    # UploadFile exposes size after read; fall back to spooled file position.
    try:
        size = file.size or 0
    except Exception:
        size = 0

    doc = {
        "media_type": media_type,
        "name": name.strip(),
        "description": (description or "").strip(),
        "file_name": file.filename,
        "content_type": file.content_type or "",
        "size": size,
        "s3_key": result["key"],
        "uploaded_by": str(current_user["_id"]),
        "created_at": datetime.utcnow(),
        "folder": (folder or "/").strip(),
        "tags": [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else []
    }

    from app.services.media_index_service import index_media_library_item, INDEXABLE_TYPES
    if media_type in INDEXABLE_TYPES:
        doc["content_status"] = "processing"

    col = get_collection("media_library")
    res = await col.insert_one(doc)
    doc["_id"] = res.inserted_id

    # Extract the file's searchable text (document text or audio/video transcript)
    # in the background so the assistant can answer questions about its contents.
    if media_type in INDEXABLE_TYPES:
        background_tasks.add_task(
            index_media_library_item, str(res.inserted_id), result["key"],
            file.filename or "media", media_type,
        )

    serialized = _serialize(doc, with_url=False)
    serialized["url"] = result["url"]
    return {"message": "File uploaded successfully", "media": serialized}


@router.get("")
async def list_media(
    media_type: Optional[str] = None,
    include_url: bool = True,
    current_user: dict = Depends(get_current_user),
):
    col = get_collection("media_library")
    query = {}
    if media_type and media_type.lower() != "all":
        mt = media_type.lower()
        if mt in ["pdf", "document"]:
            query["media_type"] = {"$in": ["pdf", "document"]}
        elif mt in ["excel", "doc"]:
            query["media_type"] = {"$in": ["document", "pdf", "other"]}
        else:
            query["media_type"] = mt

    items = await col.find(query).sort("created_at", -1).to_list(500)
    return [_serialize(i, with_url=include_url) for i in items]


@router.get("/{media_id}")
async def get_media(media_id: str, current_user: dict = Depends(get_current_user)):
    col = get_collection("media_library")
    doc = await col.find_one({"_id": ObjectId(media_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Media not found")
    return _serialize(doc)


@router.delete("/{media_id}")
async def delete_media(media_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to delete media")

    col = get_collection("media_library")
    doc = await col.find_one({"_id": ObjectId(media_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Media not found")

    if doc.get("s3_key"):
        delete_file_from_s3(doc["s3_key"])

    await col.delete_one({"_id": ObjectId(media_id)})
    # Cascade: drop the file's vector chunks so deleted content isn't retrievable.
    from app.assistant.config import config as _assistant_config
    await get_collection(_assistant_config.MEDIA_CHUNK_COLLECTION).delete_many(
        {"media_id": media_id}
    )
    return {"message": "Media deleted successfully"}
