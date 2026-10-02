"""
Admin Reports & Analytics — aggregation service.

Read-only. Reuses the task-workflow helpers already defined in app.routes.tasks
(status resolution, overdue check, completion timing, period-to-range) so the
Reports numbers always agree with the Task Management module. No new task data
is written and no existing behaviour is changed.

Design notes (grounded in docs/ADMIN_REPORTS_MODULE_ANALYSIS.md):
  * "Doer"      = task assignee(s) in `target_staff_id` (str or list); for
                  self-assigned tasks (`assigned_to == "myself"`) the creator.
  * "Delegator" = task creator (`user_id`) when `assigned_to == "other"`.
  * "Score"     = productivity = 0.6*completion_rate + 0.4*on_time_rate  (0..100).
  * "Started" / "Approved" dates and "Rejected/Approved" states do not exist in
    the data model (v1 decision) — timelines are reconstructed from `created_at`,
    `activity_logs` status changes, and `completed_at`.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from app.db.mongodb import get_collection
from app.utils.calendar_utils import CALENDAR_COLLECTIONS
from app.routes.tasks import (
    TASK_COLLECTIONS,
    WORKFLOW_STATUSES,
    _period_to_range,
    _resolve_workflow_status,
    _parse_iso,
    _is_overdue,
    _completion_timing,
)

# Sessions are calendar events (type=="event") across the calendar collections.
SESSION_COLLECTIONS = CALENDAR_COLLECTIONS + ["calendar_events"]

# Chart color tokens mirror the frontend design system (src/index.css accents).
STATUS_COLORS = {
    "pending": "var(--accent-orange)",
    "accepted": "var(--accent-indigo)",
    "in_progress": "var(--accent-indigo)",
    "dependent_on_others": "var(--accent-yellow)",
    "blocked": "var(--accent-red)",
    "verification": "var(--accent-yellow)",
    "dependency_completed": "var(--accent-indigo)",
    "completed": "var(--accent-green)",
}
STATUS_LABELS = {
    "pending": "Pending",
    "accepted": "Accepted",
    "in_progress": "In Progress",
    "dependent_on_others": "Dependent",
    "blocked": "Blocked",
    "verification": "Awaiting Approval",  # v1: verification surfaced as "awaiting approval"
    "dependency_completed": "Dependency Completed",
    "completed": "Completed",
}
PRIORITY_COLORS = {
    "High": "var(--accent-red)",
    "Normal": "var(--accent-indigo)",
    "Medium": "var(--accent-indigo)",
    "Low": "var(--accent-green)",
}


# --------------------------------------------------------------------------- #
# Loading                                                                      #
# --------------------------------------------------------------------------- #
async def load_users() -> Dict[str, dict]:
    """Return {user_id: {id, name, email, role, department, designation, is_active, tag}}."""
    users: Dict[str, dict] = {}
    for col in ("staff", "learners"):
        docs = await get_collection(col).find({}).to_list(5000)
        for u in docs:
            uid = str(u["_id"])
            name = (
                u.get("full_name")
                or f"{u.get('first_name', '') or ''} {u.get('last_name', '') or ''}".strip()
                or u.get("email")
                or "Unknown"
            )
            users[uid] = {
                "id": uid,
                "name": name,
                "email": u.get("email"),
                "role": u.get("role"),
                "department": u.get("department") or "Other",
                "designation": u.get("designation"),
                "is_active": u.get("is_active", True),
                "tag": u.get("tag") or col,
                "company_id": str(u["company_id"]) if u.get("company_id") else None,
                "created_at": u.get("created_at"),
            }
    return users


async def fetch_tasks(start_iso: Optional[str], end_iso: Optional[str]) -> List[dict]:
    """All non-deleted task documents across task collections, optional date window (by `start`)."""
    clauses: List[dict] = [{"type": "task"}, {"deleted_at": None}]
    if start_iso and end_iso:
        clauses.append({"start": {"$gte": start_iso, "$lte": end_iso}})
    query = {"$and": clauses}

    seen = set()
    out: List[dict] = []
    for col in TASK_COLLECTIONS:
        docs = await get_collection(col).find(query).to_list(5000)
        for d in docs:
            key = str(d["_id"])
            if key in seen:  # calendar_events is a fallback that can overlap
                continue
            seen.add(key)
            d["_source_col"] = col
            out.append(d)
    return out


def period_range(period, start_date, end_date):
    """Thin wrapper so routes don't import the private helper directly."""
    return _period_to_range(period, start_date, end_date)


