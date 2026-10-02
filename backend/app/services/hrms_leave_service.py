"""HRMS > Leave & Compensatory Off (BA/Functional Design v2.2, §7.10, §7.11, §22.8).

Leave: apply -> balance/eligibility validated -> reporting manager -> HR -> ledger updated;
cancellation restores the balance. C-Off is a two-sided ledger of individually-expiring
batches (§7.11): APPROVED WORK on a weekly-off/holiday earns a credit with its own expiry;
a later leave application of type "C-Off" (§22.8: "must be available in leave dropdown and
use C-Off earned balance") debits the oldest unexpired batches first.

-- Leave-type policy is NOT frozen -----------------------------------------------------------
See the Phase ATT-1 docstring in models/hrms.py. `hrms_leave_types` is seeded per company from
DEFAULT_LEAVE_TYPES the first time it is read, exactly as an adjustable starting point; nothing
here computes CL/SL/EL entitlement, accrual or lapse from a hardcoded number — every figure this
module uses comes from that row, so a client-confirmed policy takes effect by editing data, not
by a code change.

-- Ownership scoping mirrors hrms_attendance_service --------------------------------------------
An EMPLOYEE sees and applies for their own leave/C-Off only; a MANAGER additionally sees and
acts on their team's. See `_scope_query` / `_assert_self_or_privileged`.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_COFF_EARN_ACTIONED, AUDIT_COFF_EARN_REQUESTED,
    AUDIT_LEAVE_ACTIONED, AUDIT_LEAVE_APPLIED, AUDIT_LEAVE_BALANCE_ADJUSTED,
    AUDIT_LEAVE_CANCELLED, AUDIT_LEAVE_TYPE_SAVED,
    COLL_COFF_LEDGER, COLL_EMPLOYEE_PROFILES, COLL_LEAVE_BALANCES, COLL_LEAVE_TYPES,
    COLL_LEAVES,
    DEFAULT_LEAVE_TYPES,
    ENTITY_COFF, ENTITY_LEAVE_REQUEST, ENTITY_LEAVE_TYPE,
    MAX_ATTENDANCE_LIST_PAGE,
    CoffLedgerStatus, HrmsRole, LeaveStatus, OPEN_LEAVE_STATUSES,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_access import hrms_role

USER_COLLECTIONS = ("learners", "staff")


# ─────────────────────────────────────────────────────────────
# Small helpers
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


def _days_between(start: str, end: str) -> int:
    y1, m1, d1 = (int(x) for x in start.split("-"))
    y2, m2, d2 = (int(x) for x in end.split("-"))
    return (date(y2, m2, d2) - date(y1, m1, d1)).days + 1


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
    from bson import ObjectId
    from bson.errors import InvalidId
    try:
        oid = ObjectId(str(user_id))
    except (InvalidId, TypeError):
        return None
    for coll in USER_COLLECTIONS:
        user = await get_collection(coll).find_one({"_id": oid})
        if user:
            return user.get("reporting_manager")
    return None


async def _own_employee_code(actor: dict, company_id: str) -> Optional[str]:
    actor_id = str(actor.get("_id") or "")
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": actor_id})
    return (profile or {}).get("employee_code")


async def _team_employee_codes(actor: dict, company_id: str) -> list:
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
# §22.8 — leave-type policy register
# ─────────────────────────────────────────────────────────────
async def _ensure_seeded(company_id: str) -> None:
    coll = get_collection(COLL_LEAVE_TYPES)
    if await coll.count_documents({"company_id": str(company_id)}) > 0:
        return
    now = datetime.now(timezone.utc)
    rows = [{**t, "company_id": str(company_id), "policy_confirmed": False, "active": True,
            "created_at": now, "updated_at": now} for t in DEFAULT_LEAVE_TYPES]
    if rows:
        await coll.insert_many(rows)


async def list_leave_types(actor: dict, company_id: str) -> list:
    await _ensure_seeded(company_id)
    rows = await get_collection(COLL_LEAVE_TYPES).find(
        {"company_id": str(company_id)}).sort("code", 1).to_list(100)
    return [_out(r) for r in rows]


async def _get_leave_type(company_id: str, code: str) -> dict:
    await _ensure_seeded(company_id)
    doc = await get_collection(COLL_LEAVE_TYPES).find_one(
        {"company_id": str(company_id), "code": code})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Leave type '{code}' is not configured.")
    return doc


async def save_leave_type(actor: dict, company_id: str, payload: dict) -> dict:
    code = str(payload.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=422, detail="A leave type code is required.")
    now = datetime.now(timezone.utc)
    clean = {k: v for k, v in payload.items() if k != "code"}
    clean["updated_at"] = now
    await get_collection(COLL_LEAVE_TYPES).update_one(
        {"company_id": str(company_id), "code": code},
        {"$set": clean, "$setOnInsert": {"company_id": str(company_id), "code": code,
                                         "created_at": now}},
        upsert=True,
    )
    await audit(actor, AUDIT_LEAVE_TYPE_SAVED, ENTITY_LEAVE_TYPE, code,
               f"entitlement={payload.get('annual_entitlement')}, "
               f"confirmed={payload.get('policy_confirmed')}", company_id)
    return _out(await _get_leave_type(company_id, code))


# ─────────────────────────────────────────────────────────────
# Balances
# ─────────────────────────────────────────────────────────────
async def _get_balance(company_id: str, employee_code: str, leave_type: str, year: int) -> dict:
    coll = get_collection(COLL_LEAVE_BALANCES)
    doc = await coll.find_one({"company_id": str(company_id), "employee_code": employee_code,
                               "leave_type": leave_type, "year": year})
    if doc:
        return doc
    leave_cfg = await _get_leave_type(company_id, leave_type)
    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "employee_code": employee_code, "leave_type": leave_type,
        "year": year, "opening": 0, "accrued": leave_cfg.get("annual_entitlement", 0),
        "used": 0, "adjusted": 0, "encashed": 0, "carried_forward_in": 0,
        "created_at": now, "updated_at": now,
    }
    await coll.insert_one(doc)
    return doc


def _closing(bal: dict) -> float:
    return (bal.get("opening", 0) + bal.get("carried_forward_in", 0) + bal.get("accrued", 0)
            + bal.get("adjusted", 0) - bal.get("used", 0) - bal.get("encashed", 0))


async def get_leave_balances(actor: dict, company_id: str, employee_code: str,
                             year: Optional[int] = None) -> list:
    await _get_profile(company_id, employee_code)
    year = year or datetime.now(timezone.utc).year
    types = await list_leave_types(actor, company_id)
    out = []
    for t in types:
        if t["code"] == "C-Off":
            out.append({"leave_type": "C-Off", "year": year,
                       "closing": await _coff_available_balance(company_id, employee_code)})
            continue
        bal = await _get_balance(company_id, employee_code, t["code"], year)
        out.append({**_out(bal), "closing": _closing(bal)})
    return out


async def adjust_leave_balance(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    leave_type = payload.get("leave_type")
    year = int(payload.get("year") or datetime.now(timezone.utc).year)
    await _get_profile(company_id, employee_code)
    bal = await _get_balance(company_id, employee_code, leave_type, year)
    now = datetime.now(timezone.utc)
    await get_collection(COLL_LEAVE_BALANCES).update_one(
        {"_id": bal["_id"]},
        {"$inc": {"adjusted": float(payload.get("adjustment_days") or 0)},
         "$set": {"updated_at": now}},
    )
    await audit(actor, AUDIT_LEAVE_BALANCE_ADJUSTED, ENTITY_LEAVE_REQUEST,
               f"{employee_code}:{leave_type}:{year}",
               f"{payload.get('adjustment_days')}d — {payload.get('reason')}", company_id)
    return _out(await _get_balance(company_id, employee_code, leave_type, year))


# ─────────────────────────────────────────────────────────────
# §7.10 — Leave application & approval
# ─────────────────────────────────────────────────────────────
async def apply_leave(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    leave_type = payload.get("leave_type")
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")
    if not (employee_code and leave_type and start_date and end_date):
        raise HTTPException(
            status_code=422,
            detail="employee_code, leave_type, start_date and end_date are required.")
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date cannot be before start_date.")

    profile = await _get_profile(company_id, employee_code)
    await _assert_self_or_privileged(actor, company_id, employee_code)
    leave_cfg = await _get_leave_type(company_id, leave_type)
    if not leave_cfg.get("active", True):
        raise HTTPException(status_code=422, detail=f"'{leave_type}' is not an active leave type.")

    half_day = bool(payload.get("half_day"))
    days_count = 0.5 if half_day else _days_between(start_date, end_date)

    # §7.10 step 71: eligibility/balance validation before the request is even raised.
    if leave_type == "C-Off":
        available = await _coff_available_balance(company_id, employee_code)
        if days_count > available:
            raise HTTPException(
                status_code=422,
                detail=f"Only {available} C-Off day(s) available; {days_count} requested.")
    else:
        year = int(start_date[:4])
        bal = await _get_balance(company_id, employee_code, leave_type, year)
        if days_count > _closing(bal):
            raise HTTPException(
                status_code=422,
                detail=f"Insufficient {leave_type} balance: {_closing(bal)} available, "
                       f"{days_count} requested.")

    year = datetime.now(timezone.utc).year
    leave_no = await next_business_id("leave", str(company_id), year)
    now = datetime.now(timezone.utc)
    doc = {
        "leave_no": leave_no,
        "company_id": str(company_id),
        "employee_code": employee_code,
        "employee_name": profile.get("display_name") or profile.get("full_name"),
        "reporting_manager_id": await _reporting_manager_id(profile),
        "leave_type": leave_type,
        "start_date": start_date,
        "end_date": end_date,
        "half_day": half_day,
        "half_session": payload.get("half_session"),
        "days_count": days_count,
        "reason": payload.get("reason"),
        "attachment": payload.get("attachment"),
        "status": LeaveStatus.PENDING.value,
        "manager_action_by": None, "manager_action_at": None, "manager_remarks": None,
        "hr_action_by": None, "hr_action_at": None, "hr_remarks": None,
        "cancelled_reason": None, "cancelled_at": None,
        "coff_batches_used": [],
        "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_LEAVES).insert_one(doc)
    await audit(actor, AUDIT_LEAVE_APPLIED, ENTITY_LEAVE_REQUEST, leave_no,
               f"{employee_code}, {leave_type}, {start_date}..{end_date} ({days_count}d)",
               company_id)
    return _out(doc)


async def list_leaves(actor: dict, company_id: str, *, status: Optional[str] = None,
                      employee_code: Optional[str] = None, leave_type: Optional[str] = None,
                      limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if employee_code:
        query["employee_code"] = employee_code
    if leave_type:
        query["leave_type"] = leave_type
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_LEAVES).find(query).sort(
        "created_at", -1).to_list(min(limit, MAX_ATTENDANCE_LIST_PAGE))
    return [_out(r) for r in rows]


async def _get_leave(company_id: str, leave_no: str) -> dict:
    doc = await get_collection(COLL_LEAVES).find_one(
        {"company_id": str(company_id), "leave_no": leave_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Leave request '{leave_no}' not found.")
    return doc


async def act_on_leave(actor: dict, company_id: str, leave_no: str, payload: dict) -> dict:
    """§7.10 steps 73-75: manager, then HR; approval updates the ledger and the attendance
    calendar. Mirrors act_on_regularization's two-stage shape exactly."""
    doc = await _get_leave(company_id, leave_no)
    if doc["status"] not in (LeaveStatus.PENDING.value, LeaveStatus.MANAGER_APPROVED.value):
        raise HTTPException(status_code=409, detail=f"{leave_no} is already \"{doc['status']}\".")

    decision = payload.get("decision")
    now = datetime.now(timezone.utc)
    updates = {"updated_at": now}

    if decision == LeaveStatus.REJECTED.value:
        updates["status"] = LeaveStatus.REJECTED.value
    elif decision == LeaveStatus.RETURNED.value:
        updates["status"] = LeaveStatus.RETURNED.value
    elif decision == LeaveStatus.MANAGER_APPROVED.value:
        if doc["status"] != LeaveStatus.PENDING.value:
            raise HTTPException(status_code=409, detail=f"{leave_no} already passed the manager step.")
        updates.update({"status": LeaveStatus.MANAGER_APPROVED.value,
                        "manager_action_by": str(actor.get("_id") or ""),
                        "manager_action_at": now, "manager_remarks": payload.get("remarks")})
    elif decision == LeaveStatus.APPROVED.value:
        if doc["status"] != LeaveStatus.MANAGER_APPROVED.value:
            raise HTTPException(
                status_code=409,
                detail=f"{leave_no} needs the manager's approval before HR's final sign-off.")
        await _debit_on_approval(company_id, doc, now)
        updates.update({"status": LeaveStatus.APPROVED.value,
                        "hr_action_by": str(actor.get("_id") or ""),
                        "hr_action_at": now, "hr_remarks": payload.get("remarks")})
    else:
        raise HTTPException(status_code=422, detail=f"Unrecognised decision '{decision}'.")

    await get_collection(COLL_LEAVES).update_one(
        {"company_id": str(company_id), "leave_no": leave_no}, {"$set": updates})
    await audit(actor, AUDIT_LEAVE_ACTIONED, ENTITY_LEAVE_REQUEST, leave_no, decision, company_id)
    return _out(await _get_leave(company_id, leave_no))


