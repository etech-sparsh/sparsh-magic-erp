from app.config.settings import settings
import requests
import logging
from typing import Optional, Dict, Any
from app.db.mongodb import get_collection
from app.services.whatsapp_components import build_send_components, resolve_params
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import asyncio

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL notification switch (currently ENABLED — all non-TPMS modules notify normally).
# When set to False it becomes a kill-switch: NO template-based notification (email or
# WhatsApp) is sent for ANY module, since everything funnels through
# send_notification_from_template() below. Left ON so other ERP modules (calendar, tasks,
# ORM…) remain unchanged; TPMS is silenced separately via TPMS_NOTIFICATIONS_ENABLED.
# Flip to False for a full ERP-wide blackout (requires a backend restart to take effect).
NOTIFICATIONS_ENABLED = True

SESSION_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0; background-color: #f9f9f9; }
        .container { max-width: 600px; margin: 20px auto; background: #ffffff; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.05); }
        .header { background-color: #00684a; color: #ffffff; padding: 20px; text-align: center; }
        .header h1 { margin: 0; font-size: 24px; font-weight: 700; }
        .content { padding: 30px; }
        .footer { padding: 20px; text-align: center; border-top: 1px solid #eeeeee; background-color: #fafafa; }
        .session-type { font-weight: bold; }
        .meeting-link { display: block; margin: 15px 0; color: #1a73e8; font-weight: bold; text-decoration: none; word-break: break-all; }
        .details-header { font-size: 16px; font-weight: 800; color: #00684a; border-bottom: 2px solid #00684a; margin-top: 25px; margin-bottom: 15px; padding-bottom: 5px; }
        .details-table { width: 100%; border-collapse: collapse; }
        .details-table td { padding: 8px 0; font-size: 14px; }
        .details-label { width: 80px; font-weight: bold; color: #666; }
        .details-value { font-weight: bold; }
        .time-value { color: #d32f2f; }
        .important-box { background-color: #fdf5d7; border: 1px solid #fbe8a1; border-radius: 6px; padding: 15px; margin-top: 25px; font-size: 14px; }
        .important-box strong { color: #856404; }
        .regards { margin-top: 25px; color: #555; font-size: 14px; }
        .team-name { color: #00684a; font-weight: 900; font-size: 18px; margin: 5px 0; }
        .website { font-size: 12px; color: #888; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Greetings from Sparsh Magic!</h1>
        </div>
        <div class="content">
            <p>Hello,</p>
            <p>This is to inform you that the <span class="session-type">{{session_type}}</span> session has been scheduled.</p>
            <p><strong>Please join the session using the link below:</strong></p><a href="{{meeting_link}}" class="meeting-link">{{meeting_link}}</a>
            
            <div class="details-header">SESSION DETAILS</div>
            <table class="details-table">
                <tr>
                    <td class="details-label">Topic:</td>
                    <td class="details-value">{{topic}}</td>
                </tr>
                <tr>
                    <td class="details-label">Date:</td>
                    <td class="details-value">{{date}}</td>
                </tr>
                <tr>
                    <td class="details-label">Day:</td>
                    <td class="details-value">{{day}}</td>
                </tr>
                <tr>
                    <td class="details-label">Time:</td>
                    <td class="details-value time-value">{{time}}</td>
                </tr>
            </table>

            <div class="important-box"><strong>IMPORTANT:</strong> Kindly join on time and ensure you are on camera during the meeting.</div>

            <div class="regards">
                With Best Regards,<br>
                <div class="team-name">Sparsh Magic Team</div>
                Website - <a href="https://www.sparshmagic.com" class="website">www.sparshmagic.com</a>
            </div>
        </div>
    </div>
</body>
</html>"""

CONFLICT_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0; background-color: #fff4f4; }
        .container { max-width: 600px; margin: 20px auto; background: #ffffff; border: 2px solid #ffcccc; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(220, 53, 69, 0.1); }
        .header { background-color: #dc3545; color: #ffffff; padding: 25px; text-align: center; }
        .header h1 { margin: 0; font-size: 22px; font-weight: 900; text-transform: uppercase; letter-spacing: 2px; }
        .content { padding: 30px; }
        .conflict-box { background-color: #fff8f8; border: 1px solid #ffdfdf; border-radius: 8px; padding: 20px; margin: 20px 0; }
        .event-title { font-weight: 800; color: #dc3545; font-size: 16px; }
        .time-label { font-size: 12px; color: #888; text-transform: uppercase; font-weight: bold; margin-top: 10px; display: block; }
        .time-value { font-size: 14px; font-weight: 700; color: #333; }
        .divider { border: 0; border-top: 2px dashed #ffdfdf; margin: 20px 0; }
        .action-btn { display: inline-block; padding: 12px 25px; background-color: #dc3545; color: #ffffff; text-decoration: none; border-radius: 6px; font-weight: 800; text-transform: uppercase; font-size: 12px; letter-spacing: 1px; margin-top: 20px; }
        .footer { padding: 20px; text-align: center; font-size: 11px; color: #999; border-top: 1px solid #eeeeee; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚠️ Schedule Conflict Detected</h1>
        </div>
        <div class="content">
            <p>Hello <strong>{{user_name}}</strong>,</p>
            <p>Our scheduling engine has detected a timing overlap in your calendar. To maintain operational flow, one of these entries requires rescheduling.</p>
            
            <div class="conflict-box">
                <span class="time-label">New Entry [Conflict Caused By]:</span>
                <div class="event-title">{{event_title}}</div>
                <div class="time-value">{{event_time}}</div>
                
                <hr class="divider">
                
                <span class="time-label">Existing Entry [Overlapped]:</span>
                <div class="event-title">{{existing_event}}</div>
                <div class="time-value">{{existing_time}}</div>
            </div>

            <p>Please log in to the <strong>Sparsh ERP Dashboard</strong> to resolve this conflict immediately.</p>
            <center><a href="https://sparshmagic.com/calendar" class="action-btn">Resolve Conflict Now</a></center>

            <p style="font-size: 12px; color: #666; margin-top: 30px; font-style: italic;">Note: A copy of this notification has been sent to your registered organization for coordination.</p>
        </div>
        <div class="footer">
            © 2026 Sparsh Magic Operational Support • Automatic System Alert
        </div>
    </div>
</body>
</html>"""

OTP_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; line-height: 1.6; margin: 0; padding: 0; background-color: #f4f7f6; }
        .container { max-width: 500px; margin: 40px auto; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.08); }
        .header { background: linear-gradient(135deg, #00684a 0%, #00a375 100%); color: #ffffff; padding: 40px 20px; text-align: center; }
        .header h1 { margin: 0; font-size: 28px; font-weight: 800; letter-spacing: -0.5px; }
        .content { padding: 40px; text-align: center; }
        .otp-badge { display: inline-block; padding: 15px 40px; background-color: #f0f7f4; border: 2px dashed #00684a; color: #00684a; font-size: 36px; font-weight: 900; letter-spacing: 12px; border-radius: 12px; margin: 30px 0; text-indent: 12px; }
        .instruction { font-size: 15px; color: #666; margin-bottom: 20px; }
        .warning { font-size: 13px; color: #e74c3c; background-color: #fdf2f2; padding: 12px; border-radius: 8px; margin-top: 30px; }
        .footer { padding: 25px; text-align: center; background-color: #fafafa; border-top: 1px solid #eeeeee; font-size: 12px; color: #999; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Password Reset</h1>
        </div>
        <div class="content">
            <p style="font-size: 18px; font-weight: 600; color: #2c3e50; margin-bottom: 10px;">Security Verification</p>
            <p class="instruction">Use the following 6-digit code to verify your password reset request. This code is valid for 60 seconds.</p>
            
            <div class="otp-badge">{{otp}}</div>
            
            <p class="instruction">If you didn't request this, you can safely ignore this email. No changes will be made to your account until you verify.</p>
            
            <div class="warning">
                <strong>Safety Tip:</strong> Never share this code with anyone. Sparsh Team will never ask for your OTP over phone or email.
            </div>
        </div>
        <div class="footer">
            © 2026 Sparsh Magic • Security Operations Team
        </div>
    </div>
</body>
</html>"""

# Shared body for both Upcoming Reminder templates (task + todo). Renamed from
# TASK_REMINDER_HTML_TEMPLATE when the reminder slugs moved to the `upcoming_` prefix.
UPCOMING_REMINDER_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #1f2430; line-height: 1.6; margin: 0; padding: 0; background-color: #f4f5fb; }
        .container { max-width: 600px; margin: 24px auto; background: #ffffff; border: 1px solid #e6e8f0; border-radius: 14px; overflow: hidden; box-shadow: 0 6px 20px rgba(79,70,229,0.08); }
        .header { background: linear-gradient(120deg, #4f46e5 0%, #6d28d9 100%); color: #ffffff; padding: 28px 24px; text-align: center; }
        .header .bell { font-size: 26px; line-height: 1; }
        .header h1 { margin: 8px 0 0; font-size: 22px; font-weight: 800; letter-spacing: .3px; }
        .content { padding: 28px 26px; }
        .task-title { font-size: 18px; font-weight: 800; color: #111827; margin: 0 0 6px; }
        .lede { color: #4b5563; font-size: 14px; margin: 0 0 20px; }
        .deadline { background: #fef2f2; border: 1px solid #fecaca; border-radius: 10px; padding: 14px 16px; margin: 0 0 18px; }
        .deadline .label { font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .6px; color: #b91c1c; }
        .deadline .value { font-size: 15px; font-weight: 800; color: #991b1b; margin-top: 2px; }
        .desc { background: #f8f9fc; border: 1px solid #eef0f6; border-radius: 10px; padding: 14px 16px; font-size: 14px; color: #374151; }
        .desc .label { font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .6px; color: #6b7280; display: block; margin-bottom: 4px; }
        .foot-note { margin-top: 22px; color: #6b7280; font-size: 13px; }
        .footer { padding: 18px; text-align: center; background: #0f172a; color: #cbd5e1; font-size: 12px; font-weight: 700; letter-spacing: .4px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="bell">&#128276;</div>
            <h1>Task Reminder</h1>
        </div>
        <div class="content">
            <p class="task-title">{{title}}</p>
            <p class="lede">This is a reminder about your task. Please review it and keep it on track.</p>
            <div class="deadline">
                <div class="label">&#9200; Task Deadline</div>
                <div class="value">{{task_deadline}}</div>
            </div>
            <div class="desc">
                <span class="label">Description</span>
                {{description}}
            </div>
            <p class="foot-note">Open Sparsh to view and update this task.</p>
        </div>
        <div class="footer">Sparsh Magic LLP</div>
    </div>
</body>
</html>"""

DEFAULT_TEMPLATES = {
    "user_creation_email": {
        "subject": "Welcome to Sparsh 2.0 - Your Account Details",
        "body": "Hello {{name}},\n\nWelcome to Sparsh 2.0! Your account has been created successfully.\n\nCredentials:\nEmail: {{email}}\nTemporary Password: {{password}}\n\nYou can login here: {{login_url}}\n\nRegards,\nTeam Sparsh"
    },
    "task_created_email": {
        "subject": "New Task Assigned: {{task_name}}",
        "body": "Hello {{assigned_user}},\n\nA new task '{{task_name}}' has been assigned to you by {{assigned_by}}.\n\nDeadline: {{deadline}}\nPriority: {{critical_level}}\nDescription: {{description}}\n\nRegards,\nSparsh Notifications"
    },
    # NOTE: there is deliberately NO default entry for upcoming_task_reminder_email,
    # upcoming_todo_reminder_email or todo_created_email. fetch_template() falls back to this
    # dict when no DB doc resolves, which would have let those triggers render a built-in body
    # nobody configured. They must resolve ONLY to the admin's template in
    # Settings ▸ Notifications — no template, or an inactive one, means no email. The seeded
    # copies in routes/settings.py (TEMPLATE_SEEDS) supply the starting content instead.
    #
    # todo_created_email joined that list on request: a To-do mail now goes out only once the
    # admin has activated its template. The gate is in send_todo_created_email rather than
    # here, because removing the entry alone would silently fall through to whatever
    # lower-precedence doc happened to resolve — see active_user_template.
    # ─── Task Management (Delegation) module ───
    # Separate triggers from the Calendar's. task_created/updated/deleted are the
    # pre-existing slugs (they only ever fired for delegation tasks); the rest are new.
    # See app/services/task_notifications.py for the recipients and context of each.
    "task_updated_email": {
        "subject": "Task Updated: {{task_name}}",
        "body": "Hello {{name}},\n\nThe task '{{task_name}}' was updated by {{actor_name}}.\n\nDeadline: {{deadline}}\nPriority: {{critical_level}}\nStatus: {{task_status}}\n\nRegards,\nSparsh Notifications"
    },
    "task_deleted_email": {
        "subject": "Task Deleted: {{task_name}}",
        "body": "Hello {{name}},\n\nThe task '{{task_name}}' has been deleted by {{actor_name}}.\n\nRegards,\nSparsh Notifications"
    },
    "task_assigned_email": {
        "subject": "Task Assigned: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has assigned you the task '{{task_name}}'.\n\nDeadline: {{deadline}}\nPriority: {{critical_level}}\nDescription: {{description}}\n\nRegards,\nSparsh Notifications"
    },
    "task_accepted_email": {
        "subject": "Task Accepted: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has accepted the task '{{task_name}}'.\n\nDeadline: {{deadline}}\n\nRegards,\nSparsh Notifications"
    },
    "task_completed_email": {
        "subject": "Task Completed: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has marked the task '{{task_name}}' as completed.\n\nRegards,\nSparsh Notifications"
    },
    "task_reopened_email": {
        "subject": "Task Reopened: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has reopened the task '{{task_name}}'. It needs further work.\n\nReason: {{reason}}\nDeadline: {{deadline}}\n\nRegards,\nSparsh Notifications"
    },
    "task_verification_requested_email": {
        "subject": "Verification Requested: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has submitted the task '{{task_name}}' for your verification.\n\nPlease review it and either approve the completion or reopen the task.\n\nRegards,\nSparsh Notifications"
    },
    "task_verification_approved_email": {
        "subject": "Verification Approved: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has verified and approved your completion of the task '{{task_name}}'.\n\nRegards,\nSparsh Notifications"
    },
    "task_deadline_revised_email": {
        "subject": "Deadline Revised: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has revised the deadline for the task '{{task_name}}'.\n\nPrevious deadline: {{old_deadline}}\nNew deadline: {{new_deadline}}\nReason: {{reason}}\n\nRegards,\nSparsh Notifications"
    },
    "task_deadline_revision_requested_email": {
        "subject": "Deadline Revision Requested: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has requested a revision of the deadline for the task '{{task_name}}'.\n\nCurrent deadline: {{old_deadline}}\nRequested deadline: {{new_deadline}}\nReason: {{reason}}\n\nThe deadline has NOT changed yet - please approve or reject the request.\n\nRegards,\nSparsh Notifications"
    },
    "task_deadline_revision_approved_email": {
        "subject": "Deadline Revision Approved: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has approved the deadline revision requested by {{requested_by_name}} for the task '{{task_name}}'.\n\nPrevious deadline: {{old_deadline}}\nNew deadline: {{new_deadline}}\nRemark: {{remark}}\n\nThe new deadline is now in force.\n\nRegards,\nSparsh Notifications"
    },
    "task_deadline_revision_rejected_email": {
        "subject": "Deadline Revision Rejected: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has rejected the deadline revision requested by {{requested_by_name}} for the task '{{task_name}}'.\n\nRequested deadline: {{new_deadline}}\nRemark: {{remark}}\n\nThe original deadline of {{old_deadline}} still stands.\n\nRegards,\nSparsh Notifications"
    },
    "task_blocked_email": {
        "subject": "Task Blocked: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has marked the task '{{task_name}}' as Blocked.\n\nReason: {{reason}}\n\nRegards,\nSparsh Notifications"
    },
    "task_dependent_on_other_email": {
        "subject": "Task Dependent on Other: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has marked the task '{{task_name}}' as Dependent on Other, waiting on {{doer_name}}.\n\nReason: {{reason}}\nDeadline: {{deadline}}\n\nRegards,\nSparsh Notifications"
    },
    "task_dependency_resolved_email": {
        "subject": "Dependency Completed: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has completed the dependency on the task '{{task_name}}'.\n\nThe task is back with you for review and final completion.\n\nDeadline: {{deadline}}\n\nRegards,\nSparsh Notifications"
    },
    "task_follow_up_added_email": {
        "subject": "Follow-up on: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has raised a follow-up on the task '{{task_name}}'.\n\nRemark: {{remark}}\nDeadline: {{deadline}}\n\nRegards,\nSparsh Notifications"
    },
    "task_subtask_created_email": {
        "subject": "Subtask Created: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has created the subtask '{{task_name}}' under '{{parent_task}}'.\n\nDeadline: {{deadline}}\nPriority: {{critical_level}}\n\nRegards,\nSparsh Notifications"
    },
    "task_in_loop_added_email": {
        "subject": "You're now in the loop on: {{task_name}}",
        "body": "Hello {{name}},\n\n{{actor_name}} has added you to keep track of the task '{{task_name}}'.\n\nDeadline: {{deadline}}\nPriority: {{critical_level}}\n\nRegards,\nSparsh Notifications"
    },
    "event_created_email": {
        "subject": "Session Scheduled: {{event_title}}",
        "body": SESSION_HTML_TEMPLATE
    },
    "session_complete_email": {
        "subject": "Session Completed: {{topic}}",
        "body": "Hello {{user_name}},\n\nThe session '{{topic}}' has been successfully completed. Thank you for your participation.\n\nYou can access all session resources and recordings via the Sparsh 2.0 dashboard.\n\nRegards,\nTeam Sparsh"
    },
    "attendance_thanks_email": {
        "subject": "Participation Authenticated: {{event_title}}",
        "body": "Hello {{user_name}},\n\nThank you for attending the session '{{event_title}}' on {{event_time}}. Your presence has been verified and your engagement points have been updated.\n\nRegards,\nTeam Sparsh"
    },
    "attendance_absent_email": {
        "subject": "Absence Noted: {{event_title}}",
        "body": "Hello {{user_name}},\n\nWe missed you in today's session '{{event_title}}' at {{event_time}}. Please ensure you review the shared materials and complete any pending tasks to stay on track.\n\nRegards,\nTeam Sparsh"
    },
    "event_deleted_email": {
        "subject": "Session Cancelled: {{event_title}}",
        "body": "Hello {{name}},\n\nThis is to notify you that the session '{{event_title}}' has been cancelled by {{deleted_by}}.\n\nRegards,\nTeam Sparsh"
    },
    "password_reset_otp_email": {
        "subject": "{{otp}} is your Sparsh verification code",
        "body": OTP_HTML_TEMPLATE
    }
}

async def fetch_template(slug: str, company_id: str = None):
    """Resolve the notification template that should be used for `slug`.

    Precedence: company-scoped doc → staff-scoped doc → hardcoded DEFAULT.
    IMPORTANT (Active/Inactive feature): the resolution deliberately does NOT
    filter on `is_active` in the query. Instead we resolve the doc that *would*
    be used and, if an admin has deactivated it (is_active == False), we return
    None so the caller skips sending entirely — an inactive template must never
    fall through to a lower-precedence template or the hardcoded default.
    Missing `is_active` is treated as active so legacy docs keep working.

    Duplicates: the collection can hold several docs for the same (slug, scope, company)
    — POST /settings/templates used to insert blindly, so hitting "New Override" twice for
    one trigger left two copies. find_one() returned them in natural (insertion) order, which
    meant a stale *deactivated* copy could shadow a newer active one and silently kill the
    send. Resolution is therefore explicitly newest-first: the most recently touched doc is
    the admin's latest intent. create_template now upserts, so new duplicates can't appear."""
    col = get_collection("notification_templates")

    async def _newest(query: dict):
        docs = await col.find(query).to_list(50)
        if not docs:
            return None
        return max(docs, key=lambda d: d.get("updated_at") or d.get("created_at") or datetime.min)

    doc = None
    if company_id:
        doc = await _newest({
            "slug": slug,
            "company_id": str(company_id),
            "scope": "company",
        })

    if doc is None:
        doc = await _newest({
            "slug": slug,
            "scope": "staff",
        })

    if doc is not None:
        # Respect the per-template Active/Inactive switch. Inactive => skip sending.
        if not doc.get("is_active", True):
            return None
        return doc

    return DEFAULT_TEMPLATES.get(slug)


async def active_user_template(slug: str, company_id: str = None):
    """The USER-CONFIGURED DB template for `slug`, or None.

    Resolution mirrors fetch_template (company scope → staff scope, newest wins) but it NEVER
    falls back to a built-in DEFAULT_TEMPLATES entry, and it treats an Inactive template or one
    with an empty body as "no template". Used by modules that must send ONLY user-configured
    templates — Task & Delegation and Personal Todo — so a missing / inactive / empty template
    results in NO email (never a default). Leaves fetch_template (and every other module that
    relies on the built-in defaults — sessions, OTP, user/company mail) completely untouched."""
    col = get_collection("notification_templates")

    async def _newest(query: dict):
        docs = await col.find(query).to_list(50)
        if not docs:
            return None
        return max(docs, key=lambda d: d.get("updated_at") or d.get("created_at") or datetime.min)

    doc = None
    if company_id:
        doc = await _newest({"slug": slug, "company_id": str(company_id), "scope": "company"})
    if doc is None:
        doc = await _newest({"slug": slug, "scope": "staff"})

    if not doc or not doc.get("is_active", True) or not doc.get("body"):
        return None
    return doc

def render_template(template_body: str, context: Dict[str, Any]):
    content = template_body
    for key, value in context.items():
        content = content.replace(f"{{{{{key}}}}}", str(value))
    return content

async def create_in_app_notification(user_id: str, title: str, message: str, type: str = "info", meta: dict = None):
    try:
        notification = {
            "user_id": str(user_id),
            "title": title,
            "message": message,
            "type": type, # "info", "success", "warning", "error"
            "is_read": False,
            "created_at": datetime.utcnow(),
            "meta": meta or {}
        }
        col = get_collection("in_app_notifications")
        await col.insert_one(notification)
    except Exception as e:
        logger.error(f"Failed to create in-app notification: {e}")


async def log_notification(user_id: str, contact: str, channel: str, slug: str, content: str, status: str, error: str = None, meta: dict = None):
    """`meta` is optional context merged onto the log row. TPMS uses it to record which
    activity a send belonged to, so the Logs Report can show Activity/Company alongside the
    delivery result without a second lookup. Reserved keys are never overwritten."""
    try:
        log_entry = {
            "user_id": str(user_id) if user_id else "system",
            "target_contact": contact,
            "channel": channel,
            "template_slug": slug,
            "content": content,
            "status": status,
            "error_message": error,
            "sent_at": datetime.utcnow()
        }
        for k, v in (meta or {}).items():
            if k not in log_entry and v not in (None, ""):
                log_entry[k] = v
        col = get_collection("notifications")
        await col.insert_one(log_entry)
    except Exception as e:
        logger.error(f"Failed to log notification: {e}")

async def send_email_notification(to_email: str, subject: str, message: str, user_id: str = None, slug: str = "manual", cc: list = None, meta: dict = None):
    """`cc` and `meta` are optional and default to None, so existing callers are unaffected.
    `cc` exists for the TPMS escalation ladder, which addresses owners/HODs directly and
    copies SMOps; `meta` records which activity a send belonged to, for the Logs Report.

    The message is built exactly as before — same From/To/Cc/Subject headers and HTML body.
    What changed is underneath: delivery goes through app.services.smtp_delivery, which
    reuses one SMTP session across consecutive sends, paces them, retries a dropped socket
    with backoff, and stops calling out entirely once too many sends fail in a row. Opening
    a fresh authenticated connection per email is what got the Gmail account throttled.

    The contract here is unchanged: returns True/False, never raises, and writes exactly one
    `notifications` row per call with the same fields and statuses as before.
    """
    if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured")
        return False

    try:
        cc_list = [c for c in (cc or []) if c and c != to_email]
        msg = MIMEMultipart()
        msg['From'] = settings.SMTP_USERNAME
        msg['To'] = to_email
        if cc_list:
            msg['Cc'] = ", ".join(cc_list)
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'html'))

        from app.services import smtp_delivery
        sent, error = await smtp_delivery.send_message(msg, [to_email] + cc_list)
        if sent:
            await log_notification(user_id, to_email, "email", slug, message, "sent", meta=meta)
            return True

        logger.error(f"Failed to send email: {error}")
        await log_notification(user_id, to_email, "email", slug, message, "failed", error, meta=meta)
        return False
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        await log_notification(user_id, to_email, "email", slug, message, "failed", str(e), meta=meta)
        return False

# ─── Meta WhatsApp Cloud API helpers ───
def _normalize_wa_phone(phone: str) -> str:
    """Return an E.164-style number (digits only) Meta will accept.
    Strips spaces/+/-, drops leading zeros, and prefixes the default country
    code for bare local (10-digit) numbers."""
    if not phone:
        return ""
    digits = "".join(ch for ch in str(phone) if ch.isdigit()).lstrip("0")
    if len(digits) == 10:
        digits = f"{settings.WHATSAPP_DEFAULT_COUNTRY_CODE}{digits}"
    return digits

def _wa_configured() -> bool:
    return bool(settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID)

def _wa_endpoint() -> str:
    return f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"

def _wa_headers() -> dict:
    return {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}", "Content-Type": "application/json"}

async def send_whatsapp_notification(phone: str, message: str, user_id: str = None, slug: str = "manual",
                                     unconfirmed_reason: str = None):
    """Free-form WhatsApp text via Meta Cloud API.
    NOTE: Meta only delivers free-form text inside the 24h customer-service
    window. For business-initiated notifications use send_whatsapp_template().

    `unconfirmed_reason` — set when the send is business-initiated and so very unlikely to
    arrive. HTTP 200 from Meta means ACCEPTED, never delivered; such a message is accepted and
    then silently dropped. With a reason given the row is logged "accepted" (with the reason),
    not "sent", so accepted / sent / failed stay genuinely distinct in the ledger.
    """
    if not _wa_configured():
        logger.warning("WhatsApp Cloud API credentials not configured")
        return False

    to = _normalize_wa_phone(phone)
    if not to:
        logger.warning(f"WhatsApp skip: invalid phone '{phone}'")
        return False

    try:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        }
        response = requests.post(_wa_endpoint(), json=payload, headers=_wa_headers(), timeout=20)
        if response.status_code == 200:
            # 200 == Meta ACCEPTED the request. It is not proof of delivery.
            if unconfirmed_reason:
                logger.warning("WhatsApp free-form '%s' accepted but likely undelivered: %s",
                               slug, unconfirmed_reason)
                await log_notification(user_id, to, "whatsapp", slug, message,
                                       "accepted", unconfirmed_reason)
            else:
                await log_notification(user_id, to, "whatsapp", slug, message, "sent")
            return True
        error = f"WhatsApp API error: {response.status_code} - {response.text}"
        logger.error(error)
        await log_notification(user_id, to, "whatsapp", slug, message, "failed", error)
        return False
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
        await log_notification(user_id, to, "whatsapp", slug, message, "failed", str(e))
        return False

async def send_whatsapp_template(phone: str, template_name: str, language: str, params: list,
                                 user_id: str = None, slug: str = "manual",
                                 components: list = None, meta: dict = None):
    """Business-initiated WhatsApp via a Meta-approved template.
    `params` are positional body values mapped to {{1}}, {{2}}, ... in the
    approved template.

    `components` overrides that body-only structure for templates whose header or buttons also
    take variables — pass the full Cloud API components array and `params` is used only for the
    delivery log. Omit it and behaviour is exactly as before.

    `meta` is the same optional log context send_email_notification takes — TPMS passes the
    activity and company so the Logs Report can show them next to a WhatsApp row instead of
    the blank dashes it showed while only the mail path recorded them."""
    if not _wa_configured():
        logger.warning("WhatsApp Cloud API credentials not configured")
        return False

    to = _normalize_wa_phone(phone)
    if not to:
        logger.warning(f"WhatsApp skip: invalid phone '{phone}'")
        return False

    params = params or []
    if components is None:
        components = []
        if params:
            components = [{
                "type": "body",
                "parameters": [{"type": "text", "text": str(p)} for p in params],
            }]
    log_text = f"[template:{template_name}] " + " | ".join(str(p) for p in params)

    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language or "en"},
                "components": components,
            },
        }
        response = requests.post(_wa_endpoint(), json=payload, headers=_wa_headers(), timeout=20)
        if response.status_code == 200:
            await log_notification(user_id, to, "whatsapp", slug, log_text, "sent", meta=meta)
            return True
        error = f"WhatsApp template error: {response.status_code} - {response.text}"
        logger.error(error)
        await log_notification(user_id, to, "whatsapp", slug, log_text, "failed", error, meta=meta)
        return False
    except Exception as e:
        logger.error(f"Failed to send WhatsApp template: {e}")
        await log_notification(user_id, to, "whatsapp", slug, log_text, "failed", str(e), meta=meta)
        return False

async def send_notification_from_template(user_obj: dict, template_slug: str, context: Dict[str, Any], delivery_type: str = "both", scope_override: str = None):
    # GLOBAL kill-switch: suppress every template-based notification (email + WhatsApp) while off.
    if not NOTIFICATIONS_ENABLED:
        logger.info(f"[NOTIFY-OFF] Suppressed '{template_slug}' notification — global switch is off")
        return {}
    company_id = user_obj.get("company_id")

    # If scope is explicitly staff, ignore the company ID to fetch staff templates
    effective_company_id = None if scope_override == "staff" else company_id

    email_t = await fetch_template(f"{template_slug}_email", effective_company_id)
    whatsapp_t = await fetch_template(f"{template_slug}_whatsapp", effective_company_id)
    
    user_id = user_obj.get("_id") or user_obj.get("id")
    email = user_obj.get("email")
    phone = user_obj.get("mobile")
    results = {}

    if delivery_type in ["email", "both"] and email and email_t:
        rendered_body = render_template(email_t["body"], context)
        rendered_subject = render_template(email_t.get("subject", "Notification"), context)
        results["email"] = await send_email_notification(email, rendered_subject, rendered_body, user_id, email_t.get("slug", f"{template_slug}_email"))

    if delivery_type in ["whatsapp", "both"] and phone and whatsapp_t:
        wa_slug = whatsapp_t.get("slug", f"{template_slug}_whatsapp")
        meta_name = whatsapp_t.get("meta_template_name")
        if meta_name:
            # Business-initiated → must use a Meta-approved template with positional params.
            # meta_params fills the body's {{1}}, {{2}}, … in order; meta_header_params and
            # meta_button_params do the same for a text header and any variable URL button.
            # A template with neither produces components=None, which leaves send_whatsapp_template
            # on its original body-only payload — so a row saved before header/button mapping
            # existed sends exactly what it always did.
            params = resolve_params(whatsapp_t.get("meta_params"), context)
            components = build_send_components(
                params,
                header_keys=whatsapp_t.get("meta_header_params"),
                button_keys=whatsapp_t.get("meta_button_params"),
                mapping=context,
            )
            results["whatsapp"] = await send_whatsapp_template(
                phone, meta_name, whatsapp_t.get("meta_lang", "en"), params, user_id, wa_slug,
                components=components)
        else:
            # Fallback: free-form text. A system notification is business-initiated, and Meta
            # only delivers free-form inside the 24h customer-service window — so it is accepted
            # with a 200 and then dropped. Still attempted (it arrives when the window is open),
            # but logged as "accepted" rather than claiming a delivery that did not happen.
            rendered_body = render_template(whatsapp_t["body"], context)
            results["whatsapp"] = await send_whatsapp_notification(
                phone, rendered_body, user_id, wa_slug,
                unconfirmed_reason=(
                    f"No approved Meta template is bound to '{wa_slug}', so this went as "
                    "free-form text. WhatsApp only delivers free-form inside the 24-hour "
                    "customer-service window, so it most likely did NOT arrive. Bind an "
                    "approved Meta template in Notification Templates to deliver reliably."),
            )
        print(f"[DEBUG-NOTIFY] WhatsApp send result: {results.get('whatsapp')}")
    elif delivery_type in ["whatsapp", "both"]:
        print(f"[DEBUG-NOTIFY] WhatsApp skip: phone={phone}, template={bool(whatsapp_t)}")

    return results

def to_ist(dt: datetime) -> datetime:
    """Convert a datetime object to IST (UTC+5:30)"""
    if not dt: return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=5, minutes=30)))

def format_datetime_standard(dt_str: str) -> str:
    if not dt_str: return "TBD"
    try:
        if isinstance(dt_str, datetime):
            dt = dt_str
        else:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        
        # Convert to IST for display
        dt = to_ist(dt)
        return dt.strftime("%d %b %Y, %I:%M %p")
    except Exception as e:
        logger.error(f"Date parsing error for {dt_str}: {e}")
        return dt_str

async def send_notification(user_obj: dict, subject: str, message: str, delivery_type: str = "both"):
    email = user_obj.get("email")
    phone = user_obj.get("mobile")
    results = {}
    if delivery_type in ["email", "both"] and email:
        results["email"] = await send_email_notification(email, subject, message)
    if delivery_type in ["whatsapp", "both"] and phone:
        results["whatsapp"] = await send_whatsapp_notification(phone, message)
    return results

async def send_task_created_email(user_obj: dict, task_data: dict, creator_name: str, delivery_type: str = "email"):
    dt_str = task_data.get("start", "")
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        dt = to_ist(dt) # Convert to IST
        parsed_date = dt.strftime("%d %b %Y")
        parsed_day = dt.strftime("%A")
        parsed_time = dt.strftime("%I:%M %p")
    except:
        parsed_date = parsed_day = parsed_time = dt_str

    if task_data.get("all_day"):
        parsed_time = "Full Day Block"

    context = {
        "task_name": task_data.get("title"),
        "topic": task_data.get("title"), 
        "task_category": task_data.get("category"),
        "critical_level": task_data.get("priority"),
        "assigned_user": user_obj.get("full_name") or user_obj.get("first_name"),
        "assigned_by": creator_name,
        "deadline": format_datetime_standard(dt_str),
        "date": parsed_date,
        "day": parsed_day,
        "time": parsed_time,
        "description": task_data.get("description") or task_data.get("additional_details", "No description provided."),
        "task_status": task_data.get("status", "schedule"),
        "session_type": "Task",
        "name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "event_title": task_data.get("title")
    }
    await create_in_app_notification(
        user_id=user_obj.get("_id") or user_obj.get("id"),
        title="New Task Assigned",
        message=f"A new task '{task_data.get('title')}' has been assigned to you by {creator_name}.",
        type="info",
        meta={"task_id": str(task_data.get("_id", ""))}
    )
    return await send_notification_from_template(user_obj, "task_created", context, delivery_type, task_data.get("notification_scope"))

async def send_task_updated_email(user_obj: dict, task_data: dict, updated_by: str, delivery_type: str = "email"):
    dt_str = task_data.get("start", "")
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        dt = to_ist(dt) # Convert to IST
        parsed_date = dt.strftime("%d %b %Y")
        parsed_day = dt.strftime("%A")
        parsed_time = dt.strftime("%I:%M %p")
    except:
        parsed_date = parsed_day = parsed_time = dt_str

    if task_data.get("all_day"):
        parsed_time = "Full Day Block"

    context = {
        "task_name": task_data.get("title"),
        "topic": task_data.get("title"), 
        "task_category": task_data.get("category"),
        "critical_level": task_data.get("priority"),
        "assigned_user": user_obj.get("full_name") or user_obj.get("first_name"),
        "assigned_by": updated_by,
        "deadline": format_datetime_standard(dt_str),
        "date": parsed_date,
        "day": parsed_day,
        "time": parsed_time,
        "description": task_data.get("description") or task_data.get("additional_details", "No description provided."),
        "task_status": task_data.get("status", "schedule"),
        "session_type": "Task Update",
        "name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "event_title": task_data.get("title")
    }
    return await send_notification_from_template(user_obj, "task_updated", context, delivery_type, task_data.get("notification_scope"))

async def send_task_deleted_email(user_obj: dict, task_name: str, deleted_by: str, delivery_type: str = "email", scope: str = None):
    context = {"task_name": task_name, "deleted_by": deleted_by, "name": user_obj.get("full_name") or user_obj.get("first_name", "User")}
    return await send_notification_from_template(user_obj, "task_deleted", context, delivery_type, scope)

async def send_user_updated_email(user_obj: dict, updated_by: str):
    context = {
        "name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "email": user_obj.get("email"),
        "updated_by": updated_by,
        "login_url": "https://sparsh.app/login"
    }
    return await send_notification_from_template(user_obj, "user_edit", context, "email")

async def send_access_control_email(user_obj: dict, new_role: str, updated_by: str):
    context = {
        "name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "new_role": new_role,
        "updated_by": updated_by,
        "login_url": "https://sparsh.app/login"
    }
    await create_in_app_notification(
        user_id=user_obj.get("_id") or user_obj.get("id"),
        title="Access Level Changed",
        message=f"Your account role has been updated to '{new_role}' by {updated_by}.",
        type="warning"
    )
    return await send_notification_from_template(user_obj, "user_access_control_change", context, "email")

async def send_company_registration_email(admin_obj: dict, company_name: str, raw_password: str):
    context = {
        "name": admin_obj.get("first_name", "Admin"),
        "company_name": company_name,
        "email": admin_obj.get("email"),
        "password": raw_password,
        "login_url": "https://sparsh.app/login"
    }
    return await send_notification_from_template(admin_obj, "company_registration", context, "email")

async def send_todo_created_email(user_obj: dict, todo: dict, occurrences: int = 1,
                                 delivery_type: str = "email"):
    """Confirm a newly created calendar To-do to the person who owns it.

    A todo has no attendees and is never delegated, so the owner is the only recipient there
    can be — which is why this does not go through notify_users_instant (that resolves a
    session's attendee list and renders the session templates; a todo passing through it mailed
    its author "session created"). Reusing send_notification_from_template keeps the todo mail
    on the same template/override/kill-switch machinery as every other notification.

    A repeating todo writes its whole series at once; `occurrences` lets the single mail say so
    instead of one mail landing per generated date.

    SENDS ONLY FROM A TEMPLATE THE ADMIN HAS ACTIVATED. No template in
    Settings ▸ Notifications, one switched Inactive, or one saved with an empty body → no mail
    at all, never a built-in body. This mirrors what Task & Delegation and the upcoming_*
    reminders already do (see active_user_template), so every trigger an admin can see in
    Settings behaves the same way: the switch there is the whole story.
    """
    # Checked before any of the work below: nothing to render if nothing will be sent.
    # scope is always staff for a todo (scope_override below), so the company is not consulted.
    if not await active_user_template("todo_created_email", None):
        logger.info("Todo created mail skipped — no active 'todo_created' template configured")
        return {}
    try:
        due = todo.get("start") or ""
        due_date, due_time = "-", "-"
        if due:
            dt = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
            dt = to_ist(dt)
            due_date = dt.strftime("%d %b %Y")
            # A todo with no chosen time is stored due at 23:59:59 IST — that is an end-of-day
            # marker, not a time the user picked, so it is not shown back to them as one.
            due_time = "End of day" if dt.strftime("%H:%M") == "23:59" else dt.strftime("%I:%M %p")

        context = {
            "user_name": user_obj.get("full_name") or user_obj.get("first_name") or "there",
            "name": user_obj.get("full_name") or user_obj.get("first_name") or "there",
            "todo_title": todo.get("title") or "Untitled to-do",
            "title": todo.get("title") or "Untitled to-do",
            "todo_due_date": due_date,
            "todo_due_time": due_time,
            "priority": todo.get("priority") or "Normal",
            "description": todo.get("description") or todo.get("additional_details") or "-",
            "occurrence_note": (f"This is a repeating to-do — {occurrences} dates were added."
                                if occurrences > 1 else ""),
        }
        return await send_notification_from_template(
            user_obj, "todo_created", context, delivery_type=delivery_type, scope_override="staff")
    except Exception as e:
        logger.error(f"Failed to send todo created email: {e}")
        return {}


async def send_event_created_email(user_obj: dict, event_data: dict, creator_name: str, batch_name: str = "TBD", quarter: str = "TBD", delivery_type: str = "email"):
    try:
        dt_str = event_data.get("start", "")
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        dt = to_ist(dt) # Convert to IST
        context = {
            "session_type": event_data.get("session_type") or event_data.get("type", "General"),
            "meeting_link": event_data.get("meeting_link") or "No link provided.",
            "topic": event_data.get("title"),
            "date": dt.strftime("%d %b %Y"),
            "day": dt.strftime("%A"),
            "time": "Full Day Block" if event_data.get("all_day") else dt.strftime("%I:%M %p"),
            "description": event_data.get("additional_details") or "No instructions.",
            "event_title": event_data.get("title"),
            "session_strategy": event_data.get("session_type"),
            "batch_name": batch_name,
            "quarter": quarter,
            "event_datetime": dt.strftime("%d %b %Y, %I:%M %p") if not event_data.get("all_day") else f"{dt.strftime('%d %b %Y')} (Full Day)",
            "instruction": event_data.get("additional_details") or "No instructions.",
            "created_by": creator_name,
            "user_name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
            "name": user_obj.get("full_name") or user_obj.get("first_name", "User")
        }
    except Exception as e:
        logger.error(f"Error parsing date for email: {e}")
        context = {"session_type": "Session", "meeting_link": event_data.get("meeting_link", ""), "topic": event_data.get("title"), "date": "TBD", "day": "TBD", "time": "TBD", "description": ""}
    
    await create_in_app_notification(
        user_id=user_obj.get("_id") or user_obj.get("id"),
        title="New Session Scheduled",
        message=f"A new {event_data.get('session_type', 'session')} '{event_data.get('title')}' has been scheduled for {context.get('date')} ({context.get('time')}).",
        type="success",
        meta={"event_id": str(event_data.get("_id", ""))}
    )
    return await send_notification_from_template(user_obj, "event_created", context, delivery_type, event_data.get("notification_scope"))

async def send_event_updated_email(user_obj: dict, event_data: dict, updated_by: str, batch_name: str = "TBD", quarter: str = "TBD", delivery_type: str = "email"):
    try:
        dt_str = event_data.get("start", "")
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        dt = to_ist(dt) # Convert to IST
        context = {
            "session_type": event_data.get("session_type") or event_data.get("type", "General"),
            "meeting_link": event_data.get("meeting_link") or "No link provided.",
            "topic": event_data.get("title"),
            "date": dt.strftime("%d %b %Y"),
            "day": dt.strftime("%A"),
            "time": "Full Day Block" if event_data.get("all_day") else dt.strftime("%I:%M %p"),
            "description": event_data.get("additional_details") or "No instructions.",
            "event_title": event_data.get("title"),
            "session_strategy": event_data.get("session_type"),
            "batch_name": batch_name,
            "quarter": quarter,
            "event_datetime": dt.strftime("%d %b %Y, %I:%M %p") if not event_data.get("all_day") else f"{dt.strftime('%d %b %Y')} (Full Day)",
            "instruction": event_data.get("additional_details") or "No instructions.",
            "created_by": updated_by,
            "user_name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
            "name": user_obj.get("full_name") or user_obj.get("first_name", "User")
        }
    except Exception as e:
        logger.error(f"Error parsing date for email: {e}")
        context = {"session_type": "Session", "meeting_link": event_data.get("meeting_link", ""), "topic": event_data.get("title"), "date": "TBD", "day": "TBD", "time": "TBD", "description": ""}
    return await send_notification_from_template(user_obj, "event_updated", context, delivery_type, event_data.get("notification_scope"))

async def send_event_deleted_email(user_obj: dict, event_data: dict, deleted_by: str, scope: str = "staff", batch_name: str = "TBD", quarter: str = "TBD", delivery_type: str = "email"):
    try:
        # If event_data is just a string (old behavior fallback), handle it
        if isinstance(event_data, str):
            context = {"event_title": event_data, "deleted_by": deleted_by, "name": user_obj.get("full_name") or user_obj.get("first_name", "User"), "date": "N/A", "time": "N/A", "description": ""}
        else:
            dt_str = event_data.get("start", "")
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                dt = to_ist(dt)
                parsed_date = dt.strftime("%d %b %Y")
                parsed_day = dt.strftime("%A")
                parsed_time = "Full Day Block" if event_data.get("all_day") else dt.strftime("%I:%M %p")
            except:
                parsed_date = parsed_day = parsed_time = "TBD"

            context = {
                "event_title": event_data.get("title"),
                "deleted_by": deleted_by,
                "name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
                "date": parsed_date,
                "day": parsed_day,
                "time": parsed_time,
                "batch_name": batch_name,
                "quarter": quarter,
                "description": event_data.get("additional_details") or event_data.get("status_remark") or "No further details.",
                "meeting_link": event_data.get("meeting_link") or "N/A"
            }
    except Exception as e:
        logger.error(f"Error preparing delete email: {e}")
        context = {"event_title": "Scheduled Session", "deleted_by": deleted_by, "name": "User"}

    return await send_notification_from_template(user_obj, "event_deleted", context, delivery_type, scope)

def _describe_offset(reminder: dict) -> str:
    """Human phrase for a reminder's offset — e.g. '5 minutes before', '1 hour after' — used
    for the {{reminder_time}} placeholder in the reminder templates."""
    r = reminder or {}
    mins = int(r.get("offset_minutes") or 0)
    after = (r.get("timing_type") or "before").lower() == "after"
    if mins <= 0:
        return "now"
    if mins % 1440 == 0:
        qty, unit = mins // 1440, "day"
    elif mins % 60 == 0:
        qty, unit = mins // 60, "hour"
    else:
        qty, unit = mins, "minute"
    return f"{qty} {unit}{'' if qty == 1 else 's'} {'after' if after else 'before'}"


async def send_reminder_email(user_obj: dict, event: dict, reminder: dict = None):
    # A personal TODO is decided FIRST, and by the document type alone — never by the reminder's
    # label. The Reminder modal is shared across sessions, tasks and todos and stamps a
    # `parent_type` on everything it creates (defaulting to "event"), so a todo carrying a
    # reminder labelled "task" would otherwise satisfy is_task below and silently send the TASK
    # Reminder template. A todo must never fall back to a Task or Session template, so its own
    # type wins outright.
    is_todo = event.get("type") == "todo"
    # A reminder is a TASK reminder when the event is a task OR the reminder itself was
    # authored as one (parent_type == "task"). Either signal → the Task Reminder template.
    # Sessions/events (type "event", parent_type "event") keep the Session Reminder template
    # unchanged. TPMS uses a separate branch entirely, so this touches the Task module only.
    is_task = not is_todo and (
        (event.get("type") == "task") or ((reminder or {}).get("parent_type") == "task"))
    # A task or todo is "due-anchored": its reminder is about a deadline/due date, so the
    # template's {{task_deadline}} is populated; a session/event leaves it "N/A".
    is_due_anchored = event.get("type") in ("task", "todo")
    # The SAME anchor the scheduler timed this reminder against — a task's/todo's due date
    # (`end`), a session's/event's `start`. Reading `start` here regardless meant the mail
    # fired correctly on the due date but printed the task's start as its deadline.
    # Imported inside the function because reminder_scheduler imports send_reminder_email from
    # this module, so a module-level import back would be circular.
    from app.services.reminder_scheduler import get_reminder_anchor
    dt_str = get_reminder_anchor(event) or ""
    formatted_dt = format_datetime_standard(dt_str)

    # The channel the user chose in the Reminder modal. Reminders saved before this was wired
    # through have no type here, so fall back to email rather than sending nothing.
    delivery_type = (reminder or {}).get("reminder_type") or "email"

    context = {
        # The stock reminder template greets "Hello {{name}}" — without this the placeholder
        # was left in the message verbatim, since render_template only substitutes known keys.
        "name": user_obj.get("full_name") or user_obj.get("first_name") or "there",
        "title": event.get("title"),
        "reminder_time": _describe_offset(reminder),
        # Always populated: the stock template only references {{event_time}}, so restricting it
        # to non-task types printed "starting at N/A" on every task reminder. {{task_deadline}}
        # stays available for templates that word it as a deadline.
        "event_time": formatted_dt,
        "task_deadline": formatted_dt if is_due_anchored else "N/A",
        "meeting_url": event.get("meeting_link") or "View in Dashboard",
        "description": event.get("additional_details") or "No further details."
    }
    # Template per type: a TASK → Upcoming Task Reminder, a TODO → Upcoming Todo Reminder, a
    # session/event → Session Reminder. Each uses its own template only; no cross-over.
    #
    # The "upcoming_" prefix is deliberate and load-bearing: these slugs are reachable ONLY
    # from the scheduler when a reminder's time arrives. The names make that impossible to
    # confuse with the task_created / task_assigned / task_updated templates, which fire on
    # save and are a completely separate flow (see services/task_notifications.py).
    if is_todo:
        slug = "upcoming_todo_reminder"
    elif is_task:
        slug = "upcoming_task_reminder"
    else:
        slug = "reminder"
    scope = event.get("notification_scope")
    # Task & Delegation and Personal Todo reminders must use ONLY a user-configured template —
    # never a built-in default. No Active DB template (with a body) → send nothing. Sessions
    # (slug "reminder") keep their existing behavior (unrelated module).
    if slug in ("upcoming_task_reminder", "upcoming_todo_reminder"):
        eff_company = None if scope == "staff" else user_obj.get("company_id")
        if not await active_user_template(f"{slug}_email", eff_company):
            return {}
    return await send_notification_from_template(user_obj, slug, context, "email", scope)

async def send_conflict_notification_email(user_obj: dict, event_data: dict, existing_event: dict, send_company_copy: bool = True):
    # Subject: Reschedule time mail due to conflict
    subject = "⚠️ Action Required: Reschedule time mail due to conflict"
    
    # 1. Standardize Timestamps for Template
    try:
        e_dt = datetime.fromisoformat(event_data["start"].replace("Z", "+00:00"))
        e_dt = to_ist(e_dt)
        event_time_str = e_dt.strftime("%d %b, %I:%M %p")
        ex_dt = datetime.fromisoformat(existing_event["start"].replace("Z", "+00:00"))
        ex_dt = to_ist(ex_dt)
        existing_time_str = ex_dt.strftime("%d %b, %I:%M %p")
    except:
        event_time_str = event_data.get("start")
        existing_time_str = existing_event.get("start")

    context = {
        "user_name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "event_title": event_data.get("title"),
        "event_time": event_time_str,
        "existing_event": existing_event.get("title"),
        "existing_time": existing_time_str
    }
    
    rendered_body = render_template(CONFLICT_HTML_TEMPLATE, context)
    user_id = user_obj.get("_id") or user_obj.get("id")
    
    # Send to User
    results = {"user": await send_email_notification(user_obj.get("email"), subject, rendered_body, user_id, "schedule_conflict")}
    
    # 2. Fetch Company Email and Send Copy.
    # The caller passes send_company_copy=False once this save has already copied the company,
    # so a multi-user conflict produces one company copy instead of one per affected user.
    company_id = user_obj.get("company_id")
    if company_id and send_company_copy:
        try:
            company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
            if company and company.get("email"):
                results["company"] = await send_email_notification(company["email"], f"[COPY] Conflict Alert: {user_obj.get('full_name')}", rendered_body, user_id, "schedule_conflict_company_copy")
        except Exception as e:
            logger.error(f"Failed to send conflict copy to company: {e}")

    return results

async def send_attendance_thanks_email(user_obj: dict, event_data: dict):
    context = {
        "user_name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "event_title": event_data.get("title"),
        "event_time": format_datetime_standard(event_data.get("start"))
    }
    return await send_notification_from_template(user_obj, "attendance_thanks", context, "email", event_data.get("notification_scope"))

async def send_attendance_absent_email(user_obj: dict, event_data: dict):
    context = {
        "user_name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "event_title": event_data.get("title"),
        "event_time": format_datetime_standard(event_data.get("start"))
    }
    return await send_notification_from_template(user_obj, "attendance_absent", context, "email", event_data.get("notification_scope"))

async def send_session_complete_email(user_obj: dict, event_data: dict, delivery_type: str = "email"):
    print(f"[DEBUG-COMPLETE] Sending mail to {user_obj.get('email')} for {event_data.get('title')}")
    context = {
        "user_name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "name": user_obj.get("full_name") or user_obj.get("first_name", "User"),
        "topic": event_data.get("title"),
        "event_title": event_data.get("title"),
        "event_time": format_datetime_standard(event_data.get("start"))
    }
    return await send_notification_from_template(user_obj, "session_complete", context, delivery_type, event_data.get("notification_scope"))

async def send_otp_email(email: str, otp: str, user_obj: dict = None):
    context = {"otp": otp}
    user_data = user_obj or {"email": email, "first_name": "User"}
    return await send_notification_from_template(user_data, "password_reset_otp", context, "email")
