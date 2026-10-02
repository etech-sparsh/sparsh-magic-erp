"""Assessment results service (V1 decision #3 — defensive legacy handling).

Reads results from BOTH the primary `LearnerAssessments` collection and the
legacy typo'd `LearnerAsessments` (single 's'), merging by `submitted_at`. All
assessment access goes through this service; the dual-read can be removed once
TD-1 (collection consolidation) is complete.

Phase 0: signatures + collection constants only.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.assistant.schemas.context import UserContext
from app.db.mongodb import get_collection

PRIMARY_COLLECTION = "LearnerAssessments"
LEGACY_COLLECTION = "LearnerAsessments"  # TD-1: legacy typo — read defensively

SOURCES = [PRIMARY_COLLECTION, LEGACY_COLLECTION]


def _sort_key(doc: Dict) -> str:
    """Stable sort key tolerant of datetime or string `submitted_at`."""
    value = doc.get("submitted_at")
    if value is None:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


async def get_results_for_user(ctx: UserContext, user_id: str, limit: int = 100) -> List[Dict]:
    """Merged assessment results for a user (primary + legacy), newest first.

    Callers pass a `user_id` already validated against `ctx` scope (a learner may
    only request their own). Each collection is read defensively — a missing
    legacy collection or query error on one source never fails the other.
    """
    merged: List[Dict] = []
    for col_name in SOURCES:
        try:
            docs = await get_collection(col_name).find({"user_id": user_id}).to_list(limit)
            merged.extend(docs)
        except Exception:
            # Defensive: legacy collection may not exist in every environment.
            continue
    merged.sort(key=_sort_key, reverse=True)
    return merged[:limit]


async def get_latest_result(ctx: UserContext, user_id: str) -> Optional[Dict]:
    """Most recent assessment result for a user (primary + legacy), or None."""
    results = await get_results_for_user(ctx, user_id, limit=100)
    return results[0] if results else None
