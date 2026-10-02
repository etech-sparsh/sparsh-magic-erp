"""Shared access logic for GPT projects (the "Sparsh Support Engine").

Single source of truth for whether a given user can see/unlock each project,
used by BOTH the `/gpt/projects` route and the assistant's
`get_support_engine_status` tool — so the chatbot's unlock guidance can never
drift from what the website shows.

Access model (learners):
  * A project is *visible* if it's in the user's learning path — linked to a
    batch, quarter, or session they belong to — or explicitly granted.
  * A project is *unlocked* when the linked batch/quarter/session is completed,
    or when an admin granted direct access (gpt_permissions).
  * Otherwise it's locked, with a `lock_reason` naming the level to complete.
Staff/admin see every project, unlocked.
"""
from __future__ import annotations

from typing import List, Optional

from bson import ObjectId
from bson.errors import InvalidId

from app.db.mongodb import get_collection
from app.utils.calendar_utils import CALENDAR_COLLECTIONS

STAFF_ROLES = ["superadmin", "admin", "coach", "staff"]


def _oid(value):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


async def get_projects_with_access(
    user_id: str,
    role: Optional[str],
    company_id: Optional[str],
    direct_batch_ids: Optional[List[str]] = None,
    lightweight: bool = False,
) -> List[dict]:
    """Return every gpt_project the user may see, each tagged `locked` + `lock_reason`.

    Mirrors the logic formerly inline in `GET /gpt/projects` so the website and
    the assistant agree exactly.

    `lightweight=True` fetches only display fields (title/description) for each
    project — the gpt_projects docs embed heavy knowledge content, so the full
    fetch is ~10s. The assistant uses lightweight; the website needs full docs.
    """
    project_projection = {"title": 1, "description": 1} if lightweight else None
    projects = await get_collection("gpt_projects").find({}, project_projection).to_list(100)

    # Staff/admin: see all, nothing locked.
    if role in STAFF_ROLES:
        out = []
        for p in projects:
            p["id"] = str(p["_id"])
            p.pop("_id", None)
            p["locked"] = False
            out.append(p)
        return out

    # ── Learner access resolution ──────────────────────────────────────────
    # Projection shared by batch/quarter/session scans: only the fields the
    # access logic reads. Critically, this skips heavy session sub-arrays
    # (resources, view_logs) that otherwise make this scan take ~15s.
    LINK_FIELDS = {"status": 1, "gpt_project_id": 1, "gpt_projects": 1}

    # 1. Special permissions (admin-granted direct unlocks).
    special_perms = await get_collection("gpt_permissions").find({
        "$or": [
            {"entity_id": user_id, "entity_type": "user"},
            {"entity_id": company_id, "entity_type": "company"},
        ]
    }, {"project_id": 1}).to_list(100)
    unlocked_project_ids = {p["project_id"] for p in special_perms}

    # 2. Resolve relevant batches (directly assigned + via company).
    batch_ids = list(direct_batch_ids or [])
    all_batch_oids = [o for o in (_oid(bid) for bid in batch_ids) if o]
    if company_id:
        company_batches = await get_collection("batches").find(
            {"companies": str(company_id)}, {"_id": 1}
        ).to_list(100)
        for b in company_batches:
            if b["_id"] not in all_batch_oids:
                all_batch_oids.append(b["_id"])

    batches = await get_collection("batches").find(
        {"_id": {"$in": all_batch_oids}}, LINK_FIELDS
    ).to_list(100)
    batch_str_ids = [str(b["_id"]) for b in batches]

    # 3. Batch-level links.
    batch_linked = {}
    for b in batches:
        is_completed = (b.get("status", "") or "").lower() == "completed"
        old_pid = b.get("gpt_project_id")
        if old_pid:
            batch_linked[str(old_pid)] = batch_linked.get(str(old_pid), False) or is_completed
        for p_link in b.get("gpt_projects", []):
            pid = p_link.get("id")
            if pid:
                batch_linked[str(pid)] = batch_linked.get(str(pid), False) or is_completed

    # 4. Quarter-level links.
    quarters = await get_collection("quarters").find(
        {"batch_id": {"$in": batch_str_ids}}, LINK_FIELDS
    ).to_list(200)
    quarter_linked = {}
    for q in quarters:
        is_completed = (q.get("status", "") or "").lower() == "completed"
        old_pid = q.get("gpt_project_id")
        if old_pid:
            quarter_linked[str(old_pid)] = quarter_linked.get(str(old_pid), False) or is_completed
        for p_link in q.get("gpt_projects", []):
            pid = p_link.get("id")
            if pid:
                quarter_linked[str(pid)] = quarter_linked.get(str(pid), False) or is_completed

    # 5. Session-level links.
    session_collections = CALENDAR_COLLECTIONS + ["calendar_events"]
    session_linked = {}
    for col_name in session_collections:
        sessions = await get_collection(col_name).find({
            "$or": [
                {"user_id": user_id},
                {"assigned_member_ids": user_id},
                {"coach_ids": user_id},
            ]
        }, LINK_FIELDS).to_list(500)
        for s in sessions:
            is_completed = (s.get("status", "") or "").lower() == "completed"
            old_pid = s.get("gpt_project_id")
            if old_pid:
                session_linked[str(old_pid)] = session_linked.get(str(old_pid), False) or is_completed
            for p_link in s.get("gpt_projects", []):
                pid = p_link.get("id")
                if pid:
                    session_linked[str(pid)] = session_linked.get(str(pid), False) or is_completed

    # 6. Assemble: only projects in the user's path are returned.
    result = []
    for p in projects:
        pid = str(p["_id"])
        is_in_path = (
            pid in batch_linked
            or pid in quarter_linked
            or pid in session_linked
            or pid in unlocked_project_ids
        )
        if not is_in_path:
            continue

        p["id"] = pid
        p.pop("_id", None)
        is_unlocked = (
            pid in unlocked_project_ids
            or batch_linked.get(pid, False)
            or quarter_linked.get(pid, False)
            or session_linked.get(pid, False)
        )
        p["locked"] = not is_unlocked
        if p["locked"]:
            if pid in batch_linked:
                p["lock_reason"] = "Batch Level Access (Complete Batch to Unlock)"
            elif pid in quarter_linked:
                p["lock_reason"] = "Quarter Level Access (Complete Quarter to Unlock)"
            elif pid in session_linked:
                p["lock_reason"] = "Session Level Access (Complete Session to Unlock)"
        result.append(p)

    return result
