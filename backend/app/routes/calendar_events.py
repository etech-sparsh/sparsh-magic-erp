from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Form
from typing import List, Optional
from app.db.mongodb import get_collection
from app.controllers.auth_controller import (
    get_current_user, has_task_access, is_client_side_user,
    TASK_ACCESS_DENIED_MESSAGE, DELEGATION_DISABLED_MESSAGE,
    get_ineligible_recipient_ids, recipient_denied_message,
    get_rank_ineligible_assignees, ASSIGN_RANK_DENIED_MESSAGE,
    is_company_task_admin,
)
from app.models.calendar_event import CalendarEventCreate, CalendarEventResponse
from app.services.task_notifications import notify_task_event, recipients_for_event
from app.services.notification_service import (
    send_event_created_email, send_event_updated_email, send_event_deleted_email,
    send_conflict_notification_email, send_attendance_thanks_email, send_attendance_absent_email,
    send_session_complete_email
)
from app.services.activity_log_service import log_activity
from app.services.gpt_service import grade_descriptive_answer
from app.services.s3_service import upload_file_to_s3, get_signed_url
from app.services.event_sync_service import sync_event_to_collection
from app.routes.task_meta import sync_task_meta
from app.services import task_events
from bson import ObjectId
import calendar
from datetime import datetime, timedelta, timezone

router = APIRouter(prefix="/calendar/events", tags=["Calendar"])

from app.utils.calendar_utils import (

    CALENDAR_COLLECTIONS, find_user_by_id,
    get_target_collection_name, find_event_across_collections, exclude_tpms
)

async def detect_conflicts(event_dict: dict, event_id: str = None, sessions_only: bool = False):
    # Standardize Time Range
    try:
        new_start = datetime.fromisoformat(event_dict["start"].replace("Z", "+00:00")).replace(tzinfo=None)
        if event_dict.get("end"):
            new_end = datetime.fromisoformat(event_dict["end"].replace("Z", "+00:00")).replace(tzinfo=None)
        else:
            new_end = new_start + timedelta(hours=1)
    except Exception as e:
        print(f"Conflict Parser Error: {e}")
        return []

    uids = set()
    creator_id = event_dict.get("user_id")
    if creator_id: uids.add(str(creator_id))
    if event_dict.get("type") == "task":
        target = event_dict.get("target_staff_id", [])
        if isinstance(target, list):
            for t in target: uids.add(str(t))
        elif target: uids.add(str(target))
    else:
        for mid in event_dict.get("assigned_member_ids", []): uids.add(str(mid))
        for cid in event_dict.get("coach_ids", []): uids.add(str(cid))
    uids = [u for u in uids if u and u != "null"]
    if not uids: return []

    query = {
        "$and": [
            {
                "$or": [
                    {"user_id": {"$in": uids}},
                    {"assigned_member_ids": {"$in": uids}},
                    {"coach_ids": {"$in": uids}},
                    {"target_staff_id": {"$in": uids}},
                    {"target_staff_id": {"$elemMatch": {"$in": uids}}}
                ]
            }
        ]
    }
    if event_id:
        query["$and"].append({"_id": {"$ne": ObjectId(event_id)}})

    conflicts = []
    # A doc is identified by what it *is*, not by _id: the same event mirrored into another
    # collection (or re-inserted by a collection move) gets a fresh _id, so the _id filter
    # above misses it and it would otherwise conflict with itself / be counted repeatedly.
    def _identity(doc):
        return (doc.get("title"), doc.get("start"), str(doc.get("user_id")))

    self_key = _identity(event_dict)
    seen = set()
    # Search all collections for overlaps
    for col_name in (CALENDAR_COLLECTIONS + ["calendar_events"]):
        candidates = await get_collection(col_name).find(query).to_list(100)
        for ex in candidates:
            try:
                # Conflict alerts are a session-vs-session concern; tasks never occupy a slot.
                if sessions_only and ex.get("type") == "task":
                    continue
                # A cancelled slot no longer occupies the calendar.
                if str(ex.get("status", "")).lower() in ("canceled", "cancelled"):
                    continue
                key = _identity(ex)
                if key == self_key or key in seen:
                    continue
                ex_start = datetime.fromisoformat(ex["start"].replace("Z", "+00:00")).replace(tzinfo=None)
                ex_end = datetime.fromisoformat(ex["end"].replace("Z", "+00:00")).replace(tzinfo=None) if ex.get("end") else ex_start + timedelta(hours=1)
                if ex_start < new_end and ex_end > new_start:
                    ex_uids = set([str(ex.get("user_id"))])
                    for mid in ex.get("assigned_member_ids", []): ex_uids.add(str(mid))
                    for cid in ex.get("coach_ids", []): ex_uids.add(str(cid))
                    target = ex.get("target_staff_id", [])
                    if isinstance(target, list):
                        for t in target: ex_uids.add(str(t))
                    elif target: ex_uids.add(str(target))
                    overlap = list(set(uids) & ex_uids)
                    if overlap:
                        seen.add(key)
                        conflicts.append({"existing": ex, "users": overlap})
            except: continue
    return conflicts


async def notify_users_instant(event_dict: dict, action: str, creator_name: str):
    """Calendar (session/event) notifications only.

    Task Management docs (type=="task") live in these same collections but are a different
    business module with its own triggers, templates and recipients — see
    services/task_notifications.py, which the task call sites below invoke directly. Bailing
    out here is what guarantees a task can never fire a Calendar template.

    Personal TODOS are excluded for a different reason: they are private by design — never
    assignable, never delegated, no attendees. There is simply nobody to tell. Without this
    guard the recipient set below still resolved to exactly one address, the todo's OWN owner
    (user_id is always added), so deleting a private note mailed its author a session
    CANCELLATION notice — and creating or editing one sent "session created"/"session updated".
    Excluding them here covers the create, update and delete call sites in one place, matching
    the early return complete_event already does.

    This does NOT touch todo reminders: those are a separate, intended channel fired by the
    reminder scheduler off the todo's own `reminders` list.
    """
    if event_dict.get("type") in ("task", TODO_TYPE):
        return

    user_ids = set()
    # Attendees & Coaching team
    for mid in event_dict.get("assigned_member_ids", []):
        if mid: user_ids.add(mid)
    for cid in event_dict.get("coach_ids", []):
        if cid: user_ids.add(cid)
    # Notify creator
    user_ids.add(event_dict.get("user_id"))

    if not user_ids: return

    # Fetch extra metadata for sessions
    batch_name = "N/A"
    quarter_name = "N/A"
    if event_dict.get("batch_id"):
        b = await get_collection("batches").find_one({"_id": ObjectId(event_dict["batch_id"])})
        if b: batch_name = b.get("name", "N/A")
    if event_dict.get("quarter_id"):
        q = await get_collection("quarters").find_one({"_id": ObjectId(event_dict["quarter_id"])})
        if q: quarter_name = q.get("name", "N/A")

    for uid in user_ids:
        if not uid: continue
        try:
            user_data = await find_user_by_id(uid)
            if not user_data: continue

            scope = event_dict.get("notification_scope", "staff")
            # WhatsApp goes out ONLY when a staff member is the creator (scope == "staff").
            # Learner-created sessions stay email + in-app only.
            delivery = "both" if scope == "staff" else "email"
            if action == "created":
                await send_event_created_email(user_data, event_dict, creator_name, batch_name, quarter_name, delivery)
            elif action == "updated":
                status = event_dict.get("status")
                if status == "completed":
                    await send_session_complete_email(user_data, event_dict, delivery)
                elif status == "canceled":
                    await send_event_deleted_email(user_data, event_dict, creator_name, scope, batch_name, quarter_name, delivery)
                else:
                    await send_event_updated_email(user_data, event_dict, creator_name, batch_name, quarter_name, delivery)
            elif action == "deleted":
                await send_event_deleted_email(user_data, event_dict, creator_name, scope, batch_name, quarter_name, delivery)
        except Exception as e:
            print(f"Notification Error for {uid}: {e}")
            
    # ─── Conflict Logic ───
    # Sessions only (tasks already returned at the top of this function), and at most ONE mail
    # per affected user per save. The previous nested loop mailed once per (conflict × user),
    # and send_conflict_notification_email itself also copies the company — so a single save
    # could fan out into 15-20 messages.
    if action in ["created", "updated"]:
        try:
            conflicts = await detect_conflicts(event_dict, event_dict.get("id"), sessions_only=True)
            notified_uids = set()
            copied_companies = set()
            for conf in conflicts:
                existing = conf["existing"]
                for conflict_uid in conf["users"]:
                    if not conflict_uid or conflict_uid in notified_uids:
                        continue
                    notified_uids.add(conflict_uid)
                    conflict_user_data = await find_user_by_id(conflict_uid)
                    if not conflict_user_data:
                        continue
                    # One [COPY] per distinct company per save, not one per affected user.
                    company_id = str(conflict_user_data.get("company_id") or "")
                    send_copy = bool(company_id) and company_id not in copied_companies
                    if send_copy:
                        copied_companies.add(company_id)
                    await send_conflict_notification_email(
                        conflict_user_data, event_dict, existing, send_company_copy=send_copy)
            if notified_uids:
                print(f"[DEBUG-CONFLICT] {len(conflicts)} overlap(s); mailed {len(notified_uids)} user(s), {len(copied_companies)} company copy(ies)")
        except Exception as e:
            print(f"Conflict Notification Error: {e}")


async def notify_todo_created(todo: dict, occurrences: int = 1):
    """Confirm a new calendar To-do to the one person it belongs to.

    This is the todo's OWN trigger, deliberately separate from notify_users_instant above:
    that function resolves a session's attendee list and renders the Calendar session
    templates, neither of which a private todo has — which is exactly why todos are excluded
    there, and why they were left with no email at all. Recipient is the owner (`user_id`),
    template is `todo_created`, and it fires once per create, so nothing double-sends.
    """
    try:
        owner = await find_user_by_id(todo.get("user_id"))
        if not owner or not owner.get("email"):
            return
        from app.services.notification_service import send_todo_created_email
        await send_todo_created_email(owner, todo, occurrences=occurrences)
    except Exception as e:
        print(f"Todo notification error: {e}")


def _days_in_month(year, month):
    return calendar.monthrange(year, month)[1]


def _month_step(curr_dt, months, repeat_data, anchor_day):
    """The next month-based occurrence after `curr_dt`, `months` ahead.

    Day-of-month is resolved in priority order:
      1. repeat_data.lastDay      — always the final day of the target month
      2. repeat_data.monthlyDates — the user's chosen date(s); the next one after curr_dt in
         the SAME month if there is one, otherwise the first in the target month
      3. anchor_day               — the series' intended day, carried forward so a month that
         is too short cannot permanently pull the series down (Jan 31 → Feb 28 → Mar 31)
      4. curr_dt.day              — legacy fallback

    The old code clamped every month to `min(day, 28)`, which silently moved any series on the
    29th-31st to the 28th forever. Clamping is now to the target month's real length.
    """
    data = repeat_data or {}
    dates = sorted({int(d) for d in (data.get("monthlyDates") or []) if str(d).isdigit()})

    # Multiple dates in one month: the next occurrence may still be inside the current month.
    if dates and months == 1:
        later = [d for d in dates if d > curr_dt.day]
        if later:
            day = min(later[0], _days_in_month(curr_dt.year, curr_dt.month))
            return curr_dt.replace(day=day)

    total = curr_dt.month - 1 + months
    year = curr_dt.year + total // 12
    month = total % 12 + 1
    last = _days_in_month(year, month)

    if data.get("lastDay"):
        day = last
    elif dates:
        day = min(dates[0], last)
    else:
        day = min(anchor_day or curr_dt.day, last)
    return curr_dt.replace(year=year, month=month, day=day)


