"""IRM validator — a task's checklist is measured, not thrown away.

A task cannot be completed until every check point on it is ticked, so a checklist is a
real progress signal. Counting tasks all-or-nothing discarded it: nine of ten check points
done scored the same as an untouched task. This checks the partial-credit rule and the
things that must NOT have changed with it.

Pure functions only: no database is opened, no document is read or written.

Usage (from backend/):
    python scripts/validate_irm_checklist.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.irm_service import task_credit, _build_row, _pct
from app.models.irm import default_weightages

P, F = [], []


def ok(label, cond, detail=""):
    (P if cond else F).append(label)
    print(("  [PASS] " if cond else "  [FAIL] ") + label + (("  -> " + str(detail)) if detail else ""))


def items(done, total):
    return [{"id": i, "title": "step %d" % i, "completed": i < done} for i in range(total)]


print("1. ONE TASK'S CREDIT")
ok("a completed task is full credit",
   task_credit({"workflow_status": "completed"}) == 1.0)
ok("an untouched task with no checklist is zero",
   task_credit({"workflow_status": "in_progress"}) == 0.0)
ok("9 of 10 check points is 0.9 — not zero",
   task_credit({"workflow_status": "in_progress", "checklist": items(9, 10)}) == 0.9,
   "the whole point of the fix")
ok("half a checklist is 0.5",
   task_credit({"workflow_status": "in_progress", "checklist": items(5, 10)}) == 0.5)
ok("an unticked checklist is still zero",
   task_credit({"workflow_status": "in_progress", "checklist": items(0, 4)}) == 0.0)
ok("a fully ticked but not-yet-completed task is 1.0",
   task_credit({"workflow_status": "in_progress", "checklist": items(4, 4)}) == 1.0,
   "every check point done — the completion call is the only thing left")
ok("credit never exceeds 1",
   all(task_credit({"workflow_status": "in_progress", "checklist": items(d, 4)}) <= 1.0
       for d in range(5)))
ok("a completed task counts fully even if its checklist looks unticked",
   task_credit({"workflow_status": "completed", "checklist": items(0, 5)}) == 1.0,
   "completion already required them; stale flags must not reduce a finished task")

print("\n2. MALFORMED DATA CANNOT CRASH A MONTH'S SCORE")
ok("checklist of None", task_credit({"workflow_status": "x", "checklist": None}) == 0.0)
ok("checklist of junk entries",
   task_credit({"workflow_status": "x", "checklist": ["oops", 3, None]}) == 0.0)
ok("mixed junk and real items still counts the real ones",
   task_credit({"workflow_status": "x", "checklist": ["junk", {"completed": True}]}) == 1.0,
   "one valid item, ticked")

print("\n3. THE SCORE A PERSON ACTUALLY GETS")
weights = default_weightages()          # task 25 / delegation 30 / culture 25 / accountability 20

# 5 tasks: 3 completed, 1 at 9/10 check points, 1 untouched -> 3.9 of 5 = 78%
totals = {"task": {"assigned": 5, "achieved": 3.9, "completed": 3, "partial": 1},
          "delegation": {"assigned": 0, "achieved": 0.0, "completed": 0, "partial": 0}}
row = _build_row({"person_id": "p1"}, weights, totals, {})
task_param = next(p for p in row["parameters"] if p["code"] == "task")
ok("achievement is 78%, not 60%", task_param["achievement"] == 78.0,
   "binary counting would have said %.0f%%" % _pct(3, 5))
ok("weighted score follows the sheet formula",
   task_param["weighted_score"] == round(78.0 * weights["task"] / 100, 2),
   task_param["weighted_score"])
ok("the whole/part split is reported for the screen",
   task_param["completed"] == 3 and task_param["partial"] == 1,
   "3 done + 1 in progress")
ok("achieved is rounded, never a long float", task_param["achieved"] == 3.9)

print("\n4. WHAT MUST NOT HAVE CHANGED")
none_assigned = {"task": {"assigned": 0, "achieved": 0.0, "completed": 0, "partial": 0},
                 "delegation": {"assigned": 0, "achieved": 0.0, "completed": 0, "partial": 0}}
row2 = _build_row({"person_id": "p2"}, weights, none_assigned, {})
tp2 = next(p for p in row2["parameters"] if p["code"] == "task")
ok("no tasks still means 'nothing to score', not 0%",
   tp2["achievement"] is None and tp2["has_data"] is False,
   "a silent 0% would read as real failure")
ok("and it contributes nothing to the total", tp2["weighted_score"] == 0.0)
ok("applicable weightage still excludes it",
   row2["applicable_weightage"] == 0.0 and row2["final_irm_applicable"] is None)

all_done = {"task": {"assigned": 4, "achieved": 4.0, "completed": 4, "partial": 0},
            "delegation": {"assigned": 0, "achieved": 0.0, "completed": 0, "partial": 0}}
row3 = _build_row({"person_id": "p3"}, weights, all_done, {})
tp3 = next(p for p in row3["parameters"] if p["code"] == "task")
ok("a fully completed month is still exactly 100%", tp3["achievement"] == 100.0)
ok("and earns the parameter's full weightage",
   tp3["weighted_score"] == weights["task"], tp3["weighted_score"])
ok("the form parameters are untouched by any of this",
   all(p["source"] == "form" for p in row3["parameters"] if p["code"] in ("culture", "accountability")))

print("\n" + "=" * 66)
print("%d passed, %d failed%s" % (len(P), len(F), ("  <-- " + "; ".join(F)) if F else ""))
print("=" * 66)
sys.exit(1 if F else 0)
