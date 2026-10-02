"""HRMS > the employee payslip (§7.13/§22.7, screens SM-HR-031/SM-HR-064).

hrms_payroll_service.py already builds a genuinely component-driven payroll RECORD —
prorated structure earnings, PF/ESI/PT/TDS, arrears, reimbursements, variable pay, advance
and notice recovery. What did not exist anywhere was an ITEMISED view of that record an
employee could actually read, and a way for an employee to reach their own record at all
(list_records required PAYROLL_READ with no self-scope branch). This module is that view.

-- Presentation, not a new source of numbers --------------------------------------------
Every figure here is read from hrms_payroll_records (already computed by the payroll run)
plus the employee's own salary structure (for line-item LABELS — "Basic", "HRA" — rather
than a single "structured_gross" total). Nothing is recalculated.

-- Rendering, not a stored artifact -------------------------------------------------------
Unlike Letters/Appointment/Offer, a payslip is not reissued or amended — it is a read of a
payroll run that itself becomes immutable when the run is Locked. So there is no PDF
generation or S3 storage here: the frontend renders this JSON as a document and the browser
prints it, the exact pattern Offer/Appointment letters already use for the same reason
(what must stay byte-identical between two renderings is cheaper to keep as one JSON shape
read by one component than as a server-rendered file).

-- Template configuration is deliberately thin ---------------------------------------------
§7.13's own BR: "Detailed statutory and salary-component configuration requires a payroll
workshop." Full payslip theming is out of scope until that workshop happens; what a company
can configure today is the header/footer note that appears on every payslip it issues.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    COLL_DEPARTMENTS, COLL_DESIGNATIONS,
    COLL_EMPLOYEE_PROFILES, COLL_PAYROLL_RECORDS, COLL_PAYROLL_RUNS, COLL_PAYROLL_TEMPLATES,
    COLL_SALARY_COMPONENTS, COLL_SALARY_STRUCTURES,
    ComponentType, HrmsRole,
)
from app.utils.hrms_access import hrms_role


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _oid(value) -> Optional[ObjectId]:
    """A display-only lookup id — malformed input means "no name to show", never a 400."""
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        return None


async def _own_employee_code(actor: dict, company_id: str) -> Optional[str]:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": str(actor.get("_id") or "")})
    return (profile or {}).get("employee_code")


async def _resolve_employee_code(actor: dict, company_id: str,
                                  requested: Optional[str]) -> str:
    """An EMPLOYEE caller always gets their OWN code, regardless of what was requested —
    the same untrusted-input treatment hrms_appointment_service._scope_filter applies to a
    caller-supplied `uk`. Every other role must name one explicitly."""
    if hrms_role(actor) == HrmsRole.EMPLOYEE:
        own = await _own_employee_code(actor, company_id)
        if not own:
            raise HTTPException(status_code=404, detail="You have no linked employee profile.")
        return own
    if not requested:
        raise HTTPException(status_code=422, detail="employee_code is required.")
    return requested


def _line(label: str, amount) -> Optional[dict]:
    amount = float(amount or 0)
    return {"label": label, "amount": round(amount, 2)} if amount else None


async def _department_names(company_id: str, ids: set) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = await get_collection(COLL_DEPARTMENTS).find(
        {"company_id": str(company_id), "_id": {"$in": [_oid(i) for i in ids if _oid(i)]}},
        {"name": 1}).to_list(len(ids))
    return {str(r["_id"]): r.get("name") for r in rows}


async def _designation_names(company_id: str, ids: set) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = await get_collection(COLL_DESIGNATIONS).find(
        {"company_id": str(company_id), "_id": {"$in": [_oid(i) for i in ids if _oid(i)]}},
        {"name": 1}).to_list(len(ids))
    return {str(r["_id"]): r.get("name") for r in rows}


async def _latest_structure(company_id: str, employee_code: str, period: str) -> Optional[dict]:
    return await get_collection(COLL_SALARY_STRUCTURES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code,
         "effective_from": {"$lte": f"{period}-28"}},
        sort=[("effective_from", -1)],
    )


def _compose_payslip(record: dict, *, period: str, run_status: Optional[str],
                     employee_name: Optional[str], department_name: Optional[str],
                     designation_name: Optional[str], structure: Optional[dict],
                     component_meta: dict, template: dict) -> dict:
    """Every figure here is read straight off `record` (already computed by the payroll
    run) plus `structure` (for line-item LABELS — "Basic", "HRA" — rather than a single
    `structured_gross` total). Nothing is recalculated. Shared by `get_payslip` (one
    employee) and `list_payslips` (a whole run), so the two can never render differently for
    the same record."""
    earnings = []
    for c in (structure or {}).get("components", []):
        meta = component_meta.get(c.get("code")) or {}
        if meta.get("component_type") == ComponentType.EARNING.value:
            row = _line(meta.get("name") or c.get("code"), c.get("amount"))
            if row:
                earnings.append(row)

    proration_note = None
    if record["payable_days"] != record["days_in_period"]:
        proration_note = (f'Prorated for {record["payable_days"]} of '
                          f'{record["days_in_period"]} payable days '
                          f'({record["lop_days"]} LOP).')

    # §22.7 — arbitrary named ad-hoc lines, alongside the fixed named fields below. Each was
    # resolved against the component master at the moment it was set (hrms_payroll_service.
    # set_adjustments), so the type is read straight off the stored line, no second lookup.
    adjustment_earnings = [row for row in (
        _line(a.get("name") or a.get("code"), a.get("amount"))
        for a in (record.get("adjustments") or [])
        if a.get("component_type") == ComponentType.EARNING.value
    ) if row]
    adjustment_deductions = [row for row in (
        _line(a.get("name") or a.get("code"), a.get("amount"))
        for a in (record.get("adjustments") or [])
        if a.get("component_type") == ComponentType.DEDUCTION.value
    ) if row]

    other_earnings = [row for row in [
        _line("Variable Pay", record.get("variable_pay_payout")),
        _line("Arrears", record.get("arrears")),
        _line("Reimbursements", record.get("reimbursements")),
        _line("Other Earnings", record.get("other_earnings")),
    ] if row] + adjustment_earnings

    deductions = [row for row in [
        _line("PF", record.get("pf")),
        _line("ESI", record.get("esi")),
        _line("Professional Tax", record.get("pt")),
        _line("TDS", record.get("tds")),
        _line("Salary Advance Recovery", record.get("advance_recovery")),
        _line("Notice Period Recovery", record.get("notice_recovery")),
        _line("Other Deductions", record.get("other_deductions")),
    ] if row] + adjustment_deductions

    return {
        "period": period,
        "run_status": run_status,
        "employee_code": record["employee_code"],
        "employee_name": record.get("employee_name") or employee_name,
        "designation": designation_name,
        "department": department_name,
        "days_in_period": record["days_in_period"], "payable_days": record["payable_days"],
        "lop_days": record["lop_days"], "proration_note": proration_note,
        "earnings": earnings,
        "other_earnings": other_earnings,
        "deductions": deductions,
        "gross_earnings": record["gross_earnings"],
        "total_deductions": record["total_deductions"],
        "net_pay": record["net_pay"],
        "template": template,
    }


async def get_payslip(actor: dict, company_id: str, period: str,
                       employee_code: Optional[str] = None) -> dict:
    employee_code = await _resolve_employee_code(actor, company_id, employee_code)

    record = await get_collection(COLL_PAYROLL_RECORDS).find_one(
        {"company_id": str(company_id), "period": period, "employee_code": employee_code})
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"No payroll record for {employee_code} in {period}.")

    run = await get_collection(COLL_PAYROLL_RUNS).find_one(
        {"company_id": str(company_id), "period": period}, {"status": 1})

    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code},
        {"designation_id": 1, "department_id": 1, "employee_code": 1,
         "display_name": 1, "full_name": 1})
    # A profile stores department_id/designation_id, not resolved names (see
    # hrms_employee_service._compose) — the same two-lookup join late_coming_summary uses.
    departments = await _department_names(company_id, {(profile or {}).get("department_id")})
    designations = await _designation_names(company_id, {(profile or {}).get("designation_id")})

    structure = await _latest_structure(company_id, employee_code, period)
    component_meta = {c["code"]: c for c in await get_collection(COLL_SALARY_COMPONENTS).find(
        {"company_id": str(company_id)}).to_list(200)}
    template = await get_payslip_template(company_id)

    return _compose_payslip(
        record, period=period, run_status=(run or {}).get("status"),
        employee_name=(profile or {}).get("display_name") or (profile or {}).get("full_name"),
        department_name=departments.get((profile or {}).get("department_id")),
        designation_name=designations.get((profile or {}).get("designation_id")),
        structure=structure, component_meta=component_meta, template=template)


async def list_payslips(actor: dict, company_id: str, period: str) -> list:
    """§22.7 "bulk payslip" — every payslip in one run, HR-only (an EMPLOYEE holding
    PAYROLL_READ is scoped to their own single record everywhere else in this module; a
    listing across the whole run must not become the one place that scope is forgotten)."""
    if hrms_role(actor) == HrmsRole.EMPLOYEE:
        raise HTTPException(status_code=403, detail="You may only view your own payslip.")

    records = await get_collection(COLL_PAYROLL_RECORDS).find(
        {"company_id": str(company_id), "period": period}).sort("employee_code", 1).to_list(5000)
    if not records:
        return []

    run = await get_collection(COLL_PAYROLL_RUNS).find_one(
        {"company_id": str(company_id), "period": period}, {"status": 1})
    run_status = (run or {}).get("status")

    codes = [r["employee_code"] for r in records]
    profiles = {p["employee_code"]: p for p in await get_collection(COLL_EMPLOYEE_PROFILES).find(
        {"company_id": str(company_id), "employee_code": {"$in": codes}},
        {"employee_code": 1, "department_id": 1, "designation_id": 1,
         "display_name": 1, "full_name": 1}).to_list(len(codes))}
    departments = await _department_names(
        company_id, {p.get("department_id") for p in profiles.values()})
    designations = await _designation_names(
        company_id, {p.get("designation_id") for p in profiles.values()})
    component_meta = {c["code"]: c for c in await get_collection(COLL_SALARY_COMPONENTS).find(
        {"company_id": str(company_id)}).to_list(200)}
    template = await get_payslip_template(company_id)

    out = []
    for record in records:
        profile = profiles.get(record["employee_code"]) or {}
        structure = await _latest_structure(company_id, record["employee_code"], period)
        out.append(_compose_payslip(
            record, period=period, run_status=run_status,
            employee_name=profile.get("display_name") or profile.get("full_name"),
            department_name=departments.get(profile.get("department_id")),
            designation_name=designations.get(profile.get("designation_id")),
            structure=structure, component_meta=component_meta, template=template))
    return out


# ─────────────────────────────────────────────────────────────
# SM-HR-064 — Payslip Template Configuration
# ─────────────────────────────────────────────────────────────
async def get_payslip_template(company_id: str) -> dict:
    doc = await get_collection(COLL_PAYROLL_TEMPLATES).find_one({"company_id": str(company_id)})
    if not doc:
        return {"company_id": str(company_id), "company_name": None,
                "header_note": None, "footer_note": None}
    return _out(doc)


async def save_payslip_template(actor: dict, company_id: str, payload: dict) -> dict:
    """§7.13's own BR defers full statutory/component configuration to a payroll workshop —
    what is configurable today is the header/footer note every issued payslip carries."""
    now = datetime.now(timezone.utc)
    clean = {
        "company_name": (payload.get("company_name") or "").strip() or None,
        "header_note": (payload.get("header_note") or "").strip() or None,
        "footer_note": (payload.get("footer_note") or "").strip() or None,
        "updated_by": str(actor.get("_id") or ""),
        "updated_at": now,
    }
    await get_collection(COLL_PAYROLL_TEMPLATES).update_one(
        {"company_id": str(company_id)},
        {"$set": clean, "$setOnInsert": {"company_id": str(company_id), "created_at": now}},
        upsert=True,
    )
    return await get_payslip_template(company_id)
