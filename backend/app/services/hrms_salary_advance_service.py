"""HRMS > Salary Advance (BA/Functional Design v2.2, §7.14).

Employee requests -> eligibility checked (confirmed employment, request-window, once-per-
quarter) -> maximum eligible amount computed from the configured percentage of gross ->
approved through the normal or emergency route -> disbursed with a recovery entry created for
the next payroll (auto-rolled-up by hrms_payroll_service.calculate_payroll, the same way F&F
rolls up asset/clearance recoveries) -> payroll deducts the recovery until the ledger closes.

-- The 40%/20th-25th/once-per-quarter numbers are POLICY, not hardcoded constants -----------
§7.14 BR: "Current policy baseline: 40% of gross, 20th-25th, once per quarter, confirmed
employees, next-month deduction." DEFAULT_ADVANCE_POLICY carries these as the adjustable
starting point (the same discipline DEFAULT_SHIFT_POLICY / DEFAULT_ABSCONDING_POLICY already
established), read from hrms_settings, editable by HR — never compiled into the eligibility
check as a literal number.
"""
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_ADVANCE_ACTIONED, AUDIT_ADVANCE_REQUESTED,
    COLL_EMPLOYEE_PROFILES, COLL_PROBATION_REVIEWS, COLL_SALARY_ADVANCES, COLL_SETTINGS,
    DEFAULT_ADVANCE_POLICY,
    ENTITY_ADVANCE, OPEN_ADVANCE_STATUSES,
    AdvanceStatus, ProbationOutcome,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.services.hrms_payroll_service import get_current_structure, _structure_gross, _load_component_types


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _quarter_of(d: date) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


async def _get_profile(company_id: str, employee_code: str) -> dict:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        raise HTTPException(status_code=404, detail="No employee with that code in this company.")
    return profile


async def _is_confirmed(company_id: str, employee_code: str) -> bool:
    """§7.14 step 101: "employment status = Confirmed" — this module has no such status
    value (EmploymentStatus has none either); "confirmed" means NOT on probation, the same
    check hrms_exit_service._is_on_probation already makes for the same reason."""
    row = await get_collection(COLL_PROBATION_REVIEWS).find_one(
        {"company_id": str(company_id), "employee_code": employee_code},
        sort=[("started_on", -1)])
    if not row:
        return True   # no probation record on file reads as already confirmed
    return row.get("outcome") not in (ProbationOutcome.PENDING.value, ProbationOutcome.EXTENDED.value)


async def get_advance_policy(company_id: str) -> dict:
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)})
    stored = (doc or {}).get("advance_policy") or {}
    return {**DEFAULT_ADVANCE_POLICY, **stored}


async def save_advance_policy(actor: dict, company_id: str, payload: dict) -> dict:
    merged = {**await get_advance_policy(company_id),
             **{k: v for k, v in payload.items() if v is not None}}
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": str(company_id)},
        {"$set": {"advance_policy": merged, "updated_at": datetime.now(timezone.utc)},
         "$setOnInsert": {"company_id": str(company_id)}},
        upsert=True,
    )
    return merged


async def _max_eligible(company_id: str, employee_code: str, policy: dict) -> float:
    await _load_component_types(company_id)
    structure = await get_current_structure(company_id, employee_code)
    gross = _structure_gross(structure)
    if not gross:
        profile = await _get_profile(company_id, employee_code)
        gross = float(profile.get("base_salary") or 0)
    return round(gross * (policy["max_percent_of_gross"] / 100.0), 2)


async def check_eligibility(actor: dict, company_id: str, employee_code: str) -> dict:
    """Exposed as its own read so the UI can show WHY before the employee even opens the
    request form (§7.14 steps 101-104), not only reject after submission."""
    policy = await get_advance_policy(company_id)
    today = _today()
    confirmed = await _is_confirmed(company_id, employee_code)
    in_window = policy["window_start_day"] <= today.day <= policy["window_end_day"]
    quarter = _quarter_of(today)
    already_this_quarter = await get_collection(COLL_SALARY_ADVANCES).find_one({
        "company_id": str(company_id), "employee_code": employee_code, "quarter": quarter,
        "status": {"$in": list(OPEN_ADVANCE_STATUSES)},
    })
    max_eligible = await _max_eligible(company_id, employee_code, policy)
    return {
        "confirmed": confirmed, "in_window": in_window, "quarter": quarter,
        "already_availed_this_quarter": bool(already_this_quarter),
        "max_eligible_amount": max_eligible,
        "eligible": confirmed and in_window and not already_this_quarter and max_eligible > 0,
    }


