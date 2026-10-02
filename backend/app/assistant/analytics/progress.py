"""Learning-progress analytics: completion %, sessions, courses in progress.

Pure, deterministic. Completion is computed from session completion when
sessions exist, otherwise from average module progress in `learnings`.
"""
from __future__ import annotations

from typing import List

from app.assistant.schemas.analytics import ProgressSummary


def _is_completed(doc: dict) -> bool:
    return (doc.get("status") or "").lower() == "completed"


def analyze(learnings: List[dict], sessions: List[dict], quarters: List[dict]) -> ProgressSummary:
    total_sessions = len(sessions)
    completed_sessions = sum(1 for s in sessions if _is_completed(s))
    courses_in_progress = sum(1 for q in quarters if (q.get("status") or "").lower() == "active")

    if total_sessions:
        completion = round(completed_sessions / total_sessions * 100, 1)
    else:
        module_progress = [float(l.get("progress") or 0) for l in learnings]
        completion = round(sum(module_progress) / len(module_progress), 1) if module_progress else 0.0

    return ProgressSummary(
        completion_percentage=completion,
        completed_sessions=completed_sessions,
        total_sessions=total_sessions,
        courses_in_progress=courses_in_progress,
    )