async def _debit_on_approval(company_id: str, leave: dict, now: datetime) -> None:
    """§7.10 step 75: ledger + attendance calendar update on final approval."""
    if leave["leave_type"] == "C-Off":
        used_batches = await _debit_coff(
            company_id, leave["employee_code"], leave["days_count"], leave["leave_no"])
        await get_collection(COLL_LEAVES).update_one(
            {"_id": leave["_id"]}, {"$set": {"coff_batches_used": used_batches}})
    else:
        year = int(leave["start_date"][:4])
        bal = await _get_balance(company_id, leave["employee_code"], leave["leave_type"], year)
        await get_collection(COLL_LEAVE_BALANCES).update_one(
            {"_id": bal["_id"]},
            {"$inc": {"used": leave["days_count"]}, "$set": {"updated_at": now}})

    # Attendance calendar: mark every day in range On Leave, unless already locked.
    start_y, start_m, start_d = (int(x) for x in leave["start_date"].split("-"))
    end_y, end_m, end_d = (int(x) for x in leave["end_date"].split("-"))
    cursor = date(start_y, start_m, start_d)
    last = date(end_y, end_m, end_d)
    from app.models.hrms import AttendanceStatus
    from app.db.mongodb import get_collection as _gc
    while cursor <= last:
        wd = cursor.isoformat()
        existing = await _gc("hrms_attendance").find_one(
            {"company_id": str(company_id), "employee_code": leave["employee_code"], "work_date": wd})
        if not (existing and existing.get("locked")):
            await _gc("hrms_attendance").update_one(
                {"company_id": str(company_id), "employee_code": leave["employee_code"],
                 "work_date": wd},
                {"$set": {"status": AttendanceStatus.ON_LEAVE.value, "source": "leave",
                          "leave_ref": leave["leave_no"], "updated_at": now},
                 "$setOnInsert": {"company_id": str(company_id),
                                  "employee_code": leave["employee_code"], "work_date": wd,
                                  "created_at": now, "locked": False, "worked_minutes": None,
                                  "late_minutes": 0}},
                upsert=True,
            )
        cursor += timedelta(days=1)


