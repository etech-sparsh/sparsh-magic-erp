"""HRMS > Attendance (BA/Functional Design v2.2, §7.8, §7.9, §7.12, §22.9).

Daily capture -> the engine derives status/late-minutes/worked-minutes against the company's
configured shift and grace -> exceptions are regularised (employee proposes -> manager ->
HR) -> HR locks the month, freezing an immutable snapshot for payroll to consume later
(§7.13 itself is unbuilt — see hrms_exit_service's FnfInput for the same constraint). Outdoor
Duty (§7.8 step 59) is its own small request/approval workflow, routed the same way.

-- No punch source exists yet -----------------------------------------------------------------
§7.8 names the intended source as "Biometric login/logout/live-location", with API/mobile/
import as a future option. Nothing in this codebase talks to hardware, so ATTENDANCE_MARK is
the only write path today: HR (or a manager, for their own team) records a day's punches by
hand, and the daily engine still runs the same arithmetic it would run on real punch data —
the workflow is real even though the capture is manual for now.

-- Ownership scoping is enforced here, not left as a follow-up -------------------------------
Unlike Phase EXIT-1's employee self-service caps (documented there as not yet scoped), an
EMPLOYEE-role caller's list/get/request calls in this module ARE filtered to their own
employee_code — see `_scope_query` and `_assert_self_or_privileged`.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_ATTENDANCE_LOCKED, AUDIT_ATTENDANCE_MARKED, AUDIT_ATTENDANCE_UNLOCKED,
    AUDIT_CORRECTION_ACTIONED, AUDIT_CORRECTION_REQUESTED,
    AUDIT_OD_ACTIONED, AUDIT_OD_REQUESTED,
    COLL_ATTENDANCE, COLL_ATTENDANCE_CORRECTIONS, COLL_ATTENDANCE_LOCKS,
    COLL_EMPLOYEE_PROFILES, COLL_OD_REQUESTS, COLL_PUNCH_SEGMENTS, COLL_SETTINGS,
    DEFAULT_SHIFT_POLICY,
    ENTITY_ATT_LOCK, ENTITY_ATTENDANCE, ENTITY_CORRECTION, ENTITY_OD,
    MAX_ATTENDANCE_LIST_PAGE,
    AttendanceStatus, CorrectionStatus, HrmsRole, LockStatus, OdStatus,
    compute_daily_status,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import hrms_role

USER_COLLECTIONS = ("learners", "staff")


# ─────────────────────────────────────────────────────────────
# Small helpers — same shape as hrms_exit_service's
# ─────────────────────────────────────────────────────────────
def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _out_with_id(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _oid(value: str, label: str = "record") -> ObjectId:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} id.")


async def _find_user(user_id: str) -> tuple:
    try:
        oid = _oid(user_id)
    except HTTPException:
        return None, None
    for coll in USER_COLLECTIONS:
        doc = await get_collection(coll).find_one({"_id": oid})
        if doc:
            return doc, coll
    return None, None


async def _get_profile(company_id: str, employee_code: str) -> dict:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        raise HTTPException(status_code=404, detail="No employee with that code in this company.")
    return profile


async def _reporting_manager_id(profile: dict) -> Optional[str]:
    user_id = profile.get("user_id")
    if not user_id:
        return None
    user, _coll = await _find_user(user_id)
    return (user or {}).get("reporting_manager")


async def _own_employee_code(actor: dict, company_id: str) -> Optional[str]:
    """The acting user's OWN employee_code, if they have an HR profile in this company."""
    actor_id = str(actor.get("_id") or "")
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": actor_id})
    return (profile or {}).get("employee_code")


