"""
TPMS ▸ activity lifecycle service.

Direct port of the Apps Script lifecycle module (`copy_of calender/code.js:3833-4040`):
  • requestReschedule        (:3834)  → request_reschedule()
  • markLearnerDone          (:3888)  → mark_learner_done()
  • confirmCompletion        (:3915)  → confirm_completion()
  • closeLinkedActionItems_  (:3939)  → close_linked_action_items()
  • getRescheduleRequests    (:3970)  → list_reschedule_requests()
  • decideRescheduleRequest  (:3991)  → decide_reschedule_request()

THE TWO-STEP COMPLETION
-----------------------
A doer clicking "Mark Done" does NOT complete the activity — it sets `learner_done` and
notifies internal staff, who must confirm. Only confirmation sets status Completed.
That split is also what produces the learner/staff delay breakdown on the dashboards.
The ERP's own `PATCH /calendar/events/{id}/complete` is single-step and admin-gated, so
TPMS activities use these endpoints instead; non-TPMS events are unaffected.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

logger = logging.getLogger(__name__)

from app.db.mongodb import get_collection
from app.models.tpms import (
    COLL_ACTION_ITEMS, COLL_RESCHEDULE_REQUESTS,
    REQUEST_APPROVED, REQUEST_PENDING, REQUEST_REJECTED,
    RESCHEDULE_MIN_HOURS,
    STATUS_CANCELLED, STATUS_COMPLETED, STATUS_LAPSED, STATUS_RESCHEDULED, STATUS_SCHEDULED,
    TPMS_EVENT_KIND, erp_status_for,
)
from app.services.tpms_schedule_service import (
    CAL_COLLECTIONS, CLIENT_ROLES, STAFF_ROLES, update_tracker_status,
)

# Statuses that block any further lifecycle action (calCanAct, code.js:730).
TERMINAL_STATUSES = {STATUS_COMPLETED, STATUS_CANCELLED, STATUS_LAPSED}


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
async def find_tpms_event(event_id: str):
    """Locate a TPMS activity across the calendar collections. Returns (doc, collection)."""
    try:
        oid = ObjectId(event_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid activity id")
    for coll in CAL_COLLECTIONS:
        doc = await get_collection(coll).find_one({"_id": oid, "kind": TPMS_EVENT_KIND})
        if doc:
            return doc, coll
    raise HTTPException(status_code=404, detail="Activity not found.")


def _tpms_status(doc: dict) -> str:
    return doc.get("tpms_status") or STATUS_SCHEDULED


def _assert_actionable(doc: dict) -> None:
    status = _tpms_status(doc)
    if status in TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"This activity is {status}.")


def _display_name(user: dict) -> str:
    return (user.get("full_name")
            or " ".join(filter(None, [user.get("first_name"), user.get("last_name")])).strip()
            or user.get("name") or user.get("email") or "Unknown")


def _is_client(user: dict) -> bool:
    return (user.get("role") or "").lower() in CLIENT_ROLES


def _is_staff_side(user: dict) -> bool:
    """Internal Sparsh user — admin or SMOps. Anyone who isn't client-side."""
    return not _is_client(user)


def _days_between(a: str, b: str) -> int:
    try:
        d1 = datetime.fromisoformat(str(a)[:10])
        d2 = datetime.fromisoformat(str(b)[:10])
        return (d2 - d1).days
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────
# Doer: mark done  (markLearnerDone, code.js:3888)
# ─────────────────────────────────────────────────────────────
async def mark_learner_done(user: dict, event_id: str) -> dict:
    if not _is_client(user):
        raise HTTPException(status_code=403, detail="Only the doer can mark an activity done.")
    doc, coll = await find_tpms_event(event_id)
    if str(doc.get("company_id") or "") != str(user.get("company_id") or ""):
        raise HTTPException(status_code=403, detail="Not your company activity.")
    _assert_actionable(doc)

    await get_collection(coll).update_one({"_id": doc["_id"]}, {"$set": {
        "learner_done": True,
        "learner_done_by": _display_name(user),
        "learner_done_at": datetime.utcnow(),
        # Reset the escalation ladder — waiting on staff is not "overdue" (code.js:3900).
        "esc_stage": 0,
        "updated_at": datetime.utcnow(),
    }})

    # Nudge internal staff to confirm. Wrapped — a mail failure must not undo the claim.
    try:
        from app.services.tpms_notify_service import notify_learner_done
        await notify_learner_done(doc, _display_name(user))
    except Exception as e:
        logger.error(f"TPMS learner-done mail failed: {e}")

    return {"ok": True, "awaiting": "staff_confirmation"}