async def cancel_leave(actor: dict, company_id: str, leave_no: str, reason: str) -> dict:
    """§7.10 step 76: controlled withdrawal, restoring whatever it consumed."""
    doc = await _get_leave(company_id, leave_no)
    if doc["status"] not in OPEN_LEAVE_STATUSES | {LeaveStatus.APPROVED.value}:
        raise HTTPException(status_code=409, detail=f"{leave_no} cannot be cancelled from "
                                                     f"\"{doc['status']}\".")
    was_approved = doc["status"] == LeaveStatus.APPROVED.value
    now = datetime.now(timezone.utc)
    await get_collection(COLL_LEAVES).update_one(
        {"_id": doc["_id"]},
        {"$set": {"status": LeaveStatus.CANCELLED.value, "cancelled_reason": reason,
                  "cancelled_at": now, "updated_at": now}},
    )
    if was_approved:
        if doc["leave_type"] == "C-Off":
            await get_collection(COLL_COFF_LEDGER).update_many(
                {"used_in_leave_no": leave_no},
                {"$set": {"status": CoffLedgerStatus.AVAILABLE.value, "used_in_leave_no": None,
                          "used_at": None}})
        else:
            year = int(doc["start_date"][:4])
            bal = await _get_balance(company_id, doc["employee_code"], doc["leave_type"], year)
            await get_collection(COLL_LEAVE_BALANCES).update_one(
                {"_id": bal["_id"]},
                {"$inc": {"used": -doc["days_count"]}, "$set": {"updated_at": now}})
    await audit(actor, AUDIT_LEAVE_CANCELLED, ENTITY_LEAVE_REQUEST, leave_no, reason, company_id)
    return _out(await _get_leave(company_id, leave_no))


