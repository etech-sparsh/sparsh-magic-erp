"""Notifications for the Task Management (Delegation) module.

Kept separate from the Calendar's triggers in notification_service.py even though both
modules' docs share the calendar collections (a type=="task" doc belongs to Task
Management; the Calendar list endpoint filters those out). The Email/WhatsApp engine
itself is fully reused — template resolution, channel selection, Meta-approved WhatsApp
templates and the per-template Active/Inactive switch all come from
send_notification_from_template. Only the slugs, the recipients and the context are
owned here, so a Calendar session can never fire a Task Management trigger or vice versa.

`task_created` / `task_updated` / `task_deleted` are pre-existing slugs. They have only
ever fired for delegation tasks (the Calendar has no task-creation surface), so they are
reused as-is and any template an admin already customised keeps working untouched.
"""
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

from app.services.notification_service import (
    send_notification_from_template,
    active_user_template,
    create_in_app_notification,
    format_datetime_standard,
    to_ist,
)
from app.utils.calendar_utils import find_user_by_id

logger = logging.getLogger(__name__)

# Event key -> template slug. fetch_template() appends _email / _whatsapp.
TASK_EVENT_SLUGS = {
    "created": "task_created",
    "assigned": "task_assigned",
    "updated": "task_updated",
    "deleted": "task_deleted",
    "accepted": "task_accepted",
    "completed": "task_completed",
    "reopened": "task_reopened",
    "verification_requested": "task_verification_requested",
    "verification_approved": "task_verification_approved",
    "deadline_revised": "task_deadline_revised",
    # Assignee asks for the deadline to move; the assigner approves or rejects it. Only
    # the approval actually moves the date (see tasks._decide_deadline_request).
    "deadline_revision_requested": "task_deadline_revision_requested",
    "deadline_revision_approved": "task_deadline_revision_approved",
    "deadline_revision_rejected": "task_deadline_revision_rejected",
    "blocked": "task_blocked",
    "dependent_on_other": "task_dependent_on_other",
    # The dependency doer finished their part: the task goes back to the assignee who
    # delegated it, for review and final completion — it never completes itself.
    "dependency_resolved": "task_dependency_resolved",
    "follow_up_added": "task_follow_up_added",
    "subtask_created": "task_subtask_created",
    "in_loop_added": "task_in_loop_added",
    # ─── Reassignment (raised from the task update route) ───
    "reassigned": "task_reassigned",
    "unassigned": "task_unassigned",
    # ─── Time-driven nudges (raised by task_nudge_service's daily sweep, never by a user
    #     action). They are ordinary triggers in every other respect: same template
    #     resolution, same Active switch, same channels.
    "due_reminder_daily": "task_due_reminder_daily",
    "due_reminder_weekly": "task_due_reminder_weekly",
    "overdue": "task_overdue",
    "verification_pending": "task_verification_pending_reminder",
}

# In-app title + tone per event (the bell feed mirrors every email/WhatsApp trigger).
_IN_APP = {
    "created": ("New Task Assigned", "info"),
    "assigned": ("Task Assigned to You", "info"),
    "updated": ("Task Updated", "info"),
    "deleted": ("Task Deleted", "warning"),
    "accepted": ("Task Accepted", "success"),
    "completed": ("Task Completed", "success"),
    "reopened": ("Task Reopened", "warning"),
    "verification_requested": ("Verification Requested", "info"),
    "verification_approved": ("Verification Approved", "success"),
    "deadline_revised": ("Deadline Revised", "warning"),
    "deadline_revision_requested": ("Deadline Revision Requested", "warning"),
    "deadline_revision_approved": ("Deadline Revision Approved", "success"),
    "deadline_revision_rejected": ("Deadline Revision Rejected", "error"),
    "blocked": ("Task Blocked", "error"),
    "dependent_on_other": ("Task Dependent on Other", "warning"),
    "dependency_resolved": ("Dependency Completed", "info"),
    "follow_up_added": ("Follow-up Added", "info"),
    "subtask_created": ("Subtask Created", "info"),
    "in_loop_added": ("Added to Task Loop", "info"),
    "reassigned": ("Task Reassigned", "warning"),
    "unassigned": ("Removed from Task", "warning"),
    "due_reminder_daily": ("Task Due Reminder", "info"),
    "due_reminder_weekly": ("Task Due Reminder", "info"),
    "overdue": ("Task Overdue", "error"),
    "verification_pending": ("Verification Still Pending", "warning"),
}