# ─────────────────────────────────────────────────────────────
# Staff: confirm completion  (confirmCompletion, code.js:3915)
# ─────────────────────────────────────────────────────────────
async def confirm_completion(user: dict, event_id: str) -> dict:
    if not _is_staff_side(user):
        raise HTTPException(status_code=403, detail="Only internal staff can confirm completion.")
    doc, coll = await find_tpms_event(event_id)

    completed_at = datetime.utcnow()
    await get_collection(coll).update_one({"_id": doc["_id"]}, {"$set": {
        "tpms_status": STATUS_COMPLETED,
        "status": erp_status_for(STATUS_COMPLETED),
        "completed_at": completed_at,
        "completed_by": _display_name(user),
        "esc_stage": 0,
        "updated_at": completed_at,
    }})
    await update_tracker_status(event_id, STATUS_COMPLETED)
    await close_linked_action_items(event_id, doc, completed_at)

    try:
        from app.services.tpms_notify_service import EVENT_COMPLETED, notify_status
        await notify_status({**doc, "tpms_status": STATUS_COMPLETED}, EVENT_COMPLETED,
                            {"Completed_By": _display_name(user)})
    except Exception as e:
        logger.error(f"TPMS completion mail failed: {e}")

    return {"ok": True, "status": STATUS_COMPLETED}


# ─────────────────────────────────────────────────────────────
# Close follow-ups + record the delay split  (closeLinkedActionItems_, code.js:3939)
# ─────────────────────────────────────────────────────────────
async def close_linked_action_items(event_id: str, doc: dict, completed_at: datetime) -> int:
    """Close the open Action_Item and stamp the three delay figures.

    total   = target date → staff confirmation
    learner = target date → doer marked done
    staff   = doer marked done → staff confirmation
    Exactly the split the Apps Script computes, and what the dashboards show as
    Learner Delay / Staff Delay.
    """
    target = str(doc.get("start") or "")[:10]
    completed = completed_at.date().isoformat()
    learner_at = doc.get("learner_done_at")
    learner_day = learner_at.date().isoformat() if isinstance(learner_at, datetime) else None

    total_delay = max(0, _days_between(target, completed)) if target else 0
    if learner_day and target:
        learner_delay = max(0, _days_between(target, learner_day))
        staff_delay = max(0, _days_between(learner_day, completed))
    else:
        learner_delay, staff_delay = total_delay, 0

    res = await get_collection(COLL_ACTION_ITEMS).update_many(
        {"event_id": str(event_id), "status": {"$ne": "Closed"}},
        {"$set": {
            "status": "Closed",
            "delay_days": total_delay,
            "learner_delay_days": learner_delay,
            "staff_delay_days": staff_delay,
            "closed_at": completed_at,
        }},
    )
    return res.modified_count


# ─────────────────────────────────────────────────────────────
# Doer: request a reschedule  (requestReschedule, code.js:3834)
# ─────────────────────────────────────────────────────────────
async def request_reschedule(user: dict, event_id: str, new_date: str,
                             new_time: Optional[str], reason: str) -> dict:
    if not _is_client(user):
        raise HTTPException(status_code=403, detail="Only the doer can request a reschedule.")
    if not new_date:
        raise HTTPException(status_code=400, detail="Choose a new date")
    if not (reason or "").strip():
        raise HTTPException(status_code=400, detail="A reason is required to request a reschedule.")

    doc, _coll = await find_tpms_event(event_id)
    if str(doc.get("company_id") or "") != str(user.get("company_id") or ""):
        raise HTTPException(status_code=403, detail="Not your company activity.")
    _assert_actionable(doc)

    # Must be raised at least 12 hours before the activity.
    try:
        start = datetime.fromisoformat(str(doc.get("start")).replace("Z", "+00:00")).replace(tzinfo=None)
        if start - datetime.utcnow() < timedelta(hours=RESCHEDULE_MIN_HOURS):
            raise HTTPException(
                status_code=400,
                detail=f"Reschedule requests must be raised at least {RESCHEDULE_MIN_HOURS} hours before the activity.",
            )
    except HTTPException:
        raise
    except Exception:
        pass  # unparseable start — don't block the request on it

    start_str = str(doc.get("start") or "")
    request = {
        "event_id": str(event_id),
        "company_id": str(doc.get("company_id") or ""),
        "company_name": doc.get("company_name"),
        "activity": doc.get("activity"),
        "title": doc.get("title"),
        "old_date": start_str[:10],
        "old_time": start_str[11:16],
        "new_date": str(new_date)[:10],
        "new_time": (new_time or "")[:5],
        "reason": reason or "",
        "requested_by": str(user.get("_id")),
        "requested_by_name": _display_name(user),
        "requested_at": datetime.utcnow(),
        "status": REQUEST_PENDING,
    }
    res = await get_collection(COLL_RESCHEDULE_REQUESTS).insert_one(request)

    # H9 — notify internal staff that a reschedule was requested (gated by the TPMS switch).
    try:
        from app.services.tpms_notify_service import notify_reschedule_request
        await notify_reschedule_request(doc, _display_name(user), str(new_date)[:10])
    except Exception as e:
        logger.error(f"TPMS reschedule-request mail failed: {e}")

    return {"ok": True, "request_id": str(res.inserted_id)}


