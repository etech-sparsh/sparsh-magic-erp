"""HRMS > batch interview windows (Annexure C efficiency).

"Schedule interviews in batches to reduce panel disruption."

A department declares the slots its panel keeps free -- Tuesday 14:00-17:00, say -- and
scheduling outside one produces a WARNING in the response.

-- It is a warning, and it will stay a warning ------------------------------------------------
A hard block would make an urgent hire impossible at 4pm on a Friday, which is exactly when
an urgent hire happens. Worse, it would push the booking off-system: somebody would agree the
time on the phone and back-date it, and the module would then hold a schedule that is not the
schedule. A preference the system states and does not enforce is more accurate than a rule it
enforces and people route around.

The enforcement point lives in `hrms_interview_service.interview_window_warning`; this module
owns the windows themselves.

-- No windows means no warning -----------------------------------------------------------------
A company that has not opted into batching is not permanently "out of window". The check
returns nothing at all when a department has declared no slots, so the feature is genuinely
opt-in rather than opt-out-by-configuration.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_WINDOW_CREATED, AUDIT_WINDOW_DELETED, AUDIT_WINDOW_UPDATED, COLL_DEPARTMENTS,
    COLL_INTERVIEW_WINDOWS, ENTITY_INTERVIEW_WINDOW, TIME_RE, WEEKDAYS,
)
from app.services.hrms_audit_service import audit
from app.utils.hrms_public_guard import clean_text

MAX_PANEL_IDS = 20


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


def _validate_time(value: str, label: str) -> str:
    """HH:MM, 24-hour. Validated as a SHAPE before it is ever compared.

    A window stored as "2pm" would never match anything, and a comparison that silently
    never matches reads exactly like a warning that never fires -- which is indistinguishable
    from the feature working perfectly.
    """
    text = clean_text(value, limit=5) or ""
    if not TIME_RE.match(text):
        raise HTTPException(
            status_code=422,
            detail=f"{label} must be a 24-hour time like 09:30 or 14:00.")
    return text


def _validate_weekday(value: str) -> str:
    text = (clean_text(value, limit=12) or "").strip().title()
    if text not in WEEKDAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Weekday must be one of: {', '.join(WEEKDAYS)}.")
    return text


async def _resolve_department(company_id: str, department_id: str) -> str:
    if not department_id:
        raise HTTPException(status_code=422, detail="Choose a department.")
    try:
        oid = ObjectId(str(department_id))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=422, detail="Invalid department.")
    row = await get_collection(COLL_DEPARTMENTS).find_one(
        {"_id": oid, "company_id": str(company_id)}, {"name": 1})
    if not row:
        raise HTTPException(
            status_code=422, detail="That department does not exist for this company.")
    return row.get("name")


async def _resolve_panel_ids(company_id: str, panel_ids) -> list:
    """The users this department's panel usually draws on. Advisory, like the window itself.

    Still checked against the company: an id that resolves to nobody would render as a blank
    name on the screen and quietly stop meaning anything.
    """
    ids = [str(p).strip() for p in (panel_ids or []) if str(p or "").strip()]
    if len(ids) > MAX_PANEL_IDS:
        raise HTTPException(
            status_code=422, detail=f"At most {MAX_PANEL_IDS} panel members per window.")
    out = []
    for user_id in dict.fromkeys(ids):
        try:
            oid = ObjectId(user_id)
        except (InvalidId, TypeError):
            raise HTTPException(status_code=422, detail="Invalid panel member.")
        person = await get_collection("learners").find_one(
            {"_id": oid, "company_id": str(company_id)},
            {"full_name": 1, "email": 1})
        if not person:
            raise HTTPException(
                status_code=422,
                detail="Every panel member must be a user of this company.")
        out.append({"user_id": user_id,
                    "name": person.get("full_name") or person.get("email")})
    return out


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_windows(company_id: str, *, department_id: str = None,
                       include_inactive: bool = False) -> dict:
    query = {"company_id": str(company_id)}
    if department_id:
        query["department_id"] = str(department_id)
    if not include_inactive:
        query["active"] = True
    rows = await get_collection(COLL_INTERVIEW_WINDOWS).find(query).to_list(200)
    # Sorted by the week, not alphabetically: "Friday, Monday, Thursday" is a list nobody
    # can read as a schedule.
    rows.sort(key=lambda r: (WEEKDAYS.index(r["weekday"])
                             if r.get("weekday") in WEEKDAYS else 99,
                             str(r.get("start_time") or "")))
    return {"interview_windows": [_out(r) for r in rows], "total": len(rows)}


# -------------------------------------------------------------
# Write
# -------------------------------------------------------------
async def create_window(actor: dict, company_id: str, payload: dict) -> dict:
    department_id = str(payload.get("department_id") or "")
    department_name = await _resolve_department(company_id, department_id)
    weekday = _validate_weekday(payload.get("weekday"))
    start = _validate_time(payload.get("start_time"), "The start time")
    end = _validate_time(payload.get("end_time"), "The end time")
    if start >= end:
        raise HTTPException(
            status_code=422,
            detail="A window must end after it starts. For an overnight slot, define two.")

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id),
        "department_id": department_id,
        "department_name": department_name,
        "weekday": weekday,
        "start_time": start,
        "end_time": end,
        "panel_ids": await _resolve_panel_ids(company_id, payload.get("panel_ids")),
        "active": bool(payload.get("active", True)),
        "notes": clean_text(payload.get("notes"), limit=1000),
        "created_by": str(actor.get("_id") or ""),
        "created_at": now,
    }
    result = await get_collection(COLL_INTERVIEW_WINDOWS).insert_one(dict(doc))
    doc["_id"] = result.inserted_id
    await audit(actor, AUDIT_WINDOW_CREATED, ENTITY_INTERVIEW_WINDOW,
                str(result.inserted_id),
                f"{department_name}: {weekday} {start}-{end}", company_id)
    return _out(doc)


async def update_window(actor: dict, company_id: str, window_id: str,
                        payload: dict) -> dict:
    coll = get_collection(COLL_INTERVIEW_WINDOWS)
    try:
        oid = ObjectId(str(window_id))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid window id.")
    current = await coll.find_one({"_id": oid, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Interview window not found.")

    updates = {}
    if payload.get("weekday") is not None:
        updates["weekday"] = _validate_weekday(payload["weekday"])
    if payload.get("start_time") is not None:
        updates["start_time"] = _validate_time(payload["start_time"], "The start time")
    if payload.get("end_time") is not None:
        updates["end_time"] = _validate_time(payload["end_time"], "The end time")
    start = updates.get("start_time", current.get("start_time"))
    end = updates.get("end_time", current.get("end_time"))
    if start and end and start >= end:
        raise HTTPException(
            status_code=422,
            detail="A window must end after it starts. For an overnight slot, define two.")
    if payload.get("panel_ids") is not None:
        updates["panel_ids"] = await _resolve_panel_ids(company_id, payload["panel_ids"])
    if payload.get("active") is not None:
        updates["active"] = bool(payload["active"])
    if payload.get("notes") is not None:
        updates["notes"] = clean_text(payload["notes"], limit=1000)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    await coll.update_one({"_id": oid}, {"$set": updates})
    await audit(actor, AUDIT_WINDOW_UPDATED, ENTITY_INTERVIEW_WINDOW, str(window_id),
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)
    fresh = await coll.find_one({"_id": oid})
    return _out(fresh)


async def delete_window(actor: dict, company_id: str, window_id: str) -> dict:
    """Remove a window outright.

    Deleted rather than deactivated, unlike almost everything else in this module. A window
    is a PREFERENCE with no history worth keeping: nothing references it, no decision was
    made against it, and a list cluttered with retired slots is a list nobody maintains.
    """
    try:
        oid = ObjectId(str(window_id))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid window id.")
    current = await get_collection(COLL_INTERVIEW_WINDOWS).find_one(
        {"_id": oid, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Interview window not found.")
    await get_collection(COLL_INTERVIEW_WINDOWS).delete_one({"_id": oid})
    await audit(actor, AUDIT_WINDOW_DELETED, ENTITY_INTERVIEW_WINDOW, str(window_id),
                f'{current.get("department_name")}: {current.get("weekday")} '
                f'{current.get("start_time")}-{current.get("end_time")}', company_id)
    return {"deleted": True, "id": str(window_id)}
