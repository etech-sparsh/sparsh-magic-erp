"""HRMS ▸ audit trail.

Append-only record of every HRMS write. Two consumers are already planned:
  • Phase 5 — the per-candidate journey timeline is reconstructed entirely from this log.
  • Phase 15 — the filterable audit read API (the source had no global audit read at all,
    only a per-candidate view; BACKEND_ANALYSIS §15).

Design rules:
  • **Fire-and-forget.** audit() never raises into the caller. A failed audit write must
    not roll back or block the business write that triggered it — same contract as the
    ERP's existing log_activity / notification side effects.
  • **Never on the hot path's critical section.** Callers await it, but a failure is
    swallowed and logged.
  • **Closed vocabulary.** `entity` comes from the ENTITY_* constants in models/hrms.py so
    the Phase 15 API can filter on something stable.
"""
from datetime import datetime, timezone
from typing import Optional

from app.db.mongodb import get_collection
from app.models.hrms import COLL_AUDIT_LOG


async def audit(
    actor: Optional[dict],
    action: str,
    entity: str,
    entity_id: Optional[str] = None,
    detail: Optional[str] = None,
    company_id: Optional[str] = None,
) -> None:
    """Append one row to the HRMS audit trail. Never raises.

    `actor` is the session user dict (or None for system/public actions — e.g. a candidate
    submitting a public form, where there is no authenticated user).
    """
    try:
        actor = actor or {}
        doc = {
            "actor_id": str(actor.get("_id")) if actor.get("_id") else None,
            "actor_name": actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email")
            or "system",
            "action": action,
            "entity": entity,
            "entity_id": str(entity_id) if entity_id is not None else None,
            "detail": detail,
            # Fall back to the actor's own company so a caller that forgets to pass it
            # still produces a tenant-scoped row rather than an unfilterable orphan.
            "company_id": str(company_id or actor.get("company_id") or "") or None,
            "created_at": datetime.now(timezone.utc),
        }
        await get_collection(COLL_AUDIT_LOG).insert_one(doc)
    except Exception as e:
        # Deliberately swallowed — see module docstring.
        print(f"[WARN] HRMS audit write failed ({entity}/{action}): {e}")


async def read_audit(
    company_id: Optional[str] = None,
    entity: Optional[str] = None,
    entity_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    limit: int = 100,
) -> list:
    """Read the audit trail, newest first.

    Phase 1 ships this for the health check and tests; Phase 15 exposes it as a filterable
    API. Bounded by `limit` so it can never stream an unbounded result set.
    """
    query = {}
    if company_id:
        query["company_id"] = company_id
    if entity:
        query["entity"] = entity
    if entity_id:
        query["entity_id"] = str(entity_id)
    if actor_id:
        query["actor_id"] = str(actor_id)

    limit = max(1, min(int(limit or 100), 500))
    rows = await get_collection(COLL_AUDIT_LOG).find(query).sort(
        "created_at", -1
    ).to_list(limit)
    for r in rows:
        # Defensive: Mongo always supplies _id, but a projection or a caller-supplied
        # document may not. A read path must not raise on a missing optional field.
        if "_id" in r:
            r["_id"] = str(r["_id"])
    return rows
