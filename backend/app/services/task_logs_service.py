"""
Task & Delegation ▸ notification delivery log.

Every task email / WhatsApp is written to the shared `notifications` collection by
notification_service.log_notification. This reads that ledger back for the Task module the
same way tpms_dashboard_service.get_logs_report does for TPMS — same collection, same
columns, same KPI shape — so the two Logs Report screens behave identically.

WHAT SCOPES IT TO TASKS
-----------------------
Task sends are slugged from TASK_EVENT_SLUGS, every one of which begins `task_`
(`task_assigned`, `task_completed`, `task_deadline_revised`, …) plus the assigner's
`task_assignment_confirmation`. Matching that prefix keeps this a Task-only view without
needing a new field on the log rows.

RECIPIENT NAMES
---------------
A task send records `user_id` + `target_contact` and nothing else — unlike TPMS, which
attaches activity/company meta at send time. Rather than change the shared send path just to
enrich a report, the ids are resolved to names HERE, on read. The trade is one extra lookup
per page of logs against never touching delivery code.

READ-ONLY: nothing here writes, and no collection is created or altered.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.db.mongodb import get_collection
from app.services.task_notifications import TASK_EVENT_SLUGS

logger = logging.getLogger(__name__)

LOG_COLLECTION = "notifications"
TASK_SLUG_PREFIX = "^task_"
MAX_LIMIT = 3000

# slug → the words a human uses for that event, so the Action column doesn't read as
# `task_verification_requested`. Derived from TASK_EVENT_SLUGS so a new trigger appears here
# automatically, with a readable fallback for anything not in the map.
EVENT_LABELS = {
    "task_created": "Task Created",
    "task_assigned": "Task Assigned",
    "task_updated": "Task Updated",
    "task_deleted": "Task Deleted",
    "task_accepted": "Acknowledged Delegation",
    "task_completed": "Task Completed",
    "task_reopened": "Task Reopened",
    "task_verification_requested": "Verification Requested",
    "task_verification_approved": "Verification Approved",
    "task_deadline_revised": "Deadline Revised",
    "task_deadline_revision_requested": "Deadline Revision Requested",
    "task_deadline_revision_approved": "Deadline Revision Approved",
    "task_deadline_revision_rejected": "Deadline Revision Rejected",
    "task_blocked": "Task Blocked",
    "task_dependent_on_other": "Dependent on Other",
    "task_dependency_resolved": "Dependency Completed",
    "task_follow_up_added": "Follow-Up Added",
    "task_subtask_created": "Subtask Created",
    "task_in_loop_added": "In-Loop Person Added",
    "task_reassigned": "Task Reassigned",
    "task_unassigned": "Task Unassigned",
    "task_due_reminder_daily": "Daily Due Reminder",
    "task_due_reminder_weekly": "Weekly Due Reminder",
    "task_overdue": "Overdue Nudge",
    "task_assignment_confirmation": "Assignment Confirmation (to assigner)",
}


def _base_slug(slug: str) -> str:
    """Strip the channel suffix fetch_template() appends, so `task_assigned_email` and
    `task_assigned_whatsapp` report as one event rather than two."""
    s = str(slug or "")
    for suffix in ("_email", "_whatsapp"):
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def event_label(slug: str) -> str:
    base = _base_slug(slug)
    if base in EVENT_LABELS:
        return EVENT_LABELS[base]
    # Unknown / newly added trigger: title-case it rather than showing a raw slug.
    return base.replace("task_", "").replace("_", " ").strip().title() or base


def event_options() -> List[dict]:
    """The Action filter's options — every task trigger, labelled."""
    slugs = sorted(set(TASK_EVENT_SLUGS.values()) | {"task_assignment_confirmation"})
    return [{"id": s, "name": event_label(s)} for s in slugs]


async def _recipient_names(user_ids: List[str]) -> Dict[str, str]:
    """id → display name, across both directories. A task can notify an internal user or a
    client-side one, so neither collection alone is enough."""
    ids = [i for i in {str(u) for u in user_ids if u} if i and i != "system"]
    if not ids:
        return {}
    from bson import ObjectId
    from bson.errors import InvalidId
    oids = []
    for i in ids:
        try:
            oids.append(ObjectId(i))
        except (InvalidId, TypeError):
            continue
    if not oids:
        return {}
    out: Dict[str, str] = {}
    for coll in ("staff", "learners"):
        try:
            for u in await get_collection(coll).find({"_id": {"$in": oids}}).to_list(len(oids)):
                out[str(u["_id"])] = (
                    u.get("full_name")
                    or " ".join(filter(None, [u.get("first_name"), u.get("last_name")])).strip()
                    or u.get("email") or str(u["_id"])
                )
        except Exception as exc:  # noqa: BLE001 — a name is nice to have, not worth failing on
            logger.warning("Task logs: could not resolve names from %s — %s", coll, exc)
    return out


