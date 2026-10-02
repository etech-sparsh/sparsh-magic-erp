"""HRMS > Performance Improvement Plan (BA/Functional Design v2.2, §22.5).

Manager/HR initiates a PIP with objectives and support actions -> the employee acknowledges
it -> the manager records periodic review notes -> at plan end HR records the outcome
(Successfully Closed / Extended / Further Action Required / Separation Recommended).

-- Restricted, the same reasoning Phase MOVE-1's discipline cases already establish --------
A PIP record is sensitive performance data. This module gates it behind PIP_READ/MANAGE/
DECIDE the same way, though without Discipline's extra POSH-style tier — the BA doc names no
comparably narrower category within PIP itself.

-- Ownership scoping for the employee's own acknowledgement --------------------------------
`acknowledge` checks that the caller IS the PIP's own employee (via their linked profile),
the same enforced-ownership pattern Phase ATT-1 established for self-service actions —
unlike EXIT-1's documented ownership-check gap, this one is not deferred.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_PIP_ACKNOWLEDGED, AUDIT_PIP_DECIDED, AUDIT_PIP_INITIATED, AUDIT_PIP_REVIEW_ADDED,
    COLL_EMPLOYEE_PROFILES, COLL_PIP_RECORDS,
    ENTITY_PIP, MAX_PIP_LIST_PAGE,
    HrmsRole, PipStatus,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
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


async def _scope_query(actor: dict, company_id: str, query: dict) -> dict:
    """An EMPLOYEE caller (holds PIP_READ only for their own acknowledgement screen, per
    the Cap.PIP_READ comment in models/hrms.py) sees only their own plans; everyone else
    who holds PIP_READ (HR/MD/MANAGER) sees the company's. Fails CLOSED: an employee with
    no linked profile sees nothing rather than everything."""
    if hrms_role(actor) == HrmsRole.EMPLOYEE:
        own = await _own_employee_code(actor, company_id)
        query["employee_code"] = own or "__none__"
    return query


async def _own_employee_code(actor: dict, company_id: str) -> Optional[str]:
    actor_id = str(actor.get("_id") or "")
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": actor_id})
    return (profile or {}).get("employee_code")


async def initiate_pip(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    profile = await _get_profile(company_id, employee_code)

    year = datetime.now(timezone.utc).year
    pip_no = await next_business_id("pip", str(company_id), year)
    now = datetime.now(timezone.utc)
    doc = {
        "pip_no": pip_no,
        "company_id": str(company_id),
        "employee_code": employee_code,
        "employee_name": profile.get("display_name") or profile.get("full_name"),
        "initiated_by": str(actor.get("_id") or ""),
        "review_reference": payload.get("review_reference"),
        "issue_category": payload.get("issue_category"),
        "gap_statement": payload.get("gap_statement"),
        "start_date": payload.get("start_date"),
        "target_end_date": payload.get("target_end_date"),
        "review_frequency": payload.get("review_frequency"),
        "objectives": [dict(o) if isinstance(o, dict) else o.model_dump()
                      for o in (payload.get("objectives") or [])],
        "support": [dict(s) if isinstance(s, dict) else s.model_dump()
                   for s in (payload.get("support") or [])],
        "reviews": [],
        "status": PipStatus.DRAFT.value,
        "acknowledged_at": None,
        "closure_result": None, "final_rating": None, "extension_date": None,
        "next_action": None, "decided_by": None, "decided_at": None, "decision_remarks": None,
        "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_PIP_RECORDS).insert_one(doc)
    await audit(actor, AUDIT_PIP_INITIATED, ENTITY_PIP, pip_no,
               f"{employee_code}: {payload.get('gap_statement')}", company_id)
    return _out(doc)


async def list_pips(actor: dict, company_id: str, *, employee_code: Optional[str] = None,
                    status: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if employee_code:
        query["employee_code"] = employee_code
    if status:
        query["status"] = status
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_PIP_RECORDS).find(query).sort(
        "created_at", -1).to_list(min(limit, MAX_PIP_LIST_PAGE))
    return [_out(r) for r in rows]


async def _get_pip(company_id: str, pip_no: str) -> dict:
    doc = await get_collection(COLL_PIP_RECORDS).find_one(
        {"company_id": str(company_id), "pip_no": pip_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"PIP '{pip_no}' not found.")
    return doc


async def get_pip(actor: dict, company_id: str, pip_no: str) -> dict:
    doc = await _get_pip(company_id, pip_no)
    if hrms_role(actor) == HrmsRole.EMPLOYEE:
        own = await _own_employee_code(actor, company_id)
        if own != doc["employee_code"]:
            raise HTTPException(status_code=403, detail="You may only view your own PIP.")
    return _out(doc)


async def acknowledge_pip(actor: dict, company_id: str, pip_no: str) -> dict:
    """§22.5 step 217. Enforced ownership: only the PIP's OWN employee may acknowledge it."""
    doc = await _get_pip(company_id, pip_no)
    if doc["status"] != PipStatus.DRAFT.value:
        raise HTTPException(status_code=409, detail=f"{pip_no} is already \"{doc['status']}\".")

    own_code = await _own_employee_code(actor, company_id)
    if own_code != doc["employee_code"]:
        raise HTTPException(status_code=403, detail="You may only acknowledge your own PIP.")

    now = datetime.now(timezone.utc)
    await get_collection(COLL_PIP_RECORDS).update_one(
        {"_id": doc["_id"]},
        {"$set": {"status": PipStatus.ACTIVE.value, "acknowledged_at": now, "updated_at": now}},
    )
    await audit(actor, AUDIT_PIP_ACKNOWLEDGED, ENTITY_PIP, pip_no, None, company_id)
    return await get_pip(actor, company_id, pip_no)


