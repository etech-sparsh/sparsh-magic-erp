"""Student assessment tool: get_latest_quiz_result."""
from __future__ import annotations

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.services import assessment_service
from app.assistant.tools.registry import tool
from app.assistant.utils.serializers import serialize

QUIZ_FIELDS = [
    "quiz_title", "score", "total_marks", "percentage", "passed",
    "passing_score", "submitted_at", "session_id", "quiz_index",
]


@tool(
    name="get_latest_quiz_result",
    description=(
        "Get the current user's most recent quiz/assessment result (title, "
        "score, percentage, pass/fail). Use for 'how did I do on my last quiz', "
        "'my latest test score', 'did I pass my last exam'."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={},
)
async def get_latest_quiz_result(ctx: UserContext) -> ToolResult:
    # Personal scope: a learner may only read their own results. Service reads
    # both LearnerAssessments and the legacy LearnerAsessments (TD-1) defensively.
    latest = await assessment_service.get_latest_result(ctx, ctx.user_id)
    scope = f"personal:{ctx.user_id}"

    if not latest:
        return ToolResult.ok(
            "get_latest_quiz_result",
            None,
            sources=assessment_service.SOURCES,
            count=0,
            scope_applied=scope,
        )

    data = serialize(latest, QUIZ_FIELDS)
    return ToolResult.ok(
        "get_latest_quiz_result",
        data,
        sources=assessment_service.SOURCES,
        scope_applied=scope,
    )
