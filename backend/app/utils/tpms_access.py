"""Company-level TPMS access control.

Mirrors app/utils/orm_utils.py, with one deliberate difference: ORM defaults to ENABLED so
existing companies keep working, whereas TPMS defaults to **DISABLED**. A company only gets
TPMS once an Admin / Super Admin turns it on, so a missing flag means off.

Two layers use this:
  • ensure_tpms_enabled() — a route guard; client-side users of a disabled company are
    refused. Internal staff always pass so they can administer and report.
  • tpms_enabled_company_ids() — the data-layer filter; disabled companies are excluded
    from every dashboard, report, filter and aggregation.
"""
from bson import ObjectId

from app.db.mongodb import get_collection

STAFF_ROLES = {"superadmin", "admin"}
CLIENT_ROLES = {"clientadmin", "clientuser"}

# Only these roles may flip the switch (spec: Admin / Super Admin).
TOGGLE_ROLES = STAFF_ROLES


async def is_tpms_enabled(company_id: str) -> bool:
    """Whether TPMS is switched on for a company. A missing flag means OFF — TPMS is
    opt-in per company, so nothing is exposed until it is explicitly enabled."""
    if not company_id:
        return False
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
    except Exception:
        return False
    if not company:
        return False
    return bool(company.get("tpms_enabled", False))


async def ensure_tpms_enabled(current_user: dict, company_id: str = None) -> None:
    """Raise 403 when a client-side user's company has TPMS switched off.

    Internal staff (superadmin/admin and SMOps) always pass: they administer TPMS across
    clients, and the data layer already excludes disabled companies from what they see.
    `company_id` defaults to the caller's own company, which is the case that matters —
    a client user can only ever act within it.
    """
    from fastapi import HTTPException

    role = (current_user.get("role") or "").lower()
    if role not in CLIENT_ROLES:
        return
    target = company_id or str(current_user.get("company_id") or "")
    if not await is_tpms_enabled(target):
        raise HTTPException(
            status_code=403,
            detail="TPMS is not enabled for this company. Contact your administrator.",
        )


async def tpms_enabled_company_ids() -> set:
    """Ids of every company with TPMS switched on.

    The data-layer filter. Aggregations intersect against this so a disabled company never
    appears in a dashboard, matrix, report, filter dropdown or score rollup.
    """
    docs = await get_collection("companies").find(
        {"tpms_enabled": True}, {"_id": 1}
    ).to_list(5000)
    return {str(d["_id"]) for d in docs}