async def add_review(actor: dict, company_id: str, pip_no: str, payload: dict) -> dict:
    """§22.5 step 218."""
    doc = await _get_pip(company_id, pip_no)
    if doc["status"] != PipStatus.ACTIVE.value:
        raise HTTPException(
            status_code=409,
            detail=f"{pip_no} must be Active (acknowledged) before a review can be recorded.")

    now = datetime.now(timezone.utc)
    entry = {
        "at": now, "by": str(actor.get("_id") or ""),
        "progress": payload.get("progress"), "evidence": payload.get("evidence"),
        "manager_comments": payload.get("manager_comments"),
        "employee_comments": payload.get("employee_comments"),
    }
    await get_collection(COLL_PIP_RECORDS).update_one(
        {"_id": doc["_id"]}, {"$push": {"reviews": entry}, "$set": {"updated_at": now}})
    await audit(actor, AUDIT_PIP_REVIEW_ADDED, ENTITY_PIP, pip_no, payload.get("progress"), company_id)
    return await get_pip(actor, company_id, pip_no)


async def decide_pip(actor: dict, company_id: str, pip_no: str, payload: dict) -> dict:
    """§22.5 step 220-221: the outcome. "Separation Recommended" does not itself initiate a
    separation — that stays a distinct, deliberate act through Exit Management, the same
    "no workflow silently triggers another" boundary Phase MOVE-1's absconding-to-separation
    hand-off crosses only on an explicit final action, never automatically."""
    doc = await _get_pip(company_id, pip_no)
    if doc["status"] not in (PipStatus.ACTIVE.value, PipStatus.DRAFT.value):
        raise HTTPException(status_code=409, detail=f"{pip_no} is already \"{doc['status']}\".")

    now = datetime.now(timezone.utc)
    await get_collection(COLL_PIP_RECORDS).update_one(
        {"_id": doc["_id"]},
        {"$set": {"status": PipStatus.CLOSED.value,
                  "closure_result": payload.get("closure_result"),
                  "final_rating": payload.get("final_rating"),
                  "extension_date": payload.get("extension_date"),
                  "next_action": payload.get("next_action"),
                  "decided_by": str(actor.get("_id") or ""), "decided_at": now,
                  "decision_remarks": payload.get("remarks"), "updated_at": now}},
    )
    await audit(actor, AUDIT_PIP_DECIDED, ENTITY_PIP, pip_no, payload.get("closure_result"), company_id)
    return await get_pip(actor, company_id, pip_no)
