from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from typing import List, Optional
from datetime import datetime
import asyncio
import functools
import json

from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user
from app.routes.media import STAFF_ROLES, _serialize, validate_media_file_type
from app.services.s3_service import (
    create_multipart_upload,
    upload_part,
    complete_multipart_upload,
    abort_multipart_upload
)

router = APIRouter(prefix="/media/chunk", tags=["Media Chunk Uploads"])

@router.post("/start")
async def start_chunked_upload(
    filename: str = Form(...),
    content_type: str = Form(...),
    media_type: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user)
):
    """Start a multipart S3 upload for large files."""
    if current_user.get("role") not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to upload media")

    if media_type is not None:
        validate_media_file_type(media_type, filename, content_type)
        
    try:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            None,
            functools.partial(create_multipart_upload, filename, content_type),
        )
        return {"upload_id": res["upload_id"], "key": res["key"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload")
async def upload_file_chunk(
    upload_id: str = Form(...),
    key: str = Form(...),
    part_number: int = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """Upload a single chunk."""
    if current_user.get("role") not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    try:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            None,
            functools.partial(upload_part, key, upload_id, part_number, file.file),
        )
        return {"ETag": res["ETag"], "PartNumber": res["PartNumber"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/complete")
async def complete_chunked_upload(
    background_tasks: BackgroundTasks,
    upload_id: str = Form(...),
    key: str = Form(...),
    parts: str = Form(...), # JSON string of [{"ETag": "...", "PartNumber": 1}, ...]
    media_type: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    folder: str = Form("/"),
    tags: str = Form(""),
    size: int = Form(...),
    original_filename: str = Form(...),
    content_type: str = Form(""),
    current_user: dict = Depends(get_current_user)
):
    """Complete multipart upload and save to MongoDB."""
    if current_user.get("role") not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    try:
        media_type = (media_type or "other").lower().strip()
        validate_media_file_type(media_type, original_filename, content_type)

        parts_list = json.loads(parts)
        loop = asyncio.get_running_loop()
        s3_res = await loop.run_in_executor(
            None,
            functools.partial(complete_multipart_upload, key, upload_id, parts_list),
        )

        # Save to DB
            
        doc = {
            "media_type": media_type,
            "name": name.strip(),
            "description": (description or "").strip(),
            "file_name": original_filename,
            "content_type": content_type,
            "size": size,
            "s3_key": s3_res["key"],
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

        # Extract searchable text (document text or audio/video transcript) in the
        # background so the assistant can answer questions about the file contents.
        if media_type in INDEXABLE_TYPES:
            background_tasks.add_task(
                index_media_library_item, str(res.inserted_id), s3_res["key"],
                original_filename or "media", media_type,
            )

        serialized = _serialize(doc, with_url=False)
        serialized["url"] = s3_res["url"]
        return {"message": "File uploaded successfully", "media": serialized}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/abort")
async def abort_chunked_upload(
    upload_id: str = Form(...),
    key: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """Abort a multipart upload."""
    if current_user.get("role") not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    loop = asyncio.get_running_loop()
    success = await loop.run_in_executor(
        None,
        functools.partial(abort_multipart_upload, key, upload_id),
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to abort multipart upload")
    return {"message": "Upload aborted successfully"}
