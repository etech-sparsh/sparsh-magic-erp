"""Student session tool: get_my_sessions."""
from __future__ import annotations

from typing import Optional

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.tools.registry import tool
from app.assistant.utils.serializers import serialize
from app.db.mongodb import get_collection
from app.utils.calendar_utils import CALENDAR_COLLECTIONS

# Sessions span three collections (STAFF_CALENDER, LEARNER_CALENDER, calendar_events).
SESSION_COLLECTIONS = CALENDAR_COLLECTIONS + ["calendar_events"]

SESSION_FIELDS = [
    "title", "type", "start", "end", "status", "session_type",
    "batch_id", "quarter_id", "meeting_link", "priority", "additional_details",
]


@tool(
    name="get_my_sessions",
    description=(
        "Get the current user's own sessions/events (optionally within a date "
        "range). Use for 'what sessions do I have', 'my schedule next week', "
        "'upcoming classes'. Dates are ISO strings (YYYY-MM-DD)."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={
        "from_date": {"type": "string", "description": "Inclusive ISO lower bound, e.g. 2026-06-01"},
        "to_date": {"type": "string", "description": "Inclusive ISO upper bound, e.g. 2026-06-30"},
        "limit": {"type": "integer", "description": "Max sessions to return (default 20)"},
    },
)
async def get_my_sessions(
    ctx: UserContext,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 20,
) -> ToolResult:
    # Personal scope by construction: only sessions where the caller is an
    # assigned member or a coach. This binds to the user regardless of role.
    query: dict = {
        "$or": [
            {"assigned_member_ids": ctx.user_id},
            {"coach_ids": ctx.user_id},
        ]
    }
    if from_date or to_date:
        bound: dict = {}
        if from_date:
            bound["$gte"] = from_date
        if to_date:
            bound["$lte"] = to_date
        query["start"] = bound

    limit = max(1, min(int(limit or 20), 50))
    sessions = []
    for col_name in SESSION_COLLECTIONS:
        docs = await get_collection(col_name).find(query).sort("start", 1).to_list(limit)
        sessions.extend(serialize(d, SESSION_FIELDS) for d in docs)

    sessions.sort(key=lambda s: s.get("start") or "")
    sessions = sessions[:limit]

    return ToolResult.ok(
        "get_my_sessions",
        sessions,
        sources=SESSION_COLLECTIONS,
        scope_applied=f"personal:{ctx.user_id}",
    )