async def _team_employee_codes(actor: dict, company_id: str) -> list:
    """A manager's own reports, by employee_code — the same directory relationship
    hrms_employee_service._manager_scope reads (`reporting_manager` on the user doc),
    resolved here to employee_code because this module addresses people that way."""
    actor_id = str(actor.get("_id") or "")
    reports = []
    for coll in USER_COLLECTIONS:
        rows = await get_collection(coll).find(
            {"reporting_manager": actor_id}, {"_id": 1}).to_list(2000)
        reports.extend(str(r["_id"]) for r in rows)
    if not reports:
        return []
    profiles = await get_collection(COLL_EMPLOYEE_PROFILES).find(
        {"company_id": str(company_id), "user_id": {"$in": reports}},
        {"employee_code": 1}).to_list(2000)
    return [p["employee_code"] for p in profiles if p.get("employee_code")]


async def _scope_query(actor: dict, company_id: str, query: dict) -> dict:
    """Row-scopes a list query to what `actor` may see: EMPLOYEE sees only their own
    records, MANAGER sees their own plus their team's, everyone else (HR/MD/ADMIN) sees the
    whole company — the query already carries that. Fails CLOSED: an employee with no linked
    profile sees nothing rather than everything."""
    role = hrms_role(actor)
    if role == HrmsRole.EMPLOYEE:
        own = await _own_employee_code(actor, company_id)
        query["employee_code"] = own or "__none__"
    elif role == HrmsRole.MANAGER:
        own = await _own_employee_code(actor, company_id)
        team = await _team_employee_codes(actor, company_id)
        codes = list({c for c in ([own] if own else []) + team})
        query["employee_code"] = {"$in": codes or ["__none__"]}
    return query


async def _assert_self_or_privileged(actor: dict, company_id: str, employee_code: str) -> None:
    """A MANAGER may act for their own team, HR/MD/ADMIN for anyone; an EMPLOYEE only for
    themselves. Raises 403 rather than silently scoping, because this guards a WRITE."""
    role = hrms_role(actor)
    if role in (HrmsRole.HR, HrmsRole.MD, HrmsRole.ADMIN, None):
        return
    own = await _own_employee_code(actor, company_id)
    if own and own == employee_code:
        return
    if role == HrmsRole.MANAGER and employee_code in await _team_employee_codes(actor, company_id):
        return
    raise HTTPException(status_code=403, detail="You may only act on your own record.")


# ─────────────────────────────────────────────────────────────
# §7.8 — shift policy (company-configurable; see the Phase ATT-1 module docstring in
# models/hrms.py for why these numbers are adjustable defaults, not frozen constants)
# ─────────────────────────────────────────────────────────────
async def get_shift_policy(company_id: str) -> dict:
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)})
    stored = (doc or {}).get("shift_policy") or {}
    return {**DEFAULT_SHIFT_POLICY, **stored}


async def save_shift_policy(actor: dict, company_id: str, payload: dict) -> dict:
    merged = {**await get_shift_policy(company_id), **{k: v for k, v in payload.items() if v is not None}}
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": str(company_id)},
        {"$set": {"shift_policy": merged, "updated_at": datetime.now(timezone.utc)},
         "$setOnInsert": {"company_id": str(company_id)}},
        upsert=True,
    )
    await audit(actor, "shift policy updated", ENTITY_ATTENDANCE, "policy",
               ", ".join(sorted(payload.keys())), company_id)
    return merged


