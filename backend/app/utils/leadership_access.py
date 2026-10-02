"""Company-level Leadership Score access control.

Leadership Score is part of TPMS and has NO switch of its own: whichever way the TPMS
toggle is set, Leadership Score follows it. Turning TPMS on turns Leadership Score on;
turning TPMS off turns it off. There is deliberately no second control to keep in step,
because two switches for one module is how a company ends up half-enabled.

This module exists so the refusal names the module the user was actually trying to reach
rather than TPMS in general, and so every leadership route has one obvious place to look
for its gate.

Two layers use it:
  • ensure_leadership_enabled() — a route guard; client-side users of a company without
    TPMS are refused. Internal staff always pass so they can administer and support it.
  • leadership_enabled_company_ids() — the data-layer filter, so a company without TPMS
    never appears in a roll-up.
"""
from bson import ObjectId
from fastapi import HTTPException

from app.db.mongodb import get_collection

STAFF_ROLES = {"superadmin", "admin"}
CLIENT_ROLES = {"clientadmin", "clientuser"}

# Only these roles may flip the switch, same as the ORM and TPMS toggles.
TOGGLE_ROLES = STAFF_ROLES


async def is_leadership_enabled(company_id: str) -> bool:
    """Whether Leadership Score is available to a company.

    Reads `tpms_enabled` — the ONE flag that governs both. Opt-in, so a missing flag means
    OFF and nothing is exposed until TPMS is switched on.
    """
    if not company_id:
        return False
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
    except Exception:
        return False
    if not company:
        return False
    return bool(company.get("tpms_enabled", False))


async def ensure_leadership_enabled(current_user: dict, company_id: str = None) -> None:
    """Raise 403 when a client-side user's company does not have TPMS switched on.

    Internal staff always pass — they administer the module across every client and need
    to be able to set a company up before its own users can reach it.
    """
    role = (current_user.get("role") or "").lower()
    if role in STAFF_ROLES:
        return

    cid = company_id or current_user.get("company_id")
    if not await is_leadership_enabled(cid):
        raise HTTPException(
            status_code=403,
            detail="Leadership Score is not available for your company. It is part of "
                   "TPMS — ask an administrator to enable TPMS.")


async def leadership_enabled_company_ids() -> list:
    """Ids of every company that can use Leadership Score — i.e. every TPMS company."""
    rows = await get_collection("companies").find(
        {"tpms_enabled": True}, {"_id": 1}).to_list(1000)
    return [str(r["_id"]) for r in rows]
