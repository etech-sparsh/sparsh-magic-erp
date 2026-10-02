"""Structured shapes returned by the analytics & recommendation engine.

These are the contracts the LLM narrates from — analytics tools return structured
insight (not raw rows) so answers are accurate and consistent.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Union

from pydantic import BaseModel, Field


class SubjectScore(BaseModel):
    subject: str                             # derived from quiz_title/topic/quarter (V1)
    average_percentage: float
    attempts: int


class PerformanceSummary(BaseModel):
    average_percentage: float = 0.0
    trend: str = "flat"                      # improving | declining | flat
    quizzes_taken: int = 0
    quizzes_passed: int = 0
    strong_subjects: List[SubjectScore] = Field(default_factory=list)
    weak_subjects: List[SubjectScore] = Field(default_factory=list)


class ProgressSummary(BaseModel):
    completion_percentage: float = 0.0
    completed_sessions: int = 0
    total_sessions: int = 0
    courses_in_progress: int = 0


class StudyRecommendation(BaseModel):
    title: str
    reason: str
    priority: int = 0                        # higher = more urgent
    related_subject: Optional[str] = None


class StudyPlan(BaseModel):
    generated_for: str                       # user_id
    recommendations: List[StudyRecommendation] = Field(default_factory=list)


# ── Deterministic analytics envelope ──────────────────────────────────────
# Every analytics tool returns an AnalyticsResult. "Deterministic" means: the
# structure is fixed, values are computed by pure functions in assistant/analytics,
# ordering is stable, and the same input always yields the same metrics/breakdown
# (no LLM in the computation). `computed_at` is metadata only.


class AnalyticsMetric(BaseModel):
    key: str                                 # stable machine key, e.g. "average_percentage"
    label: str                               # human label, e.g. "Average score"
    value: Union[int, float, str]
    unit: Optional[str] = None               # e.g. "%"


class AnalyticsResult(BaseModel):
    analysis: str                            # "performance" | "progress" | "subject_scores"
    summary: str                             # short templated (non-LLM) summary line
    metrics: List[AnalyticsMetric] = Field(default_factory=list)
    breakdown: List[dict] = Field(default_factory=list)   # e.g. per-subject rows
    period: Optional[str] = None
    generated_for: str = ""                  # user_id
    computed_at: datetime = Field(default_factory=datetime.utcnow)
