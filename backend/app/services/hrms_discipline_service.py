"""HRMS > Discipline / Redressal (BA/Functional Design v2.2, §7.17).

Case -> investigation (committee records actions/evidence/meetings/findings) -> recommendation
-> management decision -> closure. Two capability pairs gate this, not one: DISCIPLINE_MANAGE
covers everything up to and including the recommendation ("R" — the committee's work);
DISCIPLINE_DECIDE is management's separate approve-and-implement act ("A"), the same
maker/checker split BR-021 draws for F&F.

-- POSH is a SEPARATE, narrower tier, not a flag on the same permission --------------------
A Harassment/POSH case is ALWAYS Restricted, and reading or acting on it needs
DISCIPLINE_POSH_READ/MANAGE specifically — holding the ordinary DISCIPLINE_* capabilities
grants nothing here. `_require_visibility` is the one place this is enforced, so every list
and get call routes through it rather than each caller re-deriving the same check.

-- Self-service complaint-raising is NOT built here ------------------------------------------
The BA doc names "Employee" as a triggering actor, but an anonymous/self-service intake needs
confidentiality handling (who can see a complaint against their own manager, for instance)
this phase does not attempt — see the Cap.DISCIPLINE_MANAGE comment in models/hrms.py. Every
case here is raised by an HR or manager caller, on someone's behalf.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_DISCIPLINE_CLOSED, AUDIT_DISCIPLINE_CREATED, AUDIT_DISCIPLINE_DECIDED,
    AUDIT_DISCIPLINE_INVESTIGATED, AUDIT_DISCIPLINE_RECOMMENDED,
    COLL_DISCIPLINE_CASES, COLL_EMPLOYEE_PROFILES,
    ENTITY_DISCIPLINE, POSH_CATEGORIES,
    Cap, ConfidentialityLevel, DisciplineStatus,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import can


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _require_visibility(actor: dict, case: dict) -> None:
    """§7.17 BR: POSH/harassment cases are restricted even from ordinary discipline access.
    Called by every read AND every write below — a caller who can manage ordinary cases must
    still be refused a Restricted one without the POSH grant specifically."""
    if case.get("confidentiality_level") == ConfidentialityLevel.RESTRICTED.value:
        if not (can(actor, Cap.DISCIPLINE_POSH_READ) or can(actor, Cap.DISCIPLINE_POSH_MANAGE)):
            raise HTTPException(status_code=403, detail="This case requires POSH-level access.")


async def _get_profile_name(company_id: str, employee_code: str) -> Optional[str]:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    return (profile or {}).get("display_name") or (profile or {}).get("full_name")


async def create_case(actor: dict, company_id: str, payload: dict) -> dict:
    category = payload.get("category")
    persons = payload.get("persons_involved") or []
    if not persons:
        raise HTTPException(status_code=422, detail="At least one person involved is required.")

    # §7.17 BR is not a suggestion the caller can override: a POSH/Harassment category is
    # ALWAYS Restricted, whatever confidentiality_level was (or was not) passed.
    requested_level = payload.get("confidentiality_level")
    level = (ConfidentialityLevel.RESTRICTED.value if category in POSH_CATEGORIES
             else (requested_level or ConfidentialityLevel.STANDARD.value))

    if level == ConfidentialityLevel.RESTRICTED.value and not (
            can(actor, Cap.DISCIPLINE_POSH_READ) or can(actor, Cap.DISCIPLINE_POSH_MANAGE)):
        raise HTTPException(status_code=403, detail="This case requires POSH-level access.")

    resolved_persons = []
    for p in persons:
        code = p.get("employee_code") if isinstance(p, dict) else p.employee_code
        role = p.get("role") if isinstance(p, dict) else p.role
        resolved_persons.append({
            "employee_code": code, "role": role,
            "name": await _get_profile_name(company_id, code),
        })

    year = datetime.now(timezone.utc).year
    case_no = await next_business_id("discipline_case", str(company_id), year)
    now = datetime.now(timezone.utc)
    doc = {
        "case_no": case_no,
        "company_id": str(company_id),
        "category": category,
        "confidentiality_level": level,
        "persons_involved": resolved_persons,
        "description": payload.get("description"),
        "status": DisciplineStatus.REPORTED.value,
        "investigation_log": [],
        "recommendation": None, "recommendation_at": None,
        "outcome": None, "decision_by": None, "decision_at": None, "decision_remarks": None,
        "retention_classification": None,
        "closed_at": None,
        "created_by": str(actor.get("_id") or ""),
        "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_DISCIPLINE_CASES).insert_one(doc)
    # The audit detail itself must never leak WHO or WHAT for a Restricted case — the
    # audit trail is read under a much broader capability (AUDIT_READ) than POSH access is.
    detail = ("(restricted — details withheld from the audit trail)" if level ==
             ConfidentialityLevel.RESTRICTED.value else f"{category}, {len(resolved_persons)} involved")
    await audit(actor, AUDIT_DISCIPLINE_CREATED, ENTITY_DISCIPLINE, case_no, detail, company_id)
    return _out(doc)


async def list_cases(actor: dict, company_id: str, *, status: Optional[str] = None,
                     employee_code: Optional[str] = None, limit: int = 100) -> list:
    """POSH/Restricted cases are excluded entirely for a caller without POSH access — they
    do not even appear as a row, matching "should not be treated as ordinary manager-visible
    discipline case" (a visible-but-locked row would still leak that a case exists)."""
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if employee_code:
        query["persons_involved.employee_code"] = employee_code
    if not (can(actor, Cap.DISCIPLINE_POSH_READ) or can(actor, Cap.DISCIPLINE_POSH_MANAGE)):
        query["confidentiality_level"] = {"$ne": ConfidentialityLevel.RESTRICTED.value}
    rows = await get_collection(COLL_DISCIPLINE_CASES).find(query).sort(
        "created_at", -1).to_list(limit)
    return [_out(r) for r in rows]


