"""HRMS > Group Mediclaim Policy (Phase GMP-1, §22 employee profile "GMP section").

AR-01 in the BA doc leaves GMP's exact definition to be confirmed with the client; this
phase implements the reading agreed for now — Group Mediclaim insurance enrolment
(insurer, policy number, sum insured, dependants) — as a lean, editable-in-place record.

-- Current state, not a ledger --------------------------------------------------------
Unlike Salary Structure or Movements, nothing in the BA doc asks for an effective-dated
history of GMP changes, so this is one document per employee that HR edits in place —
the same shape Employee Profile's own personal/statutory fields already take. If a
history becomes a real requirement later, that is an additive change, not a rewrite.

-- Ownership scoping -------------------------------------------------------------------
An employee may READ their own enrolment (the "GMP section" on their own profile) but
never WRITE it — the same enforced-ownership pattern PIP/Letters/Appointments establish.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_GMP_SAVED, COLL_EMPLOYEE_PROFILES, COLL_GMP_RECORDS, ENTITY_GMP, HrmsRole,
)
from app.services.hrms_audit_service import audit
from app.utils.hrms_access import hrms_role


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


async def _get_profile(company_id: str, employee_code: str) -> dict:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        raise HTTPException(status_code=404, detail="No employee with that code in this company.")
    return profile


async def _own_employee_code(actor: dict, company_id: str) -> Optional[str]:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": str(actor.get("_id") or "")})
    return (profile or {}).get("employee_code")


async def get_gmp(actor: dict, company_id: str, employee_code: str) -> Optional[dict]:
    """Row-scoped exactly like hrms_pip_service.get_pip: an EMPLOYEE caller may only open
    their own enrolment. Returns None (not 404) when nothing has been filed yet — GMP
    enrolment is optional, unlike a PIP or an appointment letter."""
    if hrms_role(actor) == HrmsRole.EMPLOYEE:
        own = await _own_employee_code(actor, company_id)
        if own != employee_code:
            raise HTTPException(status_code=403, detail="You may only view your own GMP enrolment.")
    doc = await get_collection(COLL_GMP_RECORDS).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    return _out(doc) if doc else None


async def save_gmp(actor: dict, company_id: str, employee_code: str, payload: dict) -> dict:
    """HR's upsert — creates the enrolment on first save, edits it in place after."""
    await _get_profile(company_id, employee_code)
    now = datetime.now(timezone.utc)
    clean = {
        "insurer": payload.get("insurer"),
        "policy_number": payload.get("policy_number"),
        "sum_insured": payload.get("sum_insured"),
        "enrolled_on": payload.get("enrolled_on"),
        "status": payload.get("status") or "Active",
        "dependents": [dict(d) if isinstance(d, dict) else d.model_dump()
                      for d in (payload.get("dependents") or [])],
        "remarks": payload.get("remarks"),
        "updated_by": str(actor.get("_id") or ""),
        "updated_at": now,
    }
    await get_collection(COLL_GMP_RECORDS).update_one(
        {"company_id": str(company_id), "employee_code": employee_code},
        {"$set": clean,
         "$setOnInsert": {"company_id": str(company_id), "employee_code": employee_code,
                          "created_at": now}},
        upsert=True,
    )
    await audit(actor, AUDIT_GMP_SAVED, ENTITY_GMP, employee_code, clean["status"], company_id)
    return await get_gmp(actor, company_id, employee_code)
