"""
Notification module registry — the catalogue behind the central Notification Templates module.

TPMS wires notifications by (activity × side × event) because a TPMS notification is about a
scheduled ACTIVITY, and Leadership Score has one invitation template per company; both keep
their own stores and are managed through their own APIs. Everything else keys a notification
by its trigger's SLUG — exactly the key `notification_templates` has always used — and this
module only adds the *catalogue* the admin screen needs: which triggers exist, what each one is
for, which channels its sending code can actually use, which placeholders it can offer, and
which module it belongs to.

NOTHING HERE DECIDES WHEN ANYTHING SENDS. Every trigger listed below is raised by its own
service (task_notifications, checklist_notifications, calendar_events, reminder_scheduler,
notification_service, …) exactly as before; registering it only makes it visible to the one
management screen. `channels`, `send_rule` and `schedule` DESCRIBE that existing sending code so
the screen can tell an admin the truth about it — they are never read on the send path.

  send_rule "template_only"     — the module sends ONLY from an Active template whose EMAIL copy
                                  has a body (notification_service.active_user_template). No
                                  template means no message on any channel — the WhatsApp copy
                                  included, because the gate is checked on the email slug.
                                  Delegation, Checklist, the upcoming reminders and To-Do.
  send_rule "builtin_fallback"  — fetch_template: company → staff → the built-in
                                  DEFAULT_TEMPLATES entry when one exists. Calendar events,
                                  sessions, attendance, session reminders, user & company mail.

New triggers (reassignment, the time-driven nudges, the checklist series) are deliberately left
out of the settings seeds: a deploy must not be able to start mailing an assignee every day.
Turning each one on is an explicit choice made in Notification Templates.
"""
from typing import Dict, List, Optional

MODULE_DELEGATION = "delegation"
MODULE_CHECKLIST = "checklist"
MODULE_EVENT = "event"
MODULE_SESSION = "session"
MODULE_UPCOMING = "upcoming"
MODULE_TODO = "todo"
MODULE_SYSTEM = "system"

SEND_TEMPLATE_ONLY = "template_only"
SEND_BUILTIN_FALLBACK = "builtin_fallback"

EMAIL = "email"
WHATSAPP = "whatsapp"
BOTH = (EMAIL, WHATSAPP)
EMAIL_ONLY = (EMAIL,)

# Raised by task_nudge_service's once-a-day sweep rather than by a click. The screen shows the
# sweep's configured time beside these (GET /notify-templates/schedule).
SCHEDULE_DAILY_SWEEP = "daily_sweep"

# ─────────────────────────────────────────────────────────────
# Checklist (repeat task) trigger slugs.
#
# Fired by recurring_task_service. Kept as constants so the engine, the registry and the
# settings seeds cannot drift apart on a typo.
# ─────────────────────────────────────────────────────────────
CHECKLIST_OCCURRENCE_CREATED = "checklist_occurrence_created"
CHECKLIST_SERIES_COMPLETED = "checklist_series_completed"


def _trigger(slug: str, label: str, description: str, channels=BOTH, group: str = "",
             variables: Optional[List[str]] = None, schedule: str = "") -> dict:
    """One trigger.

    `description` is written as the answer to "when does this send, and to whom".
    `group` sub-heads a long list so it is scanned rather than scrolled.
    `variables` overrides the module's placeholder list for a trigger whose sending code builds
    its own context (the assigner's confirmation).
    """
    out = {"slug": slug, "label": label, "description": description,
           "channels": list(channels), "group": group, "schedule": schedule}
    if variables is not None:
        out["variables"] = list(variables)
    return out


# ─────────────────────────────────────────────────────────────
# Placeholder catalogues.
#
# These are exactly the keys the sending code puts in its context dict, so a field offered in
# the UI is guaranteed to resolve at send time rather than rendering as a literal
# "{{placeholder}}".
# ─────────────────────────────────────────────────────────────
DELEGATION_VARIABLES = [  # task_notifications._build_context
    "task_name", "assigned_user", "assigned_by", "actor_name", "deadline", "critical_level",
    "description", "task_status", "task_category", "name", "date", "day", "time",
    "reason", "doer_name", "remark", "old_deadline", "new_deadline", "requested_by_name",
    "parent_task", "subtask_name", "loop_person",
    # Reassignment + the time-driven nudges. Populated by whichever trigger raises them and
    # empty elsewhere, which is harmless — render_template only substitutes the keys a body
    # actually uses.
    "previous_assignee", "new_assignee", "due_date", "days_overdue", "days_remaining",
]