# ─────────────────────────────────────────────────────────────
# §7.11 — Compensatory Off (earn -> ledger -> use)
# ─────────────────────────────────────────────────────────────
async def request_coff_earn(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    earned_for_date = str(payload.get("earned_for_date") or "").strip()
    if not (employee_code and earned_for_date):
        raise HTTPException(
            status_code=422, detail="employee_code and earned_for_date are required.")
    await _get_profile(company_id, employee_code)
    await _assert_self_or_privileged(actor, company_id, employee_code)

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id), "employee_code": employee_code,
        "earned_for_date": earned_for_date, "note": payload.get("note"),
        "status": CoffLedgerStatus.PENDING_APPROVAL.value,
        "credited_days": 1,
        "approved_by": None, "approved_at": None,
        "expiry_date": None,               # set on approval, from the C-Off policy's expiry days
        "used_in_leave_no": None, "used_at": None,
        "created_at": now, "updated_at": now,
    }
    result = await get_collection(COLL_COFF_LEDGER).insert_one(doc)
    doc["_id"] = result.inserted_id
    await audit(actor, AUDIT_COFF_EARN_REQUESTED, ENTITY_COFF, str(doc["_id"]),
               f"{employee_code}, worked {earned_for_date}", company_id)
    return _out_with_id(doc)