# --------------------------------------------------------------------------- #
# Small helpers                                                                #
# --------------------------------------------------------------------------- #
def doer_ids(doc: dict) -> List[str]:
    tsi = doc.get("target_staff_id")
    ids: List[str] = []
    if isinstance(tsi, list):
        ids = [str(x) for x in tsi if x]
    elif tsi:
        ids = [str(tsi)]
    if not ids and doc.get("assigned_to") == "myself" and doc.get("user_id"):
        ids = [str(doc["user_id"])]
    return ids


def is_delegated(doc: dict) -> bool:
    return doc.get("assigned_to") == "other" and bool(doc.get("target_staff_id"))


def _new_stat() -> dict:
    return {
        "assigned": 0, "completed": 0, "pending": 0, "overdue": 0,
        "inProgress": 0, "verification": 0, "onTime": 0, "delayed": 0,
        "_daysSum": 0.0, "_daysCount": 0,
    }


def _apply(stat: dict, doc: dict, now: datetime) -> None:
    ws = _resolve_workflow_status(doc)
    stat["assigned"] += 1
    if ws == "completed":
        stat["completed"] += 1
    else:
        stat["pending"] += 1
    if ws == "in_progress":
        stat["inProgress"] += 1
    elif ws == "verification":
        stat["verification"] += 1
    if _is_overdue(doc, ws, now):
        stat["overdue"] += 1
    timing = _completion_timing(doc)
    if timing == "in_time":
        stat["onTime"] += 1
    elif timing == "delayed":
        stat["delayed"] += 1
    if ws == "completed":
        cdt = _parse_iso(doc.get("completed_at"))
        sdt = _parse_iso(doc.get("start"))
        if cdt and sdt:
            days = (cdt - sdt).total_seconds() / 86400.0
            if days >= 0:
                stat["_daysSum"] += days
                stat["_daysCount"] += 1


def _finalize(stat: dict) -> dict:
    assigned = stat["assigned"]
    completed = stat["completed"]
    completion_rate = (completed / assigned) if assigned else 0.0
    on_time_rate = (stat["onTime"] / completed) if completed else 0.0
    productivity = round((0.6 * completion_rate + 0.4 * on_time_rate) * 100)
    avg_days = (stat["_daysSum"] / stat["_daysCount"]) if stat["_daysCount"] else None
    if productivity >= 85:
        rating = "Excellent"
    elif productivity >= 70:
        rating = "Good"
    elif productivity >= 50:
        rating = "Average"
    else:
        rating = "Needs Attention"
    return {
        "assigned": assigned,
        "completed": completed,
        "pending": stat["pending"],
        "overdue": stat["overdue"],
        "inProgress": stat["inProgress"],
        "verification": stat["verification"],
        "onTime": stat["onTime"],
        "delayed": stat["delayed"],
        "completionRate": round(completion_rate * 100, 1),
        "onTimeRate": round(on_time_rate * 100, 1),
        "score": productivity,
        "rating": rating,
        "avgCompletionDays": round(avg_days, 1) if avg_days is not None else None,
    }


def _month_key(dt: datetime):
    return (dt.year, dt.month), dt.strftime("%b %Y")


# --------------------------------------------------------------------------- #
# Aggregations                                                                 #
# --------------------------------------------------------------------------- #
async def compute_enterprise_overview(tasks: List[dict], users: Dict[str, dict]) -> dict:
    """Org-wide executive KPIs. Entity counts are global; task metrics respect the
    fetched `tasks` window. Reuses existing field conventions:
      * assessment score  -> LearnerAssessments.percentage  (avg)
      * attendance        -> attendance.status == "present" / total
      * sessions          -> calendar events (type=="event")
      * "courses"         -> active session templates (decision: map Courses→templates)
    """
    companies = await get_collection("companies").count_documents({})
    active_batches = await get_collection("batches").count_documents({"status": "active"})
    active_courses = await get_collection("session_templates").count_documents({})

    total_sessions = 0
    for col in SESSION_COLLECTIONS:
        total_sessions += await get_collection(col).count_documents({"type": "event"})

    total_users = len(users)
    total_coaches = sum(1 for u in users.values() if (u.get("role") or "").lower() == "coach")
    total_learners = sum(1 for u in users.values() if u.get("tag") == "learner")

    # average assessment score
    avg_assessment = 0.0
    res = await get_collection("LearnerAssessments").aggregate(
        [{"$group": {"_id": None, "avg": {"$avg": "$percentage"}}}]
    ).to_list(1)
    if res and res[0].get("avg") is not None:
        avg_assessment = round(res[0]["avg"], 1)

    # attendance rate
    att = get_collection("attendance")
    total_att = await att.count_documents({})
    present_att = await att.count_documents({"status": "present"})
    attendance_rate = round(present_att / total_att * 100, 1) if total_att else 0.0

    task_ov = compute_overview(tasks, users)
    return {
        "totalCompanies": companies,
        "totalUsers": total_users,
        "totalCoaches": total_coaches,
        "totalLearners": total_learners,
        "totalSessions": total_sessions,
        "activeBatches": active_batches,
        "activeCourses": active_courses,  # active session templates (Courses mapping)
        "totalTasks": task_ov["totalTasks"],
        "completedTasks": task_ov["completedTasks"],
        "pendingTasks": task_ov["pendingTasks"],
        "avgAssessmentScore": avg_assessment,
        "avgPerformanceScore": task_ov["avgPerformanceScore"],
        "completionRate": task_ov["avgCompletionRate"],
        "attendanceRate": attendance_rate,
    }


def compute_overview(tasks: List[dict], users: Dict[str, dict]) -> dict:
    now = datetime.utcnow()
    total = _new_stat()
    doers, delegators = set(), set()
    for doc in tasks:
        _apply(total, doc, now)
        for d in doer_ids(doc):
            doers.add(d)
        if is_delegated(doc) and doc.get("user_id"):
            delegators.add(str(doc["user_id"]))
    fin = _finalize(total)
    total_employees = sum(1 for u in users.values() if u["tag"] == "staff")
    return {
        "totalEmployees": total_employees,
        "totalDelegators": len(delegators),
        "totalDoers": len(doers),
        "totalTasks": fin["assigned"],
        "assignedTasks": fin["assigned"],
        "completedTasks": fin["completed"],
        "pendingTasks": fin["pending"],
        "overdueTasks": fin["overdue"],
        "avgCompletionRate": fin["completionRate"],
        "avgPerformanceScore": fin["score"],
    }


def _distribution(tasks, keyfn, colormap, labelmap=None):
    counts: Dict[str, int] = {}
    for doc in tasks:
        k = keyfn(doc)
        counts[k] = counts.get(k, 0) + 1
    out = []
    for k, v in counts.items():
        out.append({
            "name": (labelmap.get(k, k) if labelmap else k),
            "key": k,
            "value": v,
            "color": colormap.get(k, "var(--accent-indigo)"),
        })
    return out


def compute_company(tasks: List[dict], users: Dict[str, dict]) -> dict:
    now = datetime.utcnow()
    total = _new_stat()

    # month buckets for trends
    monthly: Dict[tuple, dict] = {}
    growth_cum = 0  # filled after sorting

    for doc in tasks:
        _apply(total, doc, now)

        sdt = _parse_iso(doc.get("start")) or _parse_iso(doc.get("created_at"))
        if sdt:
            sort_key, label = _month_key(sdt)
            b = monthly.setdefault(sort_key, {
                "_sort": sort_key, "name": label,
                "assigned": 0, "completed": 0, "overdue": 0, "onTime": 0, "delayed": 0,
            })
            b["assigned"] += 1
            ws = _resolve_workflow_status(doc)
            if ws == "completed":
                b["completed"] += 1
            if _is_overdue(doc, ws, now):
                b["overdue"] += 1
            timing = _completion_timing(doc)
            if timing == "in_time":
                b["onTime"] += 1
            elif timing == "delayed":
                b["delayed"] += 1

    monthly_list = [dict(v) for v in sorted(monthly.values(), key=lambda x: x["_sort"])]
    for m in monthly_list:
        m.pop("_sort", None)
        a = m["assigned"]
        m["productivity"] = round((m["completed"] / a) * 100) if a else 0
        m["score"] = m["onTime"]
        growth_cum += a
        m["cumulative"] = growth_cum  # Company Growth Trend = cumulative tasks/month

    # department performance
    dept_stats: Dict[str, dict] = {}
    for doc in tasks:
        assigned_depts = set()
        for did in doer_ids(doc):
            dept = users.get(did, {}).get("department", "Other")
            assigned_depts.add(dept)
        if not assigned_depts:
            assigned_depts = {"Unassigned"}
        for dept in assigned_depts:
            st = dept_stats.setdefault(dept, _new_stat())
            _apply(st, doc, now)
    departments = []
    for dept, st in dept_stats.items():
        fin = _finalize(st)
        departments.append({"name": dept, **fin})
    departments.sort(key=lambda d: d["score"], reverse=True)

    fin_total = _finalize(total)
    return {
        "totals": fin_total,
        "monthly": monthly_list,
        "statusDistribution": _distribution(
            tasks, _resolve_workflow_status, STATUS_COLORS, STATUS_LABELS
        ),
        "priorityDistribution": _distribution(
            tasks, lambda d: d.get("priority") or "Normal", PRIORITY_COLORS
        ),
        "departments": departments,
    }


def compute_doers(tasks: List[dict], users: Dict[str, dict]) -> List[dict]:
    now = datetime.utcnow()
    stats: Dict[str, dict] = {}
    for doc in tasks:
        for did in doer_ids(doc):
            _apply(stats.setdefault(did, _new_stat()), doc, now)

    rows = []
    for did, st in stats.items():
        u = users.get(did, {})
        fin = _finalize(st)
        rows.append({
            "id": did,
            "name": u.get("name", "Unknown"),
            "email": u.get("email"),
            "role": u.get("role"),
            "department": u.get("department", "Other"),
            "isActive": u.get("is_active", True),
            **fin,
        })
    rows.sort(key=lambda r: (r["score"], r["completed"]), reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


# --------------------------------------------------------------------------- #
# Employee-Wise (all employees/learners, not just task doers)                  #
# --------------------------------------------------------------------------- #
def _rate(part, total):
    return round(part / total * 100, 1) if total else 0.0


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else 0.0


async def _attendance_by_user(user_ids: List[str]) -> Dict[str, list]:
    if not user_ids:
        return {}
    docs = await get_collection("attendance").find({"user_id": {"$in": user_ids}}).to_list(200000)
    out: Dict[str, list] = {}
    for a in docs:
        out.setdefault(str(a.get("user_id")), []).append(a)
    return out


async def _assessments_by_user(user_ids: List[str]) -> Dict[str, list]:
    if not user_ids:
        return {}
    docs = await get_collection("LearnerAssessments").find({"user_id": {"$in": user_ids}}).to_list(200000)
    out: Dict[str, list] = {}
    for a in docs:
        out.setdefault(str(a.get("user_id")), []).append(a)
    return out


async def _activity_by_user(user_ids: List[str]) -> Dict[str, dict]:
    """Last login, last activity and login count per user — from the real activity_logs feed."""
    if not user_ids:
        return {}
    docs = await get_collection("activity_logs").find(
        {"user_id": {"$in": user_ids}},
        {"user_id": 1, "action": 1, "timestamp": 1},
    ).to_list(300000)
    out: Dict[str, dict] = {}
    for a in docs:
        uid = str(a.get("user_id"))
        ts = a.get("timestamp")
        if ts is None:
            continue
        k = str(ts)  # compare as string to avoid naive/aware datetime TypeErrors
        cur = out.setdefault(uid, {"lastLogin": None, "lastActivity": None, "totalLogins": 0, "_actk": "", "_logk": ""})
        if k > cur["_actk"]:
            cur["_actk"] = k
            cur["lastActivity"] = ts
        if a.get("action") == "User Login":
            cur["totalLogins"] += 1
            if k > cur["_logk"]:
                cur["_logk"] = k
                cur["lastLogin"] = ts
    for v in out.values():
        v.pop("_actk", None)
        v.pop("_logk", None)
    return out


async def compute_employees_wide(tasks: List[dict], users: Dict[str, dict]) -> List[dict]:
    """Every employee/learner (even with zero tasks) with real task + session/attendance +
    assessment + activity metrics merged. Learning Hours omitted (no data source)."""
    now = datetime.utcnow()
    stats: Dict[str, dict] = {}
    for doc in tasks:
        for did in doer_ids(doc):
            _apply(stats.setdefault(did, _new_stat()), doc, now)

    ids = list(users.keys())
    att_by_user = await _attendance_by_user(ids)
    assess_by_user = await _assessments_by_user(ids)
    activity = await _activity_by_user(ids)
    comp_docs = await get_collection("companies").find({}, {"name": 1}).to_list(5000)
    company_names = {str(c["_id"]): (c.get("name") or "Company") for c in comp_docs}

    rows = []
    for uid, u in users.items():
        fin = _finalize(stats.get(uid) or _new_stat())
        att = att_by_user.get(uid, [])
        total_sess = len(att)
        pres = sum(1 for a in att if a.get("status") == "present")
        ass = assess_by_user.get(uid, [])
        act = activity.get(uid, {})
        cid = u.get("company_id")
        rows.append({
            "id": uid,
            "employeeId": u.get("employee_id") or u.get("employeeId") or "",
            "name": u.get("name", "Unknown"),
            "email": u.get("email"),
            "role": u.get("role"),
            "tag": u.get("tag"),
            "department": u.get("department", "Other"),
            "designation": u.get("designation") or "",
            "companyId": cid,
            "company": company_names.get(cid) if cid else None,
            "isActive": u.get("is_active", True),
            # Task performance (real)
            "assigned": fin["assigned"], "completed": fin["completed"],
            "pending": fin["pending"], "overdue": fin["overdue"],
            "completionRate": fin["completionRate"], "score": fin["score"], "rating": fin["rating"],
            # Session / attendance participation (real)
            "totalSessions": total_sess,
            "sessionsAttended": pres,
            "sessionsMissed": total_sess - pres,
            "attendanceRate": _rate(pres, total_sess),
            # Assessment (real)
            "avgAssessment": _avg([x.get("percentage", 0) for x in ass]),
            # Activity (real, from activity_logs)
            "totalLogins": act.get("totalLogins", 0),
            "lastLogin": act.get("lastLogin"),
            "lastActivity": act.get("lastActivity"),
        })
    rows.sort(key=lambda r: (r["score"], r["completed"], r["attendanceRate"]), reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def _ts_key(ts) -> str:
    """Comparable YYYY-MM-DD... key from a datetime or iso string (tz-safe, string compare)."""
    return str(ts) if ts else ""


async def compute_activity(users: Dict[str, dict]) -> dict:
    """Activity report — real login/usage signals from activity_logs + attendance/assessments.
    Learning Time is omitted (no duration data source)."""
    now = datetime.utcnow()
    ids = list(users.keys())
    activity = await _activity_by_user(ids)
    att_by_user = await _attendance_by_user(ids)
    assess_by_user = await _assessments_by_user(ids)
    comp_docs = await get_collection("companies").find({}, {"name": 1}).to_list(5000)
    company_names = {str(c["_id"]): (c.get("name") or "Company") for c in comp_docs}

    cutoff_key = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    rows = []
    active30 = 0
    total_logins = 0
    for uid, u in users.items():
        act = activity.get(uid, {})
        att = att_by_user.get(uid, [])
        ass = assess_by_user.get(uid, [])
        # Last course/learning access = latest attendance date or assessment submission.
        course_dates = [_ts_key(a.get("date")) for a in att]
        course_dates += [_ts_key(x.get("submitted_at")) for x in ass]
        last_course = max([c for c in course_dates if c], default=None)
        last_login = act.get("lastLogin")
        last_activity = act.get("lastActivity")
        logins = act.get("totalLogins", 0)
        total_logins += logins
        latest_key = max(_ts_key(last_activity), _ts_key(last_login), last_course or "")
        is_active = bool(latest_key) and latest_key[:10] >= cutoff_key
        if is_active:
            active30 += 1
        rows.append({
            "id": uid,
            "name": u.get("name", "Unknown"),
            "email": u.get("email"),
            "company": company_names.get(u.get("company_id")) if u.get("company_id") else None,
            "department": u.get("department", "Other"),
            "lastLogin": last_login,
            "lastCourseAccess": last_course,
            "lastActivity": last_activity,
            "loginCount": logins,
            "active": is_active,
        })
    rows.sort(key=lambda r: _ts_key(r["lastActivity"]), reverse=True)
    total_users = len(rows)
    return {
        "summary": {
            "totalUsers": total_users,
            "activeUsers": active30,          # activity within last 30 days
            "inactiveUsers": total_users - active30,
            "totalLogins": total_logins,
        },
        "items": rows,
    }


async def compute_sessions(users: Dict[str, dict]) -> dict:
    """Session report — LMS sessions (calendar events type=event) with attendance + duration."""
    now = datetime.utcnow()
    sessions = []
    for col in SESSION_COLLECTIONS:
        evs = await get_collection(col).find({"type": "event"}).to_list(30000)
        sessions.extend(evs)

    # attendance.session_id does not map to calendar-event _id in this data, so we also index
    # by session_name for a best-effort per-session link. The overall rate uses ALL records.
    att_docs = await get_collection("attendance").find({}).to_list(300000)
    att_by_session: Dict[str, list] = {}
    att_by_name: Dict[str, list] = {}
    overall_present = sum(1 for a in att_docs if a.get("status") == "present")
    overall_total = len(att_docs)
    for a in att_docs:
        att_by_session.setdefault(str(a.get("session_id")), []).append(a)
        if a.get("session_name"):
            att_by_name.setdefault(str(a.get("session_name")).strip().lower(), []).append(a)

    completed = upcoming = missed = 0
    durations = []
    monthly: Dict[tuple, dict] = {}
    rows = []
    for s in sessions:
        sid = str(s["_id"])
        start = _parse_iso(s.get("start"))
        end = _parse_iso(s.get("end"))
        status = s.get("status")
        is_completed = status == "completed"
        if is_completed:
            completed += 1
        elif start and start > now:
            upcoming += 1
        elif start and start <= now:
            missed += 1  # past session not marked completed
        dur = None
        if start and end and end > start:
            dur = (end - start).total_seconds() / 60.0
            durations.append(dur)
        title = (s.get("title") or "Session")
        att = att_by_session.get(sid) or att_by_name.get(title.strip().lower(), [])
        pres = sum(1 for a in att if a.get("status") == "present")
        rows.append({
            "id": sid,
            "name": title,
            "date": s.get("start"),
            "status": status or "scheduled",
            "attended": pres,
            "absent": len(att) - pres,
            "attendanceRate": _rate(pres, len(att)),
            "durationMin": round(dur) if dur is not None else None,
        })
        if start:
            k, label = _month_key(start)
            m = monthly.setdefault(k, {"_s": k, "name": label, "sessions": 0, "completed": 0})
            m["sessions"] += 1
            if is_completed:
                m["completed"] += 1
    rows.sort(key=lambda r: _ts_key(r["date"]), reverse=True)
    return {
        "summary": {
            "totalSessions": len(sessions),
            "completedSessions": completed,
            "upcomingSessions": upcoming,
            "missedSessions": missed,
            "attendanceRate": _rate(overall_present, overall_total),
            "avgDurationMin": round(sum(durations) / len(durations)) if durations else None,
        },
        "monthly": [{"name": m["name"], "sessions": m["sessions"], "completed": m["completed"]}
                    for m in sorted(monthly.values(), key=lambda x: x["_s"])],
        "items": rows,
    }


def _task_module(doc: dict) -> str:
    return doc.get("category") or "Task"


def _per_task_score(doc: dict) -> Optional[int]:
    timing = _completion_timing(doc)
    if timing == "in_time":
        return 100
    if timing == "delayed":
        return 60
    if _resolve_workflow_status(doc) == "completed":
        return 80  # completed but no due date to judge timeliness
    return None


def doer_task_rows(tasks: List[dict], doer_id: str, users: Dict[str, dict]) -> List[dict]:
    now = datetime.utcnow()
    rows = []
    for doc in tasks:
        if doer_id not in doer_ids(doc):
            continue
        ws = _resolve_workflow_status(doc)
        assigner_id = str(doc.get("user_id")) if doc.get("user_id") else None
        rows.append({
            "id": str(doc["_id"]),
            "title": doc.get("title"),
            "module": _task_module(doc),
            "assignedBy": users.get(assigner_id, {}).get("name") if assigner_id else "—",
            "assignedDate": doc.get("start") or doc.get("created_at"),
            "dueDate": doc.get("end"),
            "startedDate": None,   # no started_at in data model (v1)
            "completedDate": doc.get("completed_at"),
            "approvedDate": None,  # no approval workflow (v1)
            "status": ws,
            "statusLabel": STATUS_LABELS.get(ws, ws),
            "priority": doc.get("priority") or "Normal",
            "isOverdue": _is_overdue(doc, ws, now),
            "completionTiming": _completion_timing(doc),
            "score": _per_task_score(doc),
        })
    rows.sort(key=lambda r: (r["assignedDate"] or ""), reverse=True)
    return rows


def compute_doer_detail(tasks: List[dict], doer_id: str, users: Dict[str, dict]) -> dict:
    now = datetime.utcnow()
    st = _new_stat()
    monthly: Dict[tuple, dict] = {}
    for doc in tasks:
        if doer_id not in doer_ids(doc):
            continue
        _apply(st, doc, now)
        cdt = _parse_iso(doc.get("completed_at")) or _parse_iso(doc.get("start"))
        if cdt:
            sort_key, label = _month_key(cdt)
            b = monthly.setdefault(sort_key, {
                "_sort": sort_key, "name": label,
                "assigned": 0, "completed": 0, "onTime": 0, "delayed": 0, "score": 0,
            })
            b["assigned"] += 1
            ws = _resolve_workflow_status(doc)
            if ws == "completed":
                b["completed"] += 1
            timing = _completion_timing(doc)
            if timing == "in_time":
                b["onTime"] += 1
                b["score"] += 1
            elif timing == "delayed":
                b["delayed"] += 1

    trends = [dict(v) for v in sorted(monthly.values(), key=lambda x: x["_sort"])]
    for m in trends:
        m.pop("_sort", None)

    u = users.get(doer_id, {})
    fin = _finalize(st)
    return {
        "employee": {
            "id": doer_id,
            "name": u.get("name", "Unknown"),
            "email": u.get("email"),
            "role": u.get("role"),
            "department": u.get("department", "Other"),
            "designation": u.get("designation"),
            "isActive": u.get("is_active", True),
        },
        "summary": {
            **fin,
            # v1: no approve/reject states in the workflow
            "approved": 0,
            "rejected": 0,
        },
        "trends": trends,
    }


async def build_timeline(task_id: str, source_col: Optional[str], doc: dict) -> List[dict]:
    """Reconstruct a best-effort per-task timeline (v1 = no started/approved capture).

    Events come from: created_at (Assigned), activity_logs status changes,
    completed_at (Completed).
    """
    events: List[dict] = []
    if doc.get("created_at"):
        events.append({"label": "Assigned", "at": _iso(doc.get("created_at")), "status": "assigned"})

    # status-change history lives as free text in activity_logs.details
    logs = await get_collection("activity_logs").find({
        "action": "Update Task Status",
        "details": {"$regex": task_id},
    }).to_list(200)
    for lg in logs:
        details = lg.get("details", "") or ""
        to_status = details.split("->")[-1].strip() if "->" in details else None
        events.append({
            "label": STATUS_LABELS.get(to_status, (to_status or "Status change").replace("_", " ").title()),
            "at": _iso(lg.get("timestamp")),
            "status": to_status,
            "by": lg.get("user_name"),
        })

    if doc.get("completed_at"):
        events.append({"label": "Completed", "at": _iso(doc.get("completed_at")), "status": "completed"})

    events = [e for e in events if e["at"]]
    events.sort(key=lambda e: e["at"])
    # de-dup consecutive identical (status, at)
    deduped = []
    for e in events:
        if deduped and deduped[-1]["status"] == e["status"] and deduped[-1]["at"] == e["at"]:
            continue
        deduped.append(e)
    return deduped


def _iso(value) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, str):
        return value
    try:
        return value.isoformat()
    except Exception:
        return str(value)