# ─────────────────────────────────────────────────────────────
# Staff: list + decide  (getRescheduleRequests :3970 / decideRescheduleRequest :3991)
# ─────────────────────────────────────────────────────────────
async def list_reschedule_requests(user: dict, status: str = REQUEST_PENDING) -> List[dict]:
    query = {}
    if status:
        query["status"] = status
    if _is_client(user):
        query["company_id"] = str(user.get("company_id") or "")
    docs = await get_collection(COLL_RESCHEDULE_REQUESTS).find(query).to_list(500)
    docs.sort(key=lambda d: d.get("requested_at") or datetime.min, reverse=True)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


async def decide_reschedule_request(user: dict, request_id: str,
                                    approve: bool, note: str = "") -> dict:
    """Approve → move the activity, flag it Rescheduled, bump the counter and reset the
    escalation ladder. Reject → record the decision only."""
    if not _is_staff_side(user):
        raise HTTPException(status_code=403, detail="Only internal staff can decide reschedule requests.")
    try:
        oid = ObjectId(request_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid request id")

    req = await get_collection(COLL_RESCHEDULE_REQUESTS).find_one({"_id": oid})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found.")
    if req.get("status") != REQUEST_PENDING:
        raise HTTPException(status_code=400, detail=f"Request already {req.get('status')}.")

    # Spec §4 / G-4: an internal staff member may only decide requests for a company they own
    # (admins may decide any). Mirrors the ownership rule enforced on schedule create/edit.
    from app.services.tpms_schedule_service import assert_can_schedule
    await assert_can_schedule(user, str(req.get("company_id") or ""))

    now = datetime.utcnow()
    await get_collection(COLL_RESCHEDULE_REQUESTS).update_one({"_id": oid}, {"$set": {
        "status": REQUEST_APPROVED if approve else REQUEST_REJECTED,
        "decided_by": _display_name(user),
        "decided_at": now,
        "note": note or "",
    }})

    if not approve:
        # H9 — notify the doer their request was rejected (gated by the TPMS switch).
        try:
            rej_doc, _ = await find_tpms_event(req["event_id"])
            from app.services.tpms_notify_service import notify_reschedule_decision
            await notify_reschedule_decision(rej_doc, False, note or "")
        except Exception as e:
            logger.error(f"TPMS reschedule-reject mail failed: {e}")
        return {"ok": True, "status": REQUEST_REJECTED}

    doc, coll = await find_tpms_event(req["event_id"])
    new_time = req.get("new_time") or str(doc.get("start") or "")[11:16] or "00:00"
    new_start = f"{req['new_date']}T{new_time[:5]}:00"
    await get_collection(coll).update_one({"_id": doc["_id"]}, {"$set": {
        "start": new_start,
        "tpms_status": STATUS_RESCHEDULED,
        "status": erp_status_for(STATUS_RESCHEDULED),
        "reschedule_count": int(doc.get("reschedule_count") or 0) + 1,
        "esc_stage": 0,
        "updated_at": now,
        # Re-arm every reminder against the new date.
        "reminders": [{**r, "sent": False} for r in (doc.get("reminders") or [])],
    }})
    await get_collection("tpms_activity_tracker").update_many(
        {"event_id": str(doc["_id"])},
        {"$set": {"date": req["new_date"], "status": STATUS_RESCHEDULED, "updated_at": now}},
    )

    try:
        from app.services.tpms_notify_service import EVENT_RESCHEDULE, notify_status
        await notify_status({**doc, "start": new_start, "tpms_status": STATUS_RESCHEDULED},
                            EVENT_RESCHEDULE,
                            {"Old_Date": req.get("old_date"), "New_Date": req.get("new_date"),
                             "Reason": req.get("reason")})
    except Exception as e:
        logger.error(f"TPMS reschedule mail failed: {e}")

    return {"ok": True, "status": REQUEST_APPROVED, "new_start": new_start}
