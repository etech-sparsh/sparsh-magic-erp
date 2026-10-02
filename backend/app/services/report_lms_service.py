"""
Enterprise Reports — LMS-wise aggregation.

Decision (docs/ENTERPRISE_REPORTS_ANALYSIS.md Addendum D): there is no dedicated
"LMS" entity in this system, so **an LMS instance maps to a training Batch**.
"Courses" map to the batch's sessions (calendar events, type=event). Certificates
and Learning Hours are omitted (no data captured). Read-only; no new data written.

Scoping for a batch (LMS):
  * companies   = batches.companies[]
  * users       = learners of those companies
  * sessions    = calendar events (type=event) with batch_id == this batch
  * attendance  = attendance rows for those users on those sessions
  * assessments = LearnerAssessments on those sessions
  * assignments = tasks where a batch user is the doer
"""
from datetime import datetime
from typing import Dict, List, Optional

from bson import ObjectId

from app.db.mongodb import get_collection
from app.services import report_service as rs
from app.services import report_company_service as rcs


async def _company_name_map() -> Dict[str, str]:
    docs = await get_collection("companies").find({}).to_list(5000)
    return {str(c["_id"]): (c.get("name") or "Company") for c in docs}


def _learners_by_company(users: Dict[str, dict]) -> Dict[str, list]:
    out: Dict[str, list] = {}
    for uid, u in users.items():
        if u.get("tag") == "learner" and u.get("company_id"):
            out.setdefault(u["company_id"], []).append(uid)
    return out


def _att_status(rate: float) -> str:
    """Attendance status bands (spec): >=90 Excellent, 75-89 Good, 60-74 Average, <60 Poor."""
    if rate >= 90:
        return "Excellent"
    if rate >= 75:
        return "Good"
    if rate >= 60:
        return "Average"
    return "Poor"


async def _batch_sessions(batch_id: str):
    """Return (session_ids, total, completed, last_start_iso, sessions[])."""
    s_ids, total, completed, last = [], 0, 0, None
    sessions = []
    for col in rs.SESSION_COLLECTIONS:
        evs = await get_collection(col).find({"batch_id": batch_id, "type": "event"}).to_list(3000)
        for ev in evs:
            sid = str(ev["_id"])
            s_ids.append(sid)
            total += 1
            if ev.get("status") == "completed":
                completed += 1
            st = ev.get("start")
            if st and (last is None or str(st) > str(last)):
                last = st
            sessions.append({"id": sid, "title": ev.get("title") or "Session", "status": ev.get("status"), "start": st})
    return s_ids, total, completed, last, sessions


