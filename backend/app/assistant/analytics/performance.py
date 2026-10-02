"""Performance analytics: averages, trend, strengths/weaknesses, subject scores.

Pure, deterministic functions (no LLM, stable ordering). Subject is DERIVED
(V1 decision #1) from quiz_title / session topic / quarter name.
"""
from __future__ import annotations

from typing import List

from app.assistant.schemas.analytics import PerformanceSummary, SubjectScore

# Words stripped when deriving a subject label so retakes/variants group together.
_SUBJECT_NOISE = {
    "quiz", "test", "exam", "assessment", "retake", "final", "midterm",
    "module", "paper", "part", "section", "round",
}

STRONG_THRESHOLD = 75.0
WEAK_THRESHOLD = 50.0
TREND_DELTA = 5.0


def _pct(assessment: dict) -> float:
    try:
        return float(assessment.get("percentage") or 0)
    except (TypeError, ValueError):
        return 0.0


def derive_subject(assessment: dict) -> str:
    """Derive a subject label (quiz_title → session topic/title → 'General')."""
    title = (
        assessment.get("quiz_title")
        or assessment.get("session_title")
        or assessment.get("topic")
        or ""
    ).strip()
    if not title:
        return "General"
    words = [w for w in title.replace("-", " ").split() if w.lower() not in _SUBJECT_NOISE]
    return " ".join(words).strip() or "General"


def subject_scores(assessments: List[dict]) -> List[SubjectScore]:
    """Group results by derived subject; sorted by descending average, then name."""
    groups: dict = {}
    for a in assessments:
        groups.setdefault(derive_subject(a), []).append(_pct(a))
    out = [
        SubjectScore(subject=s, average_percentage=round(sum(v) / len(v), 1), attempts=len(v))
        for s, v in groups.items()
    ]
    out.sort(key=lambda x: (-x.average_percentage, x.subject))
    return out


def analyze(assessments: List[dict]) -> PerformanceSummary:
    """Compute a deterministic PerformanceSummary from raw assessment records."""
    if not assessments:
        return PerformanceSummary()

    ordered = sorted(assessments, key=lambda a: str(a.get("submitted_at") or ""))
    pcts = [_pct(a) for a in ordered]
    avg = round(sum(pcts) / len(pcts), 1)
    passed = sum(1 for a in ordered if a.get("passed"))

    trend = "flat"
    if len(pcts) >= 2:
        half = len(pcts) // 2
        first = sum(pcts[:half]) / max(half, 1)
        second = sum(pcts[half:]) / max(len(pcts) - half, 1)
        if second - first > TREND_DELTA:
            trend = "improving"
        elif first - second > TREND_DELTA:
            trend = "declining"

    subs = subject_scores(ordered)
    return PerformanceSummary(
        average_percentage=avg,
        trend=trend,
        quizzes_taken=len(ordered),
        quizzes_passed=passed,
        strong_subjects=[s for s in subs if s.average_percentage >= STRONG_THRESHOLD],
        weak_subjects=[s for s in subs if s.average_percentage < WEAK_THRESHOLD],
    )
