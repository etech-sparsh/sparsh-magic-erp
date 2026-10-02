"""Student recommendation tool: recommend_study_plan."""
from __future__ import annotations

from datetime import datetime

from app.assistant.analytics import performance, recommender
from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.services import assessment_service
from app.assistant.tools.registry import tool
from app.assistant.tools.student.session_tools import SESSION_COLLECTIONS, SESSION_FIELDS
from app.assistant.utils.serializers import serialize
from app.db.mongodb import get_collection


@tool(
    name="recommend_study_plan",
    description=(
        "Recommend what the current user should focus on / study next, based on "
        "their weak subjects, performance trend, and upcoming sessions. Use for "
        "'what should I study today', 'what should I focus on'."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={},
)
async def recommend_study_plan(ctx: UserContext) -> ToolResult:
    # Signal 1: performance (weak subjects + trend).
    results = await assessment_service.get_results_for_user(ctx, ctx.user_id, limit=20)
    perf = performance.analyze(results)

    # Signal 2: upcoming sessions (today onward), caller-scoped.
    today = datetime.utcnow().date().isoformat()
    upcoming = []
    query = {
        "$and": [
            {"$or": [{"assigned_member_ids": ctx.user_id}, {"coach_ids": ctx.user_id}]},
            {"start": {"$gte": today}},
        ]
    }
    for col_name in SESSION_COLLECTIONS:
        upcoming.extend(await get_collection(col_name).find(query).to_list(50))
    upcoming.sort(key=lambda s: s.get("start") or "")
    upcoming_clean = [serialize(s, SESSION_FIELDS) for s in upcoming[:5]]

    # Signals 3/4 (pending assignments, attendance) land with their tools — the
    # recommender degrades gracefully without them.
    plan = recommender.build_study_plan(
        ctx.user_id, perf, upcoming_sessions=upcoming_clean
    )
    return ToolResult.ok(
        "recommend_study_plan",
        plan.model_dump(),
        sources=[*assessment_service.SOURCES, *SESSION_COLLECTIONS],
        count=len(plan.recommendations),
        scope_applied=f"personal:{ctx.user_id}",
    )
