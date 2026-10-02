"""Student performance tools: analyze_student_performance, get_subject_wise_scores."""
from __future__ import annotations

from app.assistant.analytics import performance
from app.assistant.schemas.analytics import AnalyticsMetric, AnalyticsResult
from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.services import assessment_service
from app.assistant.tools.registry import tool


@tool(
    name="analyze_student_performance",
    description=(
        "Analyze the current user's quiz/assessment performance: average score, "
        "trend, and strengths/weaknesses by subject. Use for 'how am I doing', "
        "'am I improving', 'what are my weak areas'."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={"period": {"type": "string", "enum": ["recent", "all"],
                           "description": "recent = last 8 assessments (default), all = full history"}},
)
async def analyze_student_performance(ctx: UserContext, period: str = "recent") -> ToolResult:
    limit = 8 if period == "recent" else 100
    results = await assessment_service.get_results_for_user(ctx, ctx.user_id, limit=limit)
    summary = performance.analyze(results)

    result = AnalyticsResult(
        analysis="performance",
        summary=(
            f"Average {summary.average_percentage}% across {summary.quizzes_taken} "
            f"quiz(zes); trend {summary.trend}."
        ),
        metrics=[
            AnalyticsMetric(key="average_percentage", label="Average score",
                            value=summary.average_percentage, unit="%"),
            AnalyticsMetric(key="quizzes_taken", label="Quizzes taken", value=summary.quizzes_taken),
            AnalyticsMetric(key="quizzes_passed", label="Quizzes passed", value=summary.quizzes_passed),
            AnalyticsMetric(key="trend", label="Trend", value=summary.trend),
        ],
        breakdown=[s.model_dump() for s in (summary.strong_subjects + summary.weak_subjects)],
        period=period,
        generated_for=ctx.user_id,
    )
    return ToolResult.ok(
        "analyze_student_performance",
        result.model_dump(),
        sources=assessment_service.SOURCES,
        count=summary.quizzes_taken,
        scope_applied=f"personal:{ctx.user_id}",
    )


@tool(
    name="get_subject_wise_scores",
    description=(
        "Break down the current user's assessment scores by subject (derived from "
        "quiz titles). Use for 'how am I doing in each subject', 'my scores per topic'."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={},
)
async def get_subject_wise_scores(ctx: UserContext) -> ToolResult:
    results = await assessment_service.get_results_for_user(ctx, ctx.user_id, limit=100)
    subjects = performance.subject_scores(results)

    result = AnalyticsResult(
        analysis="subject_scores",
        summary=f"Scores across {len(subjects)} subject(s).",
        metrics=[AnalyticsMetric(key="subjects", label="Subjects", value=len(subjects))],
        breakdown=[s.model_dump() for s in subjects],
        generated_for=ctx.user_id,
    )
    return ToolResult.ok(
        "get_subject_wise_scores",
        result.model_dump(),
        sources=assessment_service.SOURCES,
        count=len(subjects),
        scope_applied=f"personal:{ctx.user_id}",
    )
