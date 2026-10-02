"""
Personal-todo due-date sweep — Pending → Overdue.

A todo has no delegation workflow, only a `status`: "schedule" (shown as Pending), "completed",
and now "overdue". A todo is due at 23:59:59 IST on its own calendar day (see
calendar_events._apply_todo_due_end_of_day), and once that instant has passed an untouched todo
is no longer merely pending — it was missed. This sweep is what makes that transition happen on
its own, with no user action.

It runs on every 60-second tick of the reminder scheduler rather than nightly, so a todo flips
to Overdue within a minute of its deadline instead of at the next midnight. The move is
persisted, not derived at render time, so server-side counts, filters and reports all agree
with what the calendar shows.

Only "schedule" → "overdue" is ever written: a completed todo is finished business, and a todo
whose due date is pushed into the future is reset back to Pending by the update route, not
here.
"""
from datetime import datetime, timezone
import logging

from app.db.mongodb import get_collection
from app.utils.calendar_utils import CALENDAR_COLLECTIONS

logger = logging.getLogger(__name__)

TODO_COLLECTIONS = CALENDAR_COLLECTIONS + ["calendar_events"]

# Kept as local constants rather than imported from the calendar_events route module, so this
# service has no dependency on the API layer (the route imports this direction, not the other).
TODO_TYPE = "todo"
TODO_PENDING = "schedule"   # the stored value the UI labels "Pending"
TODO_OVERDUE = "overdue"


def _parse(v):
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def todo_due_instant(doc: dict):
    """The moment a todo is due, as a tz-aware datetime.

    `end` is the deadline for a todo (the same field the reminder scheduler anchors to — see
    reminder_scheduler.get_reminder_anchor); `start` is only a fallback for older docs saved
    before todos carried an end.
    """
    return _parse(doc.get("end") or doc.get("start"))


def is_todo_overdue(doc: dict, now=None) -> bool:
    """True when this pending todo's due instant has already passed."""
    due = todo_due_instant(doc)
    if not due:
        return False
    return due < (now or datetime.now(timezone.utc))


async def mark_overdue_todos() -> int:
    """Flip every pending todo whose due date/time has passed to Overdue. Returns the count.

    Due dates are compared in Python rather than in the query: `start`/`end` are stored as ISO
    STRINGS, and a lexicographic `$lt` would silently misjudge any legacy doc written with a
    "Z" suffix instead of "+00:00" ('Z' sorts after '+'). The candidate set is only the pending
    todos, which is small, so parsing them is cheap and always correct.
    """
    now = datetime.now(timezone.utc)
    total = 0

    for col_name in TODO_COLLECTIONS:
        col = get_collection(col_name)
        candidates = await col.find(
            {"type": TODO_TYPE, "status": TODO_PENDING, "deleted_at": None},
            {"_id": 1, "start": 1, "end": 1},
        ).to_list(20000)

        due_ids = [d["_id"] for d in candidates if is_todo_overdue(d, now)]
        if not due_ids:
            continue

        res = await col.update_many(
            {"_id": {"$in": due_ids}, "status": TODO_PENDING},
            {"$set": {"status": TODO_OVERDUE, "updated_at": now}},
        )
        total += res.modified_count

    if total:
        logger.info(f"Todo status sweep: marked {total} pending todo(s) as overdue.")
    return total
