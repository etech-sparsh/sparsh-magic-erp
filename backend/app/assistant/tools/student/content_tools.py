"""Student content tool: get_session_content (resources/materials in sessions)."""
from __future__ import annotations

from typing import Optional

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.tools.registry import tool
from app.assistant.tools.student.session_tools import SESSION_COLLECTIONS
from app.db.mongodb import get_collection


@tool(
    name="get_session_content",
    description=(
        "List the learning materials/resources (videos, audio, PDFs) attached to "
        "the current user's sessions. Optionally filter by a topic or session-title "
        "keyword. Use for 'what materials do I have', 'show me the videos', "
        "'what content is in the leadership session', 'my learning resources'."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={
        "topic": {"type": "string", "description": "Optional keyword to filter by session title or resource name"},
        "limit": {"type": "integer", "description": "Max resources to return (default 20)"},
    },
)
async def get_session_content(
    ctx: UserContext, topic: Optional[str] = None, limit: int = 20
) -> ToolResult:
    # Personal scope: only sessions the caller is assigned to or coaches.
    query = {"$or": [{"assigned_member_ids": ctx.user_id}, {"coach_ids": ctx.user_id}]}
    needle = (topic or "").strip().lower()
    limit = max(1, min(int(limit or 20), 50))

    items = []
    for col_name in SESSION_COLLECTIONS:
        docs = await get_collection(col_name).find(query).to_list(200)
        for s in docs:
            session_title = s.get("title") or ""
            for r in s.get("resources") or []:
                name = r.get("name") or ""
                if needle and needle not in f"{session_title} {name}".lower():
                    continue
                items.append({
                    "session": session_title,
                    "name": name,
                    "file_type": r.get("file_type") or r.get("system_type"),
                    "url": r.get("url"),
                    "status": r.get("status"),
                })

    items = items[:limit]
    return ToolResult.ok(
        "get_session_content",
        items,
        sources=SESSION_COLLECTIONS,
        count=len(items),
        scope_applied=f"personal:{ctx.user_id}",
    )
