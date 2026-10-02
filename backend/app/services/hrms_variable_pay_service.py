"""HRMS > Variable Pay Quarterly (BA/Functional Design v2.2, §7.15).

Create a quarter and lock the ORM score -> import/enter each employee's IRM score and
quarterly target amount -> validate eligibility (confirmed, i.e. probation completed) ->
apply the ORM entry threshold (company-wide gate) and the IRM threshold (per employee) ->
apply the approved multiplier slab -> split into payable (flows to the next payroll run,
auto-rolled-up by hrms_payroll_service the same way F&F rolls up asset/clearance recoveries)
and held (sits in a hold ledger until release or forfeiture at FY-end / an eligibility
milestone) -> maker reviews -> approver confirms the batch.

-- IRM scores are entered by hand here, not pulled from the existing IRM module -------------
A separate IRM module already exists in this codebase, but it keys on its own `person_id`,
not this module's `employee_code` — wiring the two together is a real, separate integration
this phase does not attempt. The BA doc itself offers "Import/enter" as two acceptable paths
(step 111), so hand entry is a sanctioned fallback, not a shortcut around a requirement.

-- ORM >=80% / IRM >=70% / 75%-25% split / the multiplier slabs are POLICY, not hardcoded ---
§7.15 BR: "Current policy: ORM >=80%, IRM >=70%; 75% payable quarterly and 25% held." An
adjustable default (DEFAULT_VARIABLE_PAY_POLICY), read from hrms_settings. The multiplier
TABLE itself (variable_pay_multiplier in models/hrms.py) is a pure function matching the
BA doc's literal band wording, kept separate from configuration for the same reason
notice_days_for's matrix is a function rather than a settings blob.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_VP_CALCULATED, AUDIT_VP_DECIDED, AUDIT_VP_HOLD_ACTIONED, AUDIT_VP_QUARTER_CREATED,
    AUDIT_VP_RECORD_SAVED,
    COLL_EMPLOYEE_PROFILES, COLL_PROBATION_REVIEWS, COLL_SETTINGS,
    COLL_VARIABLE_PAY_HOLD_LEDGER, COLL_VARIABLE_PAY_QUARTERS, COLL_VARIABLE_PAY_RECORDS,
    DEFAULT_VARIABLE_PAY_POLICY,
    ENTITY_HOLD_LEDGER, ENTITY_VARIABLE_PAY_QUARTER, MAX_PAYROLL_LIST_PAGE,
    HoldLedgerStatus, ProbationOutcome, VariablePayQuarterStatus,
    variable_pay_multiplier,
)
from app.services.hrms_audit_service import audit


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _out_with_id(doc: dict) -> dict:
    """Like `_out`, but for hold-ledger rows, which carry no business id of their own (no
    "no_" sequence is minted for them — see the ID_FORMATS comment in models/hrms.py) — the
    Mongo `_id` IS their identity, so it is kept, as a string, the exact convention
    hrms_exit_service uses for handover/clearance/access-clearance items for the same
    reason."""
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


async def _get_profile(company_id: str, employee_code: str) -> dict:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        raise HTTPException(status_code=404, detail="No employee with that code in this company.")
    return profile


async def _is_confirmed(company_id: str, employee_code: str) -> bool:
    row = await get_collection(COLL_PROBATION_REVIEWS).find_one(
        {"company_id": str(company_id), "employee_code": employee_code},
        sort=[("started_on", -1)])
    if not row:
        return True
    return row.get("outcome") not in (ProbationOutcome.PENDING.value, ProbationOutcome.EXTENDED.value)


async def get_variable_pay_policy(company_id: str) -> dict:
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)})
    stored = (doc or {}).get("variable_pay_policy") or {}
    return {**DEFAULT_VARIABLE_PAY_POLICY, **stored}


async def save_variable_pay_policy(actor: dict, company_id: str, payload: dict) -> dict:
    merged = {**await get_variable_pay_policy(company_id),
             **{k: v for k, v in payload.items() if v is not None}}
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": str(company_id)},
        {"$set": {"variable_pay_policy": merged, "updated_at": datetime.now(timezone.utc)},
         "$setOnInsert": {"company_id": str(company_id)}},
        upsert=True,
    )
    return merged


async def create_quarter(actor: dict, company_id: str, payload: dict) -> dict:
    quarter = payload.get("quarter")
    existing = await get_collection(COLL_VARIABLE_PAY_QUARTERS).find_one(
        {"company_id": str(company_id), "quarter": quarter})
    if existing:
        raise HTTPException(status_code=409, detail=f"A variable pay quarter for {quarter} already exists.")

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "quarter": quarter,
        "orm_score": float(payload.get("orm_score") or 0),
        "status": VariablePayQuarterStatus.DRAFT.value,
        "created_by": str(actor.get("_id") or ""), "created_at": now,
        "calculated_at": None, "decided_by": None, "decided_at": None, "decision_remarks": None,
        "updated_at": now,
    }
    await get_collection(COLL_VARIABLE_PAY_QUARTERS).insert_one(doc)
    await audit(actor, AUDIT_VP_QUARTER_CREATED, ENTITY_VARIABLE_PAY_QUARTER, quarter,
               f"ORM {doc['orm_score']}", company_id)
    return _out(doc)


async def list_quarters(actor: dict, company_id: str, limit: int = 50) -> list:
    rows = await get_collection(COLL_VARIABLE_PAY_QUARTERS).find(
        {"company_id": str(company_id)}).sort("quarter", -1).to_list(limit)
    return [_out(r) for r in rows]


async def _get_quarter(company_id: str, quarter: str) -> dict:
    doc = await get_collection(COLL_VARIABLE_PAY_QUARTERS).find_one(
        {"company_id": str(company_id), "quarter": quarter})
    if not doc:
        raise HTTPException(status_code=404, detail=f"No variable pay quarter '{quarter}'.")
    return doc


async def get_quarter(actor: dict, company_id: str, quarter: str) -> dict:
    return _out(await _get_quarter(company_id, quarter))


async def save_record(actor: dict, company_id: str, quarter: str, payload: dict) -> dict:
    """§7.15 step 111: enter (or re-enter) one employee's IRM score and quarterly target
    amount. Safe to call again before the quarter is calculated — each call replaces this
    employee's row for the quarter."""
    q = await _get_quarter(company_id, quarter)
    if q["status"] not in (VariablePayQuarterStatus.DRAFT.value,):
        raise HTTPException(
            status_code=409,
            detail=f"{quarter} is already \"{q['status']}\" — scores can only be entered "
                   f"while the quarter is in Draft.")

    employee_code = str(payload.get("employee_code") or "").strip()
    profile = await _get_profile(company_id, employee_code)
    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "quarter": quarter, "employee_code": employee_code,
        "employee_name": profile.get("display_name") or profile.get("full_name"),
        "irm_score": float(payload.get("irm_score") or 0),
        "quarterly_target_amount": float(payload.get("quarterly_target_amount") or 0),
        "eligible": None, "ineligible_reason": None, "multiplier": None,
        "calculated_amount": None, "payable_portion": None, "held_portion": None,
        "status": "Draft", "paid_in_period": None,
        "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_VARIABLE_PAY_RECORDS).update_one(
        {"company_id": str(company_id), "quarter": quarter, "employee_code": employee_code},
        {"$set": doc}, upsert=True,
    )
    await audit(actor, AUDIT_VP_RECORD_SAVED, ENTITY_VARIABLE_PAY_QUARTER, f"{quarter}:{employee_code}",
               f"IRM {doc['irm_score']}", company_id)
    saved = await get_collection(COLL_VARIABLE_PAY_RECORDS).find_one(
        {"company_id": str(company_id), "quarter": quarter, "employee_code": employee_code})
    return _out(saved)


