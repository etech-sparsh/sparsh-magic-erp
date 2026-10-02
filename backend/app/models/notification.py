from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Any

class NotificationTemplate(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    name: str  # e.g., "event_creation", "reminder_before"
    slug: str  # e.g., "event-creation-email"
    channel: str  # "email" or "whatsapp"
    subject: Optional[str] = None
    body: str  # Template with placeholders: Hello {{name}}, ...
    variables: List[str] = [] # ["name", "event_title", "time"]
    # WhatsApp Cloud API (Meta) — used when channel == "whatsapp".
    meta_template_name: Optional[str] = None  # name of the Meta-approved template
    meta_lang: Optional[str] = "en"           # template language code
    meta_params: List[str] = []               # context keys mapped to {{1}}, {{2}}, ... in order
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class NotificationLog(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    user_id: str
    target_contact: str # email or phone
    channel: str # "email" or "whatsapp"
    template_slug: str
    content: str # Rendered content
    status: str # "sent", "failed", "pending"
    error_message: Optional[str] = None
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    meta: Optional[Dict[str, Any]] = {}
