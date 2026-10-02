from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Any
from bson import ObjectId

class ActivityLog(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    user_name: str
    user_email: str
    action: str  # e.g., "created_event", "updated_task", "login"
    module: str  # e.g., "calendar", "auth", "tasks"
    details: Optional[str] = None
    metadata: Optional[dict] = {}
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        json_encoders = {ObjectId: str}

