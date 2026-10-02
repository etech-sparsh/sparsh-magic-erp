"""
Time-driven task nudges — the triggers nobody's click can raise.

Every other Task & Delegation notification is the echo of an action: somebody assigned,
accepted, completed or reopened something. These four are the opposite — they fire because
time passed and nothing happened:

  · task_due_reminder_daily              every day until the task is done or its due date is
                                         reached, so an open task cannot be quietly forgotten
  · task_due_reminder_weekly             the lighter cadence for longer-lived work: every 7
                                         days, plus the due date itself whenever one is set
  · task_overdue                         once, the first sweep after a deadline is missed
  · task_verification_pending_reminder   every ALTERNATE day while a task sits in
                                         verification, chasing the assigner to close it out

Design notes:

SILENT BY DEFAULT. Same rule as the rest of Task & Delegation: no Active template for the
slug means no email/WhatsApp. Nothing here is seeded, so a deploy cannot start nagging anyone
— an admin turns each cadence on deliberately, in Task Management ▸ Templates.

ONE MESSAGE PER CADENCE PER DAY. Every send stamps `nudge_state.<slug>` on the task with the
IST date it went out, and that stamp is what the next sweep reads. So a restart, a double tick
or a manual re-run cannot produce a second copy, and a cadence that was missed during downtime
resumes rather than firing once per day it was down.

IST THROUGHOUT. "Which day is it" and "has the deadline passed" are business questions, and
this product's business day is Indian Standard Time — the same boundary the recurrence engine
and the todo sweep already use.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.db.mongodb import get_collection
from app.services.task_notifications import notify_task_event
from app.utils.calendar_utils import CALENDAR_COLLECTIONS

logger = logging.getLogger(__name__)

TASK_COLLECTIONS = CALENDAR_COLLECTIONS + ["calendar_events"]

IST = timezone(timedelta(hours=5, minutes=30))

# Where each cadence records the date it last fired, per task.
STATE_FIELD = "nudge_state"

# Event keys (task_notifications.TASK_EVENT_SLUGS maps these to their template slugs).
DAILY = "due_reminder_daily"
WEEKLY = "due_reminder_weekly"
OVERDUE = "overdue"
VERIFICATION_PENDING = "verification_pending"

WEEKLY_INTERVAL_DAYS = 7
VERIFICATION_INTERVAL_DAYS = 2      # "every alternate day"

# A task in one of these states is finished business and is never nudged about.
TERMINAL_STATUSES = {"completed"}

# The sweep is a safety net, not an archive crawler. Overdue alerts are only raised for
# deadlines missed inside this window, so a gap in the sweep (downtime, a stopped worker) still
# alerts on what was missed while it was down, but a task that went overdue long before that is
# history and re-announcing it helps nobody.
OVERDUE_LOOKBACK_DAYS = 7

# One-time marker recording that the pre-existing overdue backlog has been absorbed.
#
# "Trigger when the due date is missed" means at the moment it is missed — not a retroactive
# audit of everything already late. On the very first sweep the ERP's open tasks were 94% past
# their deadline (median 71 days), so without this the first run would fire hundreds of alerts
# about work nobody is tracking, and the trigger would arrive discredited. The backfill stamps
# every already-overdue task as alerted WITHOUT sending, so only deadlines missed from that
# point on ever raise one.
BACKFILL_FLAG = "task_nudge_overdue_backfilled"
SETTINGS_COLLECTION = "system_settings"

# ─────────────────────────────────────────────────────────────
# When the sweep runs.
#
# ONCE A DAY, IN THE MORNING. A reminder that lands at 3 AM has been read and dismissed before
# the working day starts, so the sweep fires at 10:00 IST by default — early enough to shape
# the day, late enough that people are at their desks. The hour is stored, not hard-coded, so
# an admin can move it from Task Management ▸ Templates without a deploy.
#
# The gate is "at or after" rather than "exactly at": if the worker is restarted, busy, or was
# down at 10:00, the sweep still runs on the next tick that day instead of being skipped
# altogether. Combined with the once-per-day stamp, that means late but never twice.
# ─────────────────────────────────────────────────────────────
SEND_TIME_KEY = "task_nudge_send_time"
DEFAULT_SEND_HOUR = 10
DEFAULT_SEND_MINUTE = 0


def _clamp_time(hour, minute) -> tuple:
    """(hour, minute) coerced into a real clock time, or the default when it is not one."""
    try:
        hour, minute = int(hour), int(minute)
    except (TypeError, ValueError):
        return DEFAULT_SEND_HOUR, DEFAULT_SEND_MINUTE
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return DEFAULT_SEND_HOUR, DEFAULT_SEND_MINUTE
    return hour, minute


async def get_send_time() -> tuple:
    """The IST (hour, minute) the daily sweep runs at. Defaults to 10:00 when never set."""
    try:
        doc = await get_collection(SETTINGS_COLLECTION).find_one({"key": SEND_TIME_KEY})
    except Exception as e:
        logger.error(f"Task nudge: could not read the send time, using the default: {e}")
        return DEFAULT_SEND_HOUR, DEFAULT_SEND_MINUTE
    if not doc:
        return DEFAULT_SEND_HOUR, DEFAULT_SEND_MINUTE
    return _clamp_time(doc.get("hour"), doc.get("minute"))


async def set_send_time(hour, minute=0, actor: Optional[str] = None) -> tuple:
    """Move the daily sweep to a different IST time. Returns the stored (hour, minute)."""
    hour, minute = int(hour), int(minute)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("hour must be 0-23 and minute 0-59")
    await get_collection(SETTINGS_COLLECTION).update_one(
        {"key": SEND_TIME_KEY},
        {"$set": {"key": SEND_TIME_KEY, "hour": hour, "minute": minute,
                  "updated_at": datetime.now(timezone.utc), "updated_by": actor or ""}},
        upsert=True)
    return hour, minute


async def is_send_time(now: Optional[datetime] = None) -> bool:
    """Whether the configured send time has arrived (or passed) today, in IST."""
    ist = (now or datetime.now(timezone.utc)).astimezone(IST)
    hour, minute = await get_send_time()
    return (ist.hour, ist.minute) >= (hour, minute)

# The sweep runs on a synthetic actor. notify_task_event strips the ACTOR from every recipient
# set so nobody is told about their own action — but a nudge has no author, and the assigner
# chasing a verification must not be filtered out of their own reminder. An actor with no id
# matches nobody, which keeps the recipient list exactly as computed.
_SYSTEM_ACTOR = {"_id": "", "full_name": "Sparsh"}


def _parse(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _ist_date(dt: datetime) -> date:
    return dt.astimezone(IST).date()


def due_date_of(task: dict) -> Optional[date]:
    """The IST calendar day a task is due. `end` is the deadline; `start` is the fallback for
    older docs saved before tasks carried an end."""
    dt = _parse(task.get("end") or task.get("start"))
    return _ist_date(dt) if dt else None


def _last_sent(task: dict, event: str) -> Optional[date]:
    raw = (task.get(STATE_FIELD) or {}).get(event)
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def is_open(task: dict) -> bool:
    """Still live work: a task, not deleted, not completed."""
    if task.get("type") != "task" or task.get("deleted_at"):
        return False
    if task.get("workflow_status") in TERMINAL_STATUSES:
        return False
    # A doc predating workflow_status falls back to the legacy calendar status.
    return task.get("status") != "completed"


def due_events(task: dict, today: date) -> list:
    """Which due-date cadences this task is owed today, with their template context.

    Returns [(event, extra)] — usually empty, at most one entry per cadence. Reading it as a
    pure function of (task, today) is what makes the whole sweep testable without a database.
    """
    out = []
    due = due_date_of(task)

    # ── Daily: every day up to and INCLUDING the due date. "Until the due date is reached"
    #    stops here; from the day after, the overdue alert takes over so the two never
    #    double up on the same task on the same day.
    if due and today <= due and _last_sent(task, DAILY) != today:
        out.append((DAILY, {"days_remaining": (due - today).days}))

    # ── Weekly: every 7 days while the task is open, PLUS the due date itself when one is
    #    set ("weekly, or as per the task due date"). A task with no due date still gets the
    #    weekly beat — it is exactly the task most likely to drift.
    last_weekly = _last_sent(task, WEEKLY)
    if not due or today <= due:
        on_due_date = bool(due) and today == due
        due_for_beat = last_weekly is None or (today - last_weekly).days >= WEEKLY_INTERVAL_DAYS
        if (on_due_date or due_for_beat) and last_weekly != today:
            out.append((WEEKLY, {"days_remaining": (due - today).days if due else 0}))

    # ── Overdue: once, on the first sweep after the deadline passes.
    if due and today > due and _last_sent(task, OVERDUE) is None:
        overdue_by = (today - due).days
        if overdue_by <= OVERDUE_LOOKBACK_DAYS:
            out.append((OVERDUE, {"days_overdue": overdue_by}))

    return out


def verification_event(task: dict, today: date) -> Optional[tuple]:
    """The alternate-day chase, when this task is sitting in verification.

    The doer has finished and asked for sign-off; until the assigner closes it the work is done
    but not banked. The cadence is measured from the last nudge rather than from the moment it
    entered verification, so it stays every-other-day however long the wait runs on.
    """
    if task.get("workflow_status") != "verification":
        return None
    last = _last_sent(task, VERIFICATION_PENDING)
    if last is not None and (today - last).days < VERIFICATION_INTERVAL_DAYS:
        return None
    if last == today:
        return None
    return (VERIFICATION_PENDING, {})


async def _stamp(col_name: str, task_id, event: str, today: date) -> None:
    """Record that `event` fired for this task today, BEFORE the send is attempted.

    Deliberately written first: a notification that fails is logged and lost, but a stamp that
    was never written would make the next tick — sixty seconds later — try the whole cadence
    again. Nagging a user every minute because their mail server is down is far worse than
    missing one day of a reminder.
    """
    await get_collection(col_name).update_one(
        {"_id": task_id}, {"$set": {f"{STATE_FIELD}.{event}": today.isoformat()}})


async def absorb_overdue_backlog(today: date) -> int:
    """First run only: mark every task that is ALREADY overdue as alerted, sending nothing.

    Idempotent via a marker document — once the backlog is absorbed this returns 0 immediately
    and costs one indexed lookup per sweep. Returns how many tasks were stamped.
    """
    settings = get_collection(SETTINGS_COLLECTION)
    if await settings.find_one({"key": BACKFILL_FLAG}):
        return 0

    stamped = 0
    for col_name in TASK_COLLECTIONS:
        col = get_collection(col_name)
        try:
            tasks = await col.find({
                "type": "task", "deleted_at": None,
                "workflow_status": {"$nin": list(TERMINAL_STATUSES)},
            }).to_list(20000)
        except Exception as e:
            logger.error(f"Overdue backfill: could not read {col_name}: {e}")
            continue
        for task in tasks:
            if not is_open(task):
                continue
            due = due_date_of(task)
            if due and today > due and _last_sent(task, OVERDUE) is None:
                await _stamp(col_name, task["_id"], OVERDUE, today)
                stamped += 1

    await settings.insert_one({
        "key": BACKFILL_FLAG, "value": True,
        "tasks_stamped": stamped, "absorbed_on": today.isoformat(),
        "created_at": datetime.now(timezone.utc),
    })
    logger.info(f"Task nudge: absorbed {stamped} already-overdue task(s) without alerting. "
                "Overdue alerts now fire only for deadlines missed from here on.")
    return stamped


async def sweep_task_nudges() -> dict:
    """One pass over every open task, raising whichever time-driven triggers are due.

    Returns a per-event count. Never raises: this runs inside the reminder scheduler, and a
    failure here must not stop the reminders and recurrence rollovers that share its loop.
    """
    today = _ist_date(datetime.now(timezone.utc))
    counts = {DAILY: 0, WEEKLY: 0, OVERDUE: 0, VERIFICATION_PENDING: 0}

    # Runs before anything is raised, so the very first sweep cannot alert on the backlog.
    try:
        await absorb_overdue_backlog(today)
    except Exception as e:
        # If the backfill fails, do NOT go on to sweep: that is precisely the run that would
        # mail the whole backlog. Skipping a day costs nothing by comparison.
        logger.error(f"Task nudge: overdue backfill failed, skipping this sweep: {e}")
        return counts

    for col_name in TASK_COLLECTIONS:
        col = get_collection(col_name)
        try:
            tasks = await col.find({
                "type": "task",
                "deleted_at": None,
                "workflow_status": {"$nin": list(TERMINAL_STATUSES)},
            }).to_list(20000)
        except Exception as e:
            logger.error(f"Task nudge sweep: could not read {col_name}: {e}")
            continue

        for task in tasks:
            if not is_open(task):
                continue
            events = due_events(task, today)
            pending = verification_event(task, today)
            if pending:
                events.append(pending)
            for event, extra in events:
                try:
                    await _stamp(col_name, task["_id"], event, today)
                    await notify_task_event(event, task, _SYSTEM_ACTOR, extra)
                    counts[event] += 1
                except Exception as e:
                    # One bad task must not end the sweep for every other task.
                    logger.error(f"Task nudge '{event}' failed for {task.get('_id')}: {e}")

    if any(counts.values()):
        logger.info("Task nudge sweep: " + ", ".join(f"{k}={v}" for k, v in counts.items() if v))
    return counts