async def _get_case(company_id: str, case_no: str) -> dict:
    doc = await get_collection(COLL_DISCIPLINE_CASES).find_one(
        {"company_id": str(company_id), "case_no": case_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Discipline case '{case_no}' not found.")
    return doc


async def get_case(actor: dict, company_id: str, case_no: str) -> dict:
    doc = await _get_case(company_id, case_no)
    _require_visibility(actor, doc)
    return _out(doc)


async def add_investigation_note(actor: dict, company_id: str, case_no: str, payload: dict) -> dict:
    doc = await _get_case(company_id, case_no)
    _require_visibility(actor, doc)
    if doc["status"] == DisciplineStatus.CLOSED.value:
        raise HTTPException(status_code=409, detail=f"{case_no} is already closed.")

    now = datetime.now(timezone.utc)
    entry = {"by": str(actor.get("_id") or ""), "at": now, "note": payload.get("note"),
             "evidence": payload.get("evidence")}
    await get_collection(COLL_DISCIPLINE_CASES).update_one(
        {"_id": doc["_id"]},
        {"$push": {"investigation_log": entry},
         "$set": {"status": DisciplineStatus.UNDER_INVESTIGATION.value, "updated_at": now}},
    )
    await audit(actor, AUDIT_DISCIPLINE_INVESTIGATED, ENTITY_DISCIPLINE, case_no,
               "(restricted)" if doc["confidentiality_level"] == ConfidentialityLevel.RESTRICTED.value
               else "investigation note added", company_id)
    return await get_case(actor, company_id, case_no)


async def record_recommendation(actor: dict, company_id: str, case_no: str, payload: dict) -> dict:
    doc = await _get_case(company_id, case_no)
    _require_visibility(actor, doc)
    if doc["status"] == DisciplineStatus.CLOSED.value:
        raise HTTPException(status_code=409, detail=f"{case_no} is already closed.")

    now = datetime.now(timezone.utc)
    await get_collection(COLL_DISCIPLINE_CASES).update_one(
        {"_id": doc["_id"]},
        {"$set": {"recommendation": payload.get("recommendation"), "recommendation_at": now,
                  "status": DisciplineStatus.RECOMMENDATION_RECORDED.value, "updated_at": now}},
    )
    await audit(actor, AUDIT_DISCIPLINE_RECOMMENDED, ENTITY_DISCIPLINE, case_no,
               "(restricted)" if doc["confidentiality_level"] == ConfidentialityLevel.RESTRICTED.value
               else "recommendation recorded", company_id)
    return await get_case(actor, company_id, case_no)


async def decide_case(actor: dict, company_id: str, case_no: str, payload: dict) -> dict:
    """§7.17 step 133: management's separate approve-and-implement act. Requires
    DISCIPLINE_DECIDE (or the POSH equivalent for a Restricted case) at the ROUTE layer —
    this function additionally re-checks visibility so a direct service call can never
    bypass the POSH gate either."""
    doc = await _get_case(company_id, case_no)
    _require_visibility(actor, doc)
    if doc["status"] not in (DisciplineStatus.RECOMMENDATION_RECORDED.value,
                             DisciplineStatus.UNDER_INVESTIGATION.value):
        raise HTTPException(
            status_code=409,
            detail=f"{case_no} needs a recorded recommendation before a decision.")

    now = datetime.now(timezone.utc)
    await get_collection(COLL_DISCIPLINE_CASES).update_one(
        {"_id": doc["_id"]},
        {"$set": {"outcome": payload.get("outcome"), "decision_by": str(actor.get("_id") or ""),
                  "decision_at": now, "decision_remarks": payload.get("remarks"),
                  "status": DisciplineStatus.DECIDED.value, "updated_at": now}},
    )
    await audit(actor, AUDIT_DISCIPLINE_DECIDED, ENTITY_DISCIPLINE, case_no,
               "(restricted)" if doc["confidentiality_level"] == ConfidentialityLevel.RESTRICTED.value
               else payload.get("outcome"), company_id)
    return await get_case(actor, company_id, case_no)


async def close_case(actor: dict, company_id: str, case_no: str, payload: dict) -> dict:
    doc = await _get_case(company_id, case_no)
    _require_visibility(actor, doc)
    if doc["status"] != DisciplineStatus.DECIDED.value:
        raise HTTPException(status_code=409, detail=f"{case_no} needs a decision before closing.")

    now = datetime.now(timezone.utc)
    await get_collection(COLL_DISCIPLINE_CASES).update_one(
        {"_id": doc["_id"]},
        {"$set": {"status": DisciplineStatus.CLOSED.value, "closed_at": now,
                  "retention_classification": payload.get("retention_classification"),
                  "updated_at": now}},
    )
    await audit(actor, AUDIT_DISCIPLINE_CLOSED, ENTITY_DISCIPLINE, case_no,
               payload.get("retention_classification") or "closed", company_id)
    return await get_case(actor, company_id, case_no)


async def employee_summary(actor: dict, company_id: str, employee_code: str) -> dict:
    """§7.17 step 136: "Only a permission-controlled summary appears in Employee 360°." A
    thin, count-only projection — full case detail still goes through get_case/list_cases,
    each gated exactly as above. Full Employee 360° aggregation itself (§6) is a separate,
    much larger gap this does not attempt to close."""
    cases = await list_cases(actor, company_id, employee_code=employee_code, limit=200)
    open_count = sum(1 for c in cases if c["status"] != DisciplineStatus.CLOSED.value)
    return {"employee_code": employee_code, "total_cases": len(cases), "open_cases": open_count}
