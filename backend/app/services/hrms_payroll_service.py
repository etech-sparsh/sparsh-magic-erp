"""HRMS > Payroll (BA/Functional Design v2.2, §7.13, §22.7).

Component-driven, not a fixed set of fields (§22.7): a salary STRUCTURE is a list of
{component, amount} rows against a small configurable component MASTER — the same
"master + assignment" split hrms_designations/hrms_employee_profiles already uses.

A payroll run per (company, period): create -> import each eligible employee's structure,
prorated against Attendance's locked payable/LOP days (Phase ATT-1) -> auto-roll-up open
salary-advance recovery and the quarter's approved variable-pay payout, the same way F&F
auto-rolls-up asset/clearance recoveries -> statutory figures (PF/ESI/PT/TDS) entered by hand,
because §7.13's own BR says "Detailed statutory and salary-component configuration requires
payroll workshop" -> maker resolves exceptions and reruns -> checker approves -> LOCKED.

-- Post-lock changes must not directly rewrite final payroll (§7.13 BR) -------------------
Once a run is Locked, `calculate_payroll` and `adjust_record` both refuse — the only way
forward is the same "authorised adjustment" pattern Attendance's monthly lock already uses:
this phase does not build a reversal/arrear workflow, so a locked run is genuinely frozen.
"""
from calendar import monthrange
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_PAYROLL_ADJUSTMENTS_SET, AUDIT_PAYROLL_CALCULATED, AUDIT_PAYROLL_DECIDED,
    AUDIT_PAYROLL_RECORD_ADJUSTED,
    AUDIT_PAYROLL_RUN_CREATED, AUDIT_SALARY_COMPONENT_SAVED, AUDIT_SALARY_STRUCTURE_SAVED,
    COLL_ATTENDANCE, COLL_EMPLOYEE_PROFILES, COLL_PAYROLL_RECORDS, COLL_PAYROLL_RUNS,
    COLL_SALARY_ADVANCES, COLL_SALARY_COMPONENTS, COLL_SALARY_STRUCTURES,
    COLL_VARIABLE_PAY_RECORDS,
    ENTITY_PAYROLL_RUN, ENTITY_SALARY_COMPONENT, ENTITY_SALARY_STRUCTURE,
    MAX_PAYROLL_LIST_PAGE,
    AdvanceStatus, AttendanceStatus, ComponentType, HrmsRole, OPEN_ADVANCE_STATUSES,
    PayrollRunStatus,
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


# ─────────────────────────────────────────────────────────────
# §22.7 — salary component master + per-employee structure
# ─────────────────────────────────────────────────────────────
async def save_salary_component(actor: dict, company_id: str, payload: dict) -> dict:
    code = str(payload.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=422, detail="A component code is required.")
    now = datetime.now(timezone.utc)
    clean = {k: v for k, v in payload.items() if k != "code"}
    clean["updated_at"] = now
    await get_collection(COLL_SALARY_COMPONENTS).update_one(
        {"company_id": str(company_id), "code": code},
        {"$set": clean, "$setOnInsert": {"company_id": str(company_id), "code": code,
                                         "created_at": now}},
        upsert=True,
    )
    await audit(actor, AUDIT_SALARY_COMPONENT_SAVED, ENTITY_SALARY_COMPONENT, code,
               payload.get("component_type"), company_id)
    doc = await get_collection(COLL_SALARY_COMPONENTS).find_one(
        {"company_id": str(company_id), "code": code})
    return _out(doc)


async def list_salary_components(actor: dict, company_id: str) -> list:
    rows = await get_collection(COLL_SALARY_COMPONENTS).find(
        {"company_id": str(company_id)}).sort("code", 1).to_list(200)
    return [_out(r) for r in rows]


async def save_salary_structure(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    await _get_profile(company_id, employee_code)
    components = payload.get("components") or []
    if not components:
        raise HTTPException(status_code=422, detail="At least one component is required.")

    known = {c["code"] for c in await list_salary_components(actor, company_id)}
    for c in components:
        code = c.get("code") if isinstance(c, dict) else c.code
        if code not in known:
            raise HTTPException(status_code=422, detail=f"Unknown salary component '{code}'.")

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "employee_code": employee_code,
        "effective_from": payload.get("effective_from"),
        "components": [dict(c) if isinstance(c, dict) else c.model_dump() for c in components],
        "created_at": now, "updated_at": now,
    }
    result = await get_collection(COLL_SALARY_STRUCTURES).insert_one(doc)
    doc["id"] = str(result.inserted_id)
    await audit(actor, AUDIT_SALARY_STRUCTURE_SAVED, ENTITY_SALARY_STRUCTURE, employee_code,
               f"effective {payload.get('effective_from')}", company_id)
    return _out(doc)


