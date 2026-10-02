"""Superadmin (SA) Media Library tool.

Exposes the shared Media Library (collection: media_library) — uploaded videos,
audio, PDFs, documents and images — to the assistant, restricted to
`allowed_roles=["SA"]`. The registry enforces this at both schema-exposure and
execution time, so AD/CA/CU callers never see or run it.

Read-only and metadata-only: it returns file descriptors (name, type, size,
folder, tags, upload date) for browsing/counting in chat. It deliberately does
NOT return S3 keys or signed download URLs — downloads stay in the Media Library
UI. Query mirrors routes/media.py so behaviour stays consistent.
"""
from __future__ import annotations

import re
from typing import Optional

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.tools.registry import tool
from app.db.mongodb import get_collection

_MEDIA_TYPES = {"video", "audio", "pdf", "document", "image", "other"}
_VIEW_FIELDS = ["name", "media_type", "description", "file_name", "folder", "tags"]


def _clamp(limit, default: int, hard_max: int) -> int:
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(limit, hard_max))


def _human_size(num) -> Optional[str]:
    try:
        num = float(num or 0)
    except (TypeError, ValueError):
        return None
    if num <= 0:
        return None
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return None


def _view(doc: dict) -> dict:
    out = {k: doc.get(k) for k in _VIEW_FIELDS}
    out["size"] = _human_size(doc.get("size"))
    created = doc.get("created_at")
    out["uploaded_on"] = created.strftime("%Y-%m-%d") if hasattr(created, "strftime") else created
    return out


@tool(
    name="list_media_library",
    description=(
        "List or search the shared Media Library — uploaded videos, audio, PDFs, "
        "documents and images managed by staff. Superadmin only. Use for 'what's "
        "in the media library', 'how many videos do we have', 'find media about "
        "X', 'list the documents/PDFs'. Optionally filter by media_type or a "
        "search keyword (matches name, description, or tags). Returns file "
        "metadata (name, type, size, folder, tags, upload date) plus a count "
        "breakdown by type — not the files or download links themselves."
    ),
    allowed_roles=["SA"],
    parameters={
        "media_type": {
            "type": "string",
            "enum": ["video", "audio", "pdf", "document", "image", "other"],
            "description": "Optional type filter.",
        },
        "search": {
            "type": "string",
            "description": "Optional keyword to match in name, description, or tags.",
        },
        "limit": {"type": "integer", "description": "Max items to return (default 50, max 200)."},
    },
)
async def list_media_library(
    ctx: UserContext,
    media_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
) -> ToolResult:
    col = get_collection("media_library")

    query: dict = {}
    if media_type:
        mt = media_type.lower().strip()
        if mt not in _MEDIA_TYPES:
            return ToolResult.fail("list_media_library", f"Invalid media_type '{media_type}'.")
        query["media_type"] = mt
    if search and search.strip():
        rx = re.escape(search.strip())
        query["$or"] = [
            {"name": {"$regex": rx, "$options": "i"}},
            {"description": {"$regex": rx, "$options": "i"}},
            {"tags": {"$regex": rx, "$options": "i"}},
        ]

    docs = await col.find(query).sort("created_at", -1).to_list(_clamp(limit, 50, 200))
    items = [_view(d) for d in docs]

    # Whole-library type breakdown (independent of the filter) so counting
    # questions like "how many videos" are always answerable in one call.
    by_type: dict = {}
    async for row in col.aggregate([{"$group": {"_id": "$media_type", "n": {"$sum": 1}}}]):
        by_type[row.get("_id") or "other"] = row["n"]

    data = {
        "items": items,
        "returned": len(items),
        "total_in_library": sum(by_type.values()),
        "by_type": by_type,
    }
    return ToolResult.ok(
        "list_media_library",
        data,
        sources=["media_library"],
        count=len(items),
        scope_applied="global",
    )