def _spark_14d(by_day: Dict[str, int]) -> List[dict]:
    """The last 14 calendar days ending today, oldest first. Days with no sends are emitted
    as 0 so the series is continuous rather than gap-collapsed."""
    today = datetime.utcnow().date()
    out = []
    for offset in range(13, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        out.append({"key": day, "count": by_day.get(day, 0)})
    return out


async def _status_counts(coll, query: dict, total: int) -> Dict[str, int]:
    """sent / failed / skipped across every row the filter matches.

    Status is free text written by whichever delivery path logged it ("sent", "success",
    "failed", …), so it is bucketed by substring here rather than assumed to be an enum.
    """
    counts = {"total": total, "sent": 0, "failed": 0, "skipped": 0}
    try:
        cursor = coll.aggregate([{"$match": query},
                                 {"$group": {"_id": "$status", "n": {"$sum": 1}}}])
        async for bucket in cursor:
            status = str(bucket.get("_id") or "").lower()
            n = int(bucket.get("n") or 0)
            if "sent" in status or "success" in status:
                counts["sent"] += n
            elif "fail" in status or "error" in status:
                counts["failed"] += n
            else:
                counts["skipped"] += n
    except Exception as exc:  # noqa: BLE001 — the table is still worth showing without KPIs
        logger.warning("Task logs: status aggregation failed — %s", exc)
    return counts


async def _daily_counts(coll, query: dict) -> List[dict]:
    """Sends per day for the last 14 days, over the whole filtered set."""
    since = datetime.utcnow() - timedelta(days=13)
    since = datetime(since.year, since.month, since.day)
    by_day: Dict[str, int] = {}
    try:
        cursor = coll.aggregate([
            {"$match": {**query, "sent_at": {**(query.get("sent_at") or {}), "$gte": since}}},
            {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$sent_at"}},
                        "n": {"$sum": 1}}},
        ])
        async for bucket in cursor:
            if bucket.get("_id"):
                by_day[str(bucket["_id"])] = int(bucket.get("n") or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Task logs: sparkline aggregation failed — %s", exc)
    return _spark_14d(by_day)


async def get_task_logs_report(user: dict, channel: str, scope: dict) -> dict:
    """Task email / WhatsApp delivery logs, with KPI counts and a 14-day sparkline.

    Paginated server-side: the client asks for the page it renders.
    """
    scope = scope or {}
    query: dict = {"template_slug": {"$regex": TASK_SLUG_PREFIX}}

    # A specific trigger. The stored slug carries the channel suffix, so match the base.
    event = str(scope.get("event") or "").strip()
    if event:
        query["template_slug"] = {"$regex": f"^{_base_slug(event)}(_email|_whatsapp)?$"}
    if channel:
        query["channel"] = channel
    if scope.get("status"):
        query["status"] = scope["status"]
    if scope.get("from") or scope.get("to"):
        rng = {}
        if scope.get("from"):
            rng["$gte"] = datetime.fromisoformat(str(scope["from"])[:10])
        if scope.get("to"):
            # Inclusive of the whole end day, matching the TPMS report's window.
            rng["$lte"] = datetime.fromisoformat(str(scope["to"])[:10]) + timedelta(days=1)
        query["sent_at"] = rng
    search = str(scope.get("search") or "").strip()
    if search:
        # Recipient address or the error text — the two fields worth hunting through when
        # chasing "did this person get it, and if not why".
        query["$or"] = [
            {"target_contact": {"$regex": search, "$options": "i"}},
            {"error_message": {"$regex": search, "$options": "i"}},
        ]

    limit = min(int(scope.get("limit") or 500), MAX_LIMIT)
    skip = int(scope.get("skip") or 0)
    coll = get_collection(LOG_COLLECTION)
    total = await coll.count_documents(query)
    docs = await coll.find(query).sort("sent_at", -1).skip(skip).limit(limit).to_list(limit)

    names = await _recipient_names([d.get("user_id") for d in docs])

    # Counted over the WHOLE filtered set, not the page that was fetched. Tallying the page
    # would report "total 942, sent 5" whenever the page is smaller than the result — a KPI
    # that contradicts the total sitting next to it.
    counts = await _status_counts(coll, query, total)
    spark = await _daily_counts(coll, query)

    rows: List[list] = []
    for d in docs:
        sent_at = d.get("sent_at")
        stamp = sent_at.strftime("%Y-%m-%d %H:%M") if isinstance(sent_at, datetime) else ""
        rows.append([
            stamp,
            event_label(d.get("template_slug")),
            names.get(str(d.get("user_id") or ""), ""),
            d.get("target_contact") or "",
            d.get("channel") or "",
            d.get("status") or "",
            d.get("error_message") or "",
        ])

    return {
        "type": channel or "all",
        "columns": ["Timestamp", "Action", "Recipient", "Sent To",
                    "Channel", "Log Status", "Error"],
        "rows": rows,
        "counts": counts,
        "spark": spark,
        "events": event_options(),
        "truncated": total > len(rows),
        "total": total, "skip": skip, "limit": limit,
    }