async def get_current_structure(company_id: str, employee_code: str,
                                as_of: Optional[str] = None) -> Optional[dict]:
    """The latest structure whose effective_from is on or before `as_of` (default today) —
    never overwritten, the same never-edit-history discipline Phase MOVE-1's movements use."""
    as_of = as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    doc = await get_collection(COLL_SALARY_STRUCTURES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code,
         "effective_from": {"$lte": as_of}},
        sort=[("effective_from", -1)],
    )
    return _out(doc) if doc else None


async def list_structure_history(actor: dict, company_id: str, employee_code: str) -> list:
    rows = await get_collection(COLL_SALARY_STRUCTURES).find(
        {"company_id": str(company_id), "employee_code": employee_code}
    ).sort("effective_from", -1).to_list(100)
    return [_out(r) for r in rows]


# A tiny process-local cache of component_type by code, refreshed by _load_component_types
# before each run's calculation — avoids one query per component per employee at scale,
# the same reasoning hrms_sla_service resolves config once per loop rather than per record.
# `_structure_gross` always filters through it rather than branching on whether the cache
# happens to be non-empty: a genuinely component-free company must sum to 0, not fall back
# to summing deduction rows into "gross" by accident.
_component_type_cache: dict = {}


async def _load_component_types(company_id: str) -> None:
    global _component_type_cache
    rows = await list_salary_components(None, company_id)
    _component_type_cache = {r["code"]: r["component_type"] for r in rows}


def _structure_gross(structure: Optional[dict]) -> float:
    if not structure:
        return 0.0
    return round(sum(
        float(c.get("amount") or 0) for c in structure.get("components", [])
        if _component_type_cache.get(c.get("code")) == ComponentType.EARNING.value
    ), 2)


# ─────────────────────────────────────────────────────────────
# §7.12 integration — payable/LOP days from Attendance's own records
# ─────────────────────────────────────────────────────────────
async def _payable_days(company_id: str, employee_code: str, period: str) -> dict:
    """Every day in the period is either payable or LOP: Present/Half-Day/On Leave/On OD/
    Weekly Off/Holiday count as (fully or half) payable; Absent and a day with NO attendance
    row at all count as LOP — the safer-for-the-company default where the record is silent,
    the same principle notice_days_for's own default level follows."""
    year, month = (int(x) for x in period.split("-"))
    days_in_period = monthrange(year, month)[1]
    rows = await get_collection(COLL_ATTENDANCE).find(
        {"company_id": str(company_id), "employee_code": employee_code,
         "work_date": {"$gte": f"{period}-01", "$lte": f"{period}-{days_in_period:02d}"}},
        {"status": 1},
    ).to_list(40)

    captured = len(rows)
    lop_days = float(days_in_period - captured)   # uncaptured days default to LOP
    for r in rows:
        if r["status"] == AttendanceStatus.ABSENT.value:
            lop_days += 1
        elif r["status"] == AttendanceStatus.HALF_DAY.value:
            lop_days += 0.5
    payable_days = round(days_in_period - lop_days, 2)
    return {"days_in_period": days_in_period, "payable_days": payable_days,
           "lop_days": round(lop_days, 2)}


# ─────────────────────────────────────────────────────────────
# §7.13 — payroll run
# ─────────────────────────────────────────────────────────────
async def create_run(actor: dict, company_id: str, payload: dict) -> dict:
    period = payload.get("period")
    existing = await get_collection(COLL_PAYROLL_RUNS).find_one(
        {"company_id": str(company_id), "period": period})
    if existing:
        raise HTTPException(status_code=409, detail=f"A payroll run for {period} already exists.")

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "period": period, "status": PayrollRunStatus.DRAFT.value,
        "eligible_count": 0, "created_by": str(actor.get("_id") or ""), "created_at": now,
        "calculated_at": None, "decided_by": None, "decided_at": None, "decision_remarks": None,
        "locked_at": None, "updated_at": now,
    }
    await get_collection(COLL_PAYROLL_RUNS).insert_one(doc)
    await audit(actor, AUDIT_PAYROLL_RUN_CREATED, ENTITY_PAYROLL_RUN, period, None, company_id)
    return _out(doc)


