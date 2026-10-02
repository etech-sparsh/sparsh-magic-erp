"""Recurring Checklist validator - Task & Delegation.

A task with Repeat ON is a Recurring Checklist: it carries NO deadline, it renews itself at
12:00 AM, each occurrence is live for its own calendar day, and an occurrence not finished by
11:59 PM IST becomes OVERDUE - it is never expired or removed. A task with Repeat OFF is a
one-time task and keeps the deadline the user set.

Pure functions only: no database is opened, no document is read or written, no email is sent.
Safe to run at any time.

Usage (from backend/):
    python scripts/validate_recurring_checklist.py
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routes.calendar_events import (
    is_recurring_task, _apply_recurring_task_day_window, _next_occurrence)
from app.services.recurring_task_service import _fresh_occurrence, IST
from app.routes.tasks import _is_overdue, _completion_timing


def ist_close(iso):
    """The stored UTC end, read back as IST wall-clock."""
    return datetime.fromisoformat(iso).astimezone(IST).isoformat()


def utc_naive(ist_dt):
    """The naive-UTC clock tasks.py compares against."""
    return ist_dt.astimezone(timezone.utc).replace(tzinfo=None)

P, F = [], []


def ok(label, cond, detail=""):
    (P if cond else F).append(label)
    print(("  [PASS] " if cond else "  [FAIL] ") + label + (("  -> " + str(detail)) if detail else ""))


print("1. WHAT COUNTS AS A RECURRING CHECKLIST")
ok("a repeating task does", is_recurring_task({"type": "task", "repeat": "Daily"}))
ok("a one-time task does not", not is_recurring_task({"type": "task", "repeat": "Does not repeat"}))
ok("a blank repeat does not", not is_recurring_task({"type": "task", "repeat": ""}))
ok("a todo is untouched", not is_recurring_task({"type": "todo", "repeat": "Daily"}))

print("\n2. NO DEADLINE — the day is the window")
head = {"type": "task", "repeat": "Daily", "start": "2026-08-22T09:00:00+05:30",
        "end": "2026-09-30T17:00:00+05:30"}          # user tried to set a deadline
_apply_recurring_task_day_window(head)
ok("a submitted deadline is discarded", ist_close(head["end"]).startswith("2026-08-22T23:59:59"),
   "%s  (= %s IST)" % (head["end"], ist_close(head["end"])))
ok("it closes at 23:59:59 IST", ist_close(head["end"]).endswith("23:59:59+05:30"))
ok("but is STORED in UTC, as tasks.py reads it", head["end"].endswith("18:29:59+00:00"), head["end"])

one_off = {"type": "task", "repeat": "Does not repeat", "start": "2026-08-22T09:00:00+05:30",
           "end": "2026-09-30T17:00:00+05:30"}
_apply_recurring_task_day_window(one_off)
ok("a one-time task keeps its deadline", one_off["end"] == "2026-09-30T17:00:00+05:30", one_off["end"])

print("\n3. EACH OCCURRENCE OWNS ITS OWN DAY")
curr = datetime.fromisoformat(head["start"])
for step in range(1, 4):
    nxt = _next_occurrence(curr, "Daily", 1, None, None)
    occ = _fresh_occurrence(head, nxt, nxt, None)
    day = nxt.astimezone(IST).date().isoformat()
    ok("day %d closes at 23:59:59 IST on its OWN date" % step,
       ist_close(occ["end"]).startswith(day) and ist_close(occ["end"]).endswith("23:59:59+05:30"),
       ist_close(occ["end"]))
    curr = nxt

print("\n4. WEEKLY / MONTHLY KEEP THE SAME DAY WINDOW")
for cadence in ("Weekly", "Monthly", "Annually"):
    h = {"type": "task", "repeat": cadence, "start": "2026-08-22T09:00:00+05:30"}
    _apply_recurring_task_day_window(h)
    nxt = _next_occurrence(datetime.fromisoformat(h["start"]), cadence, 1, None, None)
    occ = _fresh_occurrence(h, nxt, nxt, None)
    day = nxt.astimezone(IST).date().isoformat()
    ok("%s occurrence closes 23:59:59 IST on its own day" % cadence,
       ist_close(occ["end"]).startswith(day) and ist_close(occ["end"]).endswith("23:59:59+05:30"),
       ist_close(occ["end"]))

print("\n5. OVERDUE AFTER 11:59 PM — NOT EXPIRED")
occ = {"type": "task", "repeat": "Daily", "start": "2026-08-22T09:00:00+05:30"}
_apply_recurring_task_day_window(occ)
ok("live during its own day (6 PM IST)",
   not _is_overdue(occ, "in_progress", utc_naive(datetime(2026, 8, 22, 18, 0, tzinfo=IST))))
ok("still live at 11:58 PM IST",
   not _is_overdue(occ, "in_progress", utc_naive(datetime(2026, 8, 22, 23, 58, tzinfo=IST))))
ok("Overdue at 12:05 AM IST the next day",
   _is_overdue(occ, "in_progress", utc_naive(datetime(2026, 8, 23, 0, 5, tzinfo=IST))))
ok("NOT overdue at 5 AM IST - the 5.5h timezone trap",
   not _is_overdue({"end": "2026-08-22T23:59:59+05:30"}, "in_progress",
                   utc_naive(datetime(2026, 8, 22, 20, 0, tzinfo=IST)))
   and _is_overdue(occ, "in_progress", utc_naive(datetime(2026, 8, 23, 5, 0, tzinfo=IST))),
   "stored UTC flips exactly at 11:59:59 PM IST")
ok("completed is never Overdue",
   not _is_overdue(occ, "completed", utc_naive(datetime(2026, 8, 23, 0, 5, tzinfo=IST))))
ok("the occurrence still EXISTS when overdue - nothing expires",
   occ.get("deleted_at") is None and bool(occ.get("end")))

print("\n6. COMPLETION TIMING STILL WORKS OFF THE SAME FIELD")
done_in_time = {**occ, "workflow_status": "completed",
                "completed_at": datetime(2026, 8, 22, 20, 0, tzinfo=IST).astimezone(timezone.utc).isoformat()}
done_late = {**occ, "workflow_status": "completed",
             "completed_at": datetime(2026, 8, 23, 10, 0, tzinfo=IST).astimezone(timezone.utc).isoformat()}
ok("finished during the day is in_time", _completion_timing(done_in_time) == "in_time")
ok("finished the next day is delayed", _completion_timing(done_late) == "delayed")

print("\n7. A FRESH OCCURRENCE IS A CLEAN CHECKLIST")
h = {"type": "task", "repeat": "Daily", "start": "2026-08-22T09:00:00+05:30",
     "checklist": [{"text": "a", "completed": True}], "remarks": ["old"],
     "attachments": ["f"], "status_history": ["x"], "completed_at": "2026-08-22T10:00:00Z"}
_apply_recurring_task_day_window(h)
nxt = _next_occurrence(datetime.fromisoformat(h["start"]), "Daily", 1, None, None)
fresh = _fresh_occurrence(h, nxt, nxt, None)
ok("checklist comes back unticked", fresh["checklist"][0]["completed"] is False)
ok("remarks cleared", fresh["remarks"] == [])
ok("attachments cleared", fresh["attachments"] == [])
ok("completion cleared", fresh["completed_at"] is None)
ok("workflow restarts in progress", fresh["workflow_status"] == "in_progress")

print("\n8. REGRESSIONS CAUGHT WHILE AUDITING THIS FEATURE")

# The day window must come from `start` alone. `end` at that point is the deadline being
# discarded, so falling back to it opened the checklist on the deadline's own date.
no_start = {"type": "task", "repeat": "Daily", "end": "2026-09-30T17:00:00+05:30"}
_apply_recurring_task_day_window(no_start)
today_ist = datetime.now(timezone.utc).astimezone(IST).date().isoformat()
ok("a missing start does not put the window on the discarded deadline",
   ist_close(no_start["end"]).startswith(today_ist),
   "%s (today), not 30 Sep" % ist_close(no_start["end"])[:10])

# A series created BEFORE this rule still holds a real deadline on its head. Carrying the
# start->end offset forward cloned that gap onto every future occurrence, so tonight's
# checklist came out "due" weeks away. The window is derived from the target date instead.
legacy = {"type": "task", "repeat": "Daily", "start": "2026-08-22T09:00:00+05:30",
          "end": "2026-09-30T17:00:00+05:30"}          # pre-rule row, never rewritten
lx = _next_occurrence(datetime.fromisoformat(legacy["start"]), "Daily", 1, None, None)
lo = _fresh_occurrence(legacy, lx, lx, None)
ok("a legacy series stops cloning its old deadline forward",
   ist_close(lo["end"]).startswith("2026-08-23") and ist_close(lo["end"]).endswith("23:59:59+05:30"),
   ist_close(lo["end"]))
ok("and the stored head is left exactly as it was",
   legacy["end"] == "2026-09-30T17:00:00+05:30", "no document rewritten")

# The shared occurrence builder must not have changed for anything else.
todo = {"type": "todo", "repeat": "Daily", "start": "2026-08-22T23:59:59+05:30",
        "end": "2026-08-22T23:59:59+05:30"}
tn = _next_occurrence(datetime.fromisoformat(todo["start"]), "Daily", 1, None, None)
to = _fresh_occurrence(todo, tn, tn, None)
ok("a todo still keeps start == end", to["start"] == to["end"], ist_close(to["end"]))

one = {"type": "task", "repeat": "Does not repeat", "start": "2026-08-22T09:00:00+05:30",
       "end": "2026-08-25T17:00:00+05:30"}
on_ = _next_occurrence(datetime.fromisoformat(one["start"]), "Daily", 1, None, None)
oo = _fresh_occurrence(one, on_, on_, None)
ok("a non-repeating task keeps its start->end offset",
   ist_close(oo["end"]).startswith("2026-08-26"), ist_close(oo["end"]))

print("\n" + "=" * 64)
print("%d passed, %d failed%s" % (len(P), len(F), ("  <-- " + "; ".join(F)) if F else ""))
print("=" * 64)
sys.exit(1 if F else 0)
