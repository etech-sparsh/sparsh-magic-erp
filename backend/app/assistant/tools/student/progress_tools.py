"""Student progress tool: get_learning_progress."""
from __future__ import annotations

from app.assistant.analytics import progress
from app.assistant.schemas.analytics import AnalyticsMetric, AnalyticsResult
from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.tools.registry import tool
from app.assistant.tools.student.session_tools import SESSION_COLLECTIONS
from app.db.mongodb import get_collection


@tool(
    name="get_learning_progress",
    description=(
        "Summarize the current user's overall learning progress: session "
        "completion, module progress, and courses in progress. Use for "
        "'how far along am I', 'my overall progress'."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={},
)
async def get_learning_progress(ctx: UserContext) -> ToolResult:
    sessions = []
    session_query = {"$or": [{"assigned_member_ids": ctx.user_id}, {"coach_ids": ctx.user_id}]}
    for col_name in SESSION_COLLECTIONS:
        sessions.extend(await get_collection(col_name).find(session_query).to_list(500))

    # Quarters (modules) the learner is enrolled in, via their batches. batch_ids
    # is backfilled from the company link in the request context.
    quarters = []
    if ctx.batch_ids:
        quarters = await get_collection("quarters").find({"batch_id": {"$in": ctx.batch_ids}}).to_list(200)

    # Progress is computed from session completion + active quarters. (The legacy
    # `learnings` module-progress collection is unused in this deployment.)
    summary = progress.analyze([], sessions, quarters)

    result = AnalyticsResult(
        analysis="progress",
        summary=(
            f"{summary.completion_percentage}% complete "
            f"({summary.completed_sessions}/{summary.total_sessions} sessions); "
            f"{summary.courses_in_progress} course(s) in progress."
        ),
        metrics=[
            AnalyticsMetric(key="completion_percentage", label="Completion",
                            value=summary.completion_percentage, unit="%"),
            AnalyticsMetric(key="completed_sessions", label="Completed sessions",
                            value=summary.completed_sessions),
            AnalyticsMetric(key="total_sessions", label="Total sessions", value=summary.total_sessions),
            AnalyticsMetric(key="courses_in_progress", label="Courses in progress",
                            value=summary.courses_in_progress),
        ],
        generated_for=ctx.user_id,
    )
    return ToolResult.ok(
        "get_learning_progress",
        result.model_dump(),
        sources=[*SESSION_COLLECTIONS, "quarters"],
        scope_applied=f"personal:{ctx.user_id}",
    )