def _ids(value) -> set:
    """Normalise a scalar-or-list id field to a set of non-empty strings."""
    if not value:
        return set()
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    return {str(v) for v in value if v}


def recipients_for_event(event: str, task: dict, extra: Optional[dict] = None) -> set:
    """Who hears about `event`. The actor is stripped by notify_task_event — nobody is
    notified about their own action."""
    extra = extra or {}
    assigner = _ids(task.get("user_id"))
    assignees = _ids(task.get("target_staff_id"))
    watchers = _ids(task.get("watchers"))

    if event == "assigned":
        # Only the people newly put on the task, not the ones who were already on it.
        return _ids(extra.get("new_assignee_ids"))
    if event == "unassigned":
        # ONLY the people just taken off it. They are no longer on the task, so they are not
        # in any of the sets below and would otherwise hear nothing about losing the work.
        return _ids(extra.get("removed_assignee_ids"))
    if event == "reassigned":
        # The task moved between people: whoever now holds it, plus the assigner and the
        # watchers tracking it. The person who LOST it gets the unassigned trigger instead, so
        # one handover never sends the same person two different messages.
        return _ids(extra.get("new_assignee_ids")) | assigner | watchers
    if event == "in_loop_added":
        # Only the people newly put in the loop (as watchers), not the existing ones.
        return _ids(extra.get("new_watcher_ids"))
    if event == "dependent_on_other":
        # The doer the task was handed to, plus the assigner tracking it.
        return _ids(extra.get("doer_id")) | assigner | watchers
    if event == "dependency_resolved":
        # The task is back with whoever delegated the dependency — `assignees` is already the
        # popped list, so this is exactly them (the doer has been dropped) — plus the watchers.
        return assignees | watchers
    if event in ("accepted", "completed", "verification_requested", "blocked"):
        # Progress reported upward, to the person who delegated it.
        return assigner | watchers
    if event == "deadline_revision_requested":
        # The assignee is ASKING for more time — it is the assigner who has to answer.
        return assigner | watchers
    if event in ("deadline_revision_approved", "deadline_revision_rejected"):
        # The verdict goes back to whoever asked for it (plus the rest of the doers/watchers,
        # since an approved request changes the date they all work to).
        return _ids(extra.get("requested_by")) | assignees | watchers
    if event in ("reopened", "verification_approved"):
        # The assigner's verdict, reported back down to whoever did the work.
        return assignees | watchers
    if event in ("due_reminder_daily", "due_reminder_weekly"):
        # A due-date nudge is addressed to the people who have to DO the work.
        return assignees
    if event == "overdue":
        # A missed deadline is the assigner's problem as much as the doer's.
        return assignees | assigner | watchers
    if event == "verification_pending":
        # The chase is aimed at whoever has to close it out — the assigner, never the doer,
        # who has already done their part and is waiting.
        return assigner
    if event == "deleted":
        return assignees | watchers
    if event == "created":
        # In-loop members (watchers) are NOT notified here — they receive the dedicated
        # In Loop Person template via a separate in_loop_added trigger (see notify_task_event),
        # never the Task Created template. Assignees only.
        return assignees
    if event == "subtask_created":
        # Same rule as "created": watchers get the In Loop Person template, not this one.
        return assignees | assigner
    # updated / deadline_revised / follow_up_added — everyone in the loop.
    return assigner | assignees | watchers