async def list_records(actor: dict, company_id: str, quarter: str) -> list:
    rows = await get_collection(COLL_VARIABLE_PAY_RECORDS).find(
        {"company_id": str(company_id), "quarter": quarter}
    ).sort("employee_code", 1).to_list(MAX_PAYROLL_LIST_PAGE)
    return [_out(r) for r in rows]


async def calculate_quarter(actor: dict, company_id: str, quarter: str) -> dict:
    """§7.15 steps 112-115: eligibility, thresholds, multiplier, split. The ORM threshold is
    a COMPANY-WIDE gate — if the quarter's own ORM score misses it, nobody in the quarter is
    eligible, whatever their individual IRM score, because the org-level trigger is what the
    doc names first ("Apply ORM entry threshold and IRM threshold")."""
    q = await _get_quarter(company_id, quarter)
    policy = await get_variable_pay_policy(company_id)
    orm_met = q["orm_score"] >= policy["orm_threshold"]

    records = await get_collection(COLL_VARIABLE_PAY_RECORDS).find(
        {"company_id": str(company_id), "quarter": quarter}).to_list(MAX_PAYROLL_LIST_PAGE)

    now = datetime.now(timezone.utc)
    for r in records:
        confirmed = await _is_confirmed(company_id, r["employee_code"])
        reasons = []
        if not orm_met:
            reasons.append(f"Company ORM {q['orm_score']}% is below the {policy['orm_threshold']}% threshold.")
        if r["irm_score"] < policy["irm_threshold"]:
            reasons.append(f"IRM {r['irm_score']}% is below the {policy['irm_threshold']}% threshold.")
        if not confirmed:
            reasons.append("Employee has not completed probation.")

        eligible = not reasons
        updates = {"eligible": eligible, "ineligible_reason": "; ".join(reasons) or None,
                  "status": "Calculated", "updated_at": now}
        if eligible:
            multiplier = variable_pay_multiplier(r["irm_score"])
            calculated = round(r["quarterly_target_amount"] * multiplier, 2)
            payable = round(calculated * policy["payable_percent"] / 100.0, 2)
            held = round(calculated - payable, 2)
            updates.update({"multiplier": multiplier, "calculated_amount": calculated,
                           "payable_portion": payable, "held_portion": held})
        else:
            updates.update({"multiplier": 0, "calculated_amount": 0, "payable_portion": 0, "held_portion": 0})
        await get_collection(COLL_VARIABLE_PAY_RECORDS).update_one({"_id": r["_id"]}, {"$set": updates})

    await get_collection(COLL_VARIABLE_PAY_QUARTERS).update_one(
        {"_id": q["_id"]},
        {"$set": {"status": VariablePayQuarterStatus.CALCULATED.value, "calculated_at": now,
                  "updated_at": now}},
    )
    await audit(actor, AUDIT_VP_CALCULATED, ENTITY_VARIABLE_PAY_QUARTER, quarter,
               f"{len(records)} employee(s), ORM met={orm_met}", company_id)
    return await get_quarter(actor, company_id, quarter)