async def list_runs(actor: dict, company_id: str, limit: int = 100) -> list:
    rows = await get_collection(COLL_PAYROLL_RUNS).find(
        {"company_id": str(company_id)}).sort("period", -1).to_list(min(limit, MAX_PAYROLL_LIST_PAGE))
    return [_out(r) for r in rows]


async def _get_run(company_id: str, period: str) -> dict:
    doc = await get_collection(COLL_PAYROLL_RUNS).find_one(
        {"company_id": str(company_id), "period": period})
    if not doc:
        raise HTTPException(status_code=404, detail=f"No payroll run for {period}.")
    return doc


async def get_run(actor: dict, company_id: str, period: str) -> dict:
    return _out(await _get_run(company_id, period))


async def calculate_payroll(actor: dict, company_id: str, period: str) -> dict:
    """§7.13 steps 91-94: determine the eligible population, load structures, import locked
    attendance/LOP + open salary-advance recovery + the quarter's approved variable pay, run
    the calculation. Safe to call again (Payroll Maker "resolves issues and reruns", step 96)
    — each call replaces this run's records rather than appending to them, as long as the run
    is not yet Locked."""
    run = await _get_run(company_id, period)
    if run["status"] == PayrollRunStatus.LOCKED.value:
        raise HTTPException(status_code=409, detail="Post-lock changes must not directly "
                                                     "rewrite final payroll (§7.13 BR).")

    await _load_component_types(company_id)
    profiles = await get_collection(COLL_EMPLOYEE_PROFILES).find(
        {"company_id": str(company_id), "employment_status": "Active"}).to_list(2000)

    now = datetime.now(timezone.utc)
    await get_collection(COLL_PAYROLL_RECORDS).delete_many(
        {"company_id": str(company_id), "period": period})

    for profile in profiles:
        employee_code = profile["employee_code"]
        structure = await get_current_structure(company_id, employee_code, f"{period}-28")
        gross_structured = _structure_gross(structure)
        days = await _payable_days(company_id, employee_code, period)
        proration = (days["payable_days"] / days["days_in_period"]) if days["days_in_period"] else 0
        prorated_gross = round(gross_structured * proration, 2)

        # Auto roll-up: open salary-advance recovery for this employee (§7.13 step 93).
        advance = await get_collection(COLL_SALARY_ADVANCES).find_one({
            "company_id": str(company_id), "employee_code": employee_code,
            "status": AdvanceStatus.RECOVERING.value,
        })
        advance_recovery = 0.0
        if advance:
            outstanding = float(advance["amount"]) - float(advance.get("recovered_amount") or 0)
            advance_recovery = round(min(outstanding, float(advance["amount"])), 2)

        # Auto roll-up: this quarter's approved, not-yet-paid variable pay for this employee.
        vp_record = await get_collection(COLL_VARIABLE_PAY_RECORDS).find_one({
            "company_id": str(company_id), "employee_code": employee_code,
            "status": "Approved", "paid_in_period": None,
        })
        variable_pay_payout = float(vp_record["payable_portion"]) if vp_record else 0.0

        exceptions = []
        if not structure:
            exceptions.append("No salary structure on file — gross earnings are 0.")

        doc = {
            "company_id": str(company_id), "period": period, "employee_code": employee_code,
            "employee_name": profile.get("display_name") or profile.get("full_name"),
            "days_in_period": days["days_in_period"], "payable_days": days["payable_days"],
            "lop_days": days["lop_days"],
            "structured_gross": gross_structured, "prorated_gross": prorated_gross,
            "advance_recovery": advance_recovery, "variable_pay_payout": variable_pay_payout,
            "vp_record_id": str(vp_record["_id"]) if vp_record else None,
            "advance_id": str(advance["_id"]) if advance else None,
            # Statutory + manual figures default to 0 until the maker adjusts them.
            "pf": 0, "esi": 0, "pt": 0, "tds": 0, "arrears": 0, "reimbursements": 0,
            "other_earnings": 0, "other_deductions": 0, "notice_recovery": 0, "remarks": None,
            # §22.7 — arbitrary named lines against the same component master the salary
            # structure uses, alongside (not instead of) the fixed fields above. Reset on
            # recalculation like every other hand-entered figure here: a rerun replaces the
            # whole record, so the maker re-adds ad-hoc lines after, same as PF/ESI/etc.
            "adjustments": [],
            "exceptions": exceptions,
            "created_at": now, "updated_at": now,
        }
        doc.update(_totals(doc))
        await get_collection(COLL_PAYROLL_RECORDS).insert_one(doc)

    await get_collection(COLL_PAYROLL_RUNS).update_one(
        {"_id": run["_id"]},
        {"$set": {"status": PayrollRunStatus.CALCULATED.value, "eligible_count": len(profiles),
                  "calculated_at": now, "updated_at": now}},
    )
    await audit(actor, AUDIT_PAYROLL_CALCULATED, ENTITY_PAYROLL_RUN, period,
               f"{len(profiles)} employee(s)", company_id)
    return await get_run(actor, company_id, period)


