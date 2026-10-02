"""Request/response contracts for the chat endpoint."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None    # None → start a new conversation
    stream: bool = False                     # streaming enabled in Phase 2
    # Index of a prior user message being edited; the stored conversation is
    # truncated to before it so the assistant answers the revised question
    # instead of replaying stale history. None → normal append.
    edit_from_index: Optional[int] = None
    # IDs of previously-uploaded, fully-processed attachments to include as
    # context for this turn (multi-modal upload). None/empty → text-only turn.
    attachment_ids: Optional[List[str]] = None


class ExportPdfRequest(BaseModel):
    """Optional body for the PDF export endpoint. `user_message` is the request
    text the user typed (e.g. "is chat ka PDF bana do"), persisted so the export
    turn survives a page reload."""

    user_message: Optional[str] = None


class ToolAttribution(BaseModel):
    """Which tool produced data backing an assistant turn (persisted per turn)."""

    tool: str
    sources: List[str] = Field(default_factory=list)
    scope_applied: Optional[str] = None
    success: bool = True
    count: Optional[int] = None


class AttachmentMeta(BaseModel):
    """Compact attachment descriptor persisted on a user turn and returned to the
    UI so past messages can re-render their file chips (icon, name, download)."""

    id: str
    filename: str
    mime_type: Optional[str] = None
    size: Optional[int] = None
    kind: Optional[str] = None               # document|image|audio|video|code|archive|other


class ChatMessage(BaseModel):
    role: str                                # user | assistant | tool | system
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tool_calls: Optional[list] = None        # retained for transparency/debugging
    attributions: Optional[List[ToolAttribution]] = None   # set on assistant turns
    attachments: Optional[List[AttachmentMeta]] = None     # set on user turns w/ uploads
    # Marks a generated export turn (e.g. "pdf") so the UI can re-render a
    # download action after a reload instead of a dead in-memory blob URL.
    export_kind: Optional[str] = None


class AttachmentOut(BaseModel):
    """API representation of a stored attachment (status polling + listing)."""

    id: str
    conversation_id: Optional[str] = None
    filename: str
    mime_type: Optional[str] = None
    size: Optional[int] = None
    kind: Optional[str] = None
    status: str                              # uploaded | processing | completed | failed
    summary: Optional[str] = None
    error: Optional[str] = None
    url: Optional[str] = None                # fresh signed/download URL
    created_at: Optional[datetime] = None


class AskResponse(BaseModel):
    conversation_id: str
    answer: str
    sources: List[str] = Field(default_factory=list)
    meta: Dict = Field(default_factory=dict)
