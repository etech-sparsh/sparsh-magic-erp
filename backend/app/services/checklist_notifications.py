"""Notifications for the Checklist module — repeating task series.

A repeat occurrence is itself a `type: "task"` document, so everything that happens TO it once
it exists (assigned, accepted, completed, verified, …) already fans out through
task_notifications. What had no notification at all is the recurrence engine's own work:

  • an occurrence being rolled forward for a new period — created by a nightly job, so nobody
    is told a fresh task is now sitting on their list;
  • a series reaching its Repeat End Date — after which it silently stops producing work.

Those two are this module's triggers. The Email/WhatsApp engine is entirely reused
(send_notification_from_template resolves the template, picks the channel and applies the
per-template Active switch); only the slugs, the recipients and the context live here.

SILENT BY DEFAULT. Like the rest of Task & Delegation this module never falls back to a
built-in body — no Active template for the slug means no send. The two slugs are also left out
of the settings seeds on purpose, so an upgrade cannot start mailing every assignee nightly:
somebody has to create the template on Task Management ▸ Templates first.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from app.models.notify_modules import (
    CHECKLIST_OCCURRENCE_CREATED,
    CHECKLIST_SERIES_COMPLETED,
)
from app.services.notification_service import (
    active_user_template,
    create_in_app_notification,
    format_datetime_standard,
    send_notification_from_template,
    to_ist,
)
from app.services.task_notifications import _ids
from app.utils.calendar_utils import find_user_by_id

logger = logging.getLogger(__name__)

# In-app title + tone, mirroring task_notifications._IN_APP.
_IN_APP = {
    CHECKLIST_OCCURRENCE_CREATED: ("Repeat Task Generated", "info"),
    CHECKLIST_SERIES_COMPLETED: ("Repeat Series Ended", "warning"),
}

# Marker written on a series head once its "ended" notice has gone out. Without it the nightly
# job would re-announce the same finished series every single night.
SERIES_DONE_FLAG = "series_completed_notified"


def _parts(value):
    """(date, day, time) for a task's date field, rendered in IST like the task templates."""
    try:
        dt = to_ist(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
        return dt.strftime("%d %b %Y"), dt.strftime("%A"), dt.strftime("%I:%M %p")
    except Exception:
        text = str(value or "") or "TBD"
        return text, text, text


def build_context(task: dict, recipient: dict, extra: Optional[dict] = None) -> dict:
    """Placeholders for the checklist templates.

    The first block deliberately uses the SAME key names as the delegation templates
    (task_name / assigned_user / deadline / …), so a body copied from a Task template renders
    correctly here instead of printing raw {{placeholders}} — render_template leaves an unknown
    key in the body verbatim.
    """
    extra = extra or {}
    recipient_name = recipient.get("full_name") or recipient.get("first_name") or "User"
    deadline = task.get("end") or task.get("start")
    date_str, day_str, time_str = _parts(task.get("start"))

    return {
        # ─── Shared with the delegation templates ───
        "task_name": task.get("title") or "Untitled Task",
        "assigned_user": recipient_name,
        "assigned_by": extra.get("assigner_name") or "",
        "name": recipient_name,
        "deadline": format_datetime_standard(deadline),
        "critical_level": task.get("priority") or "Normal",
        "description": task.get("description") or task.get("additional_details") or "No description provided.",
        "task_category": task.get("category") or "General",
        "date": date_str,
        "day": day_str,
        "time": time_str,
        # ─── Repeat-series specific ───
        "repeat_type": task.get("repeat") or "Does not repeat",
        "repeat_interval": str(task.get("repeat_interval") or 1),
        "occurrence_date": date_str,
        "repeat_end_date": format_datetime_standard(task.get("repeat_end_date")) if task.get("repeat_end_date") else "No end date",
        "series_total": str(extra.get("series_total") or ""),
    }


async def _notify(slug: str, task: dict, recipient_ids, extra: Optional[dict] = None) -> int:
    """Fan one checklist trigger out to `recipient_ids`. Returns how many were notified.

    Never raises into the caller: the nightly recurrence engine must finish rolling every
    series forward even if a notification fails, and a task that exists but was not announced
    is far better than a series that stopped generating.
    """
    targets = {str(t) for t in (recipient_ids or set()) if t}
    if not targets:
        return 0

    # WhatsApp only goes out for staff-scoped work, mirroring the Calendar and Task rules.
    scope = task.get("notification_scope", "staff")
    delivery = "both" if scope == "staff" else "email"
    title, tone = _IN_APP.get(slug, ("Repeat Task", "info"))
    task_id = str(task.get("_id") or task.get("id") or "")

    sent = 0
    for uid in targets:
        try:
            user_obj = await find_user_by_id(uid)
            if not user_obj:
                continue
            context = build_context(task, user_obj, extra)

            await create_in_app_notification(
                user_id=uid,
                title=title,
                message=f"'{context['task_name']}' — {context['occurrence_date']}",
                type=tone,
                meta={"task_id": task_id, "event": slug, "module": "checklist"},
            )
            # Only a user-configured, Active template sends. Scope resolution mirrors
            # send_notification_from_template: staff scope ignores company_id.
            eff_company = None if scope == "staff" else user_obj.get("company_id")
            if not await active_user_template(f"{slug}_email", eff_company):
                continue
            await send_notification_from_template(user_obj, slug, context, delivery, scope)
            sent += 1
        except Exception as e:
            # One bad recipient must not silence the rest, nor abort the rollover.
            logger.error(f"Checklist notification '{slug}' failed for user {uid}: {e}")
    return sent


async def notify_occurrence_created(task: dict) -> int:
    """Announce a freshly rolled-forward occurrence to the people who have to do it.

    Watchers are included: an in-loop member follows the work, and a new period of it starting
    is exactly the kind of thing being in the loop is for.
    """
    try:
        if task.get("type") != "task":
            return 0
        recipients = _ids(task.get("target_staff_id")) | _ids(task.get("watchers"))
        return await _notify(CHECKLIST_OCCURRENCE_CREATED, task, recipients)
    except Exception as e:
        logger.error(f"notify_occurrence_created failed for '{task.get('title')}': {e}")
        return 0


async def notify_series_completed(head: dict, series_total: int = 0) -> int:
    """Announce that a series has produced its last occurrence.

    Goes to the assigner as well as the doers: the person who set the repeat up is the one who
    has to decide whether to extend it, and they are the only one who can.
    """
    try:
        recipients = (_ids(head.get("target_staff_id"))
                      | _ids(head.get("user_id"))
                      | _ids(head.get("watchers")))
        return await _notify(CHECKLIST_SERIES_COMPLETED, head, recipients,
                             {"series_total": series_total})
    except Exception as e:
        logger.error(f"notify_series_completed failed for '{head.get('title')}': {e}")
        return 0


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
