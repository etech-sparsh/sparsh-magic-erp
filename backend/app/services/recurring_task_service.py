"""
Recurring task engine — nightly rollover, plus the shared occurrence builder.

Recurring TASKS (repeat = Daily / Weekly / Monthly / Annually / Custom …) are created as a
single first occurrence at creation time (see calendar_events.create_event). The nightly job
below, run once per day at/after midnight by the reminder scheduler, creates the NEXT
occurrence for each active series whose date has arrived — catching up any missed days — so
there is exactly one task per period, never a bulk dump of duplicates.

Personal TODOS do NOT roll forward nightly. A repeating todo is generated in full at creation
time, every occurrence up to its Repeat End Date at once (see build_series_occurrences and
calendar_events.create_event), so the whole series is visible on the calendar the moment it is
saved. The cadence stepping and anti-drift anchors are shared with the nightly engine — both go
through _next_occurrence and _fresh_occurrence.

Where a todo deliberately differs from a task is OFF-DAYS: a todo that falls on a holiday or a
weekly off is skipped outright, never shifted onto another day, whatever its cadence. A task
shifts instead, because the work is still owed to someone. See drops_off_days.

Recurring sessions/events keep their own bulk-generation behaviour in calendar_events.
"""
from datetime import datetime, timezone, timedelta
import logging

from app.db.mongodb import get_collection
from app.utils.calendar_utils import CALENDAR_COLLECTIONS

logger = logging.getLogger(__name__)

TASK_COLLECTIONS = CALENDAR_COLLECTIONS + ["calendar_events"]

# Document types the NIGHTLY job rolls forward. Tasks only: a repeating todo is generated in
# full at creation time instead (build_series_occurrences), so rolling it nightly here would
# only re-walk a series that already exists.
RECURRING_TYPES = ["task"]

# Ceilings for a single up-front series build. Occurrences is the number of documents written;
# steps is the number of cadence hops taken to find them (higher, because off-days are stepped
# over without producing a document). Both exist purely so an absurd end date — or a malformed
# cadence that never advances — cannot write an unbounded number of rows.
MAX_SERIES_OCCURRENCES = 365
MAX_SERIES_STEPS = 800

# The product runs on Indian Standard Time (UTC+5:30). Every "which day is it / has this
# occurrence's day arrived" decision below is made in IST, so the next occurrence is created
# at 12:00 AM IST (local midnight), not at 00:00 UTC (which is 5:30 AM IST). The scheduler that
# calls this job flips its day counter on the same IST boundary (see reminder_scheduler).
IST = timezone(timedelta(hours=5, minutes=30))


def _ist_date(dt):
    """The calendar date of a tz-aware datetime as seen in IST."""
    return dt.astimezone(IST).date()

# Weekly off day(s) — recurring occurrences never land here, matching the task due-date
# picker which blocks the same day. Python date.weekday(): Mon=0 … Sun=6, so {6} == Sunday.
# (There is no persisted per-user weekly-off setting in the backend yet — see the picker's
# WEEKLY_OFFS on the frontend.)
WEEKLY_OFF_WEEKDAYS = {6}


def _is_off_day(dt, holiday_dates) -> bool:
    """A date the task must never land on: a holiday or a weekly off (Sunday). Judged in IST
    so the day/weekday matches the date the user actually picked."""
    ist = dt.astimezone(IST)
    return ist.date().isoformat() in holiday_dates or ist.weekday() in WEEKLY_OFF_WEEKDAYS


def _steps_by_single_day(repeat_type, interval) -> bool:
    """True when consecutive occurrences are exactly one day apart (Daily, or an
    every-1-day periodic). For these, an off-day is simply dropped — the following day is
    its own occurrence, so shifting would collide with it. Every other cadence
    (Weekly/Monthly/Annually/Custom/periodic-N) instead shifts to the next working day so the
    period is never lost."""
    return repeat_type == "Daily" or (repeat_type == "periodic" and (interval or 1) == 1)


def drops_off_days(doc_type, repeat_type, interval) -> bool:
    """Whether an occurrence landing on an off-day is DROPPED (no todo/task that day at all)
    rather than shifted forward onto the next working day.

    TODOS always drop. A personal todo is a note-to-self for a specific day; if that day is a
    holiday or a weekly off there is nobody working, so the todo simply does not exist for that
    period — it is not moved onto a day the user never chose. This holds for every cadence: a
    monthly-15th todo whose 15th is a holiday produces nothing that month, and resumes on the
    15th of the next.

    TASKS keep the delegation rule, which depends on the cadence: a daily-style task drops the
    day (the next day is its own occurrence, so shifting would collide with it), while a
    weekly/monthly/annual/custom task shifts, because dropping would lose the whole period of
    work — a task is owed to someone else and still has to be done.
    """
    if doc_type == "todo":
        return True
    return _steps_by_single_day(repeat_type, interval)


