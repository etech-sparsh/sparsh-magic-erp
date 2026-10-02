"""
TPMS ▸ scheduling service.

Direct port of the Apps Script scheduling rules (`copy_of calender/code.js`):
  • buildOccurrences_        (code.js:1304)  → build_occurrences()
  • checkScheduleConflict    (code.js:735)   → check_schedule_conflict()
  • saveSchedule role scope  (code.js:808)   → assert_can_schedule()

WHY NOT REUSE THE ERP RECURRENCE ENGINE
---------------------------------------
`POST /calendar/events` has its own recurrence generator, but its semantics differ from
the Apps Script in ways that would change behaviour:
  • it is driven by `repeat` + `repeat_interval` (Daily/Weekly/Monthly/Yearly/Custom),
    whereas TPMS uses One-time/Monthly/Weekly/Periodically + a weekday mask;
  • TPMS's Monthly clamps the day-of-month to short months (31st → 28/30), which the
    ERP engine does not do;
  • its route-level permission gate allows ONLY admin/superadmin to create an event
    carrying an `activity`, while TPMS explicitly allows Staff and Learner to schedule
    (each scoped to their own companies).
So TPMS keeps its own generator for exact parity. Everything downstream — storage,
reminders, the calendar UI — is still the shared ERP machinery.
"""
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional

from bson import ObjectId
from fastapi import HTTPException

logger = logging.getLogger(__name__)

from app.db.mongodb import get_collection
from app.models.tpms import (
    COLL_ACTIVITIES, COLL_ACTIVITY_TRACKER, COLL_REMINDER_RULES,
    RECURRENCE_ONE_TIME, RECURRENCE_DAILY, RECURRENCE_MONTHLY, RECURRENCE_WEEKLY, RECURRENCE_PERIODICALLY,
    SCOPE_HOD, STATUS_CANCELLED, STATUS_RESCHEDULED, STATUS_SCHEDULED, TPMS_EVENT_KIND,
    DEFAULT_REMIND_TIME, OFFSET_UNIT_SECONDS,
    CHANNEL_EMAIL, CHANNEL_WHATSAPP, CHANNEL_BOTH,
    erp_status_for, is_once_per_month, period_from_date,
)
from app.utils.calendar_utils import get_target_collection_name

# Events are spread across these collections (see app/utils/calendar_utils.py). Every
# TPMS aggregation must scan all three — never hardcode one.
CAL_COLLECTIONS = ["STAFF_CALENDER", "LEARNER_CALENDER", "calendar_events"]

STAFF_ROLES = {"superadmin", "admin"}
CLIENT_ROLES = {"clientadmin", "clientuser"}