ASSIGNER_CONFIRMATION_VARIABLES = [  # task_notifications.notify_assigner_confirmation
    "assigner_name", "assignee_name", "task_name", "priority", "due_date", "assigned_date",
    "company_name", "name", "actor_name", "deadline", "critical_level", "description",
]

CHECKLIST_VARIABLES = [  # checklist_notifications.build_context
    "task_name", "assigned_user", "assigned_by", "deadline", "critical_level", "description",
    "name", "date", "day", "time",
    "repeat_type", "repeat_interval", "occurrence_date", "repeat_end_date",
    "series_total", "task_category",
]

EVENT_VARIABLES = [  # send_event_created_email / _updated_ / _deleted_
    "name", "user_name", "event_title", "topic", "session_type", "date", "day", "time",
    "event_datetime", "meeting_link", "description", "batch_name", "quarter",
    "created_by", "deleted_by",
]

SESSION_VARIABLES = [  # send_session_complete_email / send_attendance_*_email
    "name", "user_name", "topic", "event_title", "event_time",
]

REMINDER_VARIABLES = [  # send_reminder_email
    "name", "title", "reminder_time", "event_time", "task_deadline", "meeting_url", "description",
]

TODO_VARIABLES = [  # send_todo_created_email
    "user_name", "name", "todo_title", "title", "todo_due_date", "todo_due_time", "priority",
    "description", "occurrence_note",
]

SYSTEM_VARIABLES = [  # auth / company routes, send_user_updated_email, send_access_control_email
    "name", "email", "password", "role", "login_url", "new_role", "updated_by", "company_name",
]