def _shift_to_working_day(dt, holiday_dates, max_shift=14):
    """Move forward from an off-day to the next holiday-free, non-weekly-off day."""
    shifted = dt
    for _ in range(max_shift):
        if not _is_off_day(shifted, holiday_dates):
            return shifted
        shifted = shifted + timedelta(days=1)
    return None  # unusually long off-day streak — give up rather than loop forever


def _parse(v):
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def load_holiday_dates() -> set:
    """All active holiday dates as a set of ISO 'YYYY-MM-DD' strings.

    Same master source (collection "holidays") the Holiday module and the task
    due-date picker use, so a date marked as a holiday in one place is skipped here too.
    Inactive holidays are ignored.
    """
    col = get_collection("holidays")
    docs = await col.find({"status": {"$ne": "inactive"}}, {"holiday_date": 1}).to_list(5000)
    return {d.get("holiday_date") for d in docs if d.get("holiday_date")}


def _series_anchor_day(head: dict):
    """The series' intended day-of-month, carried forward on every occurrence. Without it a
    month too short to hold the date would pull the series down permanently (Jan 31 → Feb 28 →
    Mar 28 → …). `recurrence_day` is stamped on each generated occurrence; the FIRST occurrence
    predates it, so fall back to its own start day — the day the user actually picked, which
    was never clamped."""
    day = head.get("recurrence_day")
    if day:
        return day
    first = _parse(head.get("start"))
    return first.day if first else None


def _fresh_occurrence(head: dict, target, natural, anchor_day) -> dict:
    """A new occurrence cloned from `head`, due on `target`.

    `natural` is the UNSHIFTED date this occurrence was computed for; it is stored as
    `recurrence_anchor` so the next period is always measured from the cadence's own date even
    when this one was pushed off a holiday / weekly off. Without it a single shift would drag
    the rest of the series forward permanently.

    A fresh occurrence must not inherit the previous period's work: the checklist comes back
    unticked and remarks / attachments / status history / completion start empty, with the
    reminders re-armed for the new date.
    """
    doc = {k: v for k, v in head.items() if k not in ("_id", "id")}
    doc["start"] = target.isoformat()
    doc["recurrence_anchor"] = natural.isoformat()
    if anchor_day:
        doc["recurrence_day"] = anchor_day
    # A Recurring Checklist has no deadline: every occurrence is live for its OWN calendar
    # day and closes at 23:59:59 IST.
    #
    # Computed from the target date rather than carried forward as a start→end offset. A
    # series created before that rule still holds a real deadline on its head — often weeks
    # out — and the offset would clone that gap onto every occurrence forever, so the
    # checklist generated tonight would be "due" a month from now. Deriving it here fixes
    # those series from their next occurrence on, without rewriting a single stored row.
    #
    # Stored in UTC: Task & Delegation reads `end` with a parser that drops the offset
    # without converting (tasks._parse_iso), so an IST-marked string would read 5h30m late.
    orig_end, orig_start = _parse(head.get("end")), _parse(head.get("start"))
    if head.get("type") == "task" and str(head.get("repeat") or "").strip() not in ("", "Does not repeat"):
        close_ist = target.astimezone(IST).replace(hour=23, minute=59, second=59, microsecond=0)
        doc["end"] = close_ist.astimezone(timezone.utc).isoformat()
    elif orig_end and orig_start:
        # Preserve the original start→end offset (zero for a todo, which keeps start == end).
        doc["end"] = (target + (orig_end - orig_start)).isoformat()
    doc["created_at"] = datetime.utcnow()
    doc["updated_at"] = None
    if head.get("type") == "task":
        # Delegation workflow state — a todo has no workflow, only status.
        doc["workflow_status"] = "in_progress"  # new occurrences start In Progress
    doc["status"] = "schedule"
    doc["completed_at"] = None
    doc["completed_by"] = None
    doc["deleted_at"] = None
    if head.get("checklist"):
        doc["checklist"] = [{**c, "completed": False} for c in head["checklist"]]
    doc["remarks"] = []
    doc["attachments"] = []
    doc["status_history"] = []
    # A fresh occurrence must not inherit a still-open "Dependent on Other" hand-off from the
    # occurrence it was cloned from — `head` is simply the latest occurrence by date, picked
    # with no regard to whether its dependency chain had unwound yet. Left alone, the next
    # occurrence opened with the doer still on `target_staff_id`/`dependency_doer_id`, which
    # froze or narrowed their status dropdown for a period that was never actually delegated to
    # them. The bottom of `dependency_stack` is the ORIGINAL assignee set from before any
    # hand-off, so a new period starts there — the doer and every intermediate hand-off end
    # with the period they were raised in, not the next one.
    stack = head.get("dependency_stack") or []
    if stack:
        original = stack[0]
        doc["target_staff_id"] = original.get("assignee_ids") or []
        doc["assigned_to"] = original.get("assigned_to") or "other"
    doc["dependency_doer_id"] = None
    doc["dependency_stack"] = []
    if head.get("reminders"):
        doc["reminders"] = [{**r, "sent": False} for r in head["reminders"]]
    return doc


