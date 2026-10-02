"""Conversation persistence contracts."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.assistant.schemas.chat import ChatMessage


class ConversationSummary(BaseModel):
    """Lightweight item for listing a user's conversations."""

    id: str
    title: str
    updated_at: datetime


class Conversation(BaseModel):
    id: Optional[str] = None
    user_id: str
    title: Optional[str] = None
    messages: List[ChatMessage] = Field(default_factory=list)
    summary: Optional[str] = None            # rolling summary of older turns
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
