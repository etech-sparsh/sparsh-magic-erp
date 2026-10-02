from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class MediaAssetResponse(BaseModel):
    """A single uploaded file in the shared media library. Other features
    reference these by `id` rather than re-uploading the file."""
    id: str = Field(alias="_id")
    media_type: str          # category chosen by staff: video, audio, pdf, document, image, other
    name: str
    description: Optional[str] = ""
    file_name: str           # original uploaded filename
    content_type: Optional[str] = ""  # MIME type reported by the browser
    size: Optional[int] = 0  # bytes
    s3_key: str              # persistent S3 object key (regenerate signed URLs from this)
    url: Optional[str] = ""  # freshly signed, temporary download URL
    uploaded_by: Optional[str] = ""
    created_at: datetime

    class Config:
        populate_by_name = True
