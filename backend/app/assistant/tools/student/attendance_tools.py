"""Student attendance tool: get_my_attendance."""
from __future__ import annotations

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.tools.registry import tool
from app.assistant.utils.serializers import serialize
from app.db.mongodb import get_collection

ATTENDANCE_COLLECTION = "attendance"
ATTENDANCE_FIELDS = ["session_name", "date", "status", "type"]


@tool(
    name="get_my_attendance",
    description=(
        "Get the current user's attendance: an overall present/absent summary "
        "plus their most recent session records. Use for 'what's my attendance', "
        "'how many sessions did I miss', 'was I present last week', 'my attendance rate'."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={
        "limit": {"type": "integer", "description": "Max recent records to list (default 20)"},
    },
)
async def get_my_attendance(ctx: UserContext, limit: int = 20) -> ToolResult:
    # Personal scope: attendance rows are keyed by user_id.
    docs = (
        await get_collection(ATTENDANCE_COLLECTION)
        .find({"user_id": ctx.user_id})
        .sort("date", -1)
        .to_list(500)
    )

    total = len(docs)
    present = sum(1 for d in docs if (d.get("status") or "").lower() == "present")
    absent = sum(1 for d in docs if (d.get("status") or "").lower() == "absent")
    rate = round(present / total * 100, 1) if total else 0.0

    limit = max(1, min(int(limit or 20), 50))
    records = [serialize(d, ATTENDANCE_FIELDS) for d in docs[:limit]]

    data = {
        "summary": {
            "total_marked": total,
            "present": present,
            "absent": absent,
            "attendance_rate_pct": rate,
        },
        "records": records,
    }
    return ToolResult.ok(
        "get_my_attendance",
        data,
        sources=[ATTENDANCE_COLLECTION],
        count=total,
        scope_applied=f"personal:{ctx.user_id}",
    )
