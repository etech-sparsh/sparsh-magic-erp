"""Superadmin (SA) org-wide Calendar tool.

`get_my_sessions` (student_tools) returns only the CALLER's own sessions — the
ones where they are an assigned member or coach. That covers the personal
"what's on my schedule" question for every role, but not the org-wide
"what sessions are scheduled this week across the whole platform" view a
superadmin needs.

`list_sessions` fills that gap: it reads every calendar collection
(STAFF_CALENDER, LEARNER_CALENDER, calendar_events) WITHOUT a personal filter,
with optional date-range / batch / company / status / session-type filters. It
is `allowed_roles=["SA"]` — org-wide reads stay superadmin-only, consistent with
the other Tier-1 org tools; admins/coaches/learners keep using get_my_sessions
for their own schedule.
"""
from __future__ import annotations

import re
from typing import Optional

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.tools.registry import tool
from app.assistant.utils.serializers import serialize
from app.db.mongodb import get_collection
from app.utils.calendar_utils import CALENDAR_COLLECTIONS

# Sessions span three collections (STAFF_CALENDER, LEARNER_CALENDER, calendar_events).
SESSION_COLLECTIONS = CALENDAR_COLLECTIONS + ["calendar_events"]

# Org-wide view: include batch/company so a superadmin can see which programme
# and client each session belongs to. No PII (no attendee emails/phones).
_SESSION_FIELDS = [
    "title", "type", "start", "end", "status", "session_type",
    "batch_id", "quarter_id", "company_id", "meeting_link", "priority",
    "additional_details",
]


def _safe_regex(text: str) -> dict:
    """Case-insensitive Mongo regex from user text, metacharacters escaped."""
    return {"$regex": re.escape(text.strip()), "$options": "i"}


def _clamp(value, default: int, maximum: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n or default, maximum))


@tool(
    name="list_sessions",
    description=(
        "List scheduled COACHING SESSIONS / calendar events across the WHOLE "
        "platform (not just the caller's own) — title, type, date/time, status, "
        "and the batch and company each belongs to. Superadmin only. Use for "
        "'what sessions are scheduled this week', 'show all upcoming sessions', "
        "'which sessions does batch X have', 'how many sessions are completed'. "
        "Filter by date range (ISO YYYY-MM-DD), batch, company, status, or "
        "session type. By DEFAULT it returns coaching sessions only and EXCLUDES "
        "personal to-do / task calendar entries (set include_tasks=true to include "
        "them). For a user's OWN schedule use get_my_sessions instead."
    ),
    allowed_roles=["SA"],
    parameters={
        "from_date": {"type": "string", "description": "Inclusive ISO lower bound, e.g. 2026-06-01"},
        "to_date": {"type": "string", "description": "Inclusive ISO upper bound, e.g. 2026-06-30"},
        "batch_id": {"type": "string", "description": "Optional batch id filter"},
        "company_id": {"type": "string", "description": "Optional company id filter"},
        "status": {"type": "string", "description": "Optional status filter, e.g. scheduled, completed, cancelled"},
        "session_type": {"type": "string", "description": "Optional session-type keyword filter"},
        "include_tasks": {
            "type": "boolean",
            "description": "Include personal to-do/task entries too (default false — sessions only).",
        },
        "limit": {"type": "integer", "description": "Max sessions to return (default 30, max 100)"},
    },
)
async def list_sessions(
    ctx: UserContext,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    batch_id: Optional[str] = None,
    company_id: Optional[str] = None,
    status: Optional[str] = None,
    session_type: Optional[str] = None,
    include_tasks: bool = False,
    limit: int = 30,
) -> ToolResult:
    limit = _clamp(limit, 30, 100)

    query: dict = {}
    if from_date or to_date:
        bound: dict = {}
        if from_date:
            bound["$gte"] = from_date
        if to_date:
            bound["$lte"] = to_date
        query["start"] = bound
    if batch_id and batch_id.strip():
        query["batch_id"] = batch_id.strip()
    if company_id and company_id.strip():
        query["company_id"] = company_id.strip()
    if status and status.strip():
        query["status"] = status.strip().lower()
    if session_type and session_type.strip():
        query["session_type"] = _safe_regex(session_type)
    # Calendar entries with type=="task" are personal to-dos, not coaching
    # sessions. Exclude them by default so "what sessions are scheduled" returns
    # real sessions instead of the team's task list.
    if not include_tasks:
        query["type"] = {"$ne": "task"}

    sessions = []
    tasks_hidden = 0
    for col_name in SESSION_COLLECTIONS:
        col = get_collection(col_name)
        docs = await col.find(query).sort("start", 1).to_list(limit)
        sessions.extend(serialize(d, _SESSION_FIELDS) for d in docs)
        if not include_tasks:
            task_q = {**query, "type": "task"}  # same filters, count the to-dos we skipped
            tasks_hidden += await col.count_documents(task_q)

    sessions.sort(key=lambda s: s.get("start") or "")
    sessions = sessions[:limit]

    data = {"sessions": sessions, "total_returned": len(sessions)}
    if not include_tasks and tasks_hidden:
        data["tasks_excluded"] = tasks_hidden
        data["note"] = (
            f"{tasks_hidden} personal to-do/task entr"
            f"{'y' if tasks_hidden == 1 else 'ies'} were excluded "
            f"(set include_tasks=true to see them)."
        )

    return ToolResult.ok(
        "list_sessions",
        data,
        sources=SESSION_COLLECTIONS,
        count=len(sessions),
        scope_applied="global",
    )