# ─── Assigner confirmation ───
# The assigner's own "your assignment went out" receipt. Deliberately NOT a member of
# TASK_EVENT_SLUGS: it is not a lifecycle event anyone can raise by name, it is a SECOND mail
# that rides along with an assignment and is addressed to the one person every other trigger
# deliberately excludes — the actor. Keeping it out of that map also means recipients_for_event,
# the in-app fan-out and every existing template are untouched by it.
ASSIGNER_CONFIRMATION_SLUG = "task_assignment_confirmation"

# The lifecycle events that mean "a user just assigned this task to somebody": a task created
# with assignees, assignees added to an existing task, and a subtask created with assignees.
ASSIGNMENT_EVENTS = ("created", "assigned", "subtask_created")


async def _company_name(company_id) -> str:
    """Display name for {{company_name}}. Empty string when there is no company (internal
    Sparsh staff) or the lookup fails — a missing name must never break an assignment mail."""
    if not company_id:
        return ""
    try:
        from bson import ObjectId
        from app.db.mongodb import get_collection
        doc = await get_collection("companies").find_one({"_id": ObjectId(str(company_id))})
        return (doc or {}).get("name") or ""
    except Exception:
        return ""


async def notify_assigner_confirmation(task: dict, actor: dict, assignee_ids, scope: str = "staff") -> None:
    """Confirm to the ASSIGNER that their task assignment was sent.

    Entirely separate from the assignee's Task Assigned / Task Created mail: its own template,
    its own single recipient (the actor, whom notify_task_event strips from every other
    trigger), its own placeholders. It is additive — by the time this runs the assignee
    notification has already gone out, and nothing here can suppress or alter it.

    Email only. The assigner already knows they made the assignment, so this is a receipt, not
    an alert worth a WhatsApp message.

    Silent when the template is missing or Inactive, exactly like every other Task & Delegation
    trigger — this module never falls back to a built-in body.
    """
    try:
        assignee_ids = [str(a) for a in (assignee_ids or []) if a]
        if not actor.get("email") or not assignee_ids:
            return

        eff_company = None if scope == "staff" else actor.get("company_id")
        if not await active_user_template(f"{ASSIGNER_CONFIRMATION_SLUG}_email", eff_company):
            return

        names = []
        for uid in assignee_ids:
            u = await find_user_by_id(uid)
            if u:
                names.append(u.get("full_name") or u.get("first_name") or u.get("email") or "a team member")
        if not names:
            return

        assigner_name = actor.get("full_name") or actor.get("first_name") or actor.get("email")
        deadline = task.get("end") or task.get("start")
        priority = task.get("priority") or "Normal"
        due_date = format_datetime_standard(deadline)

        context = {
            # ─── The documented placeholders for this template ───
            "assigner_name": assigner_name,
            "assignee_name": ", ".join(names),
            "task_name": task.get("title") or "Untitled Task",
            "priority": priority,
            "due_date": due_date,
            "assigned_date": format_datetime_standard(datetime.now(timezone.utc).isoformat()),
            "company_name": await _company_name(task.get("company_id") or actor.get("company_id")),
            # Aliases, so a body copied from one of the existing task templates still renders
            # rather than printing raw {{placeholders}} (render_template leaves unknown keys as-is).
            "name": assigner_name,
            "actor_name": assigner_name,
            "deadline": due_date,
            "critical_level": priority,
            "description": task.get("description") or task.get("additional_details") or "No description provided.",
        }
        await send_notification_from_template(actor, ASSIGNER_CONFIRMATION_SLUG, context, "email", scope)
    except Exception as e:
        # Never raise into the caller — a receipt failing must not affect the assignment itself
        # or the assignee's notification.
        logger.error(f"Assigner confirmation failed for task '{task.get('title')}': {e}")