# ─────────────────────────────────────────────────────────────
# §7.8 — daily capture
# ─────────────────────────────────────────────────────────────
async def mark_attendance(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    work_date = str(payload.get("work_date") or "").strip()
    if not employee_code or not work_date:
        raise HTTPException(status_code=422, detail="employee_code and work_date are required.")
    await _get_profile(company_id, employee_code)
    await _assert_self_or_privileged(actor, company_id, employee_code)

    existing = await get_collection(COLL_ATTENDANCE).find_one(
        {"company_id": str(company_id), "employee_code": employee_code, "work_date": work_date})
    if existing and existing.get("locked"):
        raise HTTPException(
            status_code=409,
            detail=f"{work_date} is inside a locked attendance period; use an authorised "
                   f"unlock before changing it.")

    override = payload.get("override_status")
    actual_in = payload.get("actual_in")
    actual_out = payload.get("actual_out")

    if override:
        computed = {"status": override, "worked_minutes": None, "late_minutes": 0}
    else:
        policy = await get_shift_policy(company_id)
        computed = compute_daily_status(
            scheduled_in=policy["shift_start"], scheduled_out=policy["shift_end"],
            actual_in=actual_in, actual_out=actual_out,
            daily_grace_minutes=policy["daily_grace_minutes"],
            half_day_threshold_minutes=policy["half_day_threshold_minutes"])

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id),
        "employee_code": employee_code,
        "work_date": work_date,
        "actual_in": actual_in,
        "actual_out": actual_out,
        "status": computed["status"],
        "worked_minutes": computed["worked_minutes"],
        "late_minutes": computed["late_minutes"],
        "source": "manual",
        "notes": payload.get("notes"),
        "locked": False,
        "updated_at": now,
        "updated_by": str(actor.get("_id") or ""),
    }
    await get_collection(COLL_ATTENDANCE).update_one(
        {"company_id": str(company_id), "employee_code": employee_code, "work_date": work_date},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    # Raw punches are preserved as their own append-only record, never overwritten by a later
    # correction — §7.8's own BR ("Raw attendance data should not be overwritten...").
    if actual_in or actual_out:
        await get_collection(COLL_PUNCH_SEGMENTS).insert_one({
            "company_id": str(company_id), "employee_code": employee_code,
            "work_date": work_date, "punch_in": actual_in, "punch_out": actual_out,
            "source": "manual", "recorded_by": str(actor.get("_id") or ""), "recorded_at": now,
        })

    await audit(actor, AUDIT_ATTENDANCE_MARKED, ENTITY_ATTENDANCE, f"{employee_code}:{work_date}",
               computed["status"], company_id)
    saved = await get_collection(COLL_ATTENDANCE).find_one(
        {"company_id": str(company_id), "employee_code": employee_code, "work_date": work_date})
    return _out(saved)


async def list_attendance(actor: dict, company_id: str, *, employee_code: Optional[str] = None,
                          start_date: Optional[str] = None, end_date: Optional[str] = None,
                          status: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if employee_code:
        query["employee_code"] = employee_code
    if start_date or end_date:
        rng = {}
        if start_date:
            rng["$gte"] = start_date
        if end_date:
            rng["$lte"] = end_date
        query["work_date"] = rng
    if status:
        query["status"] = status
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_ATTENDANCE).find(query).sort(
        "work_date", -1).to_list(min(limit, MAX_ATTENDANCE_LIST_PAGE))
    return [_out(r) for r in rows]


# ─────────────────────────────────────────────────────────────
# §7.9 — regularisation (employee -> manager -> HR)
# ─────────────────────────────────────────────────────────────
async def request_regularization(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    work_date = str(payload.get("work_date") or "").strip()
    if not employee_code or not work_date:
        raise HTTPException(status_code=422, detail="employee_code and work_date are required.")
    profile = await _get_profile(company_id, employee_code)
    await _assert_self_or_privileged(actor, company_id, employee_code)

    attendance = await get_collection(COLL_ATTENDANCE).find_one(
        {"company_id": str(company_id), "employee_code": employee_code, "work_date": work_date})
    if attendance and attendance.get("locked"):
        raise HTTPException(
            status_code=409,
            detail=f"{work_date} is inside a locked attendance period — no regularisation "
                   f"without an authorised unlock (§7.9 BR).")

    year = datetime.now(timezone.utc).year
    req_no = await next_business_id("regularization", str(company_id), year)
    now = datetime.now(timezone.utc)
    doc = {
        "req_no": req_no,
        "company_id": str(company_id),
        "employee_code": employee_code,
        "employee_name": profile.get("display_name") or profile.get("full_name"),
        "reporting_manager_id": await _reporting_manager_id(profile),
        "work_date": work_date,
        "exception_type": payload.get("exception_type"),
        "proposed_in": payload.get("proposed_in"),
        "proposed_out": payload.get("proposed_out"),
        "reason": payload.get("reason"),
        "evidence": payload.get("evidence"),
        "status": CorrectionStatus.PENDING.value,
        "manager_action_by": None, "manager_action_at": None, "manager_remarks": None,
        "hr_action_by": None, "hr_action_at": None, "hr_remarks": None,
        "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_ATTENDANCE_CORRECTIONS).insert_one(doc)
    await audit(actor, AUDIT_CORRECTION_REQUESTED, ENTITY_CORRECTION, req_no,
               f"{employee_code}, {work_date}, {payload.get('exception_type')}", company_id)
    return _out(doc)


async def list_regularizations(actor: dict, company_id: str, *, status: Optional[str] = None,
                               employee_code: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if employee_code:
        query["employee_code"] = employee_code
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_ATTENDANCE_CORRECTIONS).find(query).sort(
        "created_at", -1).to_list(min(limit, MAX_ATTENDANCE_LIST_PAGE))
    return [_out(r) for r in rows]


async def act_on_regularization(actor: dict, company_id: str, req_no: str, payload: dict) -> dict:
    """§7.9 steps 66-69: manager decides first; HR gives the final sign-off. A caller who
    holds both levels (HR/MD/ADMIN) may also record the manager step directly — the same
    "no separate manager, no dead end" reasoning Phase EXIT-1's MD fallback already uses —
    but the ORDER itself (manager step before HR-final) is never skipped."""
    doc = await get_collection(COLL_ATTENDANCE_CORRECTIONS).find_one(
        {"company_id": str(company_id), "req_no": req_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Regularisation '{req_no}' not found.")
    if doc["status"] not in (CorrectionStatus.PENDING.value, CorrectionStatus.MANAGER_APPROVED.value):
        raise HTTPException(status_code=409, detail=f"{req_no} is already \"{doc['status']}\".")

    decision = payload.get("decision")
    now = datetime.now(timezone.utc)
    updates = {"updated_at": now}

    if decision == CorrectionStatus.REJECTED.value:
        updates.update({"status": CorrectionStatus.REJECTED.value})
    elif decision == CorrectionStatus.RETURNED.value:
        updates.update({"status": CorrectionStatus.RETURNED.value})
    elif decision == CorrectionStatus.MANAGER_APPROVED.value:
        if doc["status"] != CorrectionStatus.PENDING.value:
            raise HTTPException(status_code=409, detail=f"{req_no} already passed the manager step.")
        updates.update({"status": CorrectionStatus.MANAGER_APPROVED.value,
                        "manager_action_by": str(actor.get("_id") or ""),
                        "manager_action_at": now, "manager_remarks": payload.get("remarks")})
    elif decision == CorrectionStatus.APPROVED.value:
        if doc["status"] != CorrectionStatus.MANAGER_APPROVED.value:
            raise HTTPException(
                status_code=409,
                detail=f"{req_no} needs the manager's approval before HR's final sign-off.")
        # HR-final: recalculate attendance, preserving the original record (the update, not a
        # second row) — §7.9 step 69.
        policy = await get_shift_policy(company_id)
        computed = compute_daily_status(
            scheduled_in=policy["shift_start"], scheduled_out=policy["shift_end"],
            actual_in=doc.get("proposed_in"), actual_out=doc.get("proposed_out"),
            daily_grace_minutes=policy["daily_grace_minutes"],
            half_day_threshold_minutes=policy["half_day_threshold_minutes"])
        await get_collection(COLL_ATTENDANCE).update_one(
            {"company_id": str(company_id), "employee_code": doc["employee_code"],
             "work_date": doc["work_date"]},
            {"$set": {"actual_in": doc.get("proposed_in"), "actual_out": doc.get("proposed_out"),
                      "status": computed["status"], "worked_minutes": computed["worked_minutes"],
                      "late_minutes": computed["late_minutes"], "source": "regularization",
                      "regularized_from": req_no, "updated_at": now},
             "$setOnInsert": {"company_id": str(company_id), "employee_code": doc["employee_code"],
                              "work_date": doc["work_date"], "created_at": now, "locked": False}},
            upsert=True,
        )
        updates.update({"status": CorrectionStatus.APPROVED.value,
                        "hr_action_by": str(actor.get("_id") or ""),
                        "hr_action_at": now, "hr_remarks": payload.get("remarks")})
    else:
        raise HTTPException(status_code=422, detail=f"Unrecognised decision '{decision}'.")

    await get_collection(COLL_ATTENDANCE_CORRECTIONS).update_one(
        {"company_id": str(company_id), "req_no": req_no}, {"$set": updates})
    await audit(actor, AUDIT_CORRECTION_ACTIONED, ENTITY_CORRECTION, req_no,
               decision, company_id)
    saved = await get_collection(COLL_ATTENDANCE_CORRECTIONS).find_one(
        {"company_id": str(company_id), "req_no": req_no})
    return _out(saved)


# ─────────────────────────────────────────────────────────────
# §7.8 step 59 — Outdoor Duty
# ─────────────────────────────────────────────────────────────
async def request_od(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    od_date = str(payload.get("od_date") or "").strip()
    if not employee_code or not od_date:
        raise HTTPException(status_code=422, detail="employee_code and od_date are required.")
    profile = await _get_profile(company_id, employee_code)
    await _assert_self_or_privileged(actor, company_id, employee_code)

    year = datetime.now(timezone.utc).year
    od_no = await next_business_id("od", str(company_id), year)
    now = datetime.now(timezone.utc)
    doc = {
        "od_no": od_no,
        "company_id": str(company_id),
        "employee_code": employee_code,
        "employee_name": profile.get("display_name") or profile.get("full_name"),
        "reporting_manager_id": await _reporting_manager_id(profile),
        "od_date": od_date,
        "purpose": payload.get("purpose"),
        "location": payload.get("location"),
        "status": OdStatus.PENDING.value,
        "action_by": None, "action_at": None, "remarks": None,
        "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_OD_REQUESTS).insert_one(doc)
    await audit(actor, AUDIT_OD_REQUESTED, ENTITY_OD, od_no,
               f"{employee_code}, {od_date}", company_id)
    return _out(doc)


async def list_od_requests(actor: dict, company_id: str, *, status: Optional[str] = None,
                           employee_code: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if employee_code:
        query["employee_code"] = employee_code
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_OD_REQUESTS).find(query).sort(
        "created_at", -1).to_list(min(limit, MAX_ATTENDANCE_LIST_PAGE))
    return [_out(r) for r in rows]


async def act_on_od(actor: dict, company_id: str, od_no: str, payload: dict) -> dict:
    doc = await get_collection(COLL_OD_REQUESTS).find_one(
        {"company_id": str(company_id), "od_no": od_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"OD request '{od_no}' not found.")
    if doc["status"] != OdStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"{od_no} is already \"{doc['status']}\".")

    approved = bool(payload.get("approved"))
    now = datetime.now(timezone.utc)
    new_status = OdStatus.APPROVED.value if approved else OdStatus.REJECTED.value
    await get_collection(COLL_OD_REQUESTS).update_one(
        {"company_id": str(company_id), "od_no": od_no},
        {"$set": {"status": new_status, "action_by": str(actor.get("_id") or ""),
                  "action_at": now, "remarks": payload.get("remarks"), "updated_at": now}},
    )
    if approved:
        # §7.8: an approved OD becomes the day's attendance status directly.
        await get_collection(COLL_ATTENDANCE).update_one(
            {"company_id": str(company_id), "employee_code": doc["employee_code"],
             "work_date": doc["od_date"]},
            {"$set": {"status": AttendanceStatus.ON_OD.value, "source": "od",
                      "od_ref": od_no, "updated_at": now},
             "$setOnInsert": {"company_id": str(company_id), "employee_code": doc["employee_code"],
                              "work_date": doc["od_date"], "created_at": now, "locked": False,
                              "worked_minutes": None, "late_minutes": 0}},
            upsert=True,
        )
    await audit(actor, AUDIT_OD_ACTIONED, ENTITY_OD, od_no, new_status, company_id)
    saved = await get_collection(COLL_OD_REQUESTS).find_one(
        {"company_id": str(company_id), "od_no": od_no})
    return _out(saved)


# ─────────────────────────────────────────────────────────────
# §7.12 — monthly closure
# ─────────────────────────────────────────────────────────────
async def closure_dashboard(actor: dict, company_id: str, period: str) -> dict:
    """§7.12 steps 84-85: what is still open for this period, before HR can lock it."""
    start, end = f"{period}-01", f"{period}-31"
    missing_punches = await get_collection(COLL_ATTENDANCE).count_documents(
        {"company_id": str(company_id), "work_date": {"$gte": start, "$lte": end},
         "status": AttendanceStatus.PENDING.value})
    pending_regularizations = await get_collection(COLL_ATTENDANCE_CORRECTIONS).count_documents(
        {"company_id": str(company_id), "work_date": {"$gte": start, "$lte": end},
         "status": {"$in": [CorrectionStatus.PENDING.value, CorrectionStatus.MANAGER_APPROVED.value]}})
    pending_od = await get_collection(COLL_OD_REQUESTS).count_documents(
        {"company_id": str(company_id), "od_date": {"$gte": start, "$lte": end},
         "status": OdStatus.PENDING.value})
    unexplained_absence = await get_collection(COLL_ATTENDANCE).count_documents(
        {"company_id": str(company_id), "work_date": {"$gte": start, "$lte": end},
         "status": AttendanceStatus.ABSENT.value})
    lock = await get_collection(COLL_ATTENDANCE_LOCKS).find_one(
        {"company_id": str(company_id), "period": period})
    return {
        "period": period,
        "status": (lock or {}).get("status", LockStatus.OPEN.value),
        "missing_punches": missing_punches,
        "pending_regularizations": pending_regularizations,
        "pending_od": pending_od,
        "unexplained_absence": unexplained_absence,
        "ready_to_lock": not (missing_punches or pending_regularizations or pending_od),
        "locked_by": (lock or {}).get("locked_by"),
        "locked_at": (lock or {}).get("locked_at"),
    }


async def lock_period(actor: dict, company_id: str, period: str) -> dict:
    existing = await get_collection(COLL_ATTENDANCE_LOCKS).find_one(
        {"company_id": str(company_id), "period": period})
    if existing and existing.get("status") == LockStatus.LOCKED.value:
        raise HTTPException(status_code=409, detail=f"{period} is already locked.")

    snapshot = await closure_dashboard(actor, company_id, period)
    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "period": period, "status": LockStatus.LOCKED.value,
        "locked_by": str(actor.get("_id") or ""), "locked_at": now,
        "exceptions_at_lock": {k: snapshot[k] for k in (
            "missing_punches", "pending_regularizations", "pending_od", "unexplained_absence")},
        "unlock_history": (existing or {}).get("unlock_history", []),
        "updated_at": now,
    }
    await get_collection(COLL_ATTENDANCE_LOCKS).update_one(
        {"company_id": str(company_id), "period": period},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    # Freeze the period's own attendance rows — payroll consumes this flag, not the lock
    # document, so "is THIS row immutable" never needs a second lookup.
    start, end = f"{period}-01", f"{period}-31"
    await get_collection(COLL_ATTENDANCE).update_many(
        {"company_id": str(company_id), "work_date": {"$gte": start, "$lte": end}},
        {"$set": {"locked": True}})
    await audit(actor, AUDIT_ATTENDANCE_LOCKED, ENTITY_ATT_LOCK, period,
               f"exceptions at lock: {doc['exceptions_at_lock']}", company_id)
    return _out(doc)


async def unlock_period(actor: dict, company_id: str, period: str, reason: str) -> dict:
    existing = await get_collection(COLL_ATTENDANCE_LOCKS).find_one(
        {"company_id": str(company_id), "period": period})
    if not existing or existing.get("status") != LockStatus.LOCKED.value:
        raise HTTPException(status_code=409, detail=f"{period} is not locked.")

    now = datetime.now(timezone.utc)
    entry = {"by": str(actor.get("_id") or ""), "at": now, "reason": reason}
    await get_collection(COLL_ATTENDANCE_LOCKS).update_one(
        {"company_id": str(company_id), "period": period},
        {"$set": {"status": LockStatus.OPEN.value, "updated_at": now},
         "$push": {"unlock_history": entry}},
    )
    start, end = f"{period}-01", f"{period}-31"
    await get_collection(COLL_ATTENDANCE).update_many(
        {"company_id": str(company_id), "work_date": {"$gte": start, "$lte": end}},
        {"$set": {"locked": False}})
    await audit(actor, AUDIT_ATTENDANCE_UNLOCKED, ENTITY_ATT_LOCK, period, reason, company_id)
    saved = await get_collection(COLL_ATTENDANCE_LOCKS).find_one(
        {"company_id": str(company_id), "period": period})
    return _out(saved)


# ─────────────────────────────────────────────────────────────
# §22.9 — late-coming analytics
# ─────────────────────────────────────────────────────────────
async def late_coming_summary(actor: dict, company_id: str, *, employee_code: Optional[str] = None,
                              start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict:
    """Total late-coming days and the dates themselves, for the calendar marker and the
    monthly card's click-to-filter (§22.9)."""
    query = {"company_id": str(company_id), "late_minutes": {"$gt": 0}}
    if employee_code:
        query["employee_code"] = employee_code
    if start_date or end_date:
        rng = {}
        if start_date:
            rng["$gte"] = start_date
        if end_date:
            rng["$lte"] = end_date
        query["work_date"] = rng
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_ATTENDANCE).find(
        query, {"work_date": 1, "employee_code": 1, "late_minutes": 1}
    ).sort("work_date", -1).to_list(MAX_ATTENDANCE_LIST_PAGE)

    # Department label per employee_code, joined once for the whole result rather than once
    # per row — the same batched-lookup reasoning hrms_scheduler_service._managerial_
    # request_nos already applies for the same shape of problem. A profile stores
    # department_id, not a resolved name (see hrms_employee_service._compose), so this is
    # two batched lookups, not one.
    codes = {r["employee_code"] for r in rows}
    departments = {}
    if codes:
        from app.models.hrms import COLL_DEPARTMENTS
        profiles = await get_collection(COLL_EMPLOYEE_PROFILES).find(
            {"company_id": str(company_id), "employee_code": {"$in": list(codes)}},
            {"employee_code": 1, "department_id": 1}).to_list(len(codes))
        dept_names = {
            str(d["_id"]): d.get("name")
            for d in await get_collection(COLL_DEPARTMENTS).find(
                {"company_id": str(company_id)}, {"name": 1}).to_list(1000)
        }
        departments = {p["employee_code"]: dept_names.get(p.get("department_id"))
                       for p in profiles}

    return {
        "total_late_days": len(rows),
        "dates": [{"work_date": r["work_date"], "employee_code": r["employee_code"],
                   "late_minutes": r["late_minutes"],
                   "department": departments.get(r["employee_code"])} for r in rows],
    }