NOTIFY_MODULES: Dict[str, dict] = {
    MODULE_DELEGATION: {
        "key": MODULE_DELEGATION,
        "label": "Delegation",
        "description": "Task & Delegation lifecycle — assignment, progress and verification.",
        "send_rule": SEND_TEMPLATE_ONLY,
        "variables": DELEGATION_VARIABLES,
        "triggers": [
            _trigger("task_created", "Task Created",
                     "A task is created with assignees. Goes to the assignees.",
                     group="Assigning work"),
            _trigger("task_assigned", "Task Assigned",
                     "People are added to an existing task. Goes only to the new assignees.",
                     group="Assigning work"),
            _trigger("task_assignment_confirmation", "Assignment Confirmation (Assigner)",
                     "The assigner's own receipt that their assignment went out.",
                     channels=EMAIL_ONLY, group="Assigning work",
                     variables=ASSIGNER_CONFIRMATION_VARIABLES),
            _trigger("task_reassigned", "Task Reassigned",
                     "The task is handed over — somebody taken off and somebody else put on in "
                     "the same edit. Goes to the new holder, the assigner and the watchers.",
                     group="Assigning work"),
            _trigger("task_unassigned", "Removed from Task",
                     "Someone is taken off the task. Goes to that person only.",
                     group="Assigning work"),
            _trigger("task_in_loop_added", "In Loop Person",
                     "Someone is put in the loop as a watcher. Goes to that person.",
                     group="Assigning work"),
            _trigger("task_subtask_created", "Subtask Created",
                     "A subtask is created. Goes to its assignees and the assigner.",
                     group="Assigning work"),
            _trigger("task_accepted", "Task Accepted",
                     "The doer accepts the task. Goes to the assigner.",
                     group="While work is running"),
            _trigger("task_updated", "Task Updated",
                     "Task details change. Goes to everyone on the task.",
                     group="While work is running"),
            _trigger("task_deadline_revised", "Deadline Revised",
                     "The due date moves. Goes to everyone on the task.",
                     group="While work is running"),
            _trigger("task_deadline_revision_requested", "Deadline Revision Requested",
                     "The doer asks for the deadline to be moved. The date does NOT move yet. "
                     "Goes to the assigner, who approves or rejects it.",
                     group="While work is running"),
            _trigger("task_deadline_revision_approved", "Deadline Revision Approved",
                     "The assigner approves the request — this is when the new deadline takes "
                     "effect. Goes to the doer.",
                     group="While work is running"),
            _trigger("task_deadline_revision_rejected", "Deadline Revision Rejected",
                     "The assigner turns the request down and the original deadline stands. "
                     "Goes to the doer.",
                     group="While work is running"),
            _trigger("task_blocked", "Task Blocked",
                     "The doer flags the task as blocked. Goes to the assigner.",
                     group="While work is running"),
            _trigger("task_dependent_on_other", "Dependent on Other",
                     "The task is handed to another doer it now depends on.",
                     group="While work is running"),
            _trigger("task_dependency_resolved", "Dependency Completed",
                     "The doer finishes the dependency and the task returns to the assignee who "
                     "raised it, for review and final completion. Goes to that assignee.",
                     group="While work is running"),
            _trigger("task_follow_up_added", "Follow-up Added",
                     "A follow-up is posted. Goes to everyone on the task.",
                     group="While work is running"),
            _trigger("task_deleted", "Task Deleted",
                     "A task is deleted. Goes to its assignees and watchers.",
                     group="While work is running"),
            _trigger("task_completed", "Task Completed",
                     "The doer marks the task complete. Goes to the assigner.",
                     group="Finishing & sign-off"),
            _trigger("task_verification_requested", "Verification Requested",
                     "The doer asks for sign-off. Goes to the assigner.",
                     group="Finishing & sign-off"),
            _trigger("task_verification_approved", "Verification Approved",
                     "The assigner signs the work off. Goes to the doer.",
                     group="Finishing & sign-off"),
            _trigger("task_reopened", "Task Reopened",
                     "The assigner reopens the task. Goes to the doer.",
                     group="Finishing & sign-off"),
            # ─── Time-driven (raised by the daily sweep, not by any user action) ───
            _trigger("task_due_reminder_daily", "Daily Due Reminder",
                     "Every day until the task is completed or its due date is reached. Goes "
                     "to the assignees.",
                     group="Reminders & chasers", schedule=SCHEDULE_DAILY_SWEEP),
            _trigger("task_due_reminder_weekly", "Weekly Due Reminder",
                     "Every 7 days while the task is open, plus the due date itself. Goes to "
                     "the assignees.",
                     group="Reminders & chasers", schedule=SCHEDULE_DAILY_SWEEP),
            _trigger("task_overdue", "Overdue Alert",
                     "Once, the first day after a deadline is missed. Goes to the assignees, "
                     "the assigner and the watchers.",
                     group="Reminders & chasers", schedule=SCHEDULE_DAILY_SWEEP),
            _trigger("task_verification_pending_reminder", "Verification Chase (Assigner)",
                     "Every alternate day while a task waits for sign-off. Goes to the "
                     "assigner only.",
                     group="Reminders & chasers", schedule=SCHEDULE_DAILY_SWEEP),
        ],
    },
    MODULE_CHECKLIST: {
        "key": MODULE_CHECKLIST,
        "label": "Checklist",
        "description": ("Repeating task series. A repeat occurrence is a task, so its "
                        "assignment and completion messages come from Delegation — these two "
                        "cover the series itself."),
        "send_rule": SEND_TEMPLATE_ONLY,
        "variables": CHECKLIST_VARIABLES,
        "triggers": [
            _trigger(CHECKLIST_OCCURRENCE_CREATED, "Repeat Task Generated",
                     "The nightly engine creates this period's occurrence of a repeating task. "
                     "Goes to its assignees and watchers."),
            _trigger(CHECKLIST_SERIES_COMPLETED, "Repeat Series Ended",
                     "A repeating task passes its end date. Sent once, to the assigner and "
                     "assignees."),
        ],
    },
    MODULE_EVENT: {
        "key": MODULE_EVENT,
        "label": "Calendar Events",
        "description": "Sessions and events on the calendar — scheduled, changed or cancelled.",
        "send_rule": SEND_BUILTIN_FALLBACK,
        "variables": EVENT_VARIABLES,
        "triggers": [
            _trigger("event_created", "Event Scheduled",
                     "A session or event is put on the calendar. Goes to its attendees."),
            _trigger("event_updated", "Event Updated",
                     "A session or event is changed or moved. Goes to its attendees."),
            _trigger("event_deleted", "Event Cancelled",
                     "A session or event is cancelled. Goes to its attendees."),
        ],
    },
    MODULE_SESSION: {
        "key": MODULE_SESSION,
        "label": "Sessions & Attendance",
        "description": "Session reminders, completion and attendance.",
        "send_rule": SEND_BUILTIN_FALLBACK,
        "variables": SESSION_VARIABLES,
        "triggers": [
            # send_reminder_email builds its own context, so this trigger carries its own
            # placeholder list rather than the session one.
            _trigger("reminder", "Session Reminder",
                     "A reminder set on a session or event reaches its time. Goes to the person "
                     "the reminder is for.",
                     channels=EMAIL_ONLY, variables=REMINDER_VARIABLES),
            _trigger("session_complete", "Session Completed",
                     "A session is marked complete. Goes to its attendees."),
            _trigger("attendance_thanks", "Marked Present",
                     "Attendance is taken and the person is marked present.",
                     channels=EMAIL_ONLY),
            _trigger("attendance_absent", "Marked Absent",
                     "Attendance is taken and the person is marked absent.",
                     channels=EMAIL_ONLY),
        ],
    },
    MODULE_UPCOMING: {
        "key": MODULE_UPCOMING,
        "label": "Upcoming Reminders",
        "description": "Reminders set on a task or a to-do, sent when their time arrives.",
        "send_rule": SEND_TEMPLATE_ONLY,
        "variables": REMINDER_VARIABLES,
        "triggers": [
            _trigger("upcoming_task_reminder", "Upcoming Task Reminder",
                     "A reminder set on a task reaches its time. Goes to the person the "
                     "reminder is for.",
                     channels=EMAIL_ONLY),
            _trigger("upcoming_todo_reminder", "Upcoming To-do Reminder",
                     "A reminder set on a to-do reaches its time. Goes to the to-do's owner.",
                     channels=EMAIL_ONLY),
        ],
    },
    MODULE_TODO: {
        "key": MODULE_TODO,
        "label": "To-Do",
        "description": "Personal calendar to-dos.",
        "send_rule": SEND_TEMPLATE_ONLY,
        # send_todo_created_email always resolves the staff (default) template.
        "staff_only": True,
        "variables": TODO_VARIABLES,
        "triggers": [
            _trigger("todo_created", "To-do Added",
                     "Someone adds a to-do to their calendar (a repeating one counts once). "
                     "Goes to its owner.",
                     channels=EMAIL_ONLY),
        ],
    },
    MODULE_SYSTEM: {
        "key": MODULE_SYSTEM,
        "label": "Users & Companies",
        "description": "Account mail — welcome, profile and role changes, new companies.",
        "send_rule": SEND_BUILTIN_FALLBACK,
        "variables": SYSTEM_VARIABLES,
        "triggers": [
            _trigger("user_creation", "User Created",
                     "A new user account is created. Carries their login details.",
                     channels=EMAIL_ONLY),
            _trigger("user_edit", "Profile Updated",
                     "A user's profile is updated by someone else.",
                     channels=EMAIL_ONLY),
            _trigger("user_access_control_change", "Role Changed",
                     "A user's role is changed.",
                     channels=EMAIL_ONLY),
            _trigger("company_registration", "Company Registered",
                     "A new client company is onboarded. Goes to its admin with their login.",
                     channels=EMAIL_ONLY),
        ],
    },
}