def _build_context(event: str, task: dict, actor_name: str, extra: Optional[dict], user_obj: dict) -> dict:
    """Placeholders available to Task Management templates.

    The first block reuses the exact key names the existing task_created / task_updated
    templates already use, so bodies admins wrote against those keep rendering.
    """
    extra = extra or {}
    recipient_name = user_obj.get("full_name") or user_obj.get("first_name") or "User"
    deadline = task.get("end") or task.get("start")

    # date / day / time were part of the old task_created + task_updated context. Templates an
    # admin already customised may reference them, and render_template leaves an unknown
    # placeholder in the body verbatim — so they stay populated here.
    start = task.get("start") or ""
    try:
        dt = to_ist(datetime.fromisoformat(str(start).replace("Z", "+00:00")))
        parsed_date, parsed_day = dt.strftime("%d %b %Y"), dt.strftime("%A")
        parsed_time = "Full Day Block" if task.get("all_day") else dt.strftime("%I:%M %p")
    except Exception:
        parsed_date = parsed_day = parsed_time = str(start) or "TBD"

    context = {
        # ─── Keys the pre-existing task templates already rely on ───
        "task_name": task.get("title") or "Untitled Task",
        "assigned_user": recipient_name,
        "assigned_by": actor_name,
        "deadline": format_datetime_standard(deadline),
        "critical_level": task.get("priority") or "Normal",
        "description": task.get("description") or task.get("additional_details") or "No description provided.",
        "task_status": task.get("workflow_status") or "pending",
        "name": recipient_name,
        "event_title": task.get("title") or "Untitled Task",
        "topic": task.get("title") or "Untitled Task",
        "date": parsed_date,
        "day": parsed_day,
        "time": parsed_time,
        "session_type": "Task",
        # ─── Task Management additions ───
        "actor_name": actor_name,
        "task_category": task.get("category") or "General",
        "reason": extra.get("reason") or "Not specified.",
        "doer_name": extra.get("doer_name") or "",
        "remark": extra.get("remark") or "",
        "old_deadline": format_datetime_standard(extra.get("old_end")) if extra.get("old_end") else "Not set",
        "new_deadline": format_datetime_standard(extra.get("new_end")) if extra.get("new_end") else "Not set",
        # Who asked for the deadline revision (the deadline_revision_* triggers).
        "requested_by_name": extra.get("requested_by_name") or "",
        "parent_task": extra.get("parent_title") or "",
        "subtask_name": extra.get("subtask_title") or "",
        # ─── Reassignment + time-driven nudges ───
        # Populated by the raiser (the update route / the nightly sweep). Empty for every other
        # trigger, which is harmless: render_template only substitutes the keys a body uses.
        "previous_assignee": extra.get("previous_assignee") or "",
        "new_assignee": extra.get("new_assignee") or "",
        # Whole days, as a string so a template can print it directly. "days_overdue" counts
        # past the deadline, "days_remaining" counts down to it — only one is ever meaningful
        # for a given task, and the trigger that fires decides which.
        "days_overdue": str(extra.get("days_overdue") or 0),
        "days_remaining": str(extra.get("days_remaining") or 0),
        "due_date": format_datetime_standard(deadline),
        # The in-loop (watcher) member being notified. On task_in_loop_added the recipient IS
        # the person just put in the loop, so this mirrors their name; on other triggers it
        # simply names whoever is receiving the notification.
        "loop_person": recipient_name,
    }
    return context