async def request_advance(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    amount = float(payload.get("amount") or 0)
    if not employee_code or amount <= 0:
        raise HTTPException(status_code=422, detail="employee_code and a positive amount are required.")
    profile = await _get_profile(company_id, employee_code)

    eligibility = await check_eligibility(actor, company_id, employee_code)
    if not eligibility["confirmed"]:
        raise HTTPException(status_code=422, detail="Only confirmed employees may request a salary advance.")
    if not eligibility["in_window"]:
        policy = await get_advance_policy(company_id)
        raise HTTPException(
            status_code=422,
            detail=f"Requests are only accepted between day {policy['window_start_day']} and "
                   f"{policy['window_end_day']} of the month.")
    if eligibility["already_availed_this_quarter"]:
        raise HTTPException(status_code=409, detail="An advance has already been availed this quarter.")
    if amount > eligibility["max_eligible_amount"]:
        raise HTTPException(
            status_code=422,
            detail=f"Amount exceeds the maximum eligible ({eligibility['max_eligible_amount']}).")

    year = datetime.now(timezone.utc).year
    adv_no = await next_business_id("advance", str(company_id), year)
    now = datetime.now(timezone.utc)
    doc = {
        "adv_no": adv_no, "company_id": str(company_id), "employee_code": employee_code,
        "employee_name": profile.get("display_name") or profile.get("full_name"),
        "amount": amount, "max_eligible_amount": eligibility["max_eligible_amount"],
        "reason": payload.get("reason"), "quarter": eligibility["quarter"],
        "status": AdvanceStatus.PENDING.value,
        "action_by": None, "action_at": None, "action_remarks": None,
        "recovered_amount": 0, "disbursed_at": None,
        "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_SALARY_ADVANCES).insert_one(doc)
    await audit(actor, AUDIT_ADVANCE_REQUESTED, ENTITY_ADVANCE, adv_no,
               f"{employee_code}, {amount}", company_id)
    return _out(doc)


async def list_advances(actor: dict, company_id: str, *, status: Optional[str] = None,
                        employee_code: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if employee_code:
        query["employee_code"] = employee_code
    rows = await get_collection(COLL_SALARY_ADVANCES).find(query).sort(
        "created_at", -1).to_list(limit)
    return [_out(r) for r in rows]


async def _get_advance(company_id: str, adv_no: str) -> dict:
    doc = await get_collection(COLL_SALARY_ADVANCES).find_one(
        {"company_id": str(company_id), "adv_no": adv_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Salary advance '{adv_no}' not found.")
    return doc


async def get_advance(actor: dict, company_id: str, adv_no: str) -> dict:
    return _out(await _get_advance(company_id, adv_no))


async def act_on_advance(actor: dict, company_id: str, adv_no: str, payload: dict) -> dict:
    """§7.14 steps 106-107: approval through the normal or emergency route (the ROUTE layer
    picks which capability is required; this function does not distinguish the two, since
    once authorised, an approval is an approval)."""
    doc = await _get_advance(company_id, adv_no)
    if doc["status"] != AdvanceStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"{adv_no} is already \"{doc['status']}\".")

    approved = bool(payload.get("approved"))
    now = datetime.now(timezone.utc)
    new_status = AdvanceStatus.RECOVERING.value if approved else AdvanceStatus.REJECTED.value
    updates = {"status": new_status, "action_by": str(actor.get("_id") or ""),
              "action_at": now, "action_remarks": payload.get("remarks"), "updated_at": now}
    if approved:
        updates["disbursed_at"] = now
    await get_collection(COLL_SALARY_ADVANCES).update_one({"_id": doc["_id"]}, {"$set": updates})
    await audit(actor, AUDIT_ADVANCE_ACTIONED, ENTITY_ADVANCE, adv_no, new_status, company_id)
    return await get_advance(actor, company_id, adv_no)