async def list_coff_ledger(actor: dict, company_id: str, *, employee_code: Optional[str] = None,
                           status: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if employee_code:
        query["employee_code"] = employee_code
    if status:
        query["status"] = status
    query = await _scope_query(actor, company_id, query)
    rows = await get_collection(COLL_COFF_LEDGER).find(query).sort(
        "created_at", -1).to_list(min(limit, MAX_ATTENDANCE_LIST_PAGE))
    return [_out_with_id(r) for r in rows]


async def act_on_coff_earn(actor: dict, company_id: str, batch_id: str, payload: dict) -> dict:
    from bson import ObjectId
    from bson.errors import InvalidId
    try:
        oid = ObjectId(str(batch_id))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid C-Off batch id.")
    doc = await get_collection(COLL_COFF_LEDGER).find_one(
        {"_id": oid, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="C-Off earn request not found.")
    if doc["status"] != CoffLedgerStatus.PENDING_APPROVAL.value:
        raise HTTPException(status_code=409, detail=f"Already \"{doc['status']}\".")

    approved = bool(payload.get("approved"))
    now = datetime.now(timezone.utc)
    updates = {"approved_by": str(actor.get("_id") or ""), "approved_at": now,
              "remarks": payload.get("remarks"), "updated_at": now}
    if approved:
        coff_cfg = await _get_leave_type(company_id, "C-Off")
        expiry_days = int(coff_cfg.get("coff_expiry_days") or 60)
        earned = doc["earned_for_date"]
        y, m, d = (int(x) for x in earned.split("-"))
        updates["status"] = CoffLedgerStatus.AVAILABLE.value
        updates["expiry_date"] = (date(y, m, d) + timedelta(days=expiry_days)).isoformat()
    else:
        updates["status"] = CoffLedgerStatus.REJECTED.value
    await get_collection(COLL_COFF_LEDGER).update_one({"_id": oid}, {"$set": updates})
    await audit(actor, AUDIT_COFF_EARN_ACTIONED, ENTITY_COFF, str(oid),
               updates["status"], company_id)
    saved = await get_collection(COLL_COFF_LEDGER).find_one({"_id": oid})
    return _out_with_id(saved)


async def _coff_available_balance(company_id: str, employee_code: str) -> float:
    today = _today()
    rows = await get_collection(COLL_COFF_LEDGER).find({
        "company_id": str(company_id), "employee_code": employee_code,
        "status": CoffLedgerStatus.AVAILABLE.value, "expiry_date": {"$gte": today},
    }).to_list(1000)
    return sum(r.get("credited_days", 0) for r in rows)


async def _debit_coff(company_id: str, employee_code: str, days_needed: float,
                      leave_no: str) -> list:
    """FIFO by nearest expiry (§7.11 step 81) — the batches actually consumed, for the
    leave record's own audit trail (`coff_batches_used`) and so cancel_leave can find and
    restore exactly these batches later."""
    today = _today()
    batches = await get_collection(COLL_COFF_LEDGER).find({
        "company_id": str(company_id), "employee_code": employee_code,
        "status": CoffLedgerStatus.AVAILABLE.value, "expiry_date": {"$gte": today},
    }).sort("expiry_date", 1).to_list(1000)

    remaining = days_needed
    used_ids = []
    now = datetime.now(timezone.utc)
    for batch in batches:
        if remaining <= 0:
            break
        used_ids.append(str(batch["_id"]))
        remaining -= batch.get("credited_days", 0)
    if remaining > 0:
        raise HTTPException(status_code=409, detail="C-Off balance changed; insufficient at approval time.")

    from bson import ObjectId
    if used_ids:
        await get_collection(COLL_COFF_LEDGER).update_many(
            {"_id": {"$in": [ObjectId(i) for i in used_ids]}},
            {"$set": {"status": CoffLedgerStatus.USED.value, "used_at": now,
                      "used_in_leave_no": leave_no}})
    return used_ids