def _adjustment_sum(record: dict, component_type: str) -> float:
    return sum(float(a.get("amount") or 0) for a in (record.get("adjustments") or [])
              if a.get("component_type") == component_type)


def _totals(record: dict) -> dict:
    gross = (record["prorated_gross"] + record["variable_pay_payout"] + record["arrears"]
            + record["reimbursements"] + record["other_earnings"]
            + _adjustment_sum(record, ComponentType.EARNING.value))
    deductions = (record["pf"] + record["esi"] + record["pt"] + record["tds"]
                 + record["advance_recovery"] + record["notice_recovery"]
                 + record["other_deductions"]
                 + _adjustment_sum(record, ComponentType.DEDUCTION.value))
    return {"gross_earnings": round(gross, 2), "total_deductions": round(deductions, 2),
           "net_pay": round(gross - deductions, 2)}


async def _own_employee_code(actor: dict, company_id: str) -> Optional[str]:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": str(actor.get("_id") or "")})
    return (profile or {}).get("employee_code")


async def list_records(actor: dict, company_id: str, period: str) -> list:
    """An EMPLOYEE caller (PAYROLL_READ granted for self-service payslip access only, see
    that capability's own comment in models/hrms.py) is scoped to their OWN record — the
    same enforced-ownership pattern PIP/Letters/Appointments already establish. Every other
    role holding PAYROLL_READ sees the run's full population, as before."""
    query = {"company_id": str(company_id), "period": period}
    if hrms_role(actor) == HrmsRole.EMPLOYEE:
        own = await _own_employee_code(actor, company_id)
        query["employee_code"] = own or "__none__"
    rows = await get_collection(COLL_PAYROLL_RECORDS).find(query
    ).sort("employee_code", 1).to_list(MAX_PAYROLL_LIST_PAGE)
    return [_out(r) for r in rows]


async def adjust_record(actor: dict, company_id: str, period: str, employee_code: str,
                        payload: dict) -> dict:
    """The maker's hand-entered statutory and one-off figures — §7.13's own BR: no
    statutory engine exists, so PF/ESI/PT/TDS/arrears/reimbursements/other lines are always
    entered here, never computed."""
    run = await _get_run(company_id, period)
    if run["status"] == PayrollRunStatus.LOCKED.value:
        raise HTTPException(status_code=409, detail="Post-lock changes must not directly "
                                                     "rewrite final payroll (§7.13 BR).")
    record = await get_collection(COLL_PAYROLL_RECORDS).find_one(
        {"company_id": str(company_id), "period": period, "employee_code": employee_code})
    if not record:
        raise HTTPException(status_code=404, detail="No payroll record for that employee in this run.")

    clean = {k: float(v) for k, v in payload.items() if k != "remarks" and v is not None}
    if "remarks" in payload and payload["remarks"] is not None:
        clean["remarks"] = payload["remarks"]
    merged = {**record, **clean}
    merged.update(_totals(merged))
    now = datetime.now(timezone.utc)
    merged["updated_at"] = now
    await get_collection(COLL_PAYROLL_RECORDS).update_one(
        {"_id": record["_id"]}, {"$set": {k: v for k, v in merged.items() if k != "_id"}})
    await audit(actor, AUDIT_PAYROLL_RECORD_ADJUSTED, ENTITY_PAYROLL_RUN, f"{period}:{employee_code}",
               None, company_id)
    saved = await get_collection(COLL_PAYROLL_RECORDS).find_one({"_id": record["_id"]})
    return _out(saved)


