"""Recommendation engine: deterministic study-plan generation.

Candidate generation + ranking happen here (pure functions); the LLM only phrases
the result. Signals consumed: weak subjects + declining trend (from performance),
upcoming sessions/exams, and — when their tools land — pending assignments and
attendance gaps. Missing signals degrade gracefully.
"""
from __future__ import annotations

from typing import List, Optional

from app.assistant.schemas.analytics import PerformanceSummary, StudyPlan, StudyRecommendation

# Priority weights (higher = more urgent), kept explicit for auditability.
P_PENDING_ASSIGNMENT = 85
P_WEAK_SUBJECT = 80
P_DECLINING = 70
P_UPCOMING = 60
P_ATTENDANCE = 50
P_FALLBACK = 10


def build_study_plan(
    user_id: str,
    performance: PerformanceSummary,
    upcoming_sessions: Optional[List[dict]] = None,
    pending_assignments: Optional[List[dict]] = None,
    attendance: Optional[List[dict]] = None,
) -> StudyPlan:
    recs: List[StudyRecommendation] = []

    for a in (pending_assignments or [])[:3]:
        recs.append(StudyRecommendation(
            title=f"Complete: {a.get('title', 'assignment')}",
            reason="This assignment is still pending.",
            priority=P_PENDING_ASSIGNMENT,
        ))

    for s in (performance.weak_subjects or []):
        recs.append(StudyRecommendation(
            title=f"Revise {s.subject}",
            reason=f"Your average in {s.subject} is {s.average_percentage}% "
                   f"across {s.attempts} attempt(s) — your weakest area.",
            priority=P_WEAK_SUBJECT,
            related_subject=s.subject,
        ))

    if performance.trend == "declining":
        recs.append(StudyRecommendation(
            title="Review recent material",
            reason="Your recent scores are trending downward.",
            priority=P_DECLINING,
        ))

    for sess in (upcoming_sessions or [])[:3]:
        recs.append(StudyRecommendation(
            title=f"Prepare for: {sess.get('title', 'upcoming session')}",
            reason=f"Scheduled for {sess.get('start', 'soon')}.",
            priority=P_UPCOMING,
        ))

    absent = sum(1 for a in (attendance or []) if (a.get("status") or "").lower() == "absent")
    if absent >= 2:
        recs.append(StudyRecommendation(
            title="Catch up on missed sessions",
            reason=f"You were absent for {absent} recent session(s).",
            priority=P_ATTENDANCE,
        ))

    if not recs:
        recs.append(StudyRecommendation(
            title="Keep up the good work",
            reason="No weak areas or pending items detected right now.",
            priority=P_FALLBACK,
        ))

    # Deterministic ordering: priority desc, then title.
    recs.sort(key=lambda r: (-r.priority, r.title))
    return StudyPlan(generated_for=user_id, recommendations=recs)