async def decide_quarter(actor: dict, company_id: str, quarter: str, payload: dict) -> dict:
    """§7.15 steps 116-118: maker's exception review already happened by the time this is
    called (the UI shows every record); the approver confirms the batch, which flows the
    payable portion to payroll (via hrms_payroll_service's auto roll-up) and opens a hold-
    ledger entry for the held portion."""
    q = await _get_quarter(company_id, quarter)
    if q["status"] != VariablePayQuarterStatus.CALCULATED.value:
        raise HTTPException(status_code=409, detail=f"{quarter} must be Calculated before a decision.")

    approved = bool(payload.get("approved"))
    now = datetime.now(timezone.utc)
    new_status = VariablePayQuarterStatus.APPROVED.value if approved else VariablePayQuarterStatus.DRAFT.value
    await get_collection(COLL_VARIABLE_PAY_QUARTERS).update_one(
        {"_id": q["_id"]},
        {"$set": {"status": new_status, "decided_by": str(actor.get("_id") or ""),
                  "decided_at": now, "decision_remarks": payload.get("remarks"), "updated_at": now}},
    )

    if approved:
        records = await get_collection(COLL_VARIABLE_PAY_RECORDS).find(
            {"company_id": str(company_id), "quarter": quarter, "eligible": True}
        ).to_list(MAX_PAYROLL_LIST_PAGE)
        await get_collection(COLL_VARIABLE_PAY_RECORDS).update_many(
            {"company_id": str(company_id), "quarter": quarter, "eligible": True},
            {"$set": {"status": "Approved"}},
        )
        for r in records:
            if r["held_portion"] > 0:
                await get_collection(COLL_VARIABLE_PAY_HOLD_LEDGER).insert_one({
                    "company_id": str(company_id), "employee_code": r["employee_code"],
                    "quarter": quarter, "held_amount": r["held_portion"],
                    "status": HoldLedgerStatus.HELD.value,
                    "released_amount": 0, "release_or_forfeit_at": None, "remarks": None,
                    "created_at": now, "updated_at": now,
                })

    await audit(actor, AUDIT_VP_DECIDED, ENTITY_VARIABLE_PAY_QUARTER, quarter, new_status, company_id)
    return await get_quarter(actor, company_id, quarter)