async def build_series_occurrences(head: dict, end_dt, holiday_dates=None, taken_dates=None):
    """Every occurrence AFTER `head`, up to and including `end_dt` — the whole series at once.

    This is the up-front counterpart to the nightly rollover: same cadence steps, same
    anti-drift anchors, same per-occurrence reset, and the same off-day policy (drops_off_days —
    a todo skips holidays and weekly offs entirely). Used to generate a repeating personal todo
    in full the moment it is saved, and to extend a series when its Repeat End Date is pushed
    out.

    `head` is the first occurrence (it is NOT included in the result). `taken_dates` is a set of
    ISO 'YYYY-MM-DD' strings already occupied by this series, so an extension can never
    duplicate a date that exists.

    Returns (occurrences, truncated) — `truncated` is True when MAX_SERIES_OCCURRENCES capped
    the build, so the caller can tell the user the series was cut short rather than silently
    delivering fewer dates than they asked for.
    """
    # Lazy import avoids any import-order coupling with the calendar_events route module.
    from app.routes.calendar_events import _next_occurrence

    repeat_type = head.get("repeat")
    curr = _parse(head.get("recurrence_anchor") or head.get("start"))
    if not curr or not end_dt or not repeat_type or repeat_type in (None, "", "Does not repeat"):
        return [], False

    if holiday_dates is None:
        holiday_dates = await load_holiday_dates()

    interval = head.get("repeat_interval", 1) or 1
    anchor_day = _series_anchor_day(head)

    # The head's own date is occupied — a shifted occurrence must never collide with it.
    seen = set(taken_dates or ())
    head_start = _parse(head.get("start"))
    if head_start:
        seen.add(_ist_date(head_start).isoformat())

    occurrences, truncated = [], False
    for _ in range(MAX_SERIES_STEPS):
        try:
            nxt = _next_occurrence(curr, repeat_type, interval, head.get("repeat_data"), anchor_day)
        except Exception as e:
            logger.error(f"Recurrence step failed while building series ({repeat_type}): {e}")
            break
        if nxt is None:
            break
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        if _ist_date(nxt) > _ist_date(end_dt):
            break

        # Off-day handling, shared with the nightly engine — see drops_off_days. For a todo
        # that means: a holiday or weekly off produces NO occurrence at all, whatever the
        # cadence. The series just resumes at its next natural date.
        target = nxt
        if _is_off_day(nxt, holiday_dates):
            if drops_off_days(head.get("type"), repeat_type, interval):
                curr = nxt
                continue
            shifted = _shift_to_working_day(nxt, holiday_dates)
            if shifted is None or _ist_date(shifted) > _ist_date(end_dt):
                curr = nxt
                continue
            target = shifted

        day = _ist_date(target).isoformat()
        if day not in seen:
            seen.add(day)
            occurrences.append(_fresh_occurrence(head, target, nxt, anchor_day))
            if len(occurrences) >= MAX_SERIES_OCCURRENCES:
                truncated = True
                break
        curr = nxt

    return occurrences, truncated