async def set_adjustments(actor: dict, company_id: str, period: str, employee_code: str,
                          payload: dict) -> dict:
    """§22.7 — replace this employee's ad-hoc component lines for the period, against the
    SAME component master the salary structure uses. Additive alongside `adjust_record`'s
    fixed PF/ESI/arrears/etc. fields, not a replacement for them — a company that never
    touches this still gets exactly the payroll it had before this phase."""
    run = await _get_run(company_id, period)
    if run["status"] == PayrollRunStatus.LOCKED.value:
        raise HTTPException(status_code=409, detail="Post-lock changes must not directly "
                                                     "rewrite final payroll (§7.13 BR).")
    record = await get_collection(COLL_PAYROLL_RECORDS).find_one(
        {"company_id": str(company_id), "period": period, "employee_code": employee_code})
    if not record:
        raise HTTPException(status_code=404, detail="No payroll record for that employee in this run.")

    known = {c["code"]: c for c in await list_salary_components(actor, company_id)}
    resolved = []
    for item in payload.get("adjustments") or []:
        code = item.get("code") if isinstance(item, dict) else item.code
        amount = item.get("amount") if isinstance(item, dict) else item.amount
        meta = known.get(code)
        if not meta:
            raise HTTPException(status_code=422, detail=f"Unknown salary component '{code}'.")
        resolved.append({"code": code, "name": meta.get("name"),
                         "component_type": meta.get("component_type"),
                         "amount": round(float(amount or 0), 2)})

    merged = {**record, "adjustments": resolved}
    merged.update(_totals(merged))
    now = datetime.now(timezone.utc)
    merged["updated_at"] = now
    await get_collection(COLL_PAYROLL_RECORDS).update_one(
        {"_id": record["_id"]}, {"$set": {k: v for k, v in merged.items() if k != "_id"}})
    await audit(actor, AUDIT_PAYROLL_ADJUSTMENTS_SET, ENTITY_PAYROLL_RUN,
               f"{period}:{employee_code}", f"{len(resolved)} line(s)", company_id)
    saved = await get_collection(COLL_PAYROLL_RECORDS).find_one({"_id": record["_id"]})
    return _out(saved)


async def decide_run(actor: dict, company_id: str, period: str, payload: dict) -> dict:
    """§7.13 steps 97-98: the checker approves (locking the run and every record's advance/
    variable-pay recovery in the same transition) or rejects (back to the maker)."""
    run = await _get_run(company_id, period)
    if run["status"] not in (PayrollRunStatus.CALCULATED.value, PayrollRunStatus.REJECTED.value):
        raise HTTPException(
            status_code=409,
            detail=f"{period} must be Calculated before a decision (currently \"{run['status']}\").")

    now = datetime.now(timezone.utc)
    approved = bool(payload.get("approved"))
    new_status = PayrollRunStatus.LOCKED.value if approved else PayrollRunStatus.REJECTED.value
    updates = {"status": new_status, "decided_by": str(actor.get("_id") or ""),
              "decided_at": now, "decision_remarks": payload.get("remarks"), "updated_at": now}
    if approved:
        updates["locked_at"] = now

    await get_collection(COLL_PAYROLL_RUNS).update_one({"_id": run["_id"]}, {"$set": updates})

    if approved:
        records = await get_collection(COLL_PAYROLL_RECORDS).find(
            {"company_id": str(company_id), "period": period}).to_list(MAX_PAYROLL_LIST_PAGE)
        for record in records:
            if record.get("advance_id") and record["advance_recovery"] > 0:
                await _apply_advance_recovery(company_id, record["advance_id"], record["advance_recovery"])
            if record.get("vp_record_id"):
                await get_collection(COLL_VARIABLE_PAY_RECORDS).update_one(
                    {"_id": ObjectId(record["vp_record_id"])},
                    {"$set": {"paid_in_period": period}})

    await audit(actor, AUDIT_PAYROLL_DECIDED, ENTITY_PAYROLL_RUN, period, new_status, company_id)
    return await get_run(actor, company_id, period)


async def _apply_advance_recovery(company_id: str, advance_id: str, amount: float) -> None:
    from bson import ObjectId
    advance = await get_collection(COLL_SALARY_ADVANCES).find_one({"_id": ObjectId(advance_id)})
    if not advance:
        return
    recovered = float(advance.get("recovered_amount") or 0) + amount
    status = (AdvanceStatus.CLOSED.value if recovered >= float(advance["amount"])
             else AdvanceStatus.RECOVERING.value)
    await get_collection(COLL_SALARY_ADVANCES).update_one(
        {"_id": advance["_id"]},
        {"$set": {"recovered_amount": round(recovered, 2), "status": status,
                  "updated_at": datetime.now(timezone.utc)}},
    )