async def list_hold_ledger(actor: dict, company_id: str, *, employee_code: Optional[str] = None,
                           status: Optional[str] = None, limit: int = 200) -> list:
    query = {"company_id": str(company_id)}
    if employee_code:
        query["employee_code"] = employee_code
    if status:
        query["status"] = status
    rows = await get_collection(COLL_VARIABLE_PAY_HOLD_LEDGER).find(query).sort(
        "created_at", -1).to_list(limit)
    return [_out_with_id(r) for r in rows]


async def act_on_hold(actor: dict, company_id: str, hold_id: str, payload: dict) -> dict:
    """§7.15 step 119: at FY-end or an eligibility milestone, release the held amount to the
    next payroll run's "other_earnings", or forfeit it. "If employee leaves before 12
    months, held 25% is not payable" — a departed employee's hold is auto-forfeited by
    forfeit_holds_for_separation below rather than left for someone to remember here."""
    from bson import ObjectId
    try:
        oid = ObjectId(str(hold_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid hold ledger id.")
    doc = await get_collection(COLL_VARIABLE_PAY_HOLD_LEDGER).find_one(
        {"_id": oid, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Hold ledger entry not found.")
    if doc["status"] != HoldLedgerStatus.HELD.value:
        raise HTTPException(status_code=409, detail=f"Already \"{doc['status']}\".")

    action = payload.get("action")
    now = datetime.now(timezone.utc)
    if action == "Release":
        updates = {"status": HoldLedgerStatus.RELEASED.value, "released_amount": doc["held_amount"],
                  "release_or_forfeit_at": now, "remarks": payload.get("remarks"), "updated_at": now}
    elif action == "Forfeit":
        updates = {"status": HoldLedgerStatus.FORFEITED.value, "released_amount": 0,
                  "release_or_forfeit_at": now, "remarks": payload.get("remarks"), "updated_at": now}
    else:
        raise HTTPException(status_code=422, detail="action must be 'Release' or 'Forfeit'.")

    await get_collection(COLL_VARIABLE_PAY_HOLD_LEDGER).update_one({"_id": oid}, {"$set": updates})
    await audit(actor, AUDIT_VP_HOLD_ACTIONED, ENTITY_HOLD_LEDGER, str(oid), action, company_id)
    saved = await get_collection(COLL_VARIABLE_PAY_HOLD_LEDGER).find_one({"_id": oid})
    return _out_with_id(saved)


async def forfeit_holds_for_separation(company_id: str, employee_code: str, sep_no: str) -> int:
    """§7.15 BR: "If employee leaves before 12 months, held 25% is not payable." Called from
    hrms_exit_service.close_separation so this happens by construction on every closure,
    rather than depending on someone remembering to check the ledger by hand. Returns the
    count forfeited, for the audit trail on the calling side."""
    now = datetime.now(timezone.utc)
    result = await get_collection(COLL_VARIABLE_PAY_HOLD_LEDGER).update_many(
        {"company_id": str(company_id), "employee_code": employee_code,
         "status": HoldLedgerStatus.HELD.value},
        {"$set": {"status": HoldLedgerStatus.FORFEITED.value, "released_amount": 0,
                  "release_or_forfeit_at": now, "remarks": f"Forfeited on separation {sep_no}",
                  "updated_at": now}},
    )
    return result.modified_count