# ─────────────────────────────────────────────────────────────
# Date helpers
# ─────────────────────────────────────────────────────────────
def _parse_ymd(value) -> Optional[date]:
    """Port of parseYMD_ (code.js:1303). Returns None on anything unparseable."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value or "").strip()[:10]
    parts = s.split("-")
    if len(parts) != 3:
        return None
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        return None


def _js_weekday(d: date) -> int:
    """JavaScript getDay(): 0=Sunday..6=Saturday. Python weekday(): 0=Monday..6=Sunday."""
    return (d.weekday() + 1) % 7


def _days_in_month(year: int, month: int) -> int:
    return (date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)).day


# M14 — Sunday is a company holiday: no activity is scheduled on a Sunday or a holiday.
# TPMS_WEEKLY_OFF uses Python weekday() (Mon=0 … Sun=6), so {6} == Sunday.
TPMS_WEEKLY_OFF = {6}


async def _load_tpms_holidays() -> set:
    """Active holiday dates as ISO 'YYYY-MM-DD' strings — same master source (collection
    'holidays') the task rollover and the date pickers use."""
    try:
        docs = await get_collection("holidays").find(
            {"status": {"$ne": "inactive"}}, {"holiday_date": 1}).to_list(5000)
        return {d.get("holiday_date") for d in docs if d.get("holiday_date")}
    except Exception:
        return set()


def _is_off_day(d: date, holidays: set) -> bool:
    return d.weekday() in TPMS_WEEKLY_OFF or d.isoformat() in holidays


def _shift_off_days(dates: List[date], holidays: set, max_shift: int = 14) -> List[date]:
    """Move any occurrence that lands on a Sunday/holiday forward to the next working day,
    de-duplicating so two shifted occurrences never collide on the same date."""
    out: List[date] = []
    seen = set()
    for d in dates:
        nd = d
        for _ in range(max_shift):
            if not _is_off_day(nd, holidays):
                break
            nd = nd + timedelta(days=1)
        if nd not in seen:
            seen.add(nd)
            out.append(nd)
    return out


# ─────────────────────────────────────────────────────────────
# Recurrence — exact port of buildOccurrences_ (code.js:1304)
# ─────────────────────────────────────────────────────────────
def build_occurrences(payload: dict) -> List[date]:
    """Expand a schedule payload into its occurrence dates.

    Mirrors the Apps Script, plus one closed gap:
      • "Daily" now generates one occurrence per day from plan_start..plan_end (the Apps
        Script offered it in the UI but never implemented it).
      • Monthly clamps the day-of-month to the target month's length, so a 31st start
        lands on the 28th/30th in shorter months, then returns to 31 where possible.
      • plan_end defaults to plan_start; an end before the start yields nothing.
    """
    recurrence = payload.get("recurrence") or RECURRENCE_ONE_TIME
    start = _parse_ymd(payload.get("plan_start") or payload.get("planStart"))
    end = _parse_ymd(payload.get("plan_end") or payload.get("planEnd")) or start

    if not start:
        return []
    if recurrence == RECURRENCE_ONE_TIME:
        return [start]
    if not end or end < start:
        return []

    out: List[date] = []

    if recurrence == RECURRENCE_DAILY:
        d = start
        while d <= end:
            out.append(d)
            d += timedelta(days=1)

    elif recurrence == RECURRENCE_MONTHLY:
        day = start.day
        year, month = start.year, start.month
        while True:
            dim = _days_in_month(year, month)
            d = date(year, month, min(day, dim))
            if d > end:
                break
            if d >= start:
                out.append(d)
            month += 1
            if month > 12:
                month = 1
                year += 1

    elif recurrence == RECURRENCE_WEEKLY:
        d = start
        while d <= end:
            out.append(d)
            d += timedelta(days=7)

    elif recurrence == RECURRENCE_PERIODICALLY:
        wanted = {int(n) for n in (payload.get("weekdays") or []) if str(n).strip() != ""}
        d = start
        while d <= end:
            if _js_weekday(d) in wanted:
                out.append(d)
            d += timedelta(days=1)

    # Any unrecognized recurrence value yields [] (the caller treats empty as an error).
    return out


# ─────────────────────────────────────────────────────────────
# Activity catalogue lookup
# ─────────────────────────────────────────────────────────────
async def get_activity(name: str) -> Optional[dict]:
    if not name:
        return None
    return await get_collection(COLL_ACTIVITIES).find_one(
        {"name": {"$regex": f"^{_escape_regex(name)}$", "$options": "i"}}
    )


def _escape_regex(s: str) -> str:
    import re
    return re.escape(str(s or ""))


# ─────────────────────────────────────────────────────────────
# Duplicate / frequency check — exact port of checkScheduleConflict (code.js:735)
# ─────────────────────────────────────────────────────────────
async def check_schedule_conflict(payload: dict) -> dict:
    """Warn when a once-per-month activity is already scheduled this month.

    Scope follows the activity catalogue's `scope`:
      • company → any existing occurrence for the company that month conflicts
      • hod     → only conflicts when one of the selected doers already has it
    Cancelled occurrences never block. This is advisory: the UI offers
    "Schedule Anyway", which simply skips the check.
    """
    activity = str(payload.get("activity") or "").strip()
    company_id = str(payload.get("company_id") or payload.get("companyId") or "").strip()
    plan_start = str(payload.get("plan_start") or payload.get("planStart") or "").strip()
    if not activity or not company_id or not plan_start:
        return {"conflict": False}

    meta = await get_activity(activity)
    frequency = (meta or {}).get("frequency", "")
    scope = (meta or {}).get("scope", "")

    # Only "once"-type activities are enforced; "3-4 in month" / "multiple times" exempt.
    if not is_once_per_month(frequency):
        return {"conflict": False, "frequency": frequency, "scope": scope}

    hod_wise = scope == SCOPE_HOD
    want_period = period_from_date(plan_start)
    new_doers = {str(d).strip() for d in (payload.get("member_ids")
                                          or payload.get("companyAssigners") or []) if str(d).strip()}

    matches = []
    for coll in CAL_COLLECTIONS:
        docs = await get_collection(coll).find({
            "kind": TPMS_EVENT_KIND,
            "company_id": company_id,
            "activity": {"$regex": f"^{_escape_regex(activity)}$", "$options": "i"},
        }).to_list(2000)

        for o in docs:
            if str(o.get("status") or "").strip().lower() == STATUS_CANCELLED.lower():
                continue
            event_date = str(o.get("start") or "")[:10]
            if period_from_date(event_date) != want_period:
                continue
            if hod_wise and new_doers:
                existing = {str(m) for m in (o.get("assigned_member_ids") or [])}
                if not (existing & new_doers):
                    continue
            matches.append({
                "event_id": str(o.get("_id")),
                "title": o.get("title") or "",
                "date": event_date,
                "time": str(o.get("start") or "")[11:16],
                "status": o.get("status") or "Scheduled",
                "doers": o.get("assigned_member_ids") or [],
                "staff": o.get("coach_ids") or [],
                "company": o.get("company_name") or "",
            })

    matches.sort(key=lambda m: m.get("date") or "")
    return {
        "conflict": bool(matches),
        "scope": "HOD" if hod_wise else "Company",
        "period": want_period,
        "frequency": frequency,
        "existing": matches,
    }


# ─────────────────────────────────────────────────────────────
# Write scoping — port of the guards at the top of saveSchedule (code.js:808)
# ─────────────────────────────────────────────────────────────
async def assert_can_schedule(user: dict, company_id: str) -> None:
    """Admin: any company. Staff (internal, non-admin): only companies they own as
    SMOps. Client-side users: only their own company."""
    role = (user.get("role") or "").lower()
    company_id = str(company_id or "").strip()
    if not company_id:
        raise HTTPException(status_code=400, detail="company_id is required")

    # Nothing may be scheduled INTO a company that has TPMS switched off — including by an
    # admin, who would otherwise create activities the company can never see or act on.
    from app.utils.tpms_access import is_tpms_enabled
    if not await is_tpms_enabled(company_id):
        raise HTTPException(
            status_code=403,
            detail="TPMS is not enabled for this company. Enable it on the company page first.",
        )

    if role in STAFF_ROLES:
        return

    if role in CLIENT_ROLES:
        if company_id != str(user.get("company_id") or ""):
            raise HTTPException(status_code=403, detail="You can only schedule for your own company.")
        return

    # Internal non-admin (SMOps): must own the company.
    from bson import ObjectId
    from bson.errors import InvalidId
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
    except (InvalidId, TypeError):
        company = None
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    uid = str(user.get("_id"))
    owners = {str(company.get("owner") or ""), str(company.get("admin_id") or "")}
    owners |= {str(x) for x in (company.get("smops_ids") or [])}
    if uid not in owners:
        raise HTTPException(status_code=403, detail="You can only schedule for your own companies.")


# ─────────────────────────────────────────────────────────────
# Reminders — mapped onto the ERP's existing reminder shape so the running
# reminder_scheduler fires them. No second cron is introduced.
# (writeReminders_ code.js:1206 + autoRemindersFromRules_ code.js:3690)
# ─────────────────────────────────────────────────────────────
_CHANNEL_TO_ERP = {
    CHANNEL_EMAIL: "email",
    CHANNEL_WHATSAPP: "whatsapp",
    CHANNEL_BOTH: "both",
}


def _offset_minutes(value, unit: str) -> int:
    seconds = OFFSET_UNIT_SECONDS.get(str(unit or "DAYS").upper(), 60)
    return int((float(value or 0) * seconds) // 60)


def _reminder_doc(channel: str, direction: str, value, unit: str, stage: str = "") -> dict:
    return {
        "id": str(ObjectId()),
        "parent_type": "event",
        "reminder_type": _CHANNEL_TO_ERP.get(channel, "email"),
        "timing_type": "after" if str(direction or "before").lower() == "after" else "before",
        "offset_minutes": _offset_minutes(value, unit),
        "sent": False,
        "created_at": datetime.utcnow(),
        "tpms_stage": stage or None,
    }


async def build_reminders(payload: dict) -> List[dict]:
    """Custom reminders from the payload PLUS the catalogue defaults for this activity.

    Mirrors saveSchedule (code.js:847-848), which writes the user's reminders and then
    unconditionally appends the rule-driven ones — so an activity always gets its
    Day-2 / Day-1 / 2h-before nudges even when the user adds none.

    ⚠ Apps-Script quirk reproduced: an `exact` reminder is attached only to the FIRST
    occurrence of a recurring batch, while offset reminders attach to every one
    (code.js:1210). Callers pass `first_only` through to honour this.
    """
    out: List[dict] = []

    for r in (payload.get("reminders") or []):
        if str(r.get("type") or "offset").lower() == "exact":
            # Exact reminders are absolute; converted to an offset by the caller, which
            # knows the occurrence date. Marked so create_schedule can first-only them.
            out.append({**_reminder_doc(r.get("channel"), "before", 0, "MINS", "exact"),
                        "tpms_exact_date": r.get("date"), "tpms_exact_time": r.get("time")})
        else:
            out.append(_reminder_doc(r.get("channel"), r.get("dir"), r.get("value"), r.get("unit")))

    activity = str(payload.get("activity") or "").strip()
    rules = await get_collection(COLL_REMINDER_RULES).find({
        "active": {"$ne": False},
        "$or": [{"activity": "*"}, {"activity": activity}],
    }).to_list(100)
    for rule in rules:
        out.append(_reminder_doc(rule.get("channel"), rule.get("offset_dir"),
                                 rule.get("offset_value"), rule.get("offset_unit"),
                                 rule.get("stage") or ""))
    return out


def _exact_reminder_offset(reminder: dict, occ_start: datetime) -> dict:
    """Turn an absolute 'exact' reminder (tpms_exact_date/time) into the offset the reminder
    scheduler understands (offset_minutes + timing_type), measured from this occurrence's
    start — so it fires at the chosen absolute moment instead of at event start."""
    doc = {k: v for k, v in reminder.items() if not k.startswith("tpms_exact")}
    d = str(reminder.get("tpms_exact_date") or "").strip()
    t = str(reminder.get("tpms_exact_time") or "").strip() or DEFAULT_REMIND_TIME
    try:
        target = datetime.fromisoformat(f"{d}T{t[:5]}:00")
    except Exception:
        return doc  # unparseable → leave the 0-offset default rather than crash the create
    delta_min = int(round((occ_start - target).total_seconds() / 60))
    doc["timing_type"] = "before" if delta_min >= 0 else "after"
    doc["offset_minutes"] = abs(delta_min)
    return doc


def _start_iso(day: date, event_time: Optional[str]) -> str:
    hhmm = (event_time or "").strip() or DEFAULT_REMIND_TIME
    return f"{day.isoformat()}T{hhmm[:5]}:00"


# ─────────────────────────────────────────────────────────────
# Create — port of saveSchedule (code.js:807)
# ─────────────────────────────────────────────────────────────
async def create_schedule(user: dict, payload: dict) -> dict:
    """Expand the recurrence into N calendar events sharing one `tpms_batch_id`, attach
    reminders, and write the Activity_Tracker rows the Success-Measure engine reads.

    Returns the same envelope the Apps Script did: {count, batch_id, reminders, tracker}.
    """
    company_id = str(payload.get("company_id") or payload.get("companyId") or "").strip()
    await assert_can_schedule(user, company_id)

    title = str(payload.get("title") or "").strip()
    activity = str(payload.get("activity") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Please fill: Title")
    if not activity:
        raise HTTPException(status_code=400, detail="Please fill: Activity")

    departments = [str(d).strip() for d in (payload.get("departments") or []) if str(d).strip()]
    member_ids = [str(m).strip() for m in (payload.get("member_ids") or []) if str(m).strip()]
    staff_ids = [str(s).strip() for s in (payload.get("staff_ids") or []) if str(s).strip()]
    if not departments:
        raise HTTPException(status_code=400, detail="Select at least one Department")
    if not member_ids:
        raise HTTPException(status_code=400, detail="Select at least one Company Assigner (doer)")
    # Client-side users schedule for themselves and don't assign internal staff
    # (mirrors the Apps Script UI, which hides the staff picker for Learners).
    if staff_ids == [] and (user.get("role") or "").lower() not in CLIENT_ROLES:
        raise HTTPException(status_code=400, detail="Select at least one Staff Assigner")

    occurrences = build_occurrences(payload)
    if not occurrences:
        raise HTTPException(
            status_code=400,
            detail="No dates generated. Check dates / recurrence / weekdays.",
        )
    # M14 (signed off: Sunday is a holiday) — shift any occurrence off a Sunday/holiday to the
    # next working day, keeping TPMS scheduling consistent with the task/todo rollover engine.
    occurrences = _shift_off_days(occurrences, await _load_tpms_holidays())

    meta = await get_activity(activity)
    event_time = payload.get("event_time") or payload.get("eventTime")
    reminders = await build_reminders(payload)
    batch_id = str(ObjectId())
    now = datetime.utcnow()
    creator_id = str(user.get("_id"))
    company_name = str(payload.get("company_name") or payload.get("companyName") or "")
    # M1 — "Scheduled by" dimension: was this schedule created by a client (the doer's own
    # side) or by internal SMOps/OM? Stored per occurrence so the calendar/dashboards can
    # badge and filter on it.
    creator_role = (user.get("role") or "").lower()
    scheduled_by_side = "client" if creator_role in CLIENT_ROLES else "internal"
    scheduled_by_name = (user.get("full_name")
                         or " ".join(filter(None, [user.get("first_name"), user.get("last_name")])).strip()
                         or user.get("name") or user.get("email") or "")

    docs = []
    for idx, day in enumerate(occurrences):
        occ_start = datetime.fromisoformat(_start_iso(day, event_time))
        # Exact reminders ride only on the first occurrence (Apps Script parity) and carry an
        # absolute date/time — convert that to an offset from this occurrence's start. Offset
        # reminders pass through unchanged.
        occ_reminders = []
        for r in reminders:
            if r.get("tpms_stage") == "exact":
                if idx == 0:
                    occ_reminders.append(_exact_reminder_offset(r, occ_start))
            else:
                occ_reminders.append({k: v for k, v in r.items() if not k.startswith("tpms_exact")})
        docs.append({
            "title": title,
            "type": "event",
            "start": _start_iso(day, event_time),
            "all_day": not bool(event_time),
            "kind": TPMS_EVENT_KIND,
            "tpms_batch_id": batch_id,
            "tpms_status": STATUS_SCHEDULED,
            "status": erp_status_for(STATUS_SCHEDULED),
            "activity": activity,
            "company_id": company_id,
            "company_name": company_name,
            "assigned_departments": departments,
            "assigned_member_ids": member_ids,
            "coach_ids": staff_ids,
            "additional_details": str(payload.get("comment") or ""),
            "reminders": occ_reminders,
            "esc_stage": 0,
            "reschedule_count": 0,
            "learner_done": False,
            "user_id": creator_id,
            "scheduled_by_side": scheduled_by_side,   # M1 — internal | client
            "scheduled_by_name": scheduled_by_name,
            "created_at": now,
            "activity_meta": {
                "scope": (meta or {}).get("scope"),
                "upload_required": bool((meta or {}).get("upload_required")),
                "recurrence": payload.get("recurrence") or RECURRENCE_ONE_TIME,
                "plan_start": payload.get("plan_start") or payload.get("planStart"),
                "plan_end": payload.get("plan_end") or payload.get("planEnd"),
            },
        })

    coll_name = await get_target_collection_name(docs[0])
    result = await get_collection(coll_name).insert_many(docs)
    event_ids = [str(_id) for _id in result.inserted_ids]

    tracker = await write_tracker_rows(docs, event_ids)

    # Schedule mail to both sides — DETACHED so the API returns immediately and the user sees the
    # success toast without waiting for every email (and form-link) to be generated. The send runs
    # on the event loop in the background; inline fallback only if there is no running loop.
    mails = {"detached": True}
    try:
        from app.services.tpms_notify_service import notify_schedule, _enqueue_status_mail, EVENT_SCHEDULE
        ev = {**docs[0], "_id": event_ids[0]}
        if not _enqueue_status_mail(ev, EVENT_SCHEDULE, "Scheduled", None):
            mails = await notify_schedule(ev)  # no running loop → send inline as a fallback
    except Exception as e:
        logger.error(f"TPMS schedule mail failed: {e}")

    return {
        "ok": True,
        "count": len(event_ids),
        "batch_id": batch_id,
        "event_ids": event_ids,
        "reminders": sum(len(d["reminders"]) for d in docs),
        "tracker": tracker,
        "mails": mails,
        "collection": coll_name,
    }


# ─────────────────────────────────────────────────────────────
# Activity tracker — port of writeTrackerRows_ (code.js:884)
# One row per (occurrence × doer). Feeds the Success-Measure engine and the
# Employee Activity dashboard.
# ─────────────────────────────────────────────────────────────
async def write_tracker_rows(event_docs: List[dict], event_ids: List[str]) -> int:
    rows = []
    for doc, event_id in zip(event_docs, event_ids):
        day = str(doc.get("start") or "")[:10]
        for member_id in (doc.get("assigned_member_ids") or []):
            rows.append({
                "company_id": doc.get("company_id"),
                "member_id": member_id,
                "period": period_from_date(day),
                "date": day,
                "activity": doc.get("activity"),
                "status": doc.get("tpms_status") or STATUS_SCHEDULED,
                "event_id": event_id,
                "updated_at": datetime.utcnow(),
            })
    if not rows:
        return 0
    try:
        await get_collection(COLL_ACTIVITY_TRACKER).insert_many(rows, ordered=False)
    except Exception:
        pass  # duplicate (event_id, member_id) — the unique index makes this idempotent
    return len(rows)


async def update_tracker_status(event_id: str, status: str) -> int:
    """Port of updateTrackerStatus_ (code.js:920)."""
    res = await get_collection(COLL_ACTIVITY_TRACKER).update_many(
        {"event_id": str(event_id)},
        {"$set": {"status": status, "updated_at": datetime.utcnow()}},
    )
    return res.modified_count


# ─────────────────────────────────────────────────────────────
# Update — port of updateSchedule (code.js:679)
# ─────────────────────────────────────────────────────────────
async def update_schedule(user: dict, event_id: str, payload: dict) -> dict:
    """Edit one occurrence.

    Apps-Script behaviour preserved: changing the date OR time automatically flips the
    status to Rescheduled and bumps `reschedule_count` — the UI shows this as a hint
    before saving (calMaybeReschedule, code.js:581). Reminders are re-armed so a moved
    activity nudges again.
    """
    from app.services.tpms_lifecycle_service import find_tpms_event
    doc, coll = await find_tpms_event(event_id)
    await assert_can_schedule(user, str(doc.get("company_id") or ""))

    # Spec §3 permission matrix — "Edit any" is Admin/Staff only. A client-side Learner may
    # edit ONLY an activity they created ("Edit own created"); a non-creator has no edit
    # right at all, and instead uses Request Reschedule / Mark Done. assert_can_schedule
    # above only proves company membership, which is not sufficient on its own.
    if (user.get("role") or "").lower() in CLIENT_ROLES \
            and str(doc.get("user_id") or "") != str(user.get("_id")):
        raise HTTPException(
            status_code=403,
            detail="You can only edit activities you created. Use Request Reschedule instead.",
        )

    old_start = str(doc.get("start") or "")
    old_date, old_time = old_start[:10], old_start[11:16]
    new_date = str(payload.get("plan_start") or payload.get("planStart") or old_date)[:10]
    new_time = str(payload.get("event_time") or payload.get("eventTime") or old_time)[:5]
    moved = (new_date != old_date) or (new_time != old_time)

    updates: dict = {"updated_at": datetime.utcnow()}
    for field, key in (("title", "title"), ("activity", "activity"),
                       ("company_name", "company_name")):
        if payload.get(key) is not None:
            updates[field] = payload[key]
    if payload.get("departments") is not None:
        updates["assigned_departments"] = [str(d) for d in payload["departments"]]
    if payload.get("member_ids") is not None:
        updates["assigned_member_ids"] = [str(m) for m in payload["member_ids"]]
    if payload.get("staff_ids") is not None:
        updates["coach_ids"] = [str(s) for s in payload["staff_ids"]]
    if payload.get("comment") is not None:
        updates["additional_details"] = str(payload["comment"])

    if moved:
        updates["start"] = f"{new_date}T{new_time or '00:00'}:00"
        updates["tpms_status"] = STATUS_RESCHEDULED
        updates["status"] = erp_status_for(STATUS_RESCHEDULED)
        updates["reschedule_count"] = int(doc.get("reschedule_count") or 0) + 1
        updates["esc_stage"] = 0
        updates["reminders"] = [{**r, "sent": False} for r in (doc.get("reminders") or [])]
    elif payload.get("status"):
        requested = str(payload["status"])
        updates["tpms_status"] = requested
        updates["status"] = erp_status_for(requested)
        # Re-activating an activity clears the escalation ladder (spec §5: esc_stage resets on
        # Scheduled/Rescheduled/Completed). Completion has its own reset in confirm_completion.
        if requested in (STATUS_SCHEDULED, STATUS_RESCHEDULED):
            updates["esc_stage"] = 0

    await get_collection(coll).update_one({"_id": doc["_id"]}, {"$set": updates})

    # Cancelling notifies both sides (spec §7). The pending reminders are consumed by the
    # reminder scheduler's terminal-status guard, so there is no separate reminder cleanup here.
    if updates.get("tpms_status") == STATUS_CANCELLED:
        try:
            from app.services.tpms_notify_service import notify_status, EVENT_CANCEL
            await notify_status({**doc, **updates}, EVENT_CANCEL)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(f"TPMS cancel notify failed for {event_id}: {exc}")

    tracker_set = {"updated_at": datetime.utcnow()}
    if moved:
        tracker_set.update({"date": new_date, "period": period_from_date(new_date),
                            "status": STATUS_RESCHEDULED})
    elif updates.get("tpms_status"):
        tracker_set["status"] = updates["tpms_status"]
    await get_collection(COLL_ACTIVITY_TRACKER).update_many(
        {"event_id": str(doc["_id"])}, {"$set": tracker_set}
    )

    return {"ok": True, "rescheduled": moved,
            "status": updates.get("tpms_status") or doc.get("tpms_status")}


# ─────────────────────────────────────────────────────────────
# Delete — port of deleteSchedule (code.js:671) + its cascade helpers
# ─────────────────────────────────────────────────────────────
async def delete_schedule(user: dict, event_id: str) -> dict:
    """Remove an occurrence and everything derived from it. Admin-only, matching the
    Apps Script UI where CAN_DELETE is Admin alone (Calender.html:232)."""
    if (user.get("role") or "").lower() not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="No permission to delete")

    from app.services.tpms_lifecycle_service import find_tpms_event
    doc, coll = await find_tpms_event(event_id)
    eid = str(doc["_id"])

    await get_collection(coll).delete_one({"_id": doc["_id"]})
    # Reminders live on the event document, so they go with it. The derived rows don't.
    from app.models.tpms import (COLL_ACTION_ITEMS as _AI, COLL_ESCALATIONS as _ESC,
                                 COLL_RESCHEDULE_REQUESTS as _RR)
    deleted = {"event": 1}
    for name in (COLL_ACTIVITY_TRACKER, _AI, _ESC, _RR):
        res = await get_collection(name).delete_many({"event_id": eid})
        deleted[name] = res.deleted_count
    return {"ok": True, "deleted": deleted}