def _next_occurrence(curr_dt, repeat_type, interval, repeat_data=None, anchor_day=None):
    """Advance curr_dt by one recurrence step, or return None if repeat_type is unrecognized.

    `anchor_day` is the series' intended day-of-month, passed by the recurring engine so a
    short month cannot drift the series permanently. Omitted by other callers, in which case
    behaviour is unchanged from before.
    """
    if repeat_type == "Daily":
        return curr_dt + timedelta(days=1)
    if "Weekly" in repeat_type:
        # Specific weekdays (Mon/Wed/Fri) when the form supplied them — the next selected day
        # after curr, which may be later in the SAME week. Falls back to a plain 7-day step
        # when no weekdays were chosen, which is the previous behaviour.
        wanted = sorted({int(d) % 7 for d in ((repeat_data or {}).get("weekdays") or [])
                         if str(d).lstrip("-").isdigit()})
        if wanted:
            for ahead in range(1, 8):
                cand = curr_dt + timedelta(days=ahead)
                if cand.weekday() in wanted:
                    return cand
        return curr_dt + timedelta(weeks=1)
    if repeat_type == "Monthly":
        return _month_step(curr_dt, 1, repeat_data, anchor_day)
    if repeat_type == "Annually":
        year = curr_dt.year + 1
        # 29 Feb only exists in a leap year. replace() raised ValueError here, and because the
        # recurring engine does not catch it the exception aborted the WHOLE nightly run for
        # every series, not just this one. Clamp to the target year's month length instead —
        # via anchor_day, so a 29 Feb series returns to the 29th at the next leap year rather
        # than settling on the 28th forever.
        day = min(anchor_day or curr_dt.day, _days_in_month(year, curr_dt.month))
        return curr_dt.replace(year=year, day=day)
    if repeat_type == "periodic":
        return curr_dt + timedelta(days=interval)
    if repeat_type == "Custom":
        unit = (repeat_data or {}).get("customUnit", "Months")
        if unit == "Weeks":
            return curr_dt + timedelta(weeks=interval)
        if unit == "Days":
            return curr_dt + timedelta(days=interval)
        # "Months" steps by month like Monthly does, just with a custom N-month interval.
        return _month_step(curr_dt, max(int(interval or 1), 1), repeat_data, anchor_day)
    return None

@router.post("/validate-conflict")
async def validate_conflict(event_data: dict, current_user: dict = Depends(get_current_user)):
    # Add creator ID if not present
    if "user_id" not in event_data:
        event_data["user_id"] = str(current_user["_id"])
    
    # We pass None for event_id as it's a prospective new one
    event_id = event_data.get("id")
    conflicts = await detect_conflicts(event_data, event_id)
    
    if conflicts:
        # Simplify response for UI
        return {
            "has_conflict": True,
            "message": "This schedule conflicts with another task or event.",
            "conflicts": [
                {"title": c["existing"]["title"], "time": c["existing"]["start"], "users": c["users"]}
                for c in conflicts
            ]
        }
    return {"has_conflict": False}

# ─── Personal Todos ───
# A todo is a private, self-owned calendar item: never assignable, never delegated, never
# emailed, and visible only to its creator. It reuses the calendar_event document shape — so
# reminders, recurrence, completion and the calendar grid all keep working untouched — but is
# a distinct `type`, so Task & Delegation (which owns type=="task") never sees a todo and the
# two sets of counts can never mix.
TODO_TYPE = "todo"

# Task & Delegation owns this type. A task with `repeat` set is a Recurring Checklist and
# carries no deadline of its own — see `_apply_recurring_task_day_window`.
TASK_TYPE = "task"

TODO_PRIVATE_MESSAGE = "Todos are private — only their owner can view or change them."

# A todo's lifecycle statuses. "schedule" is the stored value the UI labels "Pending"; a todo
# whose due date/time has passed untouched is swept to "overdue" every minute by the reminder
# scheduler (see services/todo_status_service.py). "completed" is set by the complete endpoint.
TODO_PENDING_STATUS = "schedule"
TODO_OVERDUE_STATUS = "overdue"

# Fields that describe ONE occurrence rather than the series it belongs to. When an edit is
# carried onto newly generated occurrences, these must be dropped: they are the dates, identity
# and progress of the single document the user happened to open.
PER_OCCURRENCE_FIELDS = ("_id", "id", "start", "end", "recurrence_anchor", "recurrence_day",
                         "status", "completed_at", "completed_by", "updated_at")

# The product's canonical local zone (IST, UTC+5:30) — the same zone the nightly recurrence
# engine uses for every day-boundary decision. A personal todo is always due at the end of its
# day in this zone.
IST_TZ = timezone(timedelta(hours=5, minutes=30))


def _iso_utc(dt):
    """Serialize a datetime as a UTC-MARKED ISO string so the browser's `new Date()` parses it
    as UTC, not local. created_at is stored via datetime.utcnow() (naive UTC); its bare
    isoformat() carries no zone marker, so JS reads it as LOCAL and shows a time off by the UTC
    offset (e.g. an 11:07 AM IST creation reads back as 05:37 AM). Marking it UTC fixes that."""
    if not hasattr(dt, "isoformat"):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# A todo with no chosen time is due at the very end of its day, in IST. This is the value that
# means "no due time was picked" everywhere — the form leaves its time field blank for it, and
# the edit form reads it back as blank.
TODO_END_OF_DAY = (23, 59, 59)


def is_recurring_task(doc: dict) -> bool:
    """A repeating TASK — the Recurring Checklist. Not a one-time task, not a todo."""
    return (doc.get("type") == TASK_TYPE
            and str(doc.get("repeat") or "").strip() not in ("", "Does not repeat"))