# --------------------------------------------------------------------------- #
# LMS list                                                                     #
# --------------------------------------------------------------------------- #
async def compute_lms_list(users: Dict[str, dict], company_id: Optional[str] = None) -> List[dict]:
    query = {"companies": company_id} if company_id else {}
    batches = await get_collection("batches").find(query).to_list(2000)
    learners_by_company = _learners_by_company(users)
    company_names = await _company_name_map()

    # Attendance (real records): load once for every learner across all batches, then scope
    # per-batch to that batch's sessions when computing each course's average attendance.
    all_user_ids = set()
    for b in batches:
        for cid in [str(c) for c in (b.get("companies") or [])]:
            all_user_ids.update(learners_by_company.get(cid, []))
    att_by_user = await rcs._attendance_by_user(list(all_user_ids))

    rows = []
    for b in batches:
        bid = str(b["_id"])
        comp_ids = [str(c) for c in (b.get("companies") or [])]
        user_ids = [uid for cid in comp_ids for uid in learners_by_company.get(cid, [])]
        active = sum(1 for uid in user_ids if users[uid].get("is_active", True))

        s_ids, total, completed, last, _ = await _batch_sessions(bid)
        avg_score = 0.0
        if s_ids:
            ass = await get_collection("LearnerAssessments").find({"session_id": {"$in": s_ids}}).to_list(8000)
            avg_score = rcs._avg([a.get("percentage", 0) for a in ass])

        # Per-course attendance: each learner's present/total over this batch's sessions.
        s_id_set = set(s_ids)
        learner_rates, below75 = [], 0
        if s_id_set:
            for uid in user_ids:
                uatt = [a for a in att_by_user.get(uid, []) if str(a.get("session_id")) in s_id_set]
                if not uatt:
                    continue
                rate = sum(1 for a in uatt if a.get("status") == "present") / len(uatt) * 100
                learner_rates.append(rate)
                if rate < 75:
                    below75 += 1
        avg_attendance = round(sum(learner_rates) / len(learner_rates), 1) if learner_rates else 0.0

        rows.append({
            "id": bid,
            "name": b.get("name") or b.get("product_name") or "LMS",
            "company": company_names.get(comp_ids[0], "—") if len(comp_ids) == 1 else f"{len(comp_ids)} companies",
            "companyCount": len(comp_ids),
            "totalUsers": len(user_ids),
            "activeUsers": active,
            "inactiveUsers": len(user_ids) - active,
            "coursesAssigned": total,
            "coursesCompleted": completed,
            "completionRate": rcs._rate(completed, total),
            "avgScore": avg_score,
            "avgAttendance": avg_attendance,
            "learnersBelow75": below75,
            "learnersWithAttendance": len(learner_rates),
            "lastActivity": last,
            "status": b.get("status", "active"),
            # certificates / learningHours intentionally omitted (no data source)
        })
    rows.sort(key=lambda r: (r["completionRate"], r["totalUsers"]), reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


# --------------------------------------------------------------------------- #
# LMS dashboard                                                                #
# --------------------------------------------------------------------------- #
def _month_key(dt):
    return (dt.year, dt.month), dt.strftime("%b %Y")


async def compute_lms_dashboard(batch_id: str, tasks: List[dict], users: Dict[str, dict]) -> dict:
    now = datetime.utcnow()
    try:
        batch = await get_collection("batches").find_one({"_id": ObjectId(batch_id)})
    except Exception:
        batch = None
    comp_ids = [str(c) for c in ((batch or {}).get("companies") or [])]
    learners_by_company = _learners_by_company(users)
    emp_ids = [uid for cid in comp_ids for uid in learners_by_company.get(cid, [])]
    emp_set = set(emp_ids)

    s_ids, total_sessions, completed_sessions, last, sessions = await _batch_sessions(batch_id)
    s_id_set = set(s_ids)

    # attendance + assessments scoped to this batch's sessions
    attendance, assessments = [], []
    if emp_ids:
        att_docs = await get_collection("attendance").find({"user_id": {"$in": emp_ids}}).to_list(50000)
        attendance = [a for a in att_docs if str(a.get("session_id")) in s_id_set] if s_id_set else att_docs
    if s_ids:
        assessments = await get_collection("LearnerAssessments").find({"session_id": {"$in": s_ids}}).to_list(20000)

    active_users = sum(1 for uid in emp_ids if users[uid].get("is_active", True))
    avg_score = rcs._avg([a.get("percentage", 0) for a in assessments])

    # per-user productivity from assignments (tasks)
    emp_rows = []
    tbd = {}
    for t in tasks:
        for did in rs.doer_ids(t):
            if did in emp_set:
                tbd.setdefault(did, []).append(t)
    dept_stats: Dict[str, dict] = {}
    assign_total = assign_completed = 0
    for uid in emp_ids:
        st = rs._new_stat()
        for t in tbd.get(uid, []):
            rs._apply(st, t, now)
        fin = rs._finalize(st)
        assign_total += fin["assigned"]
        assign_completed += fin["completed"]
        u = users.get(uid, {})
        emp_rows.append({"id": uid, "name": u.get("name", "Unknown"), "department": u.get("department", "Other"), "score": fin["score"]})
        d = dept_stats.setdefault(u.get("department", "Other"), {"sum": 0, "n": 0})
        d["sum"] += fin["score"]
        d["n"] += 1
    emp_rows.sort(key=lambda r: r["score"], reverse=True)

    # monthly buckets: completion trend, activity, assignments
    months: Dict[tuple, dict] = {}

    def bucket(dt):
        k, label = _month_key(dt)
        return months.setdefault(k, {"_s": k, "name": label, "completed": 0, "activity": 0, "assigned": 0, "assignCompleted": 0})

    for ev in sessions:
        dt = rs._parse_iso(ev.get("start"))
        if dt and ev.get("status") == "completed":
            bucket(dt)["completed"] += 1
    for a in attendance:
        dt = rs._parse_iso(a.get("date"))
        if dt:
            bucket(dt)["activity"] += 1
    for uid in emp_ids:
        for t in tbd.get(uid, []):
            dt = rs._parse_iso(t.get("start"))
            if dt:
                b = bucket(dt)
                b["assigned"] += 1
                if rs._resolve_workflow_status(t) == "completed":
                    b["assignCompleted"] += 1
    monthly = [
        {"name": b["name"], "completed": b["completed"], "activity": b["activity"],
         "assigned": b["assigned"], "assignCompleted": b["assignCompleted"]}
        for b in sorted(months.values(), key=lambda x: x["_s"])
    ]

    # enrollment trend (cumulative users by created_at)
    enroll: Dict[tuple, dict] = {}
    for uid in emp_ids:
        dt = rs._parse_iso(users[uid].get("created_at"))
        if dt:
            k, label = _month_key(dt)
            e = enroll.setdefault(k, {"_s": k, "name": label, "users": 0})
            e["users"] += 1
    enroll_list = sorted(enroll.values(), key=lambda x: x["_s"])
    cum = 0
    enrollment = []
    for e in enroll_list:
        cum += e["users"]
        enrollment.append({"name": e["name"], "users": e["users"], "cumulative": cum})

    # score distribution buckets
    dist = {"0-40": 0, "40-60": 0, "60-75": 0, "75-90": 0, "90-100": 0}
    for a in assessments:
        p = a.get("percentage", 0) or 0
        if p < 40:
            dist["0-40"] += 1
        elif p < 60:
            dist["40-60"] += 1
        elif p < 75:
            dist["60-75"] += 1
        elif p < 90:
            dist["75-90"] += 1
        else:
            dist["90-100"] += 1
    score_distribution = [{"name": k, "value": v} for k, v in dist.items()]

    top_departments = sorted(
        [{"name": k, "score": round(v["sum"] / v["n"]) if v["n"] else 0} for k, v in dept_stats.items()],
        key=lambda x: x["score"], reverse=True,
    )[:6]

    # top courses (sessions) by attendance count
    att_by_session: Dict[str, int] = {}
    for a in attendance:
        att_by_session[str(a.get("session_id"))] = att_by_session.get(str(a.get("session_id")), 0) + 1
    session_title = {s["id"]: s["title"] for s in sessions}
    top_courses = sorted(
        [{"name": session_title.get(sid, "Session")[:18], "attendance": cnt} for sid, cnt in att_by_session.items()],
        key=lambda x: x["attendance"], reverse=True,
    )[:8]

    performance_index = round(sum(e["score"] for e in emp_rows) / len(emp_rows)) if emp_rows else 0

    return {
        "lms": {"id": batch_id, "name": (batch or {}).get("name") or (batch or {}).get("product_name") or "LMS",
                "status": (batch or {}).get("status", "active"), "companyCount": len(comp_ids)},
        "kpis": {
            "totalUsers": len(emp_ids),
            "activeUsers": active_users,
            "inactiveUsers": len(emp_ids) - active_users,
            "totalCourses": total_sessions,
            "assignedCourses": total_sessions,
            "completedCourses": completed_sessions,
            "inProgressCourses": max(0, total_sessions - completed_sessions),
            "completionRate": rcs._rate(completed_sessions, total_sessions),
            "avgScore": avg_score,
            "performanceIndex": performance_index,
            # certificatesEarned / totalLearningHours omitted (no data)
        },
        "monthly": monthly,
        "enrollment": enrollment,
        "scoreDistribution": score_distribution,
        "completionVsPending": [
            {"name": "Completed", "value": completed_sessions, "color": "var(--accent-green)"},
            {"name": "In Progress", "value": max(0, total_sessions - completed_sessions), "color": "var(--accent-orange)"},
        ],
        "activeVsInactive": [
            {"name": "Active", "value": active_users, "color": "var(--accent-green)"},
            {"name": "Inactive", "value": len(emp_ids) - active_users, "color": "var(--accent-red)"},
        ],
        "topPerformers": [{"name": e["name"].split(" ")[0] if e["name"] else "—", "score": e["score"]} for e in emp_rows[:8]],
        "topDepartments": top_departments,
        "topCourses": top_courses,
    }


async def compute_lms_employees(batch_id: str, tasks: List[dict], users: Dict[str, dict]) -> List[dict]:
    try:
        batch = await get_collection("batches").find_one({"_id": ObjectId(batch_id)})
    except Exception:
        batch = None
    comp_ids = [str(c) for c in ((batch or {}).get("companies") or [])]
    learners_by_company = _learners_by_company(users)
    emp_ids = [uid for cid in comp_ids for uid in learners_by_company.get(cid, [])]

    company_names = await _company_name_map()
    batch_name = (batch or {}).get("name") or (batch or {}).get("product_name") or "LMS"

    # Scope attendance to this course's (batch's) sessions so Total/Attended/Missed reflect
    # the course, not the learner's org-wide attendance.
    s_ids, _, _, _, _ = await _batch_sessions(batch_id)
    s_id_set = set(s_ids)

    att_by_user = await rcs._attendance_by_user(emp_ids)
    assess_by_user = await rcs._assessments_by_user(emp_ids)

    now = datetime.utcnow()
    emp_set = set(emp_ids)
    tbd = {}
    for t in tasks:
        for did in rs.doer_ids(t):
            if did in emp_set:
                tbd.setdefault(did, []).append(t)

    rows = []
    for uid in emp_ids:
        u = users.get(uid, {})
        st = rs._new_stat()
        for t in tbd.get(uid, []):
            rs._apply(st, t, now)
        fin = rs._finalize(st)
        att = [a for a in att_by_user.get(uid, []) if str(a.get("session_id")) in s_id_set] if s_id_set else []
        total_sess = len(att)
        pres = sum(1 for a in att if a.get("status") == "present")
        att_rate = rcs._rate(pres, total_sess)
        ass = assess_by_user.get(uid, [])
        rows.append({
            "id": uid, "name": u.get("name", "Unknown"), "email": u.get("email"),
            "department": u.get("department", "Other"),
            "company": company_names.get(u.get("company_id"), "—"),
            "course": batch_name, "batch": batch_name,
            "assigned": fin["assigned"], "completed": fin["completed"], "pending": fin["pending"],
            "overdue": fin["overdue"], "completionRate": fin["completionRate"],
            "totalSessions": total_sess,
            "sessionsAttended": pres,
            "sessionsMissed": total_sess - pres,
            "attendanceRate": att_rate,
            "attendanceStatus": _att_status(att_rate),
            "avgAssessment": rcs._avg([x.get("percentage", 0) for x in ass]),
            "score": fin["score"], "rating": fin["rating"],
        })
    rows.sort(key=lambda r: (r["score"], r["completed"]), reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows
