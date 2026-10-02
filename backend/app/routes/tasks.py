from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import Optional
from datetime import datetime, timedelta, timezone
from bson import ObjectId
import asyncio
import json
import re
import uuid

from app.db.mongodb import get_collection
from app.controllers.auth_controller import (
    get_user_from_token, require_task_access,
    has_task_access, is_client_side_user,
    TASK_ACCESS_DENIED_MESSAGE, DELEGATION_DISABLED_MESSAGE,
    get_ineligible_recipient_ids, recipient_denied_message,
    get_rank_ineligible_assignees, ASSIGN_RANK_DENIED_MESSAGE,
    ADMIN_TIER, client_rank, CLIENT_RANK,
    company_admin_company_id, is_company_task_admin,
)
from app.utils.calendar_utils import CALENDAR_COLLECTIONS, find_event_across_collections
from app.services.activity_log_service import log_activity
from app.services.s3_service import upload_file_to_s3_with_key
from app.routes.group import _is_member_or_manager
from app.services import task_events
from app.services.task_logs_service import get_task_logs_report
from app.services.task_notifications import notify_task_event

router = APIRouter(prefix="/tasks", tags=["Tasks"])

# calendar_event docs with type=="task" live in the same collections as calendar events
TASK_COLLECTIONS = CALENDAR_COLLECTIONS + ["calendar_events"]
ADMIN_ROLES = ["superadmin", "admin", "coach", "staff"]

# Only Super Admin + Sparsh Admin may see ALL tasks / the system-wide total. Every other
# internal user (coach/staff/SMO/member/…) sees only their own related tasks. This is
# deliberately narrower than ADMIN_ROLES, and role-based rather than permission-based, so a
# default `calendar.read`/`tasks.read` grant can't leak org-wide task data.
VIEW_ALL_ROLES = {"superadmin", "admin"}


def _can_view_all_tasks(user: dict) -> bool:
    if (user.get("role") or "").lower() in VIEW_ALL_ROLES:
        return True
    # Optional explicit grant for a specific non-admin who should see everything.
    return bool(user.get("permissions", {}).get("tasks", {}).get("view_all_tasks"))


# ── Internal vs client task separation ───────────────────────────────────────────
# The two environments are fully independent: an internal Sparsh task is never visible to
# client users, and a client task is never visible to internal Sparsh users (not even an
# internal Super Admin/Admin). Client-created tasks carry notification_scope='company' (and
# usually a company_id); internal tasks are 'staff'/unset with no company_id.
def _is_client_task(task: dict) -> bool:
    return (task.get("notification_scope") == "company"
            or bool(str(task.get("company_id") or "").strip()))

# Mongo clause selecting ONLY internal tasks (no company scope, no company_id) — used to keep
# the internal "all tasks" view from ever returning client-company tasks.
_INTERNAL_TASK_CLAUSE = {"notification_scope": {"$ne": "company"},
                         "company_id": {"$in": [None, ""]}}

# Richer workflow taken on by type=="task" docs. The legacy `status` field
# (schedule/completed/canceled/reschedule) stays authoritative for the Calendar page.
# "in_progress_reopened" is only reached via the assigner's Reopen action on a task that
# went to verification — never a directly-picked status.
# ─── Deadline revision cap ───
# A deadline may be moved twice, and no more. Past that the date stands: a task whose deadline
# can keep sliding has no deadline. Counted over `deadline_history`, so it covers BOTH ways a
# revision can happen — the assigner revising directly and an assignee's request being approved.
#
# A Reopen is exempt. It sets a new deadline as part of sending work back for rework (see the
# Reopen flow in TaskDetailsModal), so counting it would let two revisions strand the assigner
# with a task they can no longer reopen. Those entries are stamped kind="reopen".
MAX_DEADLINE_REVISIONS = 2

WORKFLOW_STATUSES = [
    "pending", "accepted", "in_progress", "dependent_on_others",
    "blocked", "verification", "completed", "in_progress_reopened",
    # Set by the system only, when a dependency doer finishes their part: the task goes back to
    # the assignee who delegated it, who reviews it and performs the final completion. It is an
    # OPEN state — the task is not done and can still run overdue.
    "dependency_completed",
]


def _period_to_range(period: Optional[str], start_date: Optional[str], end_date: Optional[str]):
    """Returns (start_iso, end_iso) or (None, None) meaning 'all time'."""
    now = datetime.utcnow()
    today = now.date()

    def day_bounds(d):
        start = datetime(d.year, d.month, d.day)
        end = start + timedelta(days=1) - timedelta(microseconds=1)
        return start, end

    if period == "custom":
        if start_date and end_date:
            return start_date, end_date
        return None, None

    if period == "today":
        s, e = day_bounds(today)
    elif period == "yesterday":
        s, e = day_bounds(today - timedelta(days=1))
    elif period == "this_week":
        monday = today - timedelta(days=today.weekday())
        s, _ = day_bounds(monday)
        _, e = day_bounds(monday + timedelta(days=6))
    elif period == "last_week":
        monday = today - timedelta(days=today.weekday() + 7)
        s, _ = day_bounds(monday)
        _, e = day_bounds(monday + timedelta(days=6))
    elif period == "this_month":
        first = today.replace(day=1)
        next_month = (first + timedelta(days=32)).replace(day=1)
        s, _ = day_bounds(first)
        _, e = day_bounds(next_month - timedelta(days=1))
    elif period == "last_month":
        first_this = today.replace(day=1)
        last_month_end = first_this - timedelta(days=1)
        s, _ = day_bounds(last_month_end.replace(day=1))
        _, e = day_bounds(last_month_end)
    elif period == "this_year":
        s, _ = day_bounds(today.replace(month=1, day=1))
        _, e = day_bounds(today.replace(month=12, day=31))
    else:
        # all_time / unspecified
        return None, None

    return s.isoformat(), e.isoformat()


def _resolve_workflow_status(doc: dict) -> str:
    """A task's working status. Nothing resolves to "pending".

    A task begins In Progress the moment it is raised (calendar_events.create_event), and
    Pending is not one of the statuses anyone can choose (SELECTABLE_STATUSES), so it only
    ever arose two ways: a document written before `workflow_status` existed, and a handful of
    rows that stored the old default. Both are the same thing in practice — work that has been
    handed over and not yet finished — so both read as In Progress rather than sitting in a
    state the task pages no longer even show a card for.

    Read-side only: the stored value is left exactly as it is.
    """
    ws = doc.get("workflow_status")
    if ws in WORKFLOW_STATUSES and ws != "pending":
        return ws
    # Legacy fallback for tasks created before workflow_status existed
    if doc.get("status") == "completed":
        return "completed"
    return "in_progress"


def _parse_iso(value):
    if not value:
        return None
    try:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        return value.replace(tzinfo=None) if value.tzinfo else value
    except Exception:
        return None


def _is_overdue(doc: dict, workflow_status: str, now: datetime) -> bool:
    if workflow_status == "completed":
        return False
    due_dt = _parse_iso(doc.get("end") or doc.get("start"))
    if not due_dt:
        return False
    return due_dt < now


def _completion_timing(doc: dict) -> Optional[str]:
    """Returns 'in_time' | 'delayed' | None (not completed, or no due date to compare against)."""
    if _resolve_workflow_status(doc) != "completed":
        return None
    completed_dt = _parse_iso(doc.get("completed_at"))
    due_dt = _parse_iso(doc.get("end") or doc.get("start"))
    if not completed_dt or not due_dt:
        return None
    return "in_time" if completed_dt <= due_dt else "delayed"


def _visibility_clauses(user_id: str):
    return [
        {"user_id": user_id},
        {"target_staff_id": user_id},
        {"target_staff_id": {"$in": [user_id]}},
        {"watchers": user_id},
        {"watchers": {"$in": [user_id]}},
    ]


async def _fetch_tasks(
    current_user: dict,
    scope: str,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    frequency: Optional[str] = None,
    assigned_to: Optional[str] = None,
    search: Optional[str] = None,
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
    group_id: Optional[str] = None,
):
    user_id = str(current_user["_id"])

    clauses = [{"type": "task"}]

    if start_iso and end_iso:
        clauses.append({"start": {"$gte": start_iso, "$lte": end_iso}})

    if scope == "my":
        clauses.append({"$or": [
            {"target_staff_id": user_id},
            {"target_staff_id": {"$in": [user_id]}},
            {"$and": [{"user_id": user_id}, {"assigned_to": "myself"}]},
        ]})
    elif scope == "delegated":
        clauses.append({"user_id": user_id})
        clauses.append({"assigned_to": "other"})
    elif scope == "subscribed":
        clauses.append({"$or": [{"watchers": user_id}, {"watchers": {"$in": [user_id]}}]})
    elif scope == "own":
        # Everything the user is related to: created ∪ assigned ∪ in-loop.
        clauses.append({"$or": _visibility_clauses(user_id)})
    elif scope == "all":
        # Only Super Admin + Sparsh Admin see every task system-wide. Everyone else silently
        # falls back to their own tasks (no 403), so "All Tasks" never leaks others' data.
        if not _can_view_all_tasks(current_user):
            vis = _visibility_clauses(user_id)
            # A reporting manager additionally sees tasks assigned to their direct reports
            # (same environment, so no cross-wall leak).
            report_ids = await _direct_report_ids(current_user)
            if report_ids:
                vis = vis + [{"target_staff_id": {"$in": report_ids}}]
            # A client user additionally sees whatever their governance rank entitles them to
            # (today: an MD sees their whole company). Unioned in, never replacing the two
            # rules above — see _company_admin_clauses.
            vis = vis + _company_admin_clauses(current_user)
            clauses.append({"$or": vis})
        else:
            # Internal admins see every INTERNAL task, but NEVER client-company tasks — the two
            # environments stay fully separate.
            clauses.append(_INTERNAL_TASK_CLAUSE)
    elif scope == "group":
        if not group_id:
            raise HTTPException(status_code=400, detail="group_id is required for group scope")
        group_doc = await get_collection("task_groups").find_one({"_id": ObjectId(group_id)})
        if not group_doc:
            raise HTTPException(status_code=404, detail="Group not found")
        if not _is_member_or_manager(group_doc, current_user):
            raise HTTPException(status_code=403, detail="Not authorized to view this group's tasks")
        # No user-restricting clause -- membership is already verified above, and the
        # generic `if group_id:` clause below scopes results to this group's tasks.
    elif scope == "deleted":
        if not _can_view_all_tasks(current_user):
            # An MD may restore any of their company's tasks, so the Deleted view has to show
            # them — otherwise they hold the authority with nothing to use it on.
            clauses.append({"$or": _visibility_clauses(user_id) + _company_admin_clauses(current_user)})
        else:
            clauses.append(_INTERNAL_TASK_CLAUSE)
    else:
        raise HTTPException(status_code=400, detail="Invalid scope")

    clauses.append({"deleted_at": {"$ne": None}} if scope == "deleted" else {"deleted_at": None})

    if category:
        clauses.append({"category": category})
    if frequency:
        clauses.append({"repeat": frequency})
    if tag:
        clauses.append({"tags": {"$in": [tag]}})
    if group_id:
        clauses.append({"group_id": group_id})
    if assigned_to:
        clauses.append({"$or": [
            {"target_staff_id": assigned_to},
            {"target_staff_id": {"$in": [assigned_to]}},
            {"$and": [{"user_id": assigned_to}, {"assigned_to": "myself"}]},
        ]})
    if search:
        clauses.append({"title": {"$regex": search, "$options": "i"}})

    query = {"$and": clauses}

    results = []
    for col_name in TASK_COLLECTIONS:
        docs = await get_collection(col_name).find(query).to_list(2000)
        for d in docs:
            d["_source_col"] = col_name
            results.append(d)
    # Latest-created first everywhere the task list is used. ObjectId encodes creation
    # time, so this holds even for a doc with a missing/malformed `created_at`.
    results.sort(key=lambda d: d["_id"], reverse=True)
    return results


def _pending_deadline_request(doc: dict) -> Optional[dict]:
    """The assignee's deadline revision request still awaiting the assigner's verdict, or None.
    At most one can be pending: raising a new one supersedes whatever was outstanding."""
    for req in reversed(doc.get("deadline_requests") or []):
        if isinstance(req, dict) and req.get("status") == "pending":
            return req
    return None


def _deadline_revision_count(doc: dict) -> int:
    """How many of this task's MAX_DEADLINE_REVISIONS have been used. Reopens don't count."""
    return len([
        h for h in (doc.get("deadline_history") or [])
        if isinstance(h, dict) and h.get("kind") != "reopen"
    ])


def _serialize_task(doc: dict, current_user_id: str, report_ids: set = None,
                    admin_company_id: str = None) -> dict:
    ws = _resolve_workflow_status(doc)
    now = datetime.utcnow()
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title"),
        "type": doc.get("type"),
        "start": doc.get("start"),
        "end": doc.get("end"),
        "category": doc.get("category"),
        "tags": doc.get("tags") or [],
        "frequency": doc.get("repeat"),
        "repeatEndDate": doc.get("repeat_end_date"),
        "repeatInterval": doc.get("repeat_interval") or 1,
        "repeatData": doc.get("repeat_data"),
        "priority": doc.get("priority") or "Normal",
        "description": doc.get("description"),
        "createdAt": doc.get("created_at"),
        "status": ws,
        "isOverdue": _is_overdue(doc, ws, now),
        "completionTiming": _completion_timing(doc),
        "assignedTo": doc.get("target_staff_id") or [],
        "assignedBy": doc.get("user_id"),
        "watchers": doc.get("watchers") or [],
        "groupId": doc.get("group_id"),
        "parentTaskId": doc.get("parent_task_id"),
        "recurringGroupId": doc.get("recurring_group_id"),
        "isCreator": doc.get("user_id") == current_user_id,
        # True when the viewer is the reporting manager of one of this task's assignees — so the
        # list dropdown shows them the VERIFIER options (Complete / Approve), not "Request for
        # Verification". Uses a pre-fetched report_ids set, so there's no per-row DB query.
        "isReportingManager": bool(report_ids) and not doc.get("user_id") == current_user_id
        and bool({str(a) for a in (doc.get("target_staff_id") or [])} & (report_ids or set())),
        # Same purpose as isReportingManager, for a company MD: the UI gates Edit / Delete /
        # Verify on role names a client MD ("clientadmin") isn't part of, so it needs the flag.
        # Uses a pre-resolved company id, so there's no per-row work here either.
        "isCompanyAdmin": bool(admin_company_id)
        and str(doc.get("company_id") or "") == admin_company_id,
        "deletedAt": doc.get("deleted_at"),
        # Exposed on the list payload too (not just detail) so list dropdowns can apply the
        # verification-aware labels / role-based options without a second fetch.
        "verificationRequired": doc.get("verification_required", False),
        "evidenceRequired": doc.get("evidence_required", False),
        # Follow-up count on the list payload too, so rows can show a badge without a detail fetch.
        "followUpCount": len(doc.get("follow_ups") or []),
        # "Dependent on Other" hand-off: who currently holds the dependency (None when nobody
        # does), and how deep the chain runs. The holder owns ONLY the dependency, so their status
        # options are limited to Complete / Dependent on Other / Revise (see statusConfig.js);
        # everyone else on the task keeps seeing it parked at "Dependent on Other".
        "dependencyDoerId": doc.get("dependency_doer_id"),
        "dependencyDepth": len(doc.get("dependency_stack") or []),
        # True while an assignee's deadline revision request is waiting on the assigner, so a
        # row can badge it without fetching the detail payload.
        "hasPendingDeadlineRequest": _pending_deadline_request(doc) is not None,
    }


async def _user_names(user_ids: list) -> dict:
    """user_id -> display name. Looks in both staff and learners, so a company user's name
    resolves too once their company has the Delegation module. Used for dependency history notes."""
    oids = [ObjectId(uid) for uid in user_ids if ObjectId.is_valid(uid)]
    if not oids:
        return {}
    names = {}
    for col_name in ("staff", "learners"):
        docs = await get_collection(col_name).find({"_id": {"$in": oids}}).to_list(1000)
        for d in docs:
            names.setdefault(
                str(d["_id"]),
                d.get("full_name") or d.get("first_name") or d.get("email") or "Unknown",
            )
    return names


async def _fetch_subtasks(parent_id: str, current_user_id: str, admin_company_id: str = None):
    """Child tasks (parent_task_id == parent_id) across the task collections, oldest first."""
    out = []
    for col_name in TASK_COLLECTIONS:
        docs = await get_collection(col_name).find({
            "type": "task", "parent_task_id": parent_id, "deleted_at": None,
        }).to_list(500)
        for d in docs:
            out.append(_serialize_task(d, current_user_id, None, admin_company_id))
    out.sort(key=lambda t: str(t.get("createdAt") or ""))
    return out


def _serialize_task_detail(doc: dict, current_user_id: str) -> dict:
    base = _serialize_task(doc, current_user_id)
    base.update({
        "evidenceRequired": doc.get("evidence_required", False),
        "verificationRequired": doc.get("verification_required", False),
        "color": doc.get("color"),
        "checklist": doc.get("checklist") or [],
        "attachments": doc.get("attachments") or [],
        "completionAttachments": doc.get("completion_attachments") or [],
        "remarks": doc.get("remarks") or [],
        "statusHistory": doc.get("status_history") or [],
        # Who actually closed the task out, and when. On a verification-required task that is
        # the assigner approving it, not the assignee who submitted it — which is exactly the
        # distinction the Involved Parties card exists to make.
        "completedBy": doc.get("completed_by"),
        "completedAt": doc.get("completed_at"),
        "deadlineHistory": doc.get("deadline_history") or [],
        # Deadline revision requests raised by assignees: the whole trail (so the decisions stay
        # auditable) plus the one still awaiting a verdict, which is what the UI acts on.
        "deadlineRequests": doc.get("deadline_requests") or [],
        "pendingDeadlineRequest": _pending_deadline_request(doc),
        # The revision budget, so the UI can retire the Revise action on its own instead of
        # offering a calendar that the backend will refuse.
        "deadlineRevisionCount": _deadline_revision_count(doc),
        "deadlineRevisionLimit": MAX_DEADLINE_REVISIONS,
        "followUps": doc.get("follow_ups") or [],
        "followUpCount": len(doc.get("follow_ups") or []),
        # Reminders are written by the task form (POST /calendar/events stores them on the
        # event doc) but the detail response never carried them back, so the View screen had
        # nothing to render. Read-side only — the write path is unchanged.
        "reminders": doc.get("reminders") or [],
    })
    return base


def _is_participant(existing: dict, current_user: dict) -> bool:
    """Creator, admin, assignee, or watcher — the set of people allowed to collaborate
    on a task (add checklist items, comment, attach files), broader than who can edit
    the core task fields or change its status."""
    user_id = str(current_user["_id"])
    # The Super Admin oversight bypass applies to INTERNAL tasks only — a client task is never
    # visible to internal Sparsh, so it must fall through to genuine participant membership.
    if current_user.get("role") == "superadmin" and not _is_client_task(existing):
        return True
    # The client-side equivalent: a company's MD participates in every task of that company.
    if is_company_task_admin(existing, current_user):
        return True
    if existing.get("user_id") == user_id:
        return True
    if user_id in (existing.get("target_staff_id") or []):
        return True
    if user_id in (existing.get("watchers") or []):
        return True
    return False


# ── Client governance authority ──────────────────────────────────────────────────
# Client-side access follows the company's governance ladder (MD > HR > HOD > Implementor,
# see auth_controller.client_rank), layered on top of — never instead of — the personal
# access every user already has (created / assigned / in-loop) and the reporting-manager rule
# below. Visibility is the UNION of all three, expressed as one Mongo $or.
#
# Rolling out one rank at a time. Implemented so far:
#   MD (governance_role == "MD", or role == "clientadmin") → full admin over their own
#   company's tasks: sees them all, and acts on them all. The client-side counterpart of the
#   internal Super Admin bypass, bounded by company instead of by the whole system.
# Every other rank returns None here and keeps exactly the access it has today.
#
# The predicate itself lives in auth_controller (is_company_task_admin) because
# calendar_events.py needs the same test for task edit/delete.
def _company_admin_clauses(user: dict) -> list:
    """Mongo $or arm giving a client MD every task in their own company.

    Matching the task's own `company_id` is what keeps SELF-ASSIGNED tasks in the result:
    those carry assigned_to == "myself" and can have an empty target_staff_id (see the "my"
    scope above), so an assignee-based match would silently drop them. It also makes company
    isolation structural — a task from another company can never satisfy the clause.
    """
    company_id = company_admin_company_id(user)
    return [{"company_id": company_id}] if company_id else []


# ── Reporting-Manager hierarchy ──────────────────────────────────────────────────
# A user's reporting manager (users.reporting_manager = the manager's id) can additionally
# see and verify tasks assigned to that user. Same environment only (internal manager ↔ staff
# reports; client manager ↔ same-company reports), so this never crosses the internal/client
# wall. Null reporting_manager → no manager, behaves exactly as before.
async def _direct_report_ids(user: dict) -> list:
    """Ids of users who report directly to `user`, within the same environment."""
    uid = str(user.get("_id") or "")
    if not uid:
        return []
    coll = "learners" if is_client_side_user(user) else "staff"
    query = {"reporting_manager": uid, "is_active": {"$ne": False}}
    if is_client_side_user(user) and user.get("company_id"):
        query["company_id"] = str(user["company_id"])
    docs = await get_collection(coll).find(query, {"_id": 1}).to_list(2000)
    return [str(d["_id"]) for d in docs]


async def _is_manager_of_assignee(task: dict, user: dict) -> bool:
    """True if `user` is the reporting manager of any assignee on `task` (same environment)."""
    uid = str(user.get("_id") or "")
    assignees = [str(a) for a in (task.get("target_staff_id") or []) if a]
    if not uid or not assignees:
        return False
    oids = []
    for a in assignees:
        try:
            oids.append(ObjectId(a))
        except Exception:
            pass
    if not oids:
        return False
    coll = "learners" if is_client_side_user(user) else "staff"
    doc = await get_collection(coll).find_one(
        {"_id": {"$in": oids}, "reporting_manager": uid}, {"_id": 1})
    return doc is not None


async def _manager_ids_for_task(task: dict) -> set:
    """Reporting-manager ids of the task's assignees. They monitor and verify the task, so the
    verification request (and other real-time status events) reach them alongside the assigner."""
    assignees = [str(a) for a in (task.get("target_staff_id") or []) if a]
    if not assignees:
        return set()
    oids = []
    for a in assignees:
        try:
            oids.append(ObjectId(a))
        except Exception:
            pass
    out: set = set()
    if not oids:
        return out
    for coll in ("staff", "learners"):
        async for u in get_collection(coll).find(
                {"_id": {"$in": oids}}, {"reporting_manager": 1}):
            mgr = str(u.get("reporting_manager") or "").strip()
            if mgr:
                out.add(mgr)
    return out


async def _get_task_or_404(task_id: str):
    existing, col_name = await find_event_across_collections(task_id)
    if not existing or existing.get("type") != "task":
        raise HTTPException(status_code=404, detail="Task not found")
    return existing, col_name


@router.get("/dashboard")
async def tasks_dashboard(
    period: Optional[str] = None,
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    assignedTo: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    frequency: Optional[str] = None,
    search: Optional[str] = None,
    viewType: Optional[str] = None,
    reportType: Optional[str] = None,
    current_user: dict = Depends(require_task_access),
):
    # reportType picks which visibility scope backs the numbers. Only Super Admin + Sparsh
    # Admin get the org-wide "all" view; every other internal user's totals/analytics are
    # scoped to their own related tasks (created ∪ assigned ∪ in-loop) via the "own" scope.
    scope_map = {"delegated": "delegated", "my_report": "my"}
    scope = scope_map.get(reportType, "all" if _can_view_all_tasks(current_user) else "own")

    start_iso, end_iso = _period_to_range(period, startDate, endDate)
    docs = await _fetch_tasks(current_user, scope, category, tag, frequency, assignedTo, search, start_iso, end_iso)

    now = datetime.utcnow()
    summary = {
        "totalTasks": 0, "overdue": 0, "pending": 0, "accepted": 0,
        "dependentOnOthers": 0, "blocked": 0, "inProgress": 0,
        "verification": 0, "completed": 0, "inTime": 0, "delayed": 0,
    }
    # A reopened task is in progress again — the status only records that it has been round
    # once. Without this it fell through to the default bucket and was counted as work nobody
    # had started. The default is the same bucket for the same reason: every task has to land
    # on a card the page actually shows, and "pending" is no longer one of them.
    status_key_map = {
        "pending": "pending", "accepted": "accepted", "in_progress": "inProgress",
        "in_progress_reopened": "inProgress",
        # The dependency is done but the task is not — it sits with the assignee, who still has
        # to review and close it, so it belongs on the In Progress card.
        "dependency_completed": "inProgress",
        "dependent_on_others": "dependentOnOthers", "blocked": "blocked",
        "verification": "verification", "completed": "completed",
    }

    monthly_buckets = {}

    for doc in docs:
        ws = _resolve_workflow_status(doc)
        summary["totalTasks"] += 1
        summary[status_key_map.get(ws, "inProgress")] += 1
        if _is_overdue(doc, ws, now):
            summary["overdue"] += 1
        timing = _completion_timing(doc)
        if timing == "in_time":
            summary["inTime"] += 1
        elif timing == "delayed":
            summary["delayed"] += 1

        start_dt = _parse_iso(doc.get("start"))
        if not start_dt:
            continue
        month_key = start_dt.strftime("%B %Y")
        bucket = monthly_buckets.setdefault(month_key, {
            "month": month_key, "_sort": (start_dt.year, start_dt.month),
            "total": 0, "score": 0, "overdue": 0, "pending": 0,
            "inProgress": 0, "inTime": 0, "delayed": 0,
        })
        bucket["total"] += 1
        if ws == "pending":
            bucket["pending"] += 1
        elif ws == "in_progress":
            bucket["inProgress"] += 1
        if _is_overdue(doc, ws, now):
            bucket["overdue"] += 1
        if timing == "in_time":
            bucket["inTime"] += 1
            bucket["score"] += 1  # No existing "score" definition in the codebase; defaults to in-time count.
        elif timing == "delayed":
            bucket["delayed"] += 1

    monthly = sorted(monthly_buckets.values(), key=lambda b: b["_sort"])
    for b in monthly:
        b.pop("_sort", None)

    return {"summary": summary, "monthly": monthly}


@router.get("")
async def list_tasks(
    scope: str = Query("my"),
    category: Optional[str] = None,
    tag: Optional[str] = None,
    frequency: Optional[str] = None,
    assignedTo: Optional[str] = None,
    search: Optional[str] = None,
    period: Optional[str] = None,
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    groupId: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, ge=1, le=200),
    current_user: dict = Depends(require_task_access),
):
    """Tasks for a scope.

    Pagination is OPT-IN via `limit`, and that is deliberate rather than a half-migration:
    the dashboard's chart panels aggregate over the whole result set (totals, donuts, the
    monthly report), so forcing a page on them would silently make every chart wrong. Callers
    that render a LIST pass skip/limit and get `{tasks, total}`; callers that AGGREGATE omit
    limit and get the plain array they always got.

    The slice happens after the merge/sort rather than in the query because `_fetch_tasks`
    unions several collections and orders the combined result in Python — a per-collection
    skip/limit would page each one independently and interleave them wrongly.
    """
    start_iso, end_iso = _period_to_range(period, startDate, endDate)
    docs = await _fetch_tasks(current_user, scope, category, tag, frequency, assignedTo, search, start_iso, end_iso, groupId)
    user_id = str(current_user["_id"])
    # Which of these tasks belong to the viewer's direct reports (computed once) — so the list
    # can flag them and show the manager the verifier controls instead of "Request for Verification".
    report_ids = set(await _direct_report_ids(current_user))
    # Resolved once for the same reason as report_ids — the rows only need a string compare.
    admin_company_id = company_admin_company_id(current_user)

    if limit is None:
        return [_serialize_task(d, user_id, report_ids, admin_company_id) for d in docs]

    total = len(docs)
    # Serialize only the page — the expensive per-row work is skipped for everything else.
    page = docs[skip:skip + limit]
    return {
        "tasks": [_serialize_task(d, user_id, report_ids, admin_company_id) for d in page],
        "total": total,
    }


# Actions written to `activity_logs` that represent task lifecycle events (see log_activity
# calls in this file and the task-typed calendar_events create/update). The Activity feed is
# scoped to exactly these so it stays task-specific and doesn't pull in session/auth logs.
TASK_ACTIVITY_ACTIONS = [
    "Create Task", "Create Recurring Tasks", "Update Task", "Update Task Status",
    "Add Sub Task", "Comment on Task", "Attach File to Task",
    "Soft Delete Task", "Restore Task",
]


@router.get("/activity")
async def tasks_activity(
    period: Optional[str] = None,
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    updatedBy: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 30,
    skip: int = 0,
    groupId: Optional[str] = None,
    current_user: dict = Depends(require_task_access),
):
    """Task Management activity feed, read from the shared `activity_logs` collection.
    Admins/staff see the whole org's task activity (and can filter by user); everyone else
    only ever sees their own -- UNLESS `groupId` is given (Group workspace's Timeline tab),
    in which case any member of that group sees the whole group's task activity uniformly,
    via `metadata.group_id` (populated by log_activity's `meta=` at the task-lifecycle call
    sites). Supports date-range, updated-by, search and pagination, and returns a per-user
    summary for the dashboard cards."""
    col = get_collection("activity_logs")
    query = {"action": {"$in": TASK_ACTIVITY_ACTIONS}}

    if groupId:
        group_doc = await get_collection("task_groups").find_one({"_id": ObjectId(groupId)})
        if not group_doc:
            raise HTTPException(status_code=404, detail="Group not found")
        if not _is_member_or_manager(group_doc, current_user):
            raise HTTPException(status_code=403, detail="Not authorized to view this group's activity")
        query["metadata.group_id"] = groupId
    elif not _can_view_all_tasks(current_user):
        # Only Super Admin + Sparsh Admin see the whole org's task activity; others see only their own.
        query["user_id"] = str(current_user["_id"])
    elif updatedBy:
        query["user_id"] = updatedBy

    # Date range on `timestamp` (a real datetime, unlike the ISO-string task dates), so we
    # convert _period_to_range's ISO output back into tz-aware UTC bounds for the comparison.
    start_iso, end_iso = _period_to_range(period, startDate, endDate)
    if start_iso and end_iso:
        try:
            start_dt = datetime.fromisoformat(start_iso)
            end_dt = datetime.fromisoformat(end_iso)
            if len(end_iso) <= 10:  # custom date-only end → include the whole day
                end_dt = end_dt + timedelta(days=1) - timedelta(microseconds=1)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            query["timestamp"] = {"$gte": start_dt, "$lte": end_dt}
        except Exception:
            pass

    if search:
        rgx = {"$regex": re.escape(search.strip()), "$options": "i"}
        query["$or"] = [{"action": rgx}, {"details": rgx}, {"user_name": rgx}]

    total = await col.count_documents(query)
    docs = await col.find(query).sort("timestamp", -1).skip(max(0, skip)).limit(max(1, min(limit, 100))).to_list(100)

    # Per-user activity counts over the whole filtered set (not just the current page).
    agg = await col.aggregate([
        {"$match": query},
        {"$group": {"_id": {"user_id": "$user_id", "user_name": "$user_name"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 12},
    ]).to_list(12)

    activities = [{
        "id": str(d["_id"]),
        "action": d.get("action"),
        "details": d.get("details"),
        "module": d.get("module"),
        "updatedBy": d.get("user_id"),
        "updatedByName": d.get("user_name"),
        "updatedByEmail": d.get("user_email"),
        "metadata": d.get("metadata") or {},
        "updatedAt": d["timestamp"].isoformat() if d.get("timestamp") else None,
    } for d in docs]

    summary = [{
        "userId": g["_id"].get("user_id"),
        "userName": g["_id"].get("user_name") or "Unknown",
        "count": g["count"],
    } for g in agg]

    return {"activities": activities, "summary": summary, "total": total}


# Real-time task event stream (SSE). Defined BEFORE /{task_id} so "stream" isn't captured
# as a task id. EventSource can't set an Authorization header, so the JWT comes in via the
# `token` query param. Emits task_created/updated/completed/deleted to the logged-in user's
# open streams (see app/services/task_events.py + emit points in this file + calendar_events.py).
@router.get("/stream")
async def task_event_stream(token: str = Query(...)):
    user = await get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    if not await has_task_access(user):
        raise HTTPException(
            status_code=403,
            detail=DELEGATION_DISABLED_MESSAGE if is_client_side_user(user) else TASK_ACCESS_DENIED_MESSAGE,
        )
    user_id = str(user["_id"])

    async def event_gen():
        q = task_events.subscribe(user_id)
        try:
            yield ": ok\n\n"  # initial comment so the client's onopen fires promptly
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield f"event: {event.get('type', 'message')}\ndata: {json.dumps(event, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # keepalive so proxies don't drop the idle connection
        finally:
            task_events.unsubscribe(user_id, q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# Users who can be picked in a task's Assigned To / In Loop dropdowns. Defined before
# /{task_id} (literal path) and gated by require_task_access, so any task creator can load it
# (unlike GET /users, which needs the users.read permission).
#
# An internal Sparsh user gets the staff directory. A company user (their company's Delegation
# module is ON) gets ONLY their own company's active users — the internal Sparsh directory is
# never exposed to a client company. Mirrors get_ineligible_recipient_ids, which enforces the
# same split on save.
@router.get("/logs")
async def task_notification_logs(
    channel: str = Query("email", description="email | whatsapp"),
    status: Optional[str] = Query(None),
    event: Optional[str] = Query(None, description="a task_* trigger slug"),
    search: Optional[str] = Query(None, description="recipient address or error text"),
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=3000),
    current_user: dict = Depends(require_task_access),
):
    """Task & Delegation email / WhatsApp delivery log, with KPI counts and a 14-day
    sparkline. Paginated server-side.

    Admin only: the ledger lists every recipient's address across the whole organisation,
    which is broader than any one user's own task visibility. Mirrors the TPMS Logs Report.
    """
    if (current_user.get("role") or "").lower() not in VIEW_ALL_ROLES:
        raise HTTPException(status_code=403, detail="Admin only")
    return await get_task_logs_report(current_user, channel, {
        "status": status, "event": event, "search": search,
        "from": date_from, "to": date_to, "skip": skip, "limit": limit,
    })


@router.get("/assignable-users")
async def list_assignable_users(
    include_all: bool = Query(False, alias="all"),
    current_user: dict = Depends(require_task_access),
):
    """Default: the rank-filtered "who I may ASSIGN to" list (drives the assign picker).
    `?all=true`: the full company/internal-scoped directory for NAME RESOLUTION on task/
    delegation detail & list views — it must still include people the viewer can't assign to
    (e.g. the admin or MD who assigned them the task), so those don't render as "Unknown"."""
    if is_client_side_user(current_user):
        company_id = current_user.get("company_id")
        if not company_id:
            return []
        docs = await get_collection("learners").find({
            "company_id": str(company_id), "is_active": {"$ne": False},
        }).to_list(1000)
        # Assign picker only: a client may assign at or below their own MD>HR>HOD>Implementor rank.
        if not include_all:
            actor_rank = client_rank(current_user)
            docs = [u for u in docs if client_rank(u) <= actor_rank]
    else:
        docs = await get_collection("staff").find({"is_active": {"$ne": False}}).to_list(1000)
        # Assign picker only: SMOPS assign to other SMOPS — hide admin/superadmin from the list.
        if not include_all and (current_user.get("role") or "").lower() not in ADMIN_TIER:
            docs = [u for u in docs if (u.get("role") or "").lower() not in ADMIN_TIER]
    return [{
        "_id": str(u["_id"]),
        "full_name": u.get("full_name") or (f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or None) or u.get("email"),
        "email": u.get("email"),
        "role": u.get("role"),
        "designation": u.get("designation"),
        # Exposed so the In Loop picker can offer "Include MD". Read-only here: the rank
        # rule itself stays in auth_controller.client_rank, which this only mirrors.
        "governance_role": u.get("governance_role"),
    } for u in docs]


@router.get("/{task_id}")
async def get_task_detail(task_id: str, current_user: dict = Depends(require_task_access)):
    existing, _ = await _get_task_or_404(task_id)
    # A participant OR the reporting manager of an assignee may view the full task (this single
    # response carries status, progress, comments, attachments and both histories).
    is_mgr = await _is_manager_of_assignee(existing, current_user)
    # A company MD passes _is_participant on any of their company's tasks, so no extra arm here.
    if not _is_participant(existing, current_user) and not is_mgr:
        raise HTTPException(status_code=403, detail="Not authorized to view this task")
    uid = str(current_user["_id"])
    admin_company_id = company_admin_company_id(current_user)
    detail = _serialize_task_detail(existing, uid)
    detail["subtasks"] = await _fetch_subtasks(task_id, uid, admin_company_id)
    # Lets the UI show the reporting manager the same task-action controls as an admin —
    # scoped to only their reports' tasks (status, Complete, Block, Dependent, Verify, Reopen).
    detail["isReportingManager"] = is_mgr
    # Same idea for a company MD, whose authority covers every task in their own company. The
    # UI gates on role names that a client MD ("clientadmin") is not part of, so it needs this
    # flag to unlock Edit / Delete / Verify / Reopen.
    detail["isCompanyAdmin"] = is_company_task_admin(existing, current_user)
    return detail


@router.patch("/{task_id}/status")
async def update_task_status(task_id: str, body: dict, current_user: dict = Depends(require_task_access)):
    new_status = body.get("workflow_status")
    reason = (body.get("reason") or "").strip() or None
    doer_name = (body.get("doer_name") or "").strip() or None
    doer_id = (body.get("doer_id") or "").strip() or None
    if new_status not in WORKFLOW_STATUSES:
        raise HTTPException(status_code=400, detail=f"workflow_status must be one of {WORKFLOW_STATUSES}")

    # "Dependent on Other" must carry who it's waiting on (Doer Name) + why (Reason) — the task
    # is reassigned to that doer. "Blocked" needs a Reason only (no doer).
    if new_status == "dependent_on_others" and (not doer_name or not reason):
        raise HTTPException(status_code=400, detail="Doer Name and Reason are required to set status to Dependent on Other.")
    if new_status == "blocked" and not reason:
        raise HTTPException(status_code=400, detail="Reason is required to set status to Blocked.")

    existing, col_name = await _get_task_or_404(task_id)

    # Dependent on Other hands the task to the picked doer, who must be an eligible recipient
    # for whoever is handing it over (internal staff, or their own company's users) — same rule
    # as create/update. Blocked captures the doer name only — no hand-off.
    reassign_doer = None
    if new_status == "dependent_on_others" and doer_id and doer_id != existing.get("dependency_doer_id"):
        # A task cannot be made to wait on somebody who is already doing it — including the
        # caller. The hand-off ADDS the doer to the assignees, so this would also mean adding
        # someone who is already there and leaving the task depending on itself.
        if doer_id in (existing.get("target_staff_id") or []):
            raise HTTPException(
                status_code=400,
                detail="That person is already working on this task — pick someone else for the task to depend on.",
            )
        bad = await get_ineligible_recipient_ids(current_user, [doer_id])
        if bad:
            raise HTTPException(status_code=403, detail=recipient_denied_message(current_user))
        rank_bad = await get_rank_ineligible_assignees(current_user, [doer_id])
        if rank_bad:
            raise HTTPException(status_code=403, detail=ASSIGN_RANK_DENIED_MESSAGE)
        reassign_doer = doer_id

    user_id = str(current_user["_id"])
    # The Super Admin bypass is for INTERNAL tasks only. On a CLIENT task it does not apply, so
    # verification/finalize/reopen stays with the client user who assigned it — an internal
    # Super Admin/Admin can never verify or act on a client-side task.
    # A company MD is the client-side admin: same authority, bounded by their own company. That
    # includes the verify / finalize / reopen rights below, via is_assigner_or_admin.
    is_admin = ((current_user.get("role") == "superadmin" and not _is_client_task(existing))
                or is_company_task_admin(existing, current_user))
    is_creator = existing.get("user_id") == user_id
    is_assignee = user_id in (existing.get("target_staff_id") or [])
    # The assignee's reporting manager may act on the task as an authorized verifier (same as
    # the assigner) — both to update status and to verify/finalize/reopen.
    is_manager = await _is_manager_of_assignee(existing, current_user)
    if not (is_admin or is_creator or is_assignee or is_manager):
        # The commonest way to arrive here is not a permissions mistake but a stale screen: a
        # dependency doer is taken OFF the task the moment they resolve it (the stack pops and
        # the task returns to whoever delegated it), so a details modal opened beforehand keeps
        # offering them a control that is no longer theirs. Say which of the two it is.
        was_doer = any(
            isinstance(h, dict) and str(h.get("doer_id") or "") == user_id
            for h in (existing.get("status_history") or [])
        )
        raise HTTPException(
            status_code=403,
            detail=("You completed your dependency on this task, so it has gone back to the "
                    "assignee for final completion and is no longer yours to update."
                    if was_doer else "Not authorized to update this task"),
        )

    old_status = _resolve_workflow_status(existing)
    # Only the assigner/delegator (creator), an admin, or the assignee's reporting manager may
    # finalize or reopen a task submitted for verification — never the assignee alone.
    is_assigner_or_admin = is_admin or is_creator or is_manager
    if old_status == "verification" and not is_assigner_or_admin:
        raise HTTPException(status_code=403, detail="Only the assigner can verify, finalize, or reopen this task.")
    if new_status == "in_progress_reopened" and not is_assigner_or_admin:
        raise HTTPException(status_code=403, detail="Only the assigner can reopen this task.")

    # ─── Dependency stack ───
    # "Dependent on Other" hands the task to a dependency doer, who owns ONLY that dependency —
    # ownership of the task itself stays with the assignee who raised it. Each hand-off pushes the
    # assignees it displaced onto `dependency_stack` and records the current holder in
    # `dependency_doer_id`, so a chain (A → B → C) unwinds one level at a time. The doer is ADDED
    # to target_staff_id rather than replacing it: the task shows up in the doer's My Tasks while
    # the original assignee keeps seeing it sitting at "Dependent on Other".
    #
    # The doer's "completed" therefore resolves their dependency and pops the task back to whoever
    # delegated it. It is NOT the doer completing the task itself, so the checklist / evidence /
    # verification rules below — which gate the real assignee's completion — must not be charged
    # to the doer.
    #
    # A resolved dependency NEVER completes the task, however far the chain has unwound. A assigns
    # to B, B makes it Dependent on Other to C: C finishing their part returns the task to B at In
    # Progress so B can review the work and complete it themselves. Whoever delegated the
    # dependency owns the task and owns the decision that it is done — the person who held only
    # the dependency cannot close it out over their head, and an auto-completion would also skip
    # B's checklist / evidence gates and their Request for Verification step.
    dependency_stack = existing.get("dependency_stack") or []
    prev_level = dependency_stack[-1] if dependency_stack else None
    resolving_dependency = (
        new_status == "completed"
        and prev_level is not None
        and existing.get("dependency_doer_id") == user_id
    )
    # Nobody picks this one out of a dropdown — it only ever describes a dependency that was
    # just resolved, and accepting it from a client would let anyone park a task there.
    if new_status == "dependency_completed" and not resolving_dependency:
        raise HTTPException(
            status_code=400,
            detail="Dependency Completed is set automatically when the dependency doer finishes — it cannot be chosen.",
        )
    if resolving_dependency:
        new_status = "dependency_completed"

    if new_status == "completed":
        # Completion rule: every check point (checklist item) must be done first.
        items = existing.get("checklist") or []
        pending_items = [c for c in items if not (isinstance(c, dict) and c.get("completed"))]
        if pending_items:
            done = len(items) - len(pending_items)
            raise HTTPException(
                status_code=400,
                detail=f"Complete all check points before completing this task ({done}/{len(items)} done).",
            )
        # Evidence Required: at least one completion-time upload must exist before the
        # task can be completed (kept separate from assignment-time `attachments`).
        if existing.get("evidence_required") and not (existing.get("completion_attachments") or []):
            raise HTTPException(status_code=400, detail="Evidence upload is required before completing this task.")
        # Verification Required: the assignee can only submit their side as done — final
        # completion is the assigner/admin's call. So route the assignee's "completed" to
        # the "verification" hand-off state instead of finalizing it.
        if existing.get("verification_required") and not is_assigner_or_admin:
            new_status = "verification"

    updates = {"workflow_status": new_status, "updated_at": datetime.now(timezone.utc)}
    # Human-readable line for the Revision History, so the dependency hand-off / hand-back reads as
    # an event rather than just a status arrow.
    history_note = None
    prior_assignees = existing.get("target_staff_id") or []
    if reassign_doer:
        # ADD the doer alongside the current assignees (delegation shape: assigned_to="other") so
        # the task lands in their My Tasks without evicting the assignee who still owns it.
        updates["target_staff_id"] = prior_assignees + [reassign_doer] if reassign_doer not in prior_assignees else prior_assignees
        updates["assigned_to"] = "other"
        updates["dependency_doer_id"] = reassign_doer
        updates["dependency_stack"] = dependency_stack + [{
            "assignee_ids": prior_assignees,
            "assigned_to": existing.get("assigned_to"),
            "delegated_by": user_id,
            "doer_id": reassign_doer,
            "doer_name": doer_name,
            "reason": reason,
            "at": datetime.now(timezone.utc),
        }]
        history_note = f"Task assigned to {doer_name} as Dependent on Other."
    elif resolving_dependency:
        # Dependency done → drop the doer, hand the task back to the assignee who raised it. If the
        # chain runs deeper (A → B → C), the level below becomes the current dependency again.
        returned_to = prev_level.get("assignee_ids") or []
        remaining_stack = dependency_stack[:-1]
        updates["target_staff_id"] = returned_to
        updates["assigned_to"] = prev_level.get("assigned_to") or "other"
        updates["dependency_stack"] = remaining_stack
        updates["dependency_doer_id"] = remaining_stack[-1].get("doer_id") if remaining_stack else None
        names = await _user_names(returned_to)
        returned_names = ", ".join(names.get(uid, "the assignee") for uid in returned_to) or "the assignee"
        actor = current_user.get("full_name") or current_user.get("email")
        history_note = (f"Dependency completed by {actor}. Task returned to {returned_names} "
                        f"for review and final completion.")
    was_completed = old_status == "completed"
    if new_status == "completed" and not was_completed:
        updates["completed_at"] = datetime.now(timezone.utc)
        updates["completed_by"] = user_id
        updates["status"] = "completed"  # keep legacy Calendar page status in sync
    elif was_completed and new_status != "completed":
        updates["completed_at"] = None
        updates["completed_by"] = None
        updates["status"] = "schedule"

    history_entry = {
        "old_status": old_status,
        "new_status": new_status,
        "changed_by": user_id,
        "changed_by_name": current_user.get("full_name") or current_user.get("email"),
        "reason": reason,
        "doer_name": doer_name,
        "doer_id": doer_id,
        "note": history_note,
        "changed_at": datetime.now(timezone.utc),
    }

    # A note is always worth recording, even when the status doesn't move — chaining a dependency
    # on from one doer to the next stays at "Dependent on Other" but is still a real event.
    if old_status != new_status or history_note:
        await get_collection(col_name).update_one(
            {"_id": ObjectId(task_id)},
            {"$set": updates, "$push": {"status_history": history_entry}},
        )
    else:
        await get_collection(col_name).update_one({"_id": ObjectId(task_id)}, {"$set": updates})

    await log_activity(current_user, "Update Task Status", col_name, f"Task {task_id} -> {new_status}",
                       meta={"task_id": task_id, "group_id": existing.get("group_id")})

    # Real-time: notify creator + assignees + watchers so their lists update without a refresh.
    # On reassignment, union old + new recipients so the task both drops off the previous
    # assignee's list and appears on the new doer's.
    #
    # The verification hand-off gets its own event types (rather than a generic task_updated)
    # so the two sides can be told what actually happened: the assigner learns a task is
    # awaiting their verification, and the assignee learns theirs was sent back for rework.
    if new_status == "completed":
        event_type = "task_completed"
    elif new_status == "verification":
        event_type = "task_verification_requested"
    elif old_status == "verification" and new_status == "in_progress_reopened":
        event_type = "task_verification_rejected"
    else:
        event_type = "task_updated"

    projected = {**existing, **updates}
    recipients = task_events.recipients_for(existing) | task_events.recipients_for(projected)
    # The assignees' reporting managers also monitor & verify the task, so the verification
    # request (and every status event) reaches them alongside the assigner.
    recipients |= await _manager_ids_for_task(projected)
    await task_events.publish(recipients, {
        "type": event_type,
        "task_id": task_id,
        "status": new_status,
        "title": existing.get("title"),
        "assigned_to": projected.get("target_staff_id") or [],
        "assigned_by": existing.get("user_id"),
        "watchers": existing.get("watchers") or [],
        "actor_id": user_id,
    })

    # ─── Email / WhatsApp / in-app (Task Management triggers only — never the Calendar's) ───
    # Only a real transition is worth an email; a no-op re-save of the same status isn't.
    # `notify_event` is the *most specific* thing that happened, so each transition sends
    # exactly one notification: an assigner approving a verification gets "verification
    # approved" (to the assignee), not that plus a generic "completed".
    if old_status != new_status or history_note:
        if resolving_dependency:
            # The hand-back, addressed to the assignee who now has to review and close it.
            notify_event = "dependency_resolved"
        elif reassign_doer or new_status == "dependent_on_others":
            notify_event = "dependent_on_other"
        elif new_status == "verification":
            notify_event = "verification_requested"
        elif old_status == "verification" and new_status == "completed":
            notify_event = "verification_approved"
        elif new_status == "in_progress_reopened":
            notify_event = "reopened"
        elif new_status == "completed":
            notify_event = "completed"
        elif new_status == "accepted":
            notify_event = "accepted"
        elif new_status == "blocked":
            notify_event = "blocked"
        else:
            notify_event = "updated"

        await notify_task_event(
            notify_event,
            projected,
            current_user,
            extra={
                "reason": reason,
                "doer_name": doer_name,
                "doer_id": reassign_doer or existing.get("dependency_doer_id"),
            },
        )

    return {"id": task_id, "workflow_status": new_status}


@router.post("/{task_id}/checklist")
async def add_checklist_item(task_id: str, body: dict, current_user: dict = Depends(require_task_access)):
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Checklist item title is required")

    existing, col_name = await _get_task_or_404(task_id)
    if not _is_participant(existing, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update this task")

    item = {"id": str(ObjectId()), "title": title, "completed": False, "completed_at": None}
    await get_collection(col_name).update_one({"_id": ObjectId(task_id)}, {"$push": {"checklist": item}})
    await log_activity(current_user, "Add Sub Task", col_name, f"Task {task_id}: {title}",
                       meta={"task_id": task_id, "group_id": existing.get("group_id")})
    return item


@router.patch("/{task_id}/checklist/{item_id}")
async def update_checklist_item(task_id: str, item_id: str, body: dict, current_user: dict = Depends(require_task_access)):
    existing, col_name = await _get_task_or_404(task_id)
    if not _is_participant(existing, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update this task")

    checklist = existing.get("checklist") or []
    item = next((c for c in checklist if c.get("id") == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Checklist item not found")

    # Update ONLY this element, via the positional operator.
    #
    # This used to mutate the in-memory list and write the WHOLE `checklist` array back. The
    # Check Points panel saves every tick at once (Promise.all), so two PATCHes for two items
    # ran concurrently: both read the same original array, each flipped its own item, and
    # whichever wrote last replaced the other's work — tick two boxes, save, and only one came
    # back ticked. Writing `checklist.$.field` touches the matched element alone, so concurrent
    # updates to different items no longer overwrite one another.
    updates = {}
    if "completed" in body:
        completed = bool(body["completed"])
        updates["checklist.$.completed"] = completed
        updates["checklist.$.completed_at"] = (
            datetime.now(timezone.utc).isoformat() if completed else None)
        item["completed"] = completed
        item["completed_at"] = updates["checklist.$.completed_at"]
    if "title" in body and str(body.get("title") or "").strip():
        title = str(body["title"]).strip()
        updates["checklist.$.title"] = title
        item["title"] = title

    if updates:
        await get_collection(col_name).update_one(
            {"_id": ObjectId(task_id), "checklist.id": item_id}, {"$set": updates})
    return item


@router.delete("/{task_id}/checklist/{item_id}")
async def delete_checklist_item(task_id: str, item_id: str, current_user: dict = Depends(require_task_access)):
    existing, col_name = await _get_task_or_404(task_id)
    if not _is_participant(existing, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update this task")

    await get_collection(col_name).update_one(
        {"_id": ObjectId(task_id)},
        {"$pull": {"checklist": {"id": item_id}}},
    )
    return {"message": "Checklist item removed"}


@router.post("/{task_id}/comments")
async def add_task_comment(task_id: str, body: dict, current_user: dict = Depends(require_task_access)):
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Comment text is required")

    existing, col_name = await _get_task_or_404(task_id)
    if not _is_participant(existing, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to comment on this task")

    comment = {
        "id": str(ObjectId()),
        "author_id": str(current_user["_id"]),
        "author_name": current_user.get("full_name") or current_user.get("email"),
        "text": text,
        "created_at": datetime.now(timezone.utc),
    }
    await get_collection(col_name).update_one({"_id": ObjectId(task_id)}, {"$push": {"remarks": comment}})
    await log_activity(current_user, "Comment on Task", col_name, f"Task {task_id}",
                       meta={"task_id": task_id, "group_id": existing.get("group_id")})
    return comment


@router.post("/{task_id}/follow-up")
async def add_task_follow_up(task_id: str, body: dict, current_user: dict = Depends(require_task_access)):
    """Follow-Up raised by an In-Loop member (watcher) — or any participant — as a nudge with a
    remark. Each call appends one entry; the follow-up count is simply len(follow_ups)."""
    remark = (body.get("remark") or "").strip()
    if not remark:
        raise HTTPException(status_code=400, detail="A follow-up remark is required")

    existing, col_name = await _get_task_or_404(task_id)
    if not _is_participant(existing, current_user):
        raise HTTPException(status_code=403, detail="Only involved users can follow up on this task")

    entry = {
        "id": str(ObjectId()),
        "by": str(current_user["_id"]),
        "by_name": current_user.get("full_name") or current_user.get("email"),
        "remark": remark,
        "created_at": datetime.now(timezone.utc),
    }
    await get_collection(col_name).update_one(
        {"_id": ObjectId(task_id)},
        {"$push": {"follow_ups": entry}, "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    await log_activity(current_user, "Task Follow-Up", col_name, f"Follow-up on task {task_id}",
                       meta={"task_id": task_id, "group_id": existing.get("group_id")})
    # Notify the assigner + assignees + watchers so the nudge surfaces on their lists in real time.
    await task_events.publish(task_events.recipients_for(existing), {
        "type": "task_updated",
        "task_id": task_id,
        "title": existing.get("title"),
        "assigned_to": existing.get("target_staff_id") or [],
        "assigned_by": existing.get("user_id"),
        "watchers": existing.get("watchers") or [],
        "actor_id": str(current_user["_id"]),
    })
    await notify_task_event("follow_up_added", existing, current_user, extra={"remark": remark})
    return {"id": task_id, "follow_up": {**entry, "created_at": entry["created_at"].isoformat()}}


@router.post("/{task_id}/attachments")
async def upload_task_attachment(task_id: str, file: UploadFile = File(...), current_user: dict = Depends(require_task_access)):
    existing, col_name = await _get_task_or_404(task_id)
    if not _is_participant(existing, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update this task")

    try:
        uploaded = upload_file_to_s3_with_key(file.file, file.filename, file.content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    attachment = {
        "id": str(ObjectId()),
        "name": file.filename,
        "size": file.size,
        "key": uploaded["key"],
        "url": uploaded["url"],
        "uploaded_by": str(current_user["_id"]),
        "uploaded_at": datetime.now(timezone.utc),
    }
    await get_collection(col_name).update_one({"_id": ObjectId(task_id)}, {"$push": {"attachments": attachment}})
    await log_activity(current_user, "Attach File to Task", col_name, f"Task {task_id}: {file.filename}",
                       meta={"task_id": task_id, "group_id": existing.get("group_id")})
    return attachment


@router.delete("/{task_id}/attachments/{attachment_id}")
async def delete_task_attachment(task_id: str, attachment_id: str, current_user: dict = Depends(require_task_access)):
    existing, col_name = await _get_task_or_404(task_id)
    if not _is_participant(existing, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update this task")

    await get_collection(col_name).update_one(
        {"_id": ObjectId(task_id)},
        {"$pull": {"attachments": {"id": attachment_id}}},
    )
    return {"message": "Attachment removed"}


# ─── Completion Evidence ───
# Same shape/flow as the /attachments endpoints above, but stored in a separate
# `completion_attachments` array so assignment-time files and completion evidence never
# mix in the UI. Evidence Required's completion gate reads this array (see update_task_status).
@router.post("/{task_id}/completion-attachments")
async def upload_completion_attachment(task_id: str, file: UploadFile = File(...), current_user: dict = Depends(require_task_access)):
    existing, col_name = await _get_task_or_404(task_id)
    if not _is_participant(existing, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update this task")

    try:
        uploaded = upload_file_to_s3_with_key(file.file, file.filename, file.content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    attachment = {
        "id": str(ObjectId()),
        "name": file.filename,
        "size": file.size,
        "key": uploaded["key"],
        "url": uploaded["url"],
        "uploaded_by": str(current_user["_id"]),
        "uploaded_at": datetime.now(timezone.utc),
    }
    await get_collection(col_name).update_one({"_id": ObjectId(task_id)}, {"$push": {"completion_attachments": attachment}})
    await log_activity(current_user, "Attach File to Task", col_name, f"Task {task_id}: completion evidence {file.filename}",
                       meta={"task_id": task_id, "group_id": existing.get("group_id")})
    return attachment


@router.delete("/{task_id}/completion-attachments/{attachment_id}")
async def delete_completion_attachment(task_id: str, attachment_id: str, current_user: dict = Depends(require_task_access)):
    existing, col_name = await _get_task_or_404(task_id)
    if not _is_participant(existing, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update this task")

    await get_collection(col_name).update_one(
        {"_id": ObjectId(task_id)},
        {"$pull": {"completion_attachments": {"id": attachment_id}}},
    )
    return {"message": "Completion evidence removed"}


# ─── Deadline / Date Revision ───
# The assigner/delegator (creator), an admin, or the assignee's reporting manager may revise a
# task's deadline (`end`) directly ("Date Revision"). Every such change is stamped into
# `deadline_history` (with who revised it), so the trail stays auditable for the assigner.
#
# The ASSIGNEE cannot move the deadline on their own. When they can't finish by the current one
# they REQUEST a revision through this same endpoint: the proposed date is parked on
# `deadline_requests` as `pending` and the deadline itself does not move. Only once the assigner
# approves it (POST .../deadline-requests/{id}/approve) does `end` change and the revision land
# in `deadline_history` — so the revised deadline only "continues" with sign-off. A rejection
# leaves the original deadline standing.
#
# Either way a task gets MAX_DEADLINE_REVISIONS of them and no more (`context` == "reopen"
# marks the Reopen flow's own deadline, which is exempt — see the constant).
#
# The reason is optional — the history renderer treats a missing reason as "not captured".
@router.patch("/{task_id}/deadline")
async def revise_task_deadline(task_id: str, body: dict, current_user: dict = Depends(require_task_access)):
    new_end = body.get("end")
    reason = (body.get("reason") or "").strip() or None
    claims_reopen = (body.get("context") or "").strip().lower() == "reopen"
    if not new_end:
        raise HTTPException(status_code=400, detail="A new deadline (end) is required")

    existing, col_name = await _get_task_or_404(task_id)

    is_admin = (current_user.get("role") == "superadmin"
                or is_company_task_admin(existing, current_user))
    is_creator = existing.get("user_id") == str(current_user["_id"])
    is_assignee = str(current_user["_id"]) in (existing.get("target_staff_id") or [])
    # The assignee's reporting manager may revise the deadline too — the Reopen flow uses this
    # to send a task back with a new due date, so without it the manager can't reopen.
    is_manager = await _is_manager_of_assignee(existing, current_user)
    if not (is_admin or is_creator or is_assignee or is_manager):
        raise HTTPException(status_code=403, detail="Only the assigner, assignee, or reporting manager can revise this task's deadline")

    old_end = existing.get("end")
    if old_end == new_end:
        return {"id": task_id, "end": new_end}

    # ─── Doer or not ───
    # Who needs approval is decided by the caller's role ON THIS TASK, not by their role on the
    # platform. Someone doing a task that somebody else gave them is the doer, Super Admin or
    # not, and the whole point of the approval is that the person who SET the deadline is the
    # one who agrees to move it. Letting an admin-flagged doer revise their own deadline
    # outright would quietly exempt exactly the people most likely to hold that flag.
    #
    # A self-assigned task is the one exception and needs no rule of its own: there the creator
    # IS the assignee, so is_creator is true and they revise directly — there is nobody else to
    # ask.
    acts_as_doer = is_assignee and not is_creator

    # A completed task's deadline is history: moving it would rewrite whether the work landed
    # on time, and there is nothing left to deliver by the new date. The Reopen flow is exempt
    # because it is the one thing that legitimately gives a finished task a future again.
    if _resolve_workflow_status(existing) == "completed" and not claims_reopen:
        raise HTTPException(
            status_code=400,
            detail="This task is completed — its deadline can no longer be revised.",
        )

    # Reopening is the assigner's move, so only they can claim the exemption that comes with it.
    # Otherwise an assignee could spend the budget and then keep going by simply posting
    # context="reopen" — the flag is a client's word, and this is the only place it is taken.
    is_reopen = claims_reopen and not acts_as_doer and (is_admin or is_creator or is_manager)

    # The budget is checked before anything is written — and before an assignee is allowed to
    # RAISE a request, so nobody waits on an approval that could never be granted.
    if not is_reopen:
        _assert_deadline_revisions_left(existing)

    # The doer raises a request; the assigner (and an admin or reporting manager acting over
    # the task rather than doing it) revises outright.
    if acts_as_doer:
        return await _raise_deadline_request(task_id, col_name, existing, current_user, new_end, reason)

    revision = {
        "old_end": old_end,
        "new_end": new_end,
        "reason": reason,
        "revised_by": str(current_user["_id"]),
        "revised_by_name": current_user.get("full_name") or current_user.get("email"),
        "revised_at": datetime.now(timezone.utc),
        # Reopens are exempt from the cap, so the trail has to say which kind this was.
        "kind": "reopen" if is_reopen else "revision",
    }
    await get_collection(col_name).update_one(
        {"_id": ObjectId(task_id)},
        {"$set": {"end": new_end, "updated_at": datetime.now(timezone.utc)}, "$push": {"deadline_history": revision}},
    )
    await log_activity(current_user, "Update Task", col_name, f"Task {task_id}: deadline revised",
                       meta={"task_id": task_id, "group_id": existing.get("group_id")})

    await task_events.publish(task_events.recipients_for(existing), {
        "type": "task_updated",
        "task_id": task_id,
        "title": existing.get("title"),
        "assigned_to": existing.get("target_staff_id") or [],
        "assigned_by": existing.get("user_id"),
        "watchers": existing.get("watchers") or [],
        "actor_id": str(current_user["_id"]),
    })
    await notify_task_event(
        "deadline_revised",
        {**existing, "end": new_end},
        current_user,
        extra={"old_end": old_end, "new_end": new_end, "reason": reason},
    )
    return {"id": task_id, "end": new_end}


# ─── Deadline revision requests (assignee proposes ▸ assigner decides) ───
# The assignee's side of "Revise". Nothing about the task changes when a request is raised —
# the deadline only moves on approval, which is where `deadline_history` gets its entry, so the
# existing audit trail keeps meaning "the deadline actually moved, and who moved it".


def _assert_deadline_revisions_left(existing: dict) -> None:
    """Refuse a revision once the task has used its MAX_DEADLINE_REVISIONS."""
    used = _deadline_revision_count(existing)
    if used >= MAX_DEADLINE_REVISIONS:
        raise HTTPException(
            status_code=400,
            detail=(f"This task's deadline has already been revised {used} times "
                    f"(limit {MAX_DEADLINE_REVISIONS}). No further revision is allowed."),
        )


async def _can_decide_deadline_request(existing: dict, current_user: dict) -> bool:
    """Who may approve/reject a request — the assigner (creator), an admin, or the assignee's
    reporting manager. A doer is excluded even when they hold one of those roles elsewhere,
    for the same reason they cannot revise directly (see acts_as_doer)."""
    user_id = str(current_user["_id"])
    if user_id in (existing.get("target_staff_id") or []) and existing.get("user_id") != user_id:
        return False
    return bool(
        current_user.get("role") == "superadmin"
        or is_company_task_admin(existing, current_user)
        or existing.get("user_id") == user_id
        or await _is_manager_of_assignee(existing, current_user)
    )


async def _raise_deadline_request(task_id: str, col_name: str, existing: dict,
                                  current_user: dict, new_end, reason):
    """Park an assignee's proposed deadline as a pending request and tell the assigner."""
    now = datetime.now(timezone.utc)
    pending = _pending_deadline_request(existing)
    if pending:
        # Only one request may be outstanding — a fresh proposal supersedes the old one rather
        # than leaving the assigner two competing dates to choose between.
        await get_collection(col_name).update_one(
            {"_id": ObjectId(task_id), "deadline_requests.id": pending.get("id")},
            {"$set": {"deadline_requests.$.status": "superseded", "deadline_requests.$.decided_at": now}},
        )

    request = {
        "id": uuid.uuid4().hex,
        "old_end": existing.get("end"),
        "new_end": new_end,
        "reason": reason,
        "requested_by": str(current_user["_id"]),
        "requested_by_name": current_user.get("full_name") or current_user.get("email"),
        "requested_at": now,
        "status": "pending",
        "decided_by": None,
        "decided_by_name": None,
        "decided_at": None,
        "decision_remark": None,
    }
    await get_collection(col_name).update_one(
        {"_id": ObjectId(task_id)},
        {"$push": {"deadline_requests": request}, "$set": {"updated_at": now}},
    )
    await log_activity(current_user, "Update Task", col_name,
                       f"Task {task_id}: deadline revision requested",
                       meta={"task_id": task_id, "group_id": existing.get("group_id")})

    recipients = task_events.recipients_for(existing) | await _manager_ids_for_task(existing)
    await task_events.publish(recipients, {
        "type": "task_updated",
        "task_id": task_id,
        "title": existing.get("title"),
        "assigned_to": existing.get("target_staff_id") or [],
        "assigned_by": existing.get("user_id"),
        "watchers": existing.get("watchers") or [],
        "actor_id": str(current_user["_id"]),
    })
    await notify_task_event(
        "deadline_revision_requested",
        existing,
        current_user,
        extra={"old_end": existing.get("end"), "new_end": new_end, "reason": reason},
    )
    # `end` is deliberately the UNCHANGED deadline: the caller must not show the new date as live.
    return {
        "id": task_id,
        "end": existing.get("end"),
        "status": "pending_approval",
        "deadline_request": request,
        "message": "Deadline revision requested — awaiting the assigner's approval.",
    }


async def _decide_deadline_request(task_id: str, request_id: str, body: dict,
                                   current_user: dict, approve: bool):
    remark = (body.get("remark") or body.get("reason") or "").strip() or None
    existing, col_name = await _get_task_or_404(task_id)

    if not await _can_decide_deadline_request(existing, current_user):
        raise HTTPException(
            status_code=403,
            detail="Only the assigner, an admin, or the reporting manager can decide a deadline revision request.",
        )

    request = next((r for r in (existing.get("deadline_requests") or [])
                    if isinstance(r, dict) and r.get("id") == request_id), None)
    if not request:
        raise HTTPException(status_code=404, detail="Deadline revision request not found")
    # Belt and braces over the rule above: whoever asked for it never gets to grant it.
    if str(request.get("requested_by")) == str(current_user["_id"]):
        raise HTTPException(
            status_code=403,
            detail="A deadline revision has to be approved by the assigner, not by the person who asked for it.",
        )
    if request.get("status") != "pending":
        raise HTTPException(status_code=400,
                            detail="This request was already " + str(request.get("status")) + ".")
    # Re-checked here, not just when the request was raised: the assigner may have revised the
    # deadline directly in the meantime and used the budget up. A rejection is always allowed —
    # it changes nothing and lets them clear a request they can no longer grant.
    if approve:
        # Same rule as revising: the deadline of a finished task is not moved. A REJECTION is
        # still allowed, so a request left hanging when the task completed can be cleared.
        if _resolve_workflow_status(existing) == "completed":
            raise HTTPException(
                status_code=400,
                detail="This task is completed — its deadline can no longer be revised. Reject the request to clear it.",
            )
        _assert_deadline_revisions_left(existing)

    now = datetime.now(timezone.utc)
    verdict = "approved" if approve else "rejected"
    updates = {"$set": {
        "deadline_requests.$.status": verdict,
        "deadline_requests.$.decided_by": str(current_user["_id"]),
        "deadline_requests.$.decided_by_name": current_user.get("full_name") or current_user.get("email"),
        "deadline_requests.$.decided_at": now,
        "deadline_requests.$.decision_remark": remark,
        "updated_at": now,
    }}

    new_end = request.get("new_end")
    # The deadline in force right now — not the one captured when the request was raised, since
    # the assigner may have revised it in the meantime.
    old_end = existing.get("end")
    if approve:
        # Approval is what actually moves the deadline, and it is the approval that goes into
        # `deadline_history` — stamped with BOTH the approver and whoever asked for it.
        updates["$set"]["end"] = new_end
        updates["$push"] = {"deadline_history": {
            "old_end": old_end,
            "new_end": new_end,
            "reason": request.get("reason"),
            "revised_by": str(current_user["_id"]),
            "revised_by_name": current_user.get("full_name") or current_user.get("email"),
            "revised_at": now,
            "kind": "revision",
            "request_id": request_id,
            "requested_by": request.get("requested_by"),
            "requested_by_name": request.get("requested_by_name"),
            "decision_remark": remark,
        }}

    await get_collection(col_name).update_one(
        {"_id": ObjectId(task_id), "deadline_requests.id": request_id}, updates,
    )
    await log_activity(current_user, "Update Task", col_name,
                       f"Task {task_id}: deadline revision request {verdict}",
                       meta={"task_id": task_id, "group_id": existing.get("group_id")})

    projected = {**existing, **({"end": new_end} if approve else {})}
    recipients = task_events.recipients_for(existing) | await _manager_ids_for_task(existing)
    await task_events.publish(recipients, {
        "type": "task_updated",
        "task_id": task_id,
        "title": existing.get("title"),
        "assigned_to": existing.get("target_staff_id") or [],
        "assigned_by": existing.get("user_id"),
        "watchers": existing.get("watchers") or [],
        "actor_id": str(current_user["_id"]),
    })
    await notify_task_event(
        f"deadline_revision_{verdict}",
        projected,
        current_user,
        extra={
            "old_end": old_end,
            "new_end": new_end,
            "reason": request.get("reason"),
            "remark": remark,
            "requested_by": request.get("requested_by"),
            "requested_by_name": request.get("requested_by_name"),
        },
    )
    return {
        "id": task_id,
        "end": new_end if approve else old_end,
        "status": verdict,
        "request_id": request_id,
    }


@router.post("/{task_id}/deadline-requests/{request_id}/approve")
async def approve_deadline_request(task_id: str, request_id: str, body: dict = None,
                                   current_user: dict = Depends(require_task_access)):
    """Approve the assignee's proposed deadline — this is the moment `end` actually moves."""
    return await _decide_deadline_request(task_id, request_id, body or {}, current_user, approve=True)


@router.post("/{task_id}/deadline-requests/{request_id}/reject")
async def reject_deadline_request(task_id: str, request_id: str, body: dict = None,
                                  current_user: dict = Depends(require_task_access)):
    """Reject it — the original deadline stands, and the assignee is told why."""
    return await _decide_deadline_request(task_id, request_id, body or {}, current_user, approve=False)


@router.delete("/{task_id}")
async def soft_delete_task(task_id: str, current_user: dict = Depends(require_task_access)):
    existing, col_name = await find_event_across_collections(task_id)
    if not existing or existing.get("type") != "task":
        raise HTTPException(status_code=404, detail="Task not found")

    is_admin = (current_user.get("role") == "superadmin"
                or is_company_task_admin(existing, current_user))
    is_creator = existing.get("user_id") == str(current_user["_id"])
    if not (is_admin or is_creator):
        raise HTTPException(status_code=403, detail="Not authorized to delete this task")

    await get_collection(col_name).update_one(
        {"_id": ObjectId(task_id)},
        {"$set": {"deleted_at": datetime.now(timezone.utc).isoformat()}},
    )
    await log_activity(current_user, "Soft Delete Task", col_name, f"Task {task_id}",
                       meta={"task_id": task_id, "group_id": existing.get("group_id")})

    await task_events.publish(task_events.recipients_for(existing), {
        "type": "task_deleted",
        "task_id": task_id,
        "title": existing.get("title"),
        "assigned_to": existing.get("target_staff_id") or [],
        "assigned_by": existing.get("user_id"),
        "watchers": existing.get("watchers") or [],
        "actor_id": str(current_user["_id"]),
    })
    # The delegation module soft-deletes (the Calendar's hard DELETE has its own trigger),
    # so without this the assignees were never told their task went away.
    await notify_task_event("deleted", existing, current_user)
    return {"message": "Task moved to Deleted Tasks"}


@router.post("/{task_id}/restore")
async def restore_task(task_id: str, current_user: dict = Depends(require_task_access)):
    existing, col_name = await find_event_across_collections(task_id)
    if not existing or existing.get("type") != "task":
        raise HTTPException(status_code=404, detail="Task not found")

    is_admin = (current_user.get("role") == "superadmin"
                or is_company_task_admin(existing, current_user))
    is_creator = existing.get("user_id") == str(current_user["_id"])
    if not (is_admin or is_creator):
        raise HTTPException(status_code=403, detail="Not authorized to restore this task")

    await get_collection(col_name).update_one(
        {"_id": ObjectId(task_id)},
        {"$set": {"deleted_at": None}},
    )
    await log_activity(current_user, "Restore Task", col_name, f"Task {task_id}",
                       meta={"task_id": task_id, "group_id": existing.get("group_id")})
    return {"message": "Task restored"}