# Every slug this registry knows, module-tagged. Used to reject a wiring row for a trigger
# that does not exist rather than silently storing a template nothing will ever read.
SLUG_MODULE: Dict[str, str] = {
    t["slug"]: key for key, mod in NOTIFY_MODULES.items() for t in mod["triggers"]
}


def _bare(slug: str) -> str:
    bare = str(slug or "")
    for suffix in ("_email", "_whatsapp"):
        if bare.endswith(suffix):
            return bare[: -len(suffix)]
    return bare


def module_for_slug(slug: str) -> Optional[str]:
    """Which module a trigger slug belongs to, or None when it is not a registered trigger.

    Accepts a channel-suffixed slug ("task_created_email") as well as the bare trigger, because
    that is how the slug is stored on a `notification_templates` document.
    """
    if not slug:
        return None
    return SLUG_MODULE.get(_bare(slug))


def find_trigger(slug: str) -> Optional[dict]:
    module = module_for_slug(slug)
    if not module:
        return None
    bare = _bare(slug)
    return next((t for t in NOTIFY_MODULES[module]["triggers"] if t["slug"] == bare), None)


def module_triggers(module: str) -> List[dict]:
    return list((NOTIFY_MODULES.get(module) or {}).get("triggers") or [])


def module_variables(module: str) -> List[str]:
    return list((NOTIFY_MODULES.get(module) or {}).get("variables") or [])


def trigger_variables(slug: str) -> List[str]:
    """The placeholders one trigger's context actually carries — its own list when it has one,
    otherwise its module's."""
    trigger = find_trigger(slug) or {}
    if trigger.get("variables"):
        return list(trigger["variables"])
    return module_variables(module_for_slug(slug) or "")