def _apply_recurring_task_day_window(doc: dict) -> None:
    """A Recurring Checklist has NO deadline — each occurrence simply owns its own day.

    A repeating task is a checklist item that comes back: the question is only "was it done
    today", so picking a due date for it is meaningless — every occurrence would carry the
    same one. Instead the occurrence is live for its whole calendar day and closes at
    23:59:59 IST, the same day boundary a personal todo uses.

    That instant is written to `end` rather than tracked separately, which is what keeps the
    rest of Task & Delegation working untouched: overdue, completion timing, reminders and
    the nightly rollover all read `end` and go on doing exactly what they did. Nothing
    "expires" — an occurrence whose day has passed is simply Overdue, and stays open.

    Any deadline the form sent is discarded here, so the rule cannot be bypassed by a stale
    tab or a direct API call. Applied only to NEW or EDITED recurring tasks; existing rows
    are left exactly as they are.
    """
    if not is_recurring_task(doc):
        return
    # `start` ONLY — never `end`. `end` at this point is the deadline being discarded, so
    # falling back to it would put the day window on the deadline's date: a checklist
    # started today but sent with a 30 Sep deadline would have opened on 30 Sep.
    raw = doc.get("start")
    base_ist = None
    if raw:
        try:
            s = str(raw)
            if len(s) <= 10:                      # date-only "YYYY-MM-DD"
                base_ist = datetime.fromisoformat(s).replace(tzinfo=IST_TZ)
            else:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                base_ist = (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(IST_TZ)
        except Exception:
            base_ist = None
    if base_ist is None:
        base_ist = datetime.now(timezone.utc).astimezone(IST_TZ)
    close_ist = base_ist.replace(hour=23, minute=59, second=59, microsecond=0)
    # Stored in UTC, which is the convention Task & Delegation reads `end` under:
    # tasks._parse_iso drops the offset WITHOUT converting and compares against a naive
    # utcnow(), so an IST-offset string here would read as 23:59:59 UTC and the occurrence
    # would only turn Overdue at 5:29 AM IST the next morning. 23:59:59 IST is 18:29:59 UTC.
    doc["end"] = close_ist.astimezone(timezone.utc).isoformat()


def _apply_todo_due_end_of_day(doc: dict) -> None:
    """Resolve a personal todo's due INSTANT on its chosen calendar DATE, in IST.

    The date behaves exactly as before: whatever day the user selected (defaulting to today).
    What is new is the TIME:

      • `all_day` truthy, or no usable time on the payload → 23:59:59 IST, the long-standing
        default. Existing todos, and any todo saved without picking a time, are unaffected.
      • otherwise → the time the user picked is kept, interpreted on that same IST date.

    The instant is written to BOTH `start` and `end` (todos keep start == end), so the calendar
    still places it on that day, the reminder anchor is the due moment, and a recurring todo
    rolls forward preserving its time-of-day (the zero start→end offset is what carries it).
    Scope: todos only.
    """
    raw = doc.get("start") or doc.get("end")
    base_ist = None
    if raw:
        try:
            s = str(raw)
            if len(s) <= 10:  # date-only "YYYY-MM-DD" → that calendar day, in IST
                base_ist = datetime.fromisoformat(s).replace(tzinfo=IST_TZ)
            else:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                base_ist = (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(IST_TZ)
        except Exception:
            base_ist = None
    if base_ist is None:
        base_ist = datetime.now(IST_TZ)  # no / invalid date → default to today

    # `all_day` is the form's "no due time picked" signal — an existing field, so this needs no
    # new one. A date-only payload has no time to honour either.
    date_only = bool(raw) and len(str(raw)) <= 10
    if doc.get("all_day") or date_only:
        hour, minute, second = TODO_END_OF_DAY
    else:
        hour, minute, second = base_ist.hour, base_ist.minute, base_ist.second

    due_utc = base_ist.replace(hour=hour, minute=minute, second=second,
                               microsecond=0).astimezone(timezone.utc)
    iso = due_utc.isoformat()
    doc["start"] = iso
    doc["end"] = iso
    # Stored false as it always has been, so nothing downstream (calendar rendering, reminder
    # anchoring, the Overdue sweep) sees a change in shape. Whether a time was chosen is read
    # back from the instant itself: 23:59:59 IST means "none".
    doc["all_day"] = False


def _series_end_cutoff(value):
    """A Repeat End Date as the LAST INSTANT that date may hold an occurrence — 23:59:59.999 IST
    on the chosen day, returned in UTC.

    Everything about recurrence is decided on IST calendar days, and a todo is due at 23:59:59
    IST, so the raw stored value cannot be used as a boundary directly: the date picker sends
    midday UTC ("2026-08-20T06:30:00Z") and a date-only value parses to midnight, both of which
    fall BEFORE the last occurrence of their own day and would silently drop it. Normalising to
    the end of the IST day makes "up to and including the date I picked" mean exactly that.
    """
    if not value:
        return None
    try:
        raw = str(value).replace("Z", "+00:00")
        if len(raw) <= 10:  # date-only "YYYY-MM-DD" → that calendar day, in IST
            dt = datetime.fromisoformat(raw).replace(tzinfo=IST_TZ)
        else:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None
    end_of_day_ist = dt.astimezone(IST_TZ).replace(hour=23, minute=59, second=59, microsecond=999999)
    return end_of_day_ist.astimezone(timezone.utc)


async def _expand_task_series(head: dict, end_date_str) -> list:
    """Every occurrence AFTER `head`, up to its Repeat End Date.

    A recurring task used to exist as a single occurrence that the nightly engine extended one
    day at a time, so the rest of the schedule simply was not there to look at — a checklist
    running to the 20th showed nothing past today, and its end date had no occurrences behind
    it. Writing the series up front makes the whole plan visible the moment it is saved.

    Dates come from the SAME builder the repeating-todo path and the nightly engine use, so
    cadence, holidays and weekly offs land identically however a date was produced. The nightly
    engine stays exactly as it was: it skips dates that already exist, and it still carries
    series with no Repeat End Date, which cannot be pre-generated at all.
    """
    from app.services.recurring_task_service import build_series_occurrences
    occurrences, _truncated = await build_series_occurrences(head, _series_end_cutoff(end_date_str))
    return occurrences


def _strip_todo_sharing(doc: dict) -> None:
    """Force a todo to be personal: no assignees, no watchers, no delegation of any kind.
    Applied on create AND update so a hand-crafted payload can't turn a todo into shared work."""
    doc["assigned_to"] = "myself"
    doc["target_staff_id"] = []
    doc["assigned_member_ids"] = []
    doc["coach_ids"] = []
    doc["assigned_departments"] = []
    doc["watchers"] = []


def _label_todo_reminders(doc: dict) -> None:
    """Stamp every reminder on a todo with parent_type "todo".

    The Reminder modal is shared with sessions and tasks and defaults a new reminder to
    "event", so a todo's reminders were being stored mislabelled. Nothing routes a todo by this
    field any more — send_reminder_email picks its template from the DOCUMENT type, precisely so
    a stray label cannot reach a Task template — but storing the truth keeps the data honest for
    anything that reads it later. Applied on create AND update, like _strip_todo_sharing, so a
    hand-crafted payload cannot relabel them.
    """
    reminders = doc.get("reminders")
    if isinstance(reminders, list):
        doc["reminders"] = [
            {**r, "parent_type": TODO_TYPE} if isinstance(r, dict) else r for r in reminders
        ]


def _require_todo_owner(doc: dict, current_user: dict) -> None:
    """403 unless the caller owns this todo. No-op for every other event type, so the
    existing session/task authorization below is left exactly as it was."""
    if (doc or {}).get("type") != TODO_TYPE:
        return
    if doc.get("user_id") != str(current_user["_id"]):
        raise HTTPException(status_code=403, detail=TODO_PRIVATE_MESSAGE)


@router.post("", response_model=dict)
async def create_event(event: CalendarEventCreate, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    event_dict = event.model_dump()

    # ─── Permission Check ───
    user_role = current_user.get("role", "").lower()
    has_create_perm = current_user.get("permissions", {}).get("calendar", {}).get("create")

    if event_dict.get("type") == "task":
        # ANY user with Task & Delegation access may create and assign tasks — the generic
        # `calendar.create` permission bit is NOT required here. (A staff/coach/SMO/member
        # without that bit was previously getting "Not authorized to create events" when
        # hitting Assign Task.) Access = internal Sparsh user, or a company user whose
        # company has the Delegation module switched on.
        if not await has_task_access(current_user):
            raise HTTPException(
                status_code=403,
                detail=DELEGATION_DISABLED_MESSAGE if is_client_side_user(current_user) else TASK_ACCESS_DENIED_MESSAGE,
            )
        # Assignees and In-Loop/watchers must be internal staff (internal creator) or users
        # of the creator's own company (company creator).
        bad = await get_ineligible_recipient_ids(current_user, (event_dict.get("target_staff_id") or []) + (event_dict.get("watchers") or []))
        if bad:
            raise HTTPException(status_code=403, detail=recipient_denied_message(current_user))
        # Assignment rank rule (assignees only): SMOPS can't assign up to admin; a client can't
        # assign above their own MD>HR>HOD>Implementor rank.
        rank_bad = await get_rank_ineligible_assignees(current_user, event_dict.get("target_staff_id") or [])
        if rank_bad:
            raise HTTPException(status_code=403, detail=ASSIGN_RANK_DENIED_MESSAGE)
        # A repeating task is a Recurring Checklist: no deadline, each occurrence owns its
        # own day and closes at 23:59:59 IST. A one-time task keeps the deadline the user set.
        _apply_recurring_task_day_window(event_dict)
    elif event_dict.get("type") == TODO_TYPE:
        # A todo is personal planning: every authenticated user may create their own, so the
        # generic `calendar.create` bit is not required (a staff member without it must still
        # be able to jot down their own todo). Sharing fields are stripped, not trusted.
        _strip_todo_sharing(event_dict)
        _label_todo_reminders(event_dict)
        # A todo is due at 23:59:59 (IST) on the calendar day it was added for (the selected day;
        # defaults to today). The user never picks a time — only the date carries over.
        _apply_todo_due_end_of_day(event_dict)
    elif user_role != "superadmin":
        # Non-task calendar / session events keep the original permission model.
        # Allow Client Users (Learners) and Client Admins to create events;
        # staff roles (admin, coach, staff) still require the explicit permission bit.
        if not has_create_perm and user_role not in ["clientuser", "clientadmin"]:
            raise HTTPException(status_code=403, detail="Not authorized to create events")

    # Backdate validation logic... (omitted summary for brevity, keeping existing code)
    # [STRICT BACKDATE VALIDATION CODE REMAINS UNCHANGED]
    try:
        now = datetime.utcnow()
        event_start = datetime.fromisoformat(event_dict["start"].replace("Z", "+00:00")).replace(tzinfo=None)
        # A task's `start` is a creation / recurrence-anchor reference stamped at "now", not a
        # scheduled calendar slot. Comparing it to the exact submit-time `utcnow()` falsely
        # flags every task as backdated (the stamp is always a few seconds old by the time it
        # reaches here). So for tasks, only block genuinely past DATES (yesterday or earlier);
        # calendar / session events keep the strict timestamp check. Todos follow the task
        # rule for the same reason — a todo written for later today must not be rejected.
        is_backdated = (event_start.date() < now.date()) if event_dict.get("type") in ("task", TODO_TYPE) else (event_start < now)
        if is_backdated:
            settings_col = get_collection("system_settings")
            settings = await settings_col.find_one({"setting_name": "backdate_control"})
            allow = False
            if settings:
                if settings.get("allow_backdate") is True: allow = True
                elif current_user.get("email") in settings.get("exception_users", []): allow = True
            if not allow:
                raise HTTPException(status_code=400, detail="Operation Blocked: Past-date scheduling is restricted by system policy.")
    except HTTPException: raise
    except Exception as e:
        print(f"CRITICAL ERROR in backdate validation: {e}")
        raise HTTPException(status_code=500, detail="Security validation failed. Request blocked.")

    event_dict["user_id"] = str(current_user["_id"])
    if current_user.get("company_id"):
        event_dict["company_id"] = str(current_user["company_id"])

    event_dict["created_at"] = datetime.utcnow()

    # New tasks start In Progress (not Pending) per the delegation workflow. Applies to every
    # insert path below (single, separate-per-assignee, and the first recurring occurrence),
    # since they all clone this event_dict.
    if event_dict.get("type") == "task":
        event_dict["workflow_status"] = "in_progress"
    
    # ─── Set Notification Scope ───
    # If a staff member creates it, it uses "staff" scope (standard design).
    # If a learner (client admin/user) creates it, it uses "company" scope (their own design).
    if current_user.get("role") in ["superadmin", "admin", "coach", "staff"]:
        event_dict["notification_scope"] = "staff"
    else:
        event_dict["notification_scope"] = "company"

    # ─── Target Collection Selection ───
    col_name = await get_target_collection_name(event_dict)
    col = get_collection(col_name)

    creator_name = current_user.get("full_name") or current_user.get("first_name", "System Admin")

    # ─── Recursive Generation Engine ───
    repeat_type = event_dict.get("repeat", "Does not repeat")
    end_date_str = event_dict.get("repeat_end_date")
    is_todo = event_dict.get("type") == TODO_TYPE
    is_repeating = repeat_type != "Does not repeat"

    # A repeating TODO is generated in full, up to its Repeat End Date, so that date is what
    # bounds the series and is therefore required. (It was optional while todos rolled forward
    # one day at a time forever — "generate every occurrence up to no end date" has no meaning.)
    if is_todo and is_repeating and not end_date_str:
        raise HTTPException(
            status_code=400,
            detail="Select a Repeat End Date — a repeating todo is generated up to that date.",
        )

    # A series needs a group id to tie its occurrences together: the nightly task rollover, the
    # series edit rules and the end-date timeline sync below all key off it.
    if is_repeating and end_date_str:
        event_dict["recurring_group_id"] = str(ObjectId())

    # ─── Recurring Todos: the whole series, up front ───
    # Every occurrence up to the Repeat End Date is written the moment the todo is saved, so the
    # user sees the full series on the calendar immediately instead of one new todo appearing at
    # 12:00 AM each day. Dates come from the SAME builder the nightly task engine uses, so a
    # repeating todo still lands exactly where a repeating task would: same cadences, holidays
    # and weekly offs dropped (daily) or shifted (weekly/monthly/…), same month-end anti-drift.
    if is_todo and is_repeating and end_date_str:
        try:
            from app.services.recurring_task_service import build_series_occurrences
            series_end = _series_end_cutoff(end_date_str)
            occurrences, truncated = await build_series_occurrences(event_dict, series_end)
            docs = [event_dict] + occurrences
            insert_res = await col.insert_many(docs)
            ids = [str(_id) for _id in insert_res.inserted_ids]
            await log_activity(current_user, "Create Recurring", col_name,
                               f"Generated {len(ids)} todos for {event_dict['title']}")
            # One mail for the whole series. The owner asked for a repeating todo once, so
            # a message per generated date would be the duplicate notification to avoid.
            background_tasks.add_task(notify_todo_created, {**event_dict, "id": ids[0]}, len(ids))
            message = f"Created {len(ids)} todos"
            if truncated:
                message += " (series capped — shorten the Repeat End Date for the remaining dates)"
            return {"id": ids[0], "ids": ids, "count": len(ids), "message": message}
        except HTTPException:
            raise
        except Exception as e:
            print(f"TODO SERIES GENERATION FAILURE: {e}")
            # Fall through to the single-document insert below, so the todo itself is never lost.

    # Recurring TASKS create only the FIRST occurrence here; a nightly job rolls the series
    # forward one occurrence at a time (see recurring_task_service.generate_due_recurring_tasks),
    # so we never bulk-create duplicates. Sessions/events keep the original bulk generation below.
    if is_repeating and end_date_str and event_dict.get("type") not in ("task", TODO_TYPE):
        try:
            # Standardize Start Date
            raw_start = event_dict["start"].replace("Z", "+00:00")
            start_dt = datetime.fromisoformat(raw_start)
            if start_dt.tzinfo is None: start_dt = start_dt.replace(tzinfo=timezone.utc)

            # Standardize End Date
            raw_end = end_date_str.replace("Z", "+00:00")
            if len(raw_end) <= 10: 
                # If only date is provided, make it end-of-day UTC
                raw_end = f"{raw_end}T23:59:59+00:00"
            
            end_dt = datetime.fromisoformat(raw_end)
            if end_dt.tzinfo is None: end_dt = end_dt.replace(tzinfo=timezone.utc)

            if end_dt < start_dt:
                print(f"Recurring Skip: End date {end_dt} is before start date {start_dt}")
            else:
                generated_events = []
                curr_dt = start_dt
                interval = event_dict.get("repeat_interval", 1) or 1
                
                while curr_dt <= end_dt:
                    new_ev = event_dict.copy()
                    new_ev["start"] = curr_dt.isoformat()
                    if event_dict.get("end"):
                        raw_orig_end = event_dict["end"].replace("Z", "+00:00")
                        orig_end = datetime.fromisoformat(raw_orig_end)
                        if orig_end.tzinfo is None: orig_end = orig_end.replace(tzinfo=timezone.utc)
                        diff = orig_end - start_dt
                        new_ev["end"] = (curr_dt + diff).isoformat()
                    
                    new_ev["created_at"] = datetime.utcnow()
                    # Remove any existing ID if we are cloning
                    if "_id" in new_ev: del new_ev["_id"]
                    generated_events.append(new_ev)
                    
                    next_dt = _next_occurrence(curr_dt, repeat_type, interval, event_dict.get("repeat_data"))
                    if next_dt is None: break
                    curr_dt = next_dt
                    if len(generated_events) > 365: break
                
                if generated_events:
                    await col.insert_many(generated_events)
                    # Log activity for batch creation. Task-typed docs use a task-specific
                    # action so the Task Management → Activity feed can pick them up.
                    is_task = event_dict.get("type") == "task"
                    await log_activity(current_user, "Create Recurring Tasks" if is_task else "Create Recurring", col_name, f"Generated {len(generated_events)} {'tasks' if is_task else 'events'} for {event_dict['title']}",
                                       meta={"group_id": event_dict.get("group_id")} if is_task else None)
                    if is_task:
                        background_tasks.add_task(sync_task_meta, event_dict.get("category"), event_dict.get("tags"), str(current_user["_id"]))
                        await task_events.publish(task_events.recipients_for(event_dict), {
                            "type": "task_created",
                            "task_id": None,  # batch create -- client refetches the list
                            "title": event_dict.get("title"),
                            "assigned_to": event_dict.get("target_staff_id") or [],
                            "assigned_by": event_dict.get("user_id"),
                            "watchers": event_dict.get("watchers") or [],
                            "actor_id": str(current_user["_id"]),
                        })
                    return {"message": f"Successfully generated {len(generated_events)} recurring duties."}
        except Exception as e:
            print(f"RECURSIVE ENGINE FAILURE: {e}")
            # Fall back to single event creation below if recursion fails

    # ─── Separate Assignment: one independent task per assignee ───
    # "combined" (default) keeps the single shared doc below. "separate" clones the fully-built
    # task into an independent doc per assignee (own status/evidence/verification/comments/
    # deadline/completion), so one assignee's progress never affects another's. Only applies to
    # tasks with more than one assignee; everything else falls through to the single insert.
    assignees = event_dict.get("target_staff_id") or []
    if event_dict.get("type") == "task" and event_dict.get("assignment_mode") == "separate" and len(assignees) > 1:
        docs = []
        for uid in assignees:
            d = {k: v for k, v in event_dict.items() if k not in ("_id", "id")}
            d["target_staff_id"] = [uid]
            # Give each assignee an independent recurrence series so the nightly roll-forward
            # (recurring_task_service) advances every user's copy separately.
            if d.get("recurring_group_id"):
                d["recurring_group_id"] = str(ObjectId())
            d["created_at"] = datetime.utcnow()
            docs.append(d)
        insert_res = await col.insert_many(docs)
        ids = [str(_id) for _id in insert_res.inserted_ids]
        # Each assignee owns an independent series, so each one is pre-generated separately
        # (see _expand_task_series). Occurrences are inserted WITHOUT notifications — the
        # assignment is announced once per assignee in the loop below, not once per date.
        if is_repeating and end_date_str:
            occurrences = []
            for d in docs:
                try:
                    occurrences.extend(await _expand_task_series(d, end_date_str))
                except Exception as e:
                    # A series that fails to expand still has its head: the nightly engine
                    # rolls it forward exactly as it did before, so no task is ever lost.
                    print(f"TASK SERIES PRE-GENERATION FAILURE: {e}")
            if occurrences:
                await col.insert_many(occurrences)
        # Mirror the single-create side effects (notifications, meta sync, activity, realtime)
        # for every created doc so nothing downstream behaves differently per assignee.
        for d, _id in zip(docs, ids):
            background_tasks.add_task(notify_task_event, "created", {**d, "id": _id}, current_user)
            await task_events.publish(task_events.recipients_for(d), {
                "type": "task_created",
                "task_id": _id,
                "title": d.get("title"),
                "assigned_to": d.get("target_staff_id") or [],
                "assigned_by": d.get("user_id"),
                "watchers": d.get("watchers") or [],
                "actor_id": str(current_user["_id"]),
            })
        background_tasks.add_task(sync_task_meta, event_dict.get("category"), event_dict.get("tags"), str(current_user["_id"]))
        await log_activity(current_user, "Create Task", col_name, f"Created {len(ids)} separate tasks: {event_dict['title']}",
                           meta={"task_id": ids[0], "group_id": event_dict.get("group_id")})
        return {"ids": ids, "id": ids[0], "count": len(ids), "message": f"Created {len(ids)} separate tasks"}

    result = await col.insert_one(event_dict)
    event_dict["id"] = str(result.inserted_id)

    # The head is inserted above; the rest of a recurring task's schedule is written here so the
    # whole series exists immediately (see _expand_task_series). Deliberately silent: the single
    # "task assigned" notification fires below, as it always has — one per assignment, never one
    # per generated date.
    if event_dict.get("type") == "task" and is_repeating and end_date_str:
        try:
            occurrences = await _expand_task_series(event_dict, end_date_str)
            if occurrences:
                await col.insert_many(occurrences)
        except Exception as e:
            # The task itself is already saved; the nightly engine extends it as before.
            print(f"TASK SERIES PRE-GENERATION FAILURE: {e}")

    is_task = event_dict.get("type") == "task"
    if is_task:
        # A subtask announces itself as a subtask, not as a brand-new top-level task.
        parent_id = event_dict.get("parent_task_id")
        if parent_id:
            parent, _ = await find_event_across_collections(parent_id)
            background_tasks.add_task(
                notify_task_event, "subtask_created", event_dict, current_user,
                {"parent_title": (parent or {}).get("title") or "its parent task"},
            )
        else:
            background_tasks.add_task(notify_task_event, "created", event_dict, current_user)
        background_tasks.add_task(sync_task_meta, event_dict.get("category"), event_dict.get("tags"), str(current_user["_id"]))
    elif event_dict.get("type") == TODO_TYPE:
        # notify_users_instant ignores todos by design, so this is the only place a calendar
        # To-do can be announced — without it, creating one sent nothing at all.
        background_tasks.add_task(notify_todo_created, event_dict, 1)
    else:
        background_tasks.add_task(notify_users_instant, event_dict, "created", creator_name)
    await log_activity(current_user, "Create Task" if is_task else "Create Event", col_name, f"{'Task' if is_task else 'Event'} created: {event_dict['title']}",
                       meta={"task_id": str(result.inserted_id), "group_id": event_dict.get("group_id")} if is_task else None)
    if is_task:
        await task_events.publish(task_events.recipients_for(event_dict), {
            "type": "task_created",
            "task_id": str(result.inserted_id),
            "title": event_dict.get("title"),
            "assigned_to": event_dict.get("target_staff_id") or [],
            "assigned_by": event_dict.get("user_id"),
            "watchers": event_dict.get("watchers") or [],
            "actor_id": str(current_user["_id"]),
        })
    return {"id": str(result.inserted_id), "message": f"Event created in {col_name}"}

async def _assignee_names(user_ids) -> str:
    """"Asha, Ravi" for a set of user ids — the {{previous_assignee}} / {{new_assignee}}
    placeholders on the reassignment templates.

    A name that cannot be resolved is simply left out rather than printed as an id: a handover
    mail naming a raw ObjectId is worse than one naming only the people it could identify.
    """
    names = []
    for uid in sorted(user_ids or []):
        user = await find_user_by_id(uid)
        if user:
            names.append(user.get("full_name") or user.get("first_name") or user.get("email") or "")
    return ", ".join(n for n in names if n)


@router.patch("/{event_id}")
async def update_event(event_id: str, updates: dict, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(event_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")

    # Block anyone without Task & Delegation access from editing a task (or turning an event
    # into a task) via this shared endpoint.
    is_task_update = existing.get("type") == "task" or updates.get("type") == "task"
    if is_task_update:
        if not await has_task_access(current_user):
            raise HTTPException(
                status_code=403,
                detail=DELEGATION_DISABLED_MESSAGE if is_client_side_user(current_user) else TASK_ACCESS_DENIED_MESSAGE,
            )
        # If assignees / watchers are being changed, every new recipient must be eligible for
        # this editor (internal staff, or the editor's own company users).
        recipients = []
        if "target_staff_id" in updates:
            recipients += updates.get("target_staff_id") or []
        if "watchers" in updates:
            recipients += updates.get("watchers") or []
        if recipients:
            bad = await get_ineligible_recipient_ids(current_user, recipients)
            if bad:
                raise HTTPException(status_code=403, detail=recipient_denied_message(current_user))
        if "target_staff_id" in updates:
            rank_bad = await get_rank_ineligible_assignees(current_user, updates.get("target_staff_id") or [])
            if rank_bad:
                raise HTTPException(status_code=403, detail=ASSIGN_RANK_DENIED_MESSAGE)

    # A todo answers to its owner alone — not to admins, not to a calendar.update grant.
    _require_todo_owner(existing, current_user)
    if existing.get("type") == TODO_TYPE:
        _strip_todo_sharing(updates)
        _label_todo_reminders(updates)
        updates.pop("type", None)  # a todo can never be converted into a shared event/task

    is_admin = current_user.get("role") == "superadmin"
    has_update_perm = current_user.get("permissions", {}).get("calendar", {}).get("update")
    is_creator = existing.get("user_id") == str(current_user["_id"])
    # A client MD administers every TASK in their own company (see auth_controller). Scoped to
    # tasks so this never widens authority over sessions/events, which the MD has no part in.
    is_company_admin = is_task_update and is_company_task_admin(existing, current_user)

    if not (is_admin or has_update_perm or is_creator or is_company_admin):
        raise HTTPException(status_code=403, detail="Not authorized to edit this event.")
         
    # ─── Record Completion Timestamp ───
    if updates.get("status") == "completed" and existing.get("status") != "completed":
        updates["completed_at"] = datetime.now(timezone.utc)
    elif updates.get("status") == "schedule":
        updates["completed_at"] = None

    # ─── A todo's status follows its due date on every edit ───
    # Pending vs Overdue is never the user's choice, it is a fact about the deadline — so it is
    # RECOMPUTED here rather than taken from the payload: a due date moved into the future puts a
    # missed todo back to Pending, one already past makes it Overdue immediately instead of on
    # the next sweep. Recomputing also matters because the edit form posts back whatever status
    # it loaded, so an overdue todo would otherwise send "overdue" straight back and stick there.
    # Completed is left alone — it is finished business, not a deadline question.
    if existing.get("type") == TODO_TYPE and updates.get("status", existing.get("status")) != "completed":
        from app.services.todo_status_service import is_todo_overdue
        updates["status"] = TODO_OVERDUE_STATUS if is_todo_overdue({**existing, **updates}) else TODO_PENDING_STATUS
        updates["completed_at"] = None

    # ─── Switching a task to/from Repeat re-resolves its day window ───
    # Turning Repeat ON drops whatever deadline the task had — a Recurring Checklist has
    # none — and turning it OFF hands the deadline back to the user. Resolved from the
    # merged document so it follows the edit, not the stale stored value.
    if existing.get("type") == TASK_TYPE:
        merged = {**existing, **updates}
        if is_recurring_task(merged):
            window = dict(merged)
            _apply_recurring_task_day_window(window)
            updates["end"] = window["end"]

    updates["updated_at"] = datetime.now(timezone.utc)

    # ─── Movement Logic ───
    projected = {**existing, **updates}
    new_col_name = await get_target_collection_name(projected)
    
    if new_col_name != col_name and col_name != "calendar_events":
        # Move document between collections
        await get_collection(col_name).delete_one({"_id": ObjectId(event_id)})
        # Ensure we don't have _id as string if it was converted
        if "id" in projected: del projected["id"]
        await get_collection(new_col_name).insert_one(projected)
        final_doc = projected
    else:
        # Standard update within the same collection
        await get_collection(col_name).update_one({"_id": ObjectId(event_id)}, {"$set": updates})
        final_doc = projected

    is_task = (projected.get("type") or existing.get("type")) == "task"
    _title = projected.get("title") or existing.get("title") or event_id
    await log_activity(current_user, "Update Task" if is_task else "Update Event", new_col_name, f"{'Task' if is_task else 'Event'} updated: {_title}",
                       meta={"task_id": event_id, "group_id": projected.get("group_id")} if is_task else None)
    if is_task and ("category" in updates or "tags" in updates):
        background_tasks.add_task(sync_task_meta, projected.get("category"), projected.get("tags"), str(current_user["_id"]))
    if is_task:
        # Union old + new recipients so a user removed from assignees/watchers also refetches
        # (and the task correctly drops off their list).
        recipients = task_events.recipients_for(existing) | task_events.recipients_for(projected)
        await task_events.publish(recipients, {
            "type": "task_updated",
            "task_id": event_id,
            "status": projected.get("workflow_status"),
            "title": _title,
            "assigned_to": projected.get("target_staff_id") or [],
            "assigned_by": projected.get("user_id"),
            "watchers": projected.get("watchers") or [],
            "actor_id": str(current_user["_id"]),
        })
    creator_name = current_user.get("full_name") or current_user.get("first_name", "System Admin")
    final_doc["id"] = str(event_id)
    if is_task:
        # Someone newly put on the task is being *assigned* it, not merely told it changed.
        # They get the assignment trigger and are held back from the update trigger, so a
        # single edit never sends one person two emails.
        old_assignees = {str(u) for u in (existing.get("target_staff_id") or []) if u}
        new_assignees = {str(u) for u in (projected.get("target_staff_id") or []) if u}
        added = new_assignees - old_assignees
        removed = old_assignees - new_assignees
        # A HANDOVER — someone taken off and someone else put on in the same edit — is not the
        # same event as simply widening a task, and the manager doing it wants both halves
        # announced. `reassigned` tells the new holder (and the assigner/watchers) that the
        # work has MOVED; `assigned` is kept for the plain "another pair of hands" case, so an
        # existing template for it never changes meaning.
        handover = bool(added and removed)
        if added:
            background_tasks.add_task(notify_task_event,
                                      "reassigned" if handover else "assigned",
                                      final_doc, current_user,
                                      {"new_assignee_ids": list(added),
                                       "previous_assignee": await _assignee_names(removed),
                                       "new_assignee": await _assignee_names(added)})
        # Whoever LOST the task hears it from the unassigned trigger. They are no longer on the
        # doc, so every other trigger's recipient set excludes them — without this they would
        # simply watch the task vanish from their list with no explanation.
        if removed:
            background_tasks.add_task(notify_task_event, "unassigned", final_doc, current_user,
                                      {"removed_assignee_ids": list(removed),
                                       "previous_assignee": await _assignee_names(removed),
                                       "new_assignee": await _assignee_names(added)})
        # Someone newly put in the loop (as a watcher) is being *added to the loop*, not merely
        # told the task changed — they get the In Loop Person trigger and are held back from the
        # generic update, so a single edit never sends one person two emails.
        old_watchers = {str(u) for u in (existing.get("watchers") or []) if u}
        new_watchers = {str(u) for u in (projected.get("watchers") or []) if u}
        added_watchers = new_watchers - old_watchers
        if added_watchers:
            background_tasks.add_task(notify_task_event, "in_loop_added", final_doc, current_user,
                                      {"new_watcher_ids": list(added_watchers)})
        already_in_loop = (recipients_for_event("updated", final_doc)
                           - added - removed - added_watchers)
        if already_in_loop:
            background_tasks.add_task(notify_task_event, "updated", final_doc, current_user,
                                      None, list(already_in_loop))
    else:
        background_tasks.add_task(notify_users_instant, final_doc, "updated", creator_name)

    # ─── Recurring Series Timeline Sync ───
    if updates.get("repeat_end_date") and existing.get("recurring_group_id"):
        new_end_str = updates["repeat_end_date"]
        old_end_str = existing.get("repeat_end_date")
        
        if new_end_str != old_end_str:
            try:
                gid = existing["recurring_group_id"]
                # Standardize parsing
                new_raw_end = new_end_str.replace("Z", "+00:00")
                if len(new_raw_end) <= 10: new_raw_end += "T23:59:59+00:00"
                new_end_dt = datetime.fromisoformat(new_raw_end)
                if new_end_dt.tzinfo is None: new_end_dt = new_end_dt.replace(tzinfo=timezone.utc)

                # 1. DELETE: Future occurrences past the new end date.
                # A todo is due at 23:59:59 IST, which is LATER in the day than the raw stored
                # end value (midday UTC from the picker) — so its boundary has to be the end of
                # the chosen IST day, or shortening a series would also delete the occurrence
                # falling on the very date the user just chose as the end.
                is_todo_series = existing.get("type") == TODO_TYPE
                cutoff_dt = (_series_end_cutoff(new_end_str) or new_end_dt) if is_todo_series else new_end_dt
                await get_collection(new_col_name).delete_many({
                    "recurring_group_id": gid,
                    "start": {"$gt": cutoff_dt.isoformat()}
                })

                # 2a. TODOS: rebuild forward from whatever occurrence is now last in the series,
                # through the shared builder — so an extended todo series keeps the holiday /
                # weekly-off and anti-drift rules its original dates were generated under. The
                # naive walk below would ignore them and put todos on Sundays and holidays.
                if is_todo_series:
                    from app.services.recurring_task_service import (
                        build_series_occurrences, MAX_SERIES_OCCURRENCES,
                    )
                    remaining = await get_collection(new_col_name).find(
                        {"recurring_group_id": gid}).to_list(MAX_SERIES_OCCURRENCES + 1)
                    if remaining:
                        # Walk on from the LAST surviving occurrence. The edit's own content
                        # (title, details, cadence) carries onto the new dates, but its
                        # per-occurrence fields must not: `updates` holds the start/end of
                        # whichever occurrence the user happened to open, and letting that
                        # through would restart the series from that date instead of the last.
                        head = max(remaining, key=lambda d: d.get("start") or "")
                        series_head = {**head, **{k: v for k, v in updates.items()
                                                  if k not in PER_OCCURRENCE_FIELDS}}
                        taken = {(d.get("start") or "")[:10] for d in remaining}
                        occurrences, _ = await build_series_occurrences(
                            series_head, cutoff_dt, taken_dates=taken)
                        if occurrences:
                            await get_collection(new_col_name).insert_many(occurrences)

                # 2b. GENERATE: If expanded, create new ones
                elif old_end_str:
                    old_raw_end = old_end_str.replace("Z", "+00:00")
                    if len(old_raw_end) <= 10: old_raw_end += "T23:59:59+00:00"
                    current_end_dt = datetime.fromisoformat(old_raw_end)
                    if current_end_dt.tzinfo is None: current_end_dt = current_end_dt.replace(tzinfo=timezone.utc)
                    
                    if new_end_dt > current_end_dt:
                        # Find the step from repeat_type
                        repeat_type = existing.get("repeat", "Daily")
                        interval = existing.get("repeat_interval", 1) or 1
                        
                        generated = []
                        curr_dt = current_end_dt
                        # Avoid duplicate on the current_end_dt itself
                        next_dt = _next_occurrence(curr_dt, repeat_type, interval, existing.get("repeat_data"))
                        if next_dt is not None: curr_dt = next_dt

                        while curr_dt <= new_end_dt:
                            new_ev = {**existing, **updates}
                            new_ev["start"] = curr_dt.isoformat()
                            if new_ev.get("end"):
                                diff = (datetime.fromisoformat(existing["end"].replace("Z", "+00:00")) - datetime.fromisoformat(existing["start"].replace("Z", "+00:00")))
                                new_ev["end"] = (curr_dt + diff).isoformat()
                            
                            new_ev["created_at"] = datetime.utcnow()
                            if "_id" in new_ev: del new_ev["_id"]
                            generated.append(new_ev)
                            
                            next_dt = _next_occurrence(curr_dt, repeat_type, interval, existing.get("repeat_data"))
                            if next_dt is None: break
                            curr_dt = next_dt
                            if len(generated) > 365: break
                        
                        if generated:
                            await get_collection(new_col_name).insert_many(generated)
            except Exception as se:
                print(f"SERIES SYNC FAILURE: {se}")

    return {"message": f"Event updated in {new_col_name}"}


@router.post("/{event_id}/attendance")
async def mark_attendance(event_id: str, attendance_data: dict, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")
    is_admin = current_user.get("role") == "superadmin"
    has_update_perm = current_user.get("permissions", {}).get("calendar", {}).get("update")
    is_creator = existing.get("user_id") == str(current_user["_id"])
    
    if not (is_admin or has_update_perm or is_creator):
         raise HTTPException(status_code=403, detail="Not authorized to mark attendance")
         
    # Expected payload: {"attendees": {"user_id_1": True, "user_id_2": False}}
    attendance = attendance_data.get("attendees", {})
    
    await get_collection(col_name).update_one({"_id": ObjectId(event_id)}, {"$set": {"attendance": attendance, "updated_at": datetime.utcnow()}})
    await log_activity(current_user, "Mark Attendance", col_name, f"Marked attendance for session: {event_id}")
    await sync_event_to_collection(event_id)

    # Process background emails and SYNC attendance collection for analytics
    async def process_attendance_sync():
        user_col = get_collection("users")
        attendance_col = get_collection("attendance")
        
        for user_id, is_present in attendance.items():
            status = "present" if is_present else "absent"
            
            # Upsert into attendance collection for individual analytics & history
            await attendance_col.update_one(
                {"user_id": user_id, "session_id": event_id},
                {
                    "$set": {
                        "user_id": user_id,
                        "session_id": event_id,
                        "session_name": existing.get("title"),
                        "status": status,
                        "date": existing.get("start"),
                        "type": existing.get("session_type", "General"),
                        "updated_at": datetime.utcnow()
                    }
                },
                upsert=True
            )

            # Send emails
            user = await user_col.find_one({"_id": ObjectId(user_id)})
            if user:
                try:
                    if is_present:
                        await send_attendance_thanks_email(user, existing)
                    else:
                        await send_attendance_absent_email(user, existing)
                except Exception as e:
                    print(f"Error sending attendance email to {user_id}: {e}")

    background_tasks.add_task(process_attendance_sync)
    
    return {"message": "Attendance marked successfully and notifications triggered"}
    
@router.post("/{event_id}/upload-content")
async def upload_content(event_id: str, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")
    
    # Creator or Admin only
    is_admin = current_user.get("role") == "superadmin"
    has_update_perm = current_user.get("permissions", {}).get("calendar", {}).get("update")
    is_creator = existing.get("user_id") == str(current_user["_id"])

    if not (is_admin or has_update_perm or is_creator):
         raise HTTPException(status_code=403, detail="Only the creator or an authorized administrator can upload content")

    try:
        url = upload_file_to_s3(file.file, file.filename, file.content_type)
        content_obj = {"id": str(ObjectId()), "name": file.filename, "url": url, "file_type": file.content_type, "uploaded_by": str(current_user["_id"]), "uploaded_at": datetime.utcnow(), "views": 0}
        await get_collection(col_name).update_one({"_id": ObjectId(event_id)}, {"$push": {"contents": content_obj}})
        await sync_event_to_collection(event_id)
        return {"message": "Content uploaded successfully", "content": content_obj}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))


import os
import aiofiles
import tempfile
from app.services.transcription_service import process_background_upload_and_transcribe, process_media_library_resource

@router.post("/{event_id}/upload-resource")
async def upload_resource(event_id: str, background_tasks: BackgroundTasks, file: UploadFile = File(...), resource_type: str = Form(...), current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")

    # Creator or Admin only
    is_admin = current_user.get("role") == "superadmin"
    has_update_perm = current_user.get("permissions", {}).get("calendar", {}).get("update")
    is_creator = existing.get("user_id") == str(current_user["_id"])

    if not (is_admin or has_update_perm or is_creator):
         raise HTTPException(status_code=403, detail="Only the creator or an authorized administrator can upload resources")

    try:
        resource_id = str(ObjectId())
        # Processing code (omitted for brevity, remains logic-same)
        # [TMP FILE HANDLING CODE REMAINS UNCHANGED]
        tmp_dir = os.path.join(tempfile.gettempdir(), f"sparsh_uploads_{event_id}")
        os.makedirs(tmp_dir, exist_ok=True)
        local_path = os.path.join(tmp_dir, f"{resource_id}_{file.filename}")
        async with aiofiles.open(local_path, 'wb') as out_file:
            while content := await file.read(1024 * 1024): await out_file.write(content)
        resource_obj = {"id": resource_id, "name": file.filename, "url": None, "system_type": resource_type, "file_type": file.content_type, "uploaded_by": str(current_user["_id"]), "uploaded_at": datetime.utcnow(), "status": "processing", "progress": 0, "transcription": None, "views": 0}
        await get_collection(col_name).update_one({"_id": ObjectId(event_id)}, {"$push": {"resources": resource_obj}})
        # ... background tasks
        background_tasks.add_task(process_background_upload_and_transcribe, event_id, resource_id, local_path, file.filename, file.content_type, resource_type, col_name)
        return {"message": "Resource accepted.", "resource": resource_obj}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))


async def _get_media_asset(media_id: str) -> dict:
    """Fetch a Media Library record or raise 404."""
    try:
        media = await get_collection("media_library").find_one({"_id": ObjectId(media_id)})
    except Exception:
        media = None
    if not media:
        raise HTTPException(status_code=404, detail="Media Library file not found")
    return media


@router.post("/{event_id}/add-content-from-media")
async def add_content_from_media(event_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    """Attach an existing Media Library file as Shared Content (by reference)."""
    existing, col_name = await find_event_across_collections(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")

    is_admin = current_user.get("role") == "superadmin"
    has_update_perm = current_user.get("permissions", {}).get("calendar", {}).get("update")
    is_creator = existing.get("user_id") == str(current_user["_id"])
    if not (is_admin or has_update_perm or is_creator):
        raise HTTPException(status_code=403, detail="Only the creator or an authorized administrator can add content")

    media = await _get_media_asset(payload.get("media_id"))
    # Regenerate a fresh signed URL from the stored key (signed URLs expire).
    url = get_signed_url(media["s3_key"]) if media.get("s3_key") else media.get("url")

    content_obj = {
        "id": str(ObjectId()),
        "name": media.get("name") or media.get("file_name"),
        "url": url,
        "file_type": media.get("content_type"),
        "media_id": str(media["_id"]),   # reference back to the library
        "s3_key": media.get("s3_key"),
        "uploaded_by": str(current_user["_id"]),
        "uploaded_at": datetime.utcnow(),
        "views": 0,
    }
    await get_collection(col_name).update_one({"_id": ObjectId(event_id)}, {"$push": {"contents": content_obj}})
    await sync_event_to_collection(event_id)
    return {"message": "Content added from Media Library", "content": content_obj}


@router.post("/{event_id}/add-resource-from-media")
async def add_resource_from_media(event_id: str, background_tasks: BackgroundTasks, payload: dict, current_user: dict = Depends(get_current_user)):
    """Attach an existing Media Library file as an Executive Resource (by
    reference). Audio/video still get auto-transcribed, same as a direct upload."""
    existing, col_name = await find_event_across_collections(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")

    is_admin = current_user.get("role") == "superadmin"
    has_update_perm = current_user.get("permissions", {}).get("calendar", {}).get("update")
    is_creator = existing.get("user_id") == str(current_user["_id"])
    if not (is_admin or has_update_perm or is_creator):
        raise HTTPException(status_code=403, detail="Only the creator or an authorized administrator can add resources")

    media = await _get_media_asset(payload.get("media_id"))
    # Resource format: caller may override, else fall back to the library type.
    resource_type = (payload.get("resource_type") or media.get("media_type") or "other").lower()
    url = get_signed_url(media["s3_key"]) if media.get("s3_key") else media.get("url")

    resource_id = str(ObjectId())
    resource_obj = {
        "id": resource_id,
        "name": media.get("name") or media.get("file_name"),
        "url": url,
        "system_type": resource_type,
        "file_type": media.get("content_type"),
        "media_id": str(media["_id"]),
        "s3_key": media.get("s3_key"),
        "uploaded_by": str(current_user["_id"]),
        "uploaded_at": datetime.utcnow(),
        "status": "processing",
        "progress": 0,
        "transcription": None,
        "views": 0,
    }
    await get_collection(col_name).update_one({"_id": ObjectId(event_id)}, {"$push": {"resources": resource_obj}})

    background_tasks.add_task(
        process_media_library_resource,
        event_id, resource_id, media.get("s3_key"),
        resource_obj["name"], media.get("content_type") or "",
        resource_type, url, col_name,
    )
    return {"message": "Resource added from Media Library", "resource": resource_obj}


@router.delete("/{event_id}")
async def delete_event(event_id: str, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")

    is_admin = current_user.get("role") == "superadmin"
    has_delete_perm = current_user.get("permissions", {}).get("calendar", {}).get("delete")
    is_creator = existing.get("user_id") == str(current_user["_id"])
    # A client MD administers every TASK in their own company — tasks only, so a session/event
    # (and, via the owner check below, a todo) is unaffected.
    is_company_admin = (existing.get("type") == "task"
                        and is_company_task_admin(existing, current_user))

    # Only the owner may delete their todo — a calendar.delete grant does not reach it.
    _require_todo_owner(existing, current_user)

    if not (is_admin or has_delete_perm or is_creator or is_company_admin):
         raise HTTPException(status_code=403, detail="Not authorized to delete this event")

    await get_collection(col_name).delete_one({"_id": ObjectId(event_id)})
    creator_name = current_user.get("full_name") or current_user.get("first_name", "System Admin")
    if existing.get("type") == "task":
        background_tasks.add_task(notify_task_event, "deleted", existing, current_user)
    else:
        background_tasks.add_task(notify_users_instant, existing, "deleted", creator_name)
    return {"message": "Deleted successfully"}


@router.get("/{event_id}")
async def get_event(event_id: str, current_user: dict = Depends(get_current_user)):
    event, col_name = await find_event_across_collections(event_id)
    if not event: raise HTTPException(status_code=404, detail="Event not found")
    _require_todo_owner(event, current_user)  # a todo is readable only by its owner
    event["id"] = str(event["_id"])
    del event["_id"]
    
    from app.services.s3_service import get_signed_url
    import urllib.parse
    
    def refresh_url(item):
        url = item.get("url")
        if url and ".amazonaws.com/" in url:
            try:
                path_part = url.split(".amazonaws.com/")[-1]
                s3_key = urllib.parse.unquote(path_part.split("?")[0])
                item["url"] = get_signed_url(s3_key)
            except Exception: pass

    for content in event.get("contents", []):
        refresh_url(content)
        
    for content in event.get("learner_contents", []):
        refresh_url(content)
        
    for resource in event.get("resources", []):
        refresh_url(resource)

    return event


@router.get("")
async def get_all_events(target_user_id: Optional[str] = None, view_mode: str = "personal", current_user: dict = Depends(get_current_user)):
    events = []
    current_uid = str(current_user["_id"])
    role = current_user.get("role", "").lower()
    is_staff_admin = role in ["superadmin", "admin", "coach", "staff"]
    has_team_read_perm = current_user.get("permissions", {}).get("calendar", {}).get("read")
    
    # ─── Effective Identity Resolution ───
    effective_user_id = current_uid
    if target_user_id:
        if is_staff_admin:
            effective_user_id = target_user_id
        elif role == "clientadmin":
            # Verify company alignment for Client Admins
            target_user = await find_user_by_id(target_user_id)
            if target_user and str(target_user.get("company_id")) == str(current_user.get("company_id")):
                effective_user_id = target_user_id
    
    # Enable team view for those with 'calendar: read' or superadmins
    can_view_team = (view_mode == "team") and (role == "superadmin" or has_team_read_perm)
    
    # ─── Batches & Quarters ───
    if not target_user_id:
        if can_view_team:
            batches = await get_collection("batches").find({}).to_list(100)
            quarters = await get_collection("quarters").find({}).to_list(200)
        else:
            # Filter batches where the user is a member OR a coach
            # For simplicity, if they have batch_ids in profile, use those
            batch_ids = current_user.get("batch_ids", [])
            if not batch_ids and current_user.get("batch_id"):
                batch_ids = [current_user.get("batch_id")]
                
            # If still no batch_ids, find where user is involved in sessions
            if not batch_ids and is_staff_admin:
                # Admins with personal view still might want see their active batches
                # But for now, stick to the stored batch_ids or all if team view.
                pass
                
            batches = await get_collection("batches").find({"_id": {"$in": [ObjectId(bid) for bid in batch_ids if bid]}}).to_list(10)
            quarters = await get_collection("quarters").find({"batch_id": {"$in": [str(bid) for bid in batch_ids if bid]}}).to_list(50)
    else:
        batches = []; quarters = []

    for b in batches:
        if b.get("start_date"): events.append({"id": str(b["_id"]), "title": b["name"], "type": "batch", "start": b["start_date"], "color": "var(--accent-indigo)", "bg": "var(--accent-indigo-bg)", "editable": False})
    for q in quarters:
        if q.get("start_date"): events.append({"id": str(q["_id"]), "title": f"Q: {q['name']}", "type": "quarter", "start": q["start_date"], "color": "var(--accent-orange)", "bg": "var(--accent-orange-bg)", "editable": False})
            
    # ─── Pre-fetch staff IDs for creator_is_staff enrichment ───
    staff_docs = await get_collection("staff").find({}, {"_id": 1}).to_list(None)
    staff_id_set = {str(doc["_id"]) for doc in staff_docs}

    # ─── Aggregated Events, Tasks & Todos ───
    # Todos are private, so no branch below may ever surface one belonging to someone else:
    # this clause is AND-ed onto every query — team view, admin view and impersonation alike.
    # A doc is allowed through when it is NOT a todo, or when it is the caller's own todo.
    # (`current_uid`, never `effective_user_id`: viewing another user's calendar must not
    # reveal their todos either.)
    not_others_todo = {"$or": [{"type": {"$ne": TODO_TYPE}}, {"user_id": current_uid}]}

    for col_name in (CALENDAR_COLLECTIONS + ["calendar_events"]):
        custom_col = get_collection(col_name)

        if can_view_team and not target_user_id:
            query = {}
            if role != "superadmin" and current_user.get("company_id"):
                # If team view but not superadmin, limit to their company
                query = {
                    "$or": [
                        {"company_id": str(current_user["company_id"])},
                        {"user_id": current_uid},
                        {"assigned_member_ids": current_uid},
                        {"assigned_member_ids": {"$in": [current_uid]}},
                        {"target_staff_id": current_uid},
                        {"target_staff_id": {"$in": [current_uid]}}
                    ]
                }
            # TPMS activities live in these collections too — they belong to the TPMS
            # Calendar, not the Session Calendar. See calendar_utils.exclude_tpms.
            db_docs = await custom_col.find(exclude_tpms(query)).to_list(1000)
        else:
            # Privacy Logic: 
            # Visible if Creator OR explicitly involved in any capacity (Attendee, Coach, Target)
            involvement_clauses = [
                {"user_id": effective_user_id},
                {"assigned_member_ids": effective_user_id},
                {"coach_ids": effective_user_id},
                {"target_staff_id": effective_user_id},
                {"assigned_member_ids": {"$in": [effective_user_id]}},
                {"coach_ids": {"$in": [effective_user_id]}},
                {"target_staff_id": {"$in": [effective_user_id]}}
            ]
            db_docs = await custom_col.find(
                exclude_tpms({"$or": involvement_clauses})).to_list(1000)
        
        for c in db_docs:
            events.append({
                "id": str(c["_id"]), "title": c["title"], "type": c["type"], "start": c["start"], "end": c.get("end"), "allDay": c.get("all_day", False),
                "extendedProps": { **{k: v for k, v in c.items() if k not in ["_id", "created_at", "updated_at"]}, "id": str(c["_id"]), "created_at": _iso_utc(c.get("created_at")), "isCreator": c.get("user_id") == current_uid, "isAssigned": current_uid in (c.get("target_staff_id") or []) or current_uid in (c.get("assigned_member_ids") or []), "canEdit": role == "superadmin" or c.get("user_id") == current_uid, "source_col": col_name, "creator_is_staff": c.get("user_id") in staff_id_set }
            })
    return events


@router.get("/{event_id}/resources/{resource_id}")
async def get_resource_details(event_id: str, resource_id: str, current_user: dict = Depends(get_current_user)):
    event, col_name = await find_event_across_collections(event_id)
    if not event: raise HTTPException(status_code=404, detail="Event not found")
    all_items = (event.get("resources") or []) + (event.get("contents") or [])
    resource = next((r for r in all_items if r.get("id") == resource_id), None)
    if not resource: raise HTTPException(status_code=404, detail="Resource not found")
    # ... URL signing logic (unchanged)
    from app.services.s3_service import get_signed_url
    import urllib.parse
    url = resource.get("url") or resource.get("link")
    if url and ".amazonaws.com/" in url:
        try:
            # Extract only the object key, ignoring existing query parameters
            path_part = url.split(".amazonaws.com/")[-1]
            s3_key_quoted = path_part.split("?")[0]
            # Crucial: Unquote the key because the stored URL already has %20 for spaces
            # If we don't unquote, boto3 will double-encode it (e.g., %20 -> %2520), causing a 404.
            s3_key = urllib.parse.unquote(s3_key_quoted)
            resource["url"] = get_signed_url(s3_key)
        except Exception: pass
    return resource


@router.post("/{event_id}/resources/{resource_id}/view")
async def track_resource_view(event_id: str, resource_id: str, current_user: dict = Depends(get_current_user)):
    event, col_name = await find_event_across_collections(event_id)
    if not event: raise HTTPException(status_code=404, detail="Event not found")
    
    view_entry = {
        "user_id": str(current_user["_id"]),
        "user_name": current_user.get("full_name") or current_user.get("email"),
        "timestamp": datetime.utcnow(),
        "duration": 0, # Seconds
        "session_id": str(ObjectId()) # Unique ID for this specific watch session
    }
    
    await get_collection(col_name).update_one(
        {"_id": ObjectId(event_id), "resources.id": resource_id}, 
        {
            "$inc": {"resources.$.views": 1},
            "$push": {"resources.$.view_logs": view_entry}
        }
    )
    
    # Log Activity
    await log_activity(current_user, "View Resource", "Calendar", f"Started viewing resource {resource_id} in {event.get('title')}")
    return {"message": "View tracked", "watch_session_id": view_entry["session_id"]}


@router.post("/{event_id}/resources/{resource_id}/watch-time")
async def update_watch_time(event_id: str, resource_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    watch_session_id = payload.get("watch_session_id")
    increment = payload.get("seconds", 10)
    
    if not watch_session_id: return {"status": "ignored"}
    
    event, col_name = await find_event_across_collections(event_id)
    if not event: raise HTTPException(status_code=404, detail="Event not found")
    
    # Update the specific log entry for this session
    # Using arrayFilters to target the correct resource AND the correct log entry inside it
    await get_collection(col_name).update_one(
        {"_id": ObjectId(event_id)},
        {"$inc": {"resources.$[res].view_logs.$[log].duration": increment}},
        array_filters=[
            {"res.id": resource_id},
            {"log.session_id": watch_session_id}
        ]
    )
    return {"status": "updated"}

@router.get("/{event_id}/resources/{resource_id}/analytics")
async def get_resource_analytics(event_id: str, resource_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["superadmin", "admin", "coach", "staff"]:
        if not current_user.get("permissions", {}).get("calendar", {}).get("read"):
            raise HTTPException(status_code=403, detail="Access denied")
        
    event, col_name = await find_event_across_collections(event_id)
    if not event: raise HTTPException(status_code=404, detail="Event not found")
    
    resource = next((r for r in (event.get("resources") or []) if r.get("id") == resource_id), None)
    if not resource: raise HTTPException(status_code=404, detail="Resource not found")
    
    logs = resource.get("view_logs", [])
    
    # Aggregated mapping
    unique_users = {}
    for log in logs:
        uid = log["user_id"]
        if uid not in unique_users:
            unique_users[uid] = {
                "user_name": log["user_name"],
                "total_duration": 0,
                "first_view": log["timestamp"],
                "last_view": log["timestamp"],
                "view_count": 0
            }
        
        unique_users[uid]["total_duration"] += log.get("duration", 0)
        unique_users[uid]["view_count"] += 1
        if log["timestamp"] > unique_users[uid]["last_view"]:
            unique_users[uid]["last_view"] = log["timestamp"]

    return {
        "total_views": resource.get("views", 0),
        "unique_viewers_count": len(unique_users),
        "unique_logs": list(unique_users.values()),
        "full_logs": logs
    }



@router.post("/{event_id}/resources/{resource_id}/chat")
async def ai_companion_chat(event_id: str, resource_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    from openai import AsyncOpenAI
    from app.config.settings import settings
    
    question = payload.get("question")
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")
        
    event, col_name = await find_event_across_collections(event_id)
    if not event: raise HTTPException(status_code=404, detail="Event not found")
    
    resource = next((r for r in (event.get("resources") or []) if r.get("id") == resource_id), None)
    if not resource:
        resource = next((r for r in (event.get("contents") or []) if r.get("id") == resource_id), None)
    
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
        
    transcription = resource.get("transcription", "No transcription available for this file.")
    file_name = resource.get("name", "Unknown File")
    system_type = resource.get("system_type", "Document")
    
    try:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        
        system_prompt = f"""You are a helpful AI Companion for the Sparsh ERP system. 
You are assisting a user with a specific file: "{file_name}" (Type: {system_type}).
Below is the transcription of the audio/video content if available:
---
{transcription}
---
Please answer the user's question based strictly on this transcription and the file context. 
If the user asks about specific parts of the video/audio, try to infer timestamps if mentions of time or clear segments are in the transcription.
Structure your response clearly. Use markdown.
"""
        
        response = await client.chat.completions.create(
            model="gpt-4o", # Using a standard model
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            temperature=0.7
        )
        
        # Log AI Chat
        await log_activity(current_user, "AI Chat", "Calendar", f"Consulted AI Companion for {file_name} in {event.get('title')}")
        
        return {"answer": response.choices[0].message.content}
    except Exception as e:
        print(f"AI Chat Error: {e}")
        # Check if it's a quota issue
        if "insufficient_quota" in str(e):
             return {"answer": "I'm sorry, my AI processing unit (OpenAI) has run out of credits. Please contact your administrator to top up the OpenAI API quota.", "error": "insufficient_quota"}
        return {"answer": f"Error interacting with AI: {str(e)}"}

@router.patch("/{event_id}/complete")
async def complete_event(event_id: str, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    event, col_name = await find_event_across_collections(event_id)
    if not event: raise HTTPException(status_code=404, detail="Event not found")

    is_admin = current_user.get("role") == "superadmin"
    has_update_perm = current_user.get("permissions", {}).get("calendar", {}).get("update")
    is_creator = event.get("user_id") == str(current_user["_id"])

    # Only the owner may complete their todo.
    _require_todo_owner(event, current_user)

    if not (is_admin or has_update_perm or is_creator):
         raise HTTPException(status_code=403, detail="Not authorized")

    updates = {"status": "completed", "updated_at": datetime.utcnow()}
    if event.get("type") == TASK_TYPE:
        # This quick-action is a second door onto the same completion as PATCH
        # /tasks/{id}/status (tasks.py) — without the same checkpoint gate, it let a Task or
        # Delegation (recurring or one-time) be marked done here while its check points sat
        # unticked, and it never touched `workflow_status`, so the Task module kept showing
        # the task as still in progress. Both rules apply identically to every task, so no
        # recurring/one-time branch is needed.
        pending_items = [c for c in (event.get("checklist") or []) if not (isinstance(c, dict) and c.get("completed"))]
        if pending_items:
            done = len(event.get("checklist") or []) - len(pending_items)
            raise HTTPException(
                status_code=400,
                detail=f"Complete all check points before completing this task ({done}/{len(event.get('checklist') or [])} done).",
            )
        updates["workflow_status"] = "completed"
        updates["completed_at"] = datetime.utcnow()
        updates["completed_by"] = str(current_user["_id"])

    await get_collection(col_name).update_one({"_id": ObjectId(event_id)}, {"$set": updates})
    await sync_event_to_collection(event_id)

    # A completed todo notifies nobody — it is personal, and it has no attendees by design.
    if event.get("type") == TODO_TYPE:
        return {"message": "Todo marked as completed", "status": "completed"}

    # ─── Notify Attendees of Completion ───
    async def process_completion_emails():
        try:
            print(f"[DEBUG-TRACE-1] Starting completion mailing task for: {event_id}")
            member_ids = event.get("assigned_member_ids", [])
            coaches = event.get("coach_ids", [])
            target_ids = list(set(str(uid) for uid in (member_ids + coaches) if uid))
            
            print(f"[DEBUG-TRACE-2] Target IDs: {target_ids}")
            
            for uid in target_ids:
                try:
                    # Robust lookup across staff/learners collections
                    user = await find_user_by_id(uid)
                    if user:
                        print(f"[DEBUG-TRACE-3] Calling mail function for: {user.get('email')}")
                        await send_session_complete_email(user, event)
                        print(f"[DEBUG-TRACE-4] Mail function completed for: {user.get('email')}")
                    else:
                        print(f"[DEBUG-TRACE-ERR] User record not found for ID: {uid}")
                except Exception as mail_err:
                    print(f"[DEBUG-TRACE-ERR] Local mail error for {uid}: {mail_err}")
                    
        except Exception as e:
            print(f"[DEBUG-FATAL] Logic error in scheduler: {e}")

    background_tasks.add_task(process_completion_emails)
    
    return {"message": "Session marked as completed", "status": "completed"}

@router.post("/{event_id}/learner-upload")
async def learner_upload_content(event_id: str, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    event, col_name = await find_event_across_collections(event_id)
    if not event: raise HTTPException(status_code=404, detail="Session not found")
    
    # Upload to S3
    import io
    file_bytes = await file.read()
    s3_url = upload_file_to_s3(io.BytesIO(file_bytes), f"learners/{event_id}/{file.filename}", file.content_type)
    
    content_obj = {
        "id": str(datetime.utcnow().timestamp()),
        "name": file.filename,
        "url": s3_url,
        "type": file.content_type,
        "uploaded_by": str(current_user["_id"]),
        "uploader_name": current_user.get("full_name") or current_user.get("email"),
        "uploaded_at": datetime.utcnow().isoformat(),
        "company_id": current_user.get("company_id")
    }
    
    await get_collection(col_name).update_one(
        {"_id": ObjectId(event_id)},
        {"$push": {"learner_contents": content_obj}}
    )
    
    await log_activity(current_user, "Learner Upload", "Calendar", f"Uploaded {file.filename} to session {event.get('title')}")
    return {"message": "Content uploaded successfully", "content": content_obj}

@router.post("/{event_id}/track-join")
async def track_join_session(event_id: str, current_user: dict = Depends(get_current_user)):
    event, col_name = await find_event_across_collections(event_id)
    if not event: raise HTTPException(status_code=404, detail="Session not found")
    
    await log_activity(current_user, "Join Session", "Calendar", f"Joined virtual link for {event.get('title')}")
    return {"message": "Join activity logged"}


@router.delete("/{event_id}/resources/{resource_id}")
async def delete_resource(event_id: str, resource_id: str, current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")
    is_admin = current_user.get("role") in ["superadmin", "admin", "coach", "staff", "clientadmin"]
    has_update_perm = current_user.get("permissions", {}).get("calendar", {}).get("update")
    is_creator = existing.get("user_id") == str(current_user["_id"])

    if not (is_admin or has_update_perm or is_creator):
         raise HTTPException(status_code=403, detail="Not authorized to delete resources")
         
    await get_collection(col_name).update_one({"_id": ObjectId(event_id)}, {"$pull": {"resources": {"id": resource_id}}})
    return {"message": "Resource removed"}

@router.delete("/{event_id}/contents/{content_id}")
async def delete_content(event_id: str, content_id: str, current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")
    if current_user.get("role") not in ["superadmin", "admin", "coach", "staff", "clientadmin"] and existing.get("user_id") != str(current_user["_id"]):
         raise HTTPException(status_code=403, detail="Not authorized to delete content")
    await get_collection(col_name).update_one({"_id": ObjectId(event_id)}, {"$pull": {"contents": {"id": content_id}}})
    return {"message": "Content removed"}

# ─── Assessment Submission ───
@router.post("/{event_id}/assessments/{quiz_index}/submit")
async def submit_assessment(event_id: str, quiz_index: int, payload: dict, current_user: dict = Depends(get_current_user)):
    existing, col_name = await find_event_across_collections(event_id)
    if not existing: raise HTTPException(status_code=404, detail="Event not found")
    
    # Fetch original quiz data for reliable grading
    assessments = existing.get("assessments") or existing.get("quizzes") or []
    if not assessments and existing.get("session_template_id"):
        temp = await get_collection("session_templates").find_one({"_id": ObjectId(existing["session_template_id"])})
        if temp: 
            assessments = temp.get("assessments") or temp.get("quizzes") or []
    
    active_quiz = assessments[quiz_index] if quiz_index < len(assessments) else None
    if not active_quiz: raise HTTPException(status_code=404, detail="Assessment template not found")

    # Grade the submission
    graded_responses = []
    total_earned = 0
    total_available = 0

    # Identify which questions to grade (handling shuffle/limit from frontend)
    original_questions = active_quiz.get("questions", [])
    question_indices = payload.get("question_indices")

    if question_indices:
        questions_to_grade = []
        for idx in question_indices:
            if 0 <= idx < len(original_questions):
                questions_to_grade.append(original_questions[idx])
    else:
        questions_to_grade = original_questions

    for i, q in enumerate(questions_to_grade):
        user_answer = payload.get("answers", {}).get(str(i))
        q_type = q.get("type", "MCQ")
        q_marks = q.get("marks") or 1
        total_available += q_marks
        
        is_correct = False
        earned = 0
        feedback = ""

        if q_type == "MCQ":
            correct_idx = q.get("correct_option_index")
            if str(user_answer) == str(correct_idx):
                is_correct = True
                earned = q_marks
        else:
            # Descriptive AI Grading
            keywords = q.get("expected_keywords") or ""
            instructions = q.get("checker_instructions") or "Grade based on accuracy and completeness."
            ai_result = await grade_descriptive_answer(
                question=q.get("question_text"),
                user_answer=str(user_answer or ""),
                keywords=keywords,
                checker_instructions=instructions,
                max_marks=float(q_marks)
            )
            earned = ai_result.get("score", 0)
            feedback = ai_result.get("feedback", "")
            is_correct = earned >= (q_marks / 2) # Arbitrary threshold for 'correct' flag

        total_earned += earned
        graded_responses.append({
            "question": q.get("question_text"),
            "user_answer": user_answer,
            "is_correct": is_correct,
            "marks_earned": earned,
            "total_marks": q_marks,
            "feedback": feedback
        })

    percentage = (total_earned / total_available * 100) if total_available > 0 else 0
    passing_score = active_quiz.get("passing_score") or 50
    passed = percentage >= passing_score

    result_obj = {
        "id": str(ObjectId()),
        "user_id": str(current_user["_id"]),
        "user_name": current_user.get("full_name") or current_user.get("email"),
        "quiz_index": quiz_index,
        "session_id": event_id,
        "company_id": current_user.get("company_id"),
        "quiz_title": active_quiz.get("title"),
        "score": total_earned,
        "total_marks": total_available,
        "percentage": percentage,
        "passed": passed,
        "passing_score": passing_score,
        "responses": graded_responses,
        "submitted_at": datetime.now(timezone.utc)
    }
    
    # Store in the new dedicated collection
    await get_collection("LearnerAssessments").insert_one(result_obj)
    
    # Also keep a link in the session document for curriculum continuity
    await get_collection(col_name).update_one(
        {"_id": ObjectId(event_id)},
        {"$push": {"assessment_submissions": {
            "submission_id": result_obj["id"],
            "user_id": result_obj["user_id"],
            "percentage": result_obj["percentage"],
            "passed": result_obj["passed"]
        }}}
    )
    
    await log_activity(current_user, "Submit Assessment", col_name, f"Submitted quiz {quiz_index} for session {event_id}")
    
    # Stringify the auto-generated MongoDB _id for JSON serialization
    if "_id" in result_obj:
        result_obj["_id"] = str(result_obj["_id"])
        
    return {"message": "Assessment processed with AI grading", "result": result_obj}


@router.get("/assessments/submissions/{submission_id}")
async def get_assessment_submission(submission_id: str, current_user: dict = Depends(get_current_user)):
    col = get_collection("LearnerAssessments")
    submission = await col.find_one({"_id": ObjectId(submission_id)})
    if not submission:
        # Check legacy typo
        submission = await get_collection("LearnerAsessments").find_one({"_id": ObjectId(submission_id)})
        
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
        
    submission["_id"] = str(submission["_id"])
    return submission

@router.patch("/assessments/submissions/{submission_id}/marks")
async def update_submission_marks(submission_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    # payload: { "question_index": 0, "new_marks": 5 }
    if current_user.get("role") not in ["superadmin", "admin", "coach", "staff"]:
        raise HTTPException(status_code=403, detail="Only staff can modify marks")
        
    col = get_collection("LearnerAssessments")
    submission = await col.find_one({"_id": ObjectId(submission_id)})
    if not submission:
         raise HTTPException(status_code=404, detail="Submission not found")
         
    q_idx = payload.get("question_index")
    new_marks = float(payload.get("new_marks", 0))
    
    responses = submission.get("responses", [])
    if q_idx < 0 or q_idx >= len(responses):
        raise HTTPException(status_code=400, detail="Invalid question index")
        
    responses[q_idx]["marks_earned"] = new_marks
    responses[q_idx]["overwritten_by"] = str(current_user["_id"])
    responses[q_idx]["overwritten_by_name"] = current_user.get("full_name") or current_user.get("email")
    responses[q_idx]["overwritten_at"] = datetime.utcnow()
    responses[q_idx]["is_correct"] = new_marks >= (responses[q_idx].get("total_marks", 1) / 2)
    
    # Recalculate totals
    total_earned = sum(r.get("marks_earned", 0) for r in responses)
    total_available = sum(r.get("total_marks", 1) for r in responses)
    percentage = (total_earned / total_available * 100) if total_available > 0 else 0
    
    passing_score = submission.get("passing_score", 50)
    passed = percentage >= passing_score
    
    updates = {
        "responses": responses,
        "score": total_earned,
        "percentage": percentage,
        "passed": passed,
        "updated_at": datetime.utcnow(),
        "last_overwritten_by": current_user.get("full_name") or current_user.get("email")
    }
    
    await col.update_one({"_id": ObjectId(submission_id)}, {"$set": updates})
    
    # Sync status back to calendar event if linked
    event_id = submission.get("session_id")
    if event_id:
        existing, col_name = await find_event_across_collections(event_id)
        if existing:
            await get_collection(col_name).update_one(
                {"_id": ObjectId(event_id), "assessment_submissions.submission_id": str(submission_id)},
                {"$set": {
                    "assessment_submissions.$.percentage": percentage,
                    "assessment_submissions.$.passed": passed
                }}
            )
            
    await log_activity(current_user, "Edit Marks", "Assessment", f"Updated marks for {submission.get('user_name')} in {submission.get('quiz_title')}")
    
    return {"message": "Marks updated successfully", "new_score": total_earned, "new_percentage": percentage, "passed": passed}
