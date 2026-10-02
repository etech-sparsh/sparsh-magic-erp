"""
Enterprise Reports — Company (E2) and Employee (E3) aggregation.

Read-only. Builds on report_service.py (task helpers, user loading) and joins the
existing company/batch/session/attendance/assessment collections. No new data is
written and no existing behaviour changes.

Data sources (verified conventions):
  * companies                 — company docs
  * batches.companies[]       — company ↔ batch membership
  * calendar events (type=event, batch_id) — sessions; coach_ids for coaches
  * attendance{user_id,session_id,session_name,date,status}  — attendance history
  * LearnerAssessments{user_id,company_id,quiz_title,session_id,score,total_marks,
                       percentage,passed,submitted_at}       — assessment history

v1 gaps surfaced as null/"—": Employee ID, profile photo, started/submitted/
reviewed/approved dates, check-in/out & duration, learning hours, assessment
time-taken. Joining date proxies to user.created_at.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from bson import ObjectId

from app.db.mongodb import get_collection
from app.services import report_service as rs


# --------------------------------------------------------------------------- #
# Loaders                                                                      #
# --------------------------------------------------------------------------- #
async def _attendance_by_user(user_ids: List[str]) -> Dict[str, list]:
    if not user_ids:
        return {}
    docs = await get_collection("attendance").find({"user_id": {"$in": user_ids}}).to_list(50000)
    out: Dict[str, list] = {}
    for a in docs:
        out.setdefault(str(a.get("user_id")), []).append(a)
    return out


async def _assessments_by_user(user_ids: List[str]) -> Dict[str, list]:
    if not user_ids:
        return {}
    docs = await get_collection("LearnerAssessments").find({"user_id": {"$in": user_ids}}).to_list(50000)
    out: Dict[str, list] = {}
    for a in docs:
        out.setdefault(str(a.get("user_id")), []).append(a)
    return out


async def load_company_batches():
    """Return (company_id -> set(batch_id), batch_id -> {id,name,status})."""
    docs = await get_collection("batches").find({}).to_list(5000)
    comp2batch: Dict[str, set] = {}
    batches: Dict[str, dict] = {}
    for b in docs:
        bid = str(b["_id"])
        batches[bid] = {
            "id": bid,
            "name": b.get("name") or b.get("product_name") or "Batch",
            "status": b.get("status"),
        }
        for cid in (b.get("companies") or []):
            comp2batch.setdefault(str(cid), set()).add(bid)
    return comp2batch, batches


def _tasks_by_doer(tasks: List[dict], restrict: Optional[set] = None) -> Dict[str, list]:
    out: Dict[str, list] = {}
    for t in tasks:
        for did in rs.doer_ids(t):
            if restrict is not None and did not in restrict:
                continue
            out.setdefault(did, []).append(t)
    return out


def _rate(part, total):
    return round(part / total * 100, 1) if total else 0.0


def _avg(vals):
    return round(sum(vals) / len(vals), 1) if vals else 0.0


# --------------------------------------------------------------------------- #
# E2 — Companies                                                               #
# --------------------------------------------------------------------------- #
async def compute_companies(tasks: List[dict], users: Dict[str, dict]) -> List[dict]:
    now = datetime.utcnow()
    companies = await get_collection("companies").find({}).to_list(5000)

    emp_by_company: Dict[str, list] = {}
    for uid, u in users.items():
        if u.get("company_id"):
            emp_by_company.setdefault(u["company_id"], []).append(uid)

    all_emp_ids = [uid for ids in emp_by_company.values() for uid in ids]
    att_by_user = await _attendance_by_user(all_emp_ids)

    assessments = await get_collection("LearnerAssessments").find({}).to_list(50000)
    assess_by_company: Dict[str, list] = {}
    for a in assessments:
        assess_by_company.setdefault(str(a.get("company_id")), []).append(a)

    tbd = _tasks_by_doer(tasks)

    rows = []
    for c in companies:
        cid = str(c["_id"])
        emp_ids = emp_by_company.get(cid, [])
        st = rs._new_stat()
        for eid in emp_ids:
            for t in tbd.get(eid, []):
                rs._apply(st, t, now)
        fin = rs._finalize(st)

        tot = pres = 0
        sessions = set()
        for eid in emp_ids:
            for a in att_by_user.get(eid, []):
                tot += 1
                sessions.add(a.get("session_id"))
                if a.get("status") == "present":
                    pres += 1

        ass = assess_by_company.get(cid, [])
        rows.append({
            "id": cid,
            "name": c.get("name") or "Company",
            "status": c.get("status", "active"),
            "employees": len(emp_ids),
            "sessions": len(sessions),
            "assigned": fin["assigned"],
            "completed": fin["completed"],
            "pending": fin["pending"],
            "overdue": fin["overdue"],
            "completionRate": fin["completionRate"],
            "attendanceRate": _rate(pres, tot),
            "avgAssessment": _avg([x.get("percentage", 0) for x in ass]),
            "score": fin["score"],
            "rating": fin["rating"],
        })
    rows.sort(key=lambda r: (r["score"], r["completed"]), reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def compute_company_employees(company_id, tasks, users, att_by_user, assess_by_user) -> List[dict]:
    now = datetime.utcnow()
    emp_ids = [uid for uid, u in users.items() if u.get("company_id") == company_id]
    emp_set = set(emp_ids)
    tbd = _tasks_by_doer(tasks, restrict=emp_set)

    rows = []
    for eid in emp_ids:
        u = users.get(eid, {})
        st = rs._new_stat()
        for t in tbd.get(eid, []):
            rs._apply(st, t, now)
        fin = rs._finalize(st)

        att = att_by_user.get(eid, [])
        pres = sum(1 for a in att if a.get("status") == "present")
        ass = assess_by_user.get(eid, [])
        rows.append({
            "id": eid,
            "name": u.get("name", "Unknown"),
            "email": u.get("email"),
            "department": u.get("department", "Other"),
            "assigned": fin["assigned"],
            "completed": fin["completed"],
            "pending": fin["pending"],
            "overdue": fin["overdue"],
            "completionRate": fin["completionRate"],
            "attendanceRate": _rate(pres, len(att)),
            "avgAssessment": _avg([x.get("percentage", 0) for x in ass]),
            "score": fin["score"],
            "rating": fin["rating"],
        })
    rows.sort(key=lambda r: (r["score"], r["completed"]), reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def _month_bucket(store, dt, label):
    key = (dt.year, dt.month)
    return store.setdefault(key, {
        "_s": key, "name": label,
        "assigned": 0, "completed": 0, "scoreSum": 0.0, "scoreCount": 0,
        "attTotal": 0, "attPresent": 0,
    })


async def compute_company_dashboard(company_id: str, tasks: List[dict], users: Dict[str, dict]) -> dict:
    now = datetime.utcnow()
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
    except Exception:
        company = None

    emp_ids = [uid for uid, u in users.items() if u.get("company_id") == company_id]
    emp_set = set(emp_ids)
    att_by_user = await _attendance_by_user(emp_ids)
    assessments = await get_collection("LearnerAssessments").find({"company_id": company_id}).to_list(50000)
    assess_by_user: Dict[str, list] = {}
    for a in assessments:
        assess_by_user.setdefault(str(a.get("user_id")), []).append(a)

    comp2batch, batches = await load_company_batches()
    batch_ids = list(comp2batch.get(company_id, set()))

    employees = compute_company_employees(company_id, tasks, users, att_by_user, assess_by_user)

    # sessions + coaches from calendar events of this company's batches
    sessions_total = 0
    coaches = set()
    batch_session_counts: Dict[str, dict] = {b: {"name": batches[b]["name"], "sessions": 0, "completed": 0} for b in batch_ids}
    if batch_ids:
        for col in rs.SESSION_COLLECTIONS:
            evs = await get_collection(col).find({"batch_id": {"$in": batch_ids}, "type": "event"}).to_list(5000)
            sessions_total += len(evs)
            for ev in evs:
                for c in (ev.get("coach_ids") or []):
                    coaches.add(str(c))
                bid = str(ev.get("batch_id"))
                if bid in batch_session_counts:
                    batch_session_counts[bid]["sessions"] += 1
                    if ev.get("status") == "completed":
                        batch_session_counts[bid]["completed"] += 1

    # KPI rollups (from employee rows + raw attendance/assessment)
    assigned = sum(e["assigned"] for e in employees)
    completed = sum(e["completed"] for e in employees)
    pending = sum(e["pending"] for e in employees)
    overdue = sum(e["overdue"] for e in employees)
    att_total = sum(len(att_by_user.get(e["id"], [])) for e in employees)
    att_present = sum(1 for e in employees for a in att_by_user.get(e["id"], []) if a.get("status") == "present")
    productivity = round(sum(e["score"] for e in employees) / len(employees)) if employees else 0
    learners = sum(1 for uid in emp_ids if users[uid].get("tag") == "learner")

    # Active users = activity (login/learning) within the last 30 days (real, from activity_logs).
    activity = await rs._activity_by_user(emp_ids)
    cutoff_key = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    active_users = 0
    for uid in emp_ids:
        act = activity.get(uid, {})
        latest = str(act.get("lastActivity") or act.get("lastLogin") or "")
        if latest and latest[:10] >= cutoff_key:
            active_users += 1

    # Active batches = company batches with status "active".
    active_batches = 0
    if batch_ids:
        try:
            active_batches = await get_collection("batches").count_documents(
                {"_id": {"$in": [ObjectId(b) for b in batch_ids]}, "status": "active"})
        except Exception:
            active_batches = 0
    completed_sessions = sum(v["completed"] for v in batch_session_counts.values())

    kpis = {
        "totalEmployees": len(emp_ids),
        "activeUsers": active_users,
        "totalCoaches": len(coaches),
        "totalLearners": learners,
        "totalSessions": sessions_total,
        "activeCourses": max(0, sessions_total - completed_sessions),
        "totalBatches": len(batch_ids),
        "activeBatches": active_batches,
        "totalAssignments": assigned,
        "completedAssignments": completed,
        "pendingAssignments": pending,
        "overdueAssignments": overdue,
        "avgAttendance": _rate(att_present, att_total),
        "avgAssessment": _avg([a.get("percentage", 0) for a in assessments]),
        "productivity": productivity,
        "completionRate": _rate(completed, assigned),
    }

    # monthly trends
    months: Dict[tuple, dict] = {}
    for a in assessments:
        dt = rs._parse_iso(a.get("submitted_at"))
        if dt:
            b = _month_bucket(months, dt, dt.strftime("%b %Y"))
            b["scoreSum"] += a.get("percentage", 0)
            b["scoreCount"] += 1
    for eid in emp_ids:
        for a in att_by_user.get(eid, []):
            dt = rs._parse_iso(a.get("date"))
            if dt:
                b = _month_bucket(months, dt, dt.strftime("%b %Y"))
                b["attTotal"] += 1
                if a.get("status") == "present":
                    b["attPresent"] += 1
    for t in tasks:
        if not (emp_set & set(rs.doer_ids(t))):
            continue
        dt = rs._parse_iso(t.get("start"))
        if dt:
            b = _month_bucket(months, dt, dt.strftime("%b %Y"))
            b["assigned"] += 1
            if rs._resolve_workflow_status(t) == "completed":
                b["completed"] += 1

    monthly = []
    for b in sorted(months.values(), key=lambda x: x["_s"]):
        monthly.append({
            "name": b["name"],
            "assigned": b["assigned"],
            "completed": b["completed"],
            "avgScore": round(b["scoreSum"] / b["scoreCount"], 1) if b["scoreCount"] else 0,
            "attendance": _rate(b["attPresent"], b["attTotal"]),
            "productivity": round(b["completed"] / b["assigned"] * 100) if b["assigned"] else 0,
        })

    # distributions
    dept_counts: Dict[str, int] = {}
    for uid in emp_ids:
        d = users[uid].get("department", "Other")
        dept_counts[d] = dept_counts.get(d, 0) + 1
    department_distribution = [{"name": k, "value": v} for k, v in sorted(dept_counts.items(), key=lambda x: -x[1])]

    rating_colors = {
        "Excellent": "var(--accent-green)", "Good": "var(--accent-indigo)",
        "Average": "var(--accent-orange)", "Needs Attention": "var(--accent-red)",
    }
    rating_counts: Dict[str, int] = {}
    for e in employees:
        rating_counts[e["rating"]] = rating_counts.get(e["rating"], 0) + 1
    employee_distribution = [
        {"name": k, "value": v, "color": rating_colors.get(k, "var(--accent-indigo)")}
        for k, v in rating_counts.items()
    ]

    batch_performance = [
        {"name": v["name"], "sessions": v["sessions"], "completed": v["completed"]}
        for v in batch_session_counts.values()
    ]

    top = employees[:5]
    lowest = sorted([e for e in employees if e["assigned"] > 0], key=lambda e: e["score"])[:5]

    return {
        "company": {"id": company_id, "name": (company or {}).get("name", "Company"),
                    "status": (company or {}).get("status", "active")},
        "kpis": kpis,
        "monthly": monthly,
        "departmentDistribution": department_distribution,
        "employeeDistribution": employee_distribution,
        "batchPerformance": batch_performance,
        "topPerformers": [{"name": e["name"], "score": e["score"]} for e in top],
        "lowestPerformers": [{"name": e["name"], "score": e["score"]} for e in lowest],
    }


# --------------------------------------------------------------------------- #
# E3 — Employee                                                                #
# --------------------------------------------------------------------------- #
async def compute_employee_report(user_id: str, tasks: List[dict], users: Dict[str, dict]) -> Optional[dict]:
    u = users.get(user_id)
    if not u:
        return None
    now = datetime.utcnow()

    st = rs._new_stat()
    for t in tasks:
        if user_id in rs.doer_ids(t):
            rs._apply(st, t, now)
    fin = rs._finalize(st)

    att = await get_collection("attendance").find({"user_id": user_id}).to_list(5000)
    att_present = sum(1 for a in att if a.get("status") == "present")
    sessions_total = len({a.get("session_id") for a in att})

    ass = await get_collection("LearnerAssessments").find({"user_id": user_id}).to_list(5000)
    avg_ass = _avg([a.get("percentage", 0) for a in ass])

    company_name = None
    batch_name = None
    if u.get("company_id"):
        try:
            c = await get_collection("companies").find_one({"_id": ObjectId(u["company_id"])})
            company_name = c.get("name") if c else None
        except Exception:
            pass
        comp2batch, batches = await load_company_batches()
        bids = list(comp2batch.get(u["company_id"], set()))
        if bids:
            batch_name = batches[bids[0]]["name"]  # best-effort (indirect via company)

    # monthly trends
    months: Dict[tuple, dict] = {}
    for a in ass:
        dt = rs._parse_iso(a.get("submitted_at"))
        if dt:
            b = _month_bucket(months, dt, dt.strftime("%b %Y"))
            b["scoreSum"] += a.get("percentage", 0)
            b["scoreCount"] += 1
    for a in att:
        dt = rs._parse_iso(a.get("date"))
        if dt:
            b = _month_bucket(months, dt, dt.strftime("%b %Y"))
            b["attTotal"] += 1
            if a.get("status") == "present":
                b["attPresent"] += 1
    for t in tasks:
        if user_id not in rs.doer_ids(t):
            continue
        dt = rs._parse_iso(t.get("start"))
        if dt:
            b = _month_bucket(months, dt, dt.strftime("%b %Y"))
            b["assigned"] += 1
            if rs._resolve_workflow_status(t) == "completed":
                b["completed"] += 1
    trends = []
    for b in sorted(months.values(), key=lambda x: x["_s"]):
        trends.append({
            "name": b["name"],
            "assigned": b["assigned"],
            "completed": b["completed"],
            "avgScore": round(b["scoreSum"] / b["scoreCount"], 1) if b["scoreCount"] else 0,
            "attendance": _rate(b["attPresent"], b["attTotal"]),
        })

    return {
        "employee": {
            "id": user_id,
            "name": u.get("name"),
            "email": u.get("email"),
            "role": u.get("role"),
            "department": u.get("department", "Other"),
            "company": company_name,
            "batch": batch_name,          # indirect (company→batch)
            "quarter": None,              # indirect; not resolved in v1
            "coach": None,                # via session coach_ids; not resolved in v1
            "joiningDate": rs._iso(u.get("created_at")),
            "designation": u.get("designation"),
            "isActive": u.get("is_active", True),
            "employeeId": None,           # not stored (v1)
            "photo": None,                # not stored → initials avatar
        },
        "summary": {
            "totalSessions": sessions_total,
            "completedSessions": att_present,
            "pendingSessions": max(0, sessions_total - att_present),
            "assigned": fin["assigned"],
            "completed": fin["completed"],
            "pending": fin["pending"],
            "overdue": fin["overdue"],
            "attendanceRate": _rate(att_present, len(att)),
            "avgAssessment": avg_ass,
            "learningProgress": fin["completionRate"],   # proxy: assignment completion
            "productivity": fin["score"],
            "rating": fin["rating"],
        },
        "trends": trends,
    }


async def employee_assessments(user_id: str) -> List[dict]:
    docs = await get_collection("LearnerAssessments").find({"user_id": user_id}).to_list(2000)
    out = []
    for d in docs:
        out.append({
            "id": str(d.get("_id")),
            "name": d.get("quiz_title") or "Assessment",
            "sessionId": d.get("session_id"),
            "date": rs._iso(d.get("submitted_at")),
            "score": d.get("score"),
            "totalMarks": d.get("total_marks"),
            "percentage": round(d.get("percentage", 0), 1),
            "passed": d.get("passed"),
            "timeTaken": None,  # not stored (v1)
        })
    out.sort(key=lambda r: (r["date"] or ""), reverse=True)
    return out


async def employee_attendance(user_id: str) -> List[dict]:
    docs = await get_collection("attendance").find({"user_id": user_id}).to_list(3000)
    out = []
    for d in docs:
        out.append({
            "sessionName": d.get("session_name") or "Session",
            "date": d.get("date"),
            "status": d.get("status"),
            "checkIn": None,    # not stored (v1)
            "checkOut": None,   # not stored (v1)
            "duration": None,   # not stored (v1)
        })
    out.sort(key=lambda r: (r["date"] or ""), reverse=True)
    return out