async def generate_due_recurring_tasks():
    # Lazy import avoids any import-order coupling with the calendar_events route module.
    from app.routes.calendar_events import _next_occurrence

    from app.services.checklist_notifications import (
        SERIES_DONE_FLAG, notify_occurrence_created, notify_series_completed,
    )

    now = datetime.now(timezone.utc)
    today = _ist_date(now)  # "today" in IST — the boundary the next occurrence is created on
    created = 0
    notified = 0
    skipped_holidays = 0
    skipped_weekly_offs = 0
    shifted_occurrences = 0

    # Repeat tasks must not trigger on holidays — load the holiday set once for this run.
    holiday_dates = await load_holiday_dates()

    for col_name in TASK_COLLECTIONS:
        col = get_collection(col_name)
        docs = await col.find({
            "type": {"$in": RECURRING_TYPES},
            "recurring_group_id": {"$ne": None},
            "repeat": {"$nin": [None, "", "Does not repeat"]},
            "deleted_at": None,
        }).to_list(10000)

        # Keep only the latest occurrence per series (by start).
        latest = {}
        for d in docs:
            gid = d.get("recurring_group_id")
            if not gid:
                continue
            if gid not in latest or (d.get("start") or "") > (latest[gid].get("start") or ""):
                latest[gid] = d

        for gid, head in latest.items():
            repeat_type = head.get("repeat")
            interval = head.get("repeat_interval", 1) or 1
            end_dt = _parse(head.get("repeat_end_date"))
            # Advance from the NATURAL (unshifted) date of the latest occurrence, never its
            # stored `start`. When an occurrence is shifted off a holiday/weekly-off (e.g. the
            # 15th → the 16th), its `start` is the shifted date; computing the next period from
            # that would drift the whole series forward permanently. `recurrence_anchor` holds
            # the natural date for exactly this reason. Fall back to `start` for the first
            # occurrence (created by calendar_events.create_event) and legacy docs, which have
            # no anchor and were never shifted.
            curr = _parse(head.get("recurrence_anchor") or head.get("start"))
            if not curr:
                continue
            anchor_day = _series_anchor_day(head)

            guard = 0
            while guard < 400:
                guard += 1
                try:
                    nxt = _next_occurrence(curr, repeat_type, interval,
                                           head.get("repeat_data"), anchor_day)
                except Exception as e:
                    # One malformed series must not abort the nightly run for every other
                    # series — the outer handler would have swallowed the whole job.
                    logger.error(f"Recurrence step failed for series {gid} ({repeat_type}): {e}")
                    break
                if nxt is None:
                    break
                if nxt.tzinfo is None:
                    nxt = nxt.replace(tzinfo=timezone.utc)
                if end_dt and _ist_date(nxt) > _ist_date(end_dt):
                    # The cadence has stepped past the Repeat End Date: this series is finished
                    # and will never generate again. Announce it ONCE — the flag is what stops
                    # the nightly run re-announcing every finished series every night — and only
                    # after the end date has actually passed, so a series whose last occurrence
                    # is still ahead of us is not declared over early.
                    if not head.get(SERIES_DONE_FLAG) and _ist_date(end_dt) <= today:
                        total = await col.count_documents({"recurring_group_id": gid,
                                                           "deleted_at": None})
                        notified += await notify_series_completed(head, total)
                        await col.update_many({"recurring_group_id": gid},
                                              {"$set": {SERIES_DONE_FLAG: True}})
                    break
                if _ist_date(nxt) > today:
                    break  # future occurrence — created at 12 AM IST on its own day
                # An off-day (holiday or weekly off) must never hold a task — drop it or shift
                # it forward per drops_off_days:
                #   • Daily-style (1-day step): drop that day — the next day is its own
                #     occurrence, so shifting would collide with it. e.g. a daily 1–10 Aug task
                #     with 3 & 7 Aug holidays generates every day except 3 & 7 Aug.
                #   • Weekly / Monthly / Annually / Custom: shift the occurrence forward to the
                #     next working day so the whole week/month is not lost. e.g. a monthly-15th
                #     task whose 15th is a Sunday generates on Mon the 16th instead.
                target = nxt
                if _is_off_day(nxt, holiday_dates):
                    if drops_off_days(head.get("type"), repeat_type, interval):
                        if _ist_date(nxt).isoformat() in holiday_dates:
                            skipped_holidays += 1
                        else:
                            skipped_weekly_offs += 1
                        curr = nxt
                        continue
                    shifted = _shift_to_working_day(nxt, holiday_dates)
                    if shifted is None or (end_dt and _ist_date(shifted) > _ist_date(end_dt)):
                        curr = nxt
                        continue
                    if _ist_date(shifted) > today:
                        break  # shifted target hasn't arrived yet — created on its own day
                    shifted_occurrences += 1
                    target = shifted
                # Skip if an occurrence already exists for that date in this series.
                day_prefix = target.date().isoformat()
                exists = await col.find_one({"recurring_group_id": gid, "start": {"$regex": f"^{day_prefix}"}})
                if not exists:
                    # Same builder the up-front series generator uses, so a rolled-forward
                    # occurrence and a bulk-generated one are byte-for-byte the same shape.
                    occurrence = _fresh_occurrence(head, target, nxt, anchor_day)
                    result = await col.insert_one(occurrence)
                    created += 1
                    # Tell the doers a new period of work exists. Until now this job created
                    # tasks in total silence — the occurrence simply appeared on someone's list
                    # overnight with nothing to announce it. Silent unless an admin has made an
                    # Active "Repeat Task Generated" template (see checklist_notifications), so
                    # this cannot start mailing anyone on its own.
                    occurrence["_id"] = result.inserted_id
                    notified += await notify_occurrence_created(occurrence)
                curr = nxt

    if created or skipped_holidays or skipped_weekly_offs or shifted_occurrences:
        logger.info(
            f"Recurring engine: created {created} task/todo occurrence(s); "
            f"skipped {skipped_holidays} holiday and {skipped_weekly_offs} weekly-off date(s); "
            f"shifted {shifted_occurrences} occurrence(s) to the next working day; "
            f"notified {notified} recipient(s)."
        )
    return created
