"""HRMS > Absconding / Abandonment (BA/Functional Design v2.2, §7.19).

3 consecutive unexplained working days -> flag -> logged contact attempts -> a two-stage
warning ladder (First, then Second, each gated on a configurable window since the case was
flagged / the prior warning) -> an authorised final decision that either returns the case to
Returned-to-Work or converts it into a separation (handed to Exit Management, exit_type
Absconding — this module owns the pre-separation ladder, not the exit process itself).

-- The window is a POLICY VALUE, not a hardcoded constant --------------------------------------
§7.19 BR: "Current policy uses 3 consecutive working days and two 7-day warning windows before
final action." DEFAULT_ABSCONDING_POLICY carries these as the adjustable starting point (the
same discipline DEFAULT_SHIFT_POLICY already established for Attendance) — read from
hrms_settings, editable by HR, never compiled into the escalation check as a literal number.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_ABSCONDING_CONTACT, AUDIT_ABSCONDING_DECIDED, AUDIT_ABSCONDING_FLAGGED,
    AUDIT_ABSCONDING_WARNING,
    COLL_ABSCONDING_CASES, COLL_EMPLOYEE_PROFILES, COLL_SETTINGS,
    DEFAULT_ABSCONDING_POLICY,
    ENTITY_ABSCONDING, OPEN_ABSCONDING_STATUSES,
    AbscondingStatus,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _get_profile(company_id: str, employee_code: str) -> dict:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code})
    if not profile:
        raise HTTPException(status_code=404, detail="No employee with that code in this company.")
    return profile


async def get_absconding_policy(company_id: str) -> dict:
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)})
    stored = (doc or {}).get("absconding_policy") or {}
    return {**DEFAULT_ABSCONDING_POLICY, **stored}


async def save_absconding_policy(actor: dict, company_id: str, payload: dict) -> dict:
    merged = {**await get_absconding_policy(company_id),
             **{k: v for k, v in payload.items() if v is not None}}
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": str(company_id)},
        {"$set": {"absconding_policy": merged, "updated_at": datetime.now(timezone.utc)},
         "$setOnInsert": {"company_id": str(company_id)}},
        upsert=True,
    )
    return merged


async def flag_case(actor: dict, company_id: str, payload: dict) -> dict:
    employee_code = str(payload.get("employee_code") or "").strip()
    if not employee_code:
        raise HTTPException(status_code=422, detail="Select an employee.")
    profile = await _get_profile(company_id, employee_code)

    existing_open = await get_collection(COLL_ABSCONDING_CASES).find_one({
        "company_id": str(company_id), "employee_code": employee_code,
        "status": {"$in": list(OPEN_ABSCONDING_STATUSES)},
    })
    if existing_open:
        raise HTTPException(
            status_code=409,
            detail=f"{employee_code} already has an open absconding case "
                   f"({existing_open['case_no']}).")

    flagged_date = payload.get("flagged_date") or _today()
    year = datetime.now(timezone.utc).year
    case_no = await next_business_id("absconding_case", str(company_id), year)
    now = datetime.now(timezone.utc)
    doc = {
        "case_no": case_no,
        "company_id": str(company_id),
        "employee_code": employee_code,
        "employee_name": profile.get("display_name") or profile.get("full_name"),
        "flagged_date": flagged_date,
        "notes": payload.get("notes"),
        "status": AbscondingStatus.FLAGGED.value,
        "contact_attempts": [],
        "first_warning_sent_at": None, "second_warning_sent_at": None,
        "final_action_at": None, "final_resolution": None, "final_remarks": None,
        "linked_sep_no": None,
        "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_ABSCONDING_CASES).insert_one(doc)
    await audit(actor, AUDIT_ABSCONDING_FLAGGED, ENTITY_ABSCONDING, case_no,
               f"{employee_code}, unexplained since {flagged_date}", company_id)
    return _out(doc)


async def list_cases(actor: dict, company_id: str, *, status: Optional[str] = None,
                     employee_code: Optional[str] = None, limit: int = 100) -> list:
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    if employee_code:
        query["employee_code"] = employee_code
    rows = await get_collection(COLL_ABSCONDING_CASES).find(query).sort(
        "created_at", -1).to_list(limit)
    return [_out(r) for r in rows]


async def _get_case(company_id: str, case_no: str) -> dict:
    doc = await get_collection(COLL_ABSCONDING_CASES).find_one(
        {"company_id": str(company_id), "case_no": case_no})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Absconding case '{case_no}' not found.")
    return doc


async def get_case(actor: dict, company_id: str, case_no: str) -> dict:
    return _out(await _get_case(company_id, case_no))


async def log_contact_attempt(actor: dict, company_id: str, case_no: str, payload: dict) -> dict:
    doc = await _get_case(company_id, case_no)
    if doc["status"] not in OPEN_ABSCONDING_STATUSES:
        raise HTTPException(status_code=409, detail=f"{case_no} is already \"{doc['status']}\".")

    now = datetime.now(timezone.utc)
    entry = {"at": now, "by": str(actor.get("_id") or ""), "method": payload.get("method"),
             "outcome": payload.get("outcome"),
             "postal_tracking_ref": payload.get("postal_tracking_ref")}
    await get_collection(COLL_ABSCONDING_CASES).update_one(
        {"_id": doc["_id"]}, {"$push": {"contact_attempts": entry}, "$set": {"updated_at": now}})
    await audit(actor, AUDIT_ABSCONDING_CONTACT, ENTITY_ABSCONDING, case_no,
               f"{payload.get('method')}: {payload.get('outcome')}", company_id)
    return await get_case(actor, company_id, case_no)


def _days_since(iso_date: str) -> int:
    y, m, d = (int(x) for x in iso_date.split("-"))
    return (date.today() - date(y, m, d)).days


async def send_warning(actor: dict, company_id: str, case_no: str, stage: str,
                       payload: dict) -> dict:
    """§7.19 steps 150-152: First, then Second, each gated on the configured window since the
    case was flagged (First) or the first warning was sent (Second) — the SLA clock the BA doc
    names explicitly, enforced here rather than left to whoever remembers to check a calendar.
    """
    doc = await _get_case(company_id, case_no)
    if doc["status"] not in OPEN_ABSCONDING_STATUSES:
        raise HTTPException(status_code=409, detail=f"{case_no} is already \"{doc['status']}\".")
    policy = await get_absconding_policy(company_id)
    window = policy["warning_window_days"]
    now = datetime.now(timezone.utc)

    if stage == "First":
        if doc["status"] != AbscondingStatus.FLAGGED.value:
            raise HTTPException(status_code=409, detail=f"{case_no} already has a First Warning.")
        update = {"status": AbscondingStatus.FIRST_WARNING_SENT.value,
                 "first_warning_sent_at": now}
    elif stage == "Second":
        if doc["status"] != AbscondingStatus.FIRST_WARNING_SENT.value:
            raise HTTPException(
                status_code=409, detail=f"{case_no} needs a First Warning before a Second.")
        elapsed = _days_since(doc["first_warning_sent_at"].strftime("%Y-%m-%d"))
        if elapsed < window:
            raise HTTPException(
                status_code=409,
                detail=f"Only {elapsed} of {window} configured days have passed since the "
                       f"First Warning.")
        update = {"status": AbscondingStatus.SECOND_WARNING_SENT.value,
                 "second_warning_sent_at": now}
    else:
        raise HTTPException(status_code=422, detail="stage must be 'First' or 'Second'.")

    update["updated_at"] = now
    await get_collection(COLL_ABSCONDING_CASES).update_one({"_id": doc["_id"]}, {"$set": update})
    await audit(actor, AUDIT_ABSCONDING_WARNING, ENTITY_ABSCONDING, case_no,
               f"{stage} Warning sent", company_id)
    return await get_case(actor, company_id, case_no)


async def final_action(actor: dict, company_id: str, case_no: str, payload: dict) -> dict:
    """§7.19 step 153: "Employee status is changed only after authorised final decision" —
    the gate this capability (ABSCONDING_DECIDE) exists for. A resolution of "Converted to
    Separation" hands off to Exit Management by calling initiate_separation directly, so the
    case and the resulting SEP-number are linked from the moment the decision is made."""
    doc = await _get_case(company_id, case_no)
    if doc["status"] not in OPEN_ABSCONDING_STATUSES:
        raise HTTPException(status_code=409, detail=f"{case_no} is already \"{doc['status']}\".")

    resolution = payload.get("resolution")
    now = datetime.now(timezone.utc)
    update = {"final_action_at": now, "final_resolution": resolution,
             "final_remarks": payload.get("remarks"), "updated_at": now}

    if resolution == "Returned to Work":
        update["status"] = AbscondingStatus.RETURNED_TO_WORK.value
    elif resolution == "Converted to Separation":
        from app.services import hrms_exit_service as exit_mgmt
        sep = await exit_mgmt.initiate_separation(actor, company_id, {
            "employee_code": doc["employee_code"], "exit_type": "Absconding",
            "resignation_date": doc["flagged_date"],
            "reason": f"Absconding case {case_no}: {payload.get('remarks') or 'no response to warnings'}",
        })
        update["status"] = AbscondingStatus.CONVERTED_TO_SEPARATION.value
        update["linked_sep_no"] = sep["sep_no"]
    else:
        raise HTTPException(
            status_code=422,
            detail="resolution must be 'Returned to Work' or 'Converted to Separation'.")

    await get_collection(COLL_ABSCONDING_CASES).update_one({"_id": doc["_id"]}, {"$set": update})
    await audit(actor, AUDIT_ABSCONDING_DECIDED, ENTITY_ABSCONDING, case_no, resolution, company_id)
    return await get_case(actor, company_id, case_no)