async def notify_task_event(
    event: str,
    task: dict,
    actor: dict,
    extra: Optional[dict] = None,
    recipient_ids: Optional[Iterable[str]] = None,
) -> None:
    """Fan a Task Management lifecycle event out over Email / WhatsApp / in-app.

    Never raises into the caller — a notification failure must not roll back the task
    mutation that triggered it. Intended to be awaited from a BackgroundTask or directly
    after the DB write.
    """
    # A personal TODO can never enter the Task pipeline. Todos share the calendar_event document
    # shape and live in the same collections, so a doc reaching here is not self-evidently a
    # task; every call site is already gated on type == "task", but making the exclusion
    # structural means no future caller can wire a private, self-owned todo into an assignment,
    # completion or deletion mail. (Mirrors calendar_events.TODO_TYPE — kept as a literal so
    # this service takes no dependency on the route module.)
    if task.get("type") == "todo":
        return

    slug = TASK_EVENT_SLUGS.get(event)
    if not slug:
        logger.warning(f"notify_task_event: unknown event '{event}'")
        return

    actor_id = str(actor.get("_id") or actor.get("id") or "")
    actor_name = actor.get("full_name") or actor.get("first_name") or actor.get("email") or "A team member"

    targets = set(recipient_ids) if recipient_ids is not None else recipients_for_event(event, task, extra)
    targets = {str(t) for t in targets if t and str(t) != actor_id}
    if not targets:
        return

    # WhatsApp only goes out for staff-scoped work, mirroring the Calendar's rule.
    scope = task.get("notification_scope", "staff")
    delivery = "both" if scope == "staff" else "email"

    title, tone = _IN_APP.get(event, ("Task Notification", "info"))
    task_id = str(task.get("_id") or task.get("id") or "")

    for uid in targets:
        try:
            user_obj = await find_user_by_id(uid)
            if not user_obj:
                continue

            context = _build_context(event, task, actor_name, extra, user_obj)

            await create_in_app_notification(
                user_id=uid,
                title=title,
                message=f"{actor_name}: '{context['task_name']}'",
                type=tone,
                meta={"task_id": task_id, "event": event, "module": "task_management"},
            )
            # Task & Delegation must use ONLY user-configured templates — never a built-in
            # default. Send the email only when an Active DB template (with a body) exists for
            # this event; otherwise send nothing. (In-app above is a separate channel and still
            # fires.) Scope resolution mirrors send_notification_from_template: staff scope
            # ignores company_id.
            eff_company = None if scope == "staff" else user_obj.get("company_id")
            if not await active_user_template(f"{slug}_email", eff_company):
                continue
            await send_notification_from_template(user_obj, slug, context, delivery, scope)
        except Exception as e:
            # Log and keep going: one bad recipient must not silence the rest.
            logger.error(f"Task notification '{event}' failed for user {uid}: {e}")

    # In-loop members are ALWAYS notified with the In Loop Person template — even when they were
    # added at task/subtask creation. "created"/"subtask_created" notify assignees only (above);
    # here the same task's watchers are fanned out through the dedicated in_loop_added trigger so
    # they never receive the Task Created / Subtask Created template. One Event → One Template.
    # (recipient_ids is None guard: an explicit-recipient call must not re-trigger this; and the
    # recursive call is event "in_loop_added", so it can never loop back here.)
    if event in ("created", "subtask_created") and recipient_ids is None:
        watcher_ids = _ids(task.get("watchers")) - _ids(task.get("target_staff_id"))
        if watcher_ids:
            await notify_task_event("in_loop_added", task, actor,
                                    {"new_watcher_ids": list(watcher_ids)})

    # ─── The assigner's own confirmation copy ───
    # Sent IN ADDITION to the assignee notification above, never instead of it, and only on the
    # events that actually constitute assigning work to someone. `targets` is exactly the set of
    # people who were just assigned and notified, so the receipt names the right people and is
    # skipped entirely when an assignment reached nobody (e.g. assigning only to yourself — the
    # actor is stripped above and the function returns before here).
    # The `recipient_ids is None` guard mirrors the in-loop chain: an explicit-recipient call is
    # a targeted re-send to people already on the task, not a fresh assignment.
    if event in ASSIGNMENT_EVENTS and recipient_ids is None:
        await notify_assigner_confirmation(task, actor, sorted(targets), scope)
