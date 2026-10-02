from fastapi import APIRouter, Depends, HTTPException, Body
from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user
from app.models.system_settings import (
    SystemSettings, SystemSettingsUpdate, AppUrlUpdate,
)
from app.models.notification import NotificationTemplate
from app.services.notification_service import UPCOMING_REMINDER_HTML_TEMPLATE
from datetime import datetime
from bson import ObjectId
from typing import List, Optional
from pydantic import BaseModel

router = APIRouter(prefix="/settings", tags=["Settings"])

@router.get("/backdate-control", response_model=dict)
async def get_backdate_settings(current_user: dict = Depends(get_current_user)):
    # Standard users can read settings to check permission if needed, but validation is backend-side
    col = get_collection("system_settings")
    settings = await col.find_one({"setting_name": "backdate_control"})
    if not settings:
        default = SystemSettings().model_dump()
        result = await col.insert_one(default)
        default["_id"] = str(result.inserted_id)
        return default
    
    settings["_id"] = str(settings["_id"])
    return settings

@router.put("/backdate-control")
async def update_backdate_settings(updates: SystemSettingsUpdate = Body(...), current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("settings", {}).get("update", False) # Fallback to settings node if it exists, or superadmin
    
    if current_user.get("role") != "superadmin" and not can_update:
        raise HTTPException(status_code=403, detail="Only authorized personnel can update backdate settings")
    
    col = get_collection("system_settings")
    print(f"DEBUG: RECEIVED UPDATES: {updates.model_dump()}")
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}

    update_data["updated_by"] = str(current_user["_id"])
    update_data["updated_at"] = datetime.utcnow()
    
    await col.update_one(
        {"setting_name": "backdate_control"},
        {"$set": update_data},
        upsert=True
    )
    return {"message": "Backdate settings updated successfully"}

# ─────────────────────────────────────────────────────────────
# Application URL — the base every mailed link is built on.
# ─────────────────────────────────────────────────────────────
@router.get("/app-url", response_model=dict)
async def get_app_url(current_user: dict = Depends(get_current_user)):
    """The configured base URL plus the one actually in effect.

    `effective_url` and `source` are returned so the screen can show what links are being built
    with RIGHT NOW — which is the question being asked when someone reports a localhost link,
    and it is not answerable from the stored value alone (it falls back to the environment).
    """
    from app.services.tpms_form_link_service import (
        configured_base_url, base_url_source, LOCAL_FRONTEND_URL,
    )
    doc = await get_collection("system_settings").find_one({"setting_name": "app_url"})
    return {
        "frontend_url": (doc or {}).get("frontend_url") or "",
        "effective_url": await configured_base_url(),
        "source": await base_url_source(),
        "default_url": LOCAL_FRONTEND_URL,
        "updated_at": (doc or {}).get("updated_at"),
    }


@router.put("/app-url")
async def update_app_url(payload: AppUrlUpdate = Body(...),
                         current_user: dict = Depends(get_current_user)):
    """Set the base URL used to build mailed links. Superadmin / settings-update only."""
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("settings", {}).get("update", False)
    if current_user.get("role") != "superadmin" and not can_update:
        raise HTTPException(status_code=403, detail="Only authorized personnel can update the application URL")

    url = (payload.frontend_url or "").strip().rstrip("/")
    if url and not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400,
                            detail="Enter the full address including http:// or https://")
    if url and " " in url:
        raise HTTPException(status_code=400, detail="The application URL cannot contain spaces")

    await get_collection("system_settings").update_one(
        {"setting_name": "app_url"},
        {"$set": {"frontend_url": url, "updated_by": str(current_user["_id"]),
                  "updated_at": datetime.utcnow()}},
        upsert=True,
    )
    from app.services.tpms_form_link_service import configured_base_url, base_url_source
    return {"message": "Application URL updated",
            "effective_url": await configured_base_url(),
            "source": await base_url_source()}


# Notification templates are managed by Super Admin and Admin only — the same rule the
# Notification Templates module (routes/notify_templates.py) applies to these rows.
TEMPLATE_ADMIN_ROLES = {"superadmin", "admin"}
TEMPLATE_ADMIN_ONLY = "Only Admin and Super Admin can manage notification templates"


@router.get("/templates", response_model=List[dict])
async def get_templates(scope: Optional[str] = None, company_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_read = permissions.get("templates", {}).get("read", False)
    
    if current_user.get("role") not in TEMPLATE_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail=TEMPLATE_ADMIN_ONLY)

    col = get_collection("notification_templates")
    query = {}
    if scope: query["scope"] = scope
    if company_id: query["company_id"] = company_id
    
    # Client Admins should only see their company templates
    if current_user.get("role") == "clientadmin":
        query["scope"] = "company"
        query["company_id"] = current_user.get("company_id")
        
    cursor = col.find(query)
    templates = await cursor.to_list(length=200)
    for t in templates: t["_id"] = str(t["_id"])
    return templates

@router.post("/templates")
async def create_template(template: dict = Body(...), current_user: dict = Depends(get_current_user)):
    # Permission check: superadmin can create for anyone, clientadmin only for their company, staff with perm
    permissions = current_user.get("permissions", {})
    can_create = permissions.get("templates", {}).get("create", False)
    
    role = current_user.get("role")
    if role not in TEMPLATE_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail=TEMPLATE_ADMIN_ONLY)
    
    col = get_collection("notification_templates")
    new_template = {
        **template,
        "created_by": str(current_user["_id"]),
        "created_at": datetime.utcnow(),
        "is_active": True
    }

    if role == "clientadmin":
        new_template["scope"] = "company"
        new_template["company_id"] = current_user.get("company_id")

    # One template per (slug, scope, company). This used to insert blindly, so creating an
    # override twice for the same trigger left duplicate docs and fetch_template could then
    # resolve the wrong one — a deactivated copy shadowing an active one silently stopped the
    # notification from sending. Overwrite the existing doc instead of stacking another.
    # `is_active` is deliberately preserved: status may only change via PATCH /templates/{id}/status.
    existing = await col.find_one({
        "slug": new_template.get("slug"),
        "scope": new_template.get("scope"),
        "company_id": new_template.get("company_id"),
    })
    if existing:
        new_template.pop("is_active", None)
        new_template["created_at"] = existing.get("created_at", new_template["created_at"])
        new_template["updated_at"] = datetime.utcnow()
        await col.update_one({"_id": existing["_id"]}, {"$set": new_template})
        return {"id": str(existing["_id"]), "message": "Template updated"}

    result = await col.insert_one(new_template)
    return {"id": str(result.inserted_id), "message": "Template created"}

@router.put("/templates/{template_id}")
async def update_template(template_id: str, template: dict = Body(...), current_user: dict = Depends(get_current_user)):
    col = get_collection("notification_templates")
    existing = await col.find_one({"_id": ObjectId(template_id)})
    if not existing: raise HTTPException(status_code=404, detail="Not found")

    # Authorization
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("templates", {}).get("update", False)
    
    role = current_user.get("role")
    if role == "clientadmin" and existing.get("company_id") != current_user.get("company_id"):
        raise HTTPException(status_code=403, detail="Unauthorized")
    if role not in TEMPLATE_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail=TEMPLATE_ADMIN_ONLY)

    # `is_active` is intentionally excluded here: template status may ONLY be changed via
    # the strictly-gated PATCH /templates/{id}/status endpoint (Admin & Super Admin only).
    # This prevents a staff user with `templates.update` from flipping status through Sync.
    IMMUTABLE_VIA_UPDATE = {"_id", "created_at", "created_by", "is_active"}
    update_data = {k: v for k, v in template.items() if k not in IMMUTABLE_VIA_UPDATE}
    update_data["updated_at"] = datetime.utcnow()

    await col.update_one({"_id": ObjectId(template_id)}, {"$set": update_data})
    return {"message": "Template updated"}

# ─── Active / Inactive status (Admin & Super Admin only) ───
# Only Super Admin and Admin roles may flip a template's status. This is a
# deliberately STRICTER gate than update_template: a staff member who merely
# holds the granular `templates.update` permission must NOT be able to toggle
# status.
TEMPLATE_STATUS_ADMIN_ROLES = TEMPLATE_ADMIN_ROLES


class TemplateStatusUpdate(BaseModel):
    is_active: bool


@router.patch("/templates/{template_id}/status")
async def update_template_status(
    template_id: str,
    payload: TemplateStatusUpdate = Body(...),
    current_user: dict = Depends(get_current_user),
):
    try:
        oid = ObjectId(template_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid template id")

    role = current_user.get("role")
    if role not in TEMPLATE_STATUS_ADMIN_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only Admin and Super Admin can change template status",
        )

    col = get_collection("notification_templates")
    existing = await col.find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")

    # Client Admins are scoped to their own company's templates.
    if role == "clientadmin" and existing.get("company_id") != current_user.get("company_id"):
        raise HTTPException(status_code=403, detail="Unauthorized")

    await col.update_one(
        {"_id": oid},
        {"$set": {"is_active": payload.is_active, "updated_at": datetime.utcnow()}},
    )

    return {
        "success": True,
        "message": "Template status updated successfully",
        "is_active": payload.is_active,
    }


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, current_user: dict = Depends(get_current_user)):
    col = get_collection("notification_templates")
    existing = await col.find_one({"_id": ObjectId(template_id)})
    
    permissions = current_user.get("permissions", {})
    can_delete = permissions.get("templates", {}).get("delete", False)
    
    role = current_user.get("role")
    if role == "clientadmin" and existing.get("company_id") != current_user.get("company_id"):
        raise HTTPException(status_code=403, detail="Unauthorized")
    if role not in TEMPLATE_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail=TEMPLATE_ADMIN_ONLY)

    await col.delete_one({"_id": ObjectId(template_id)})
    return {"message": "Template deleted"}

# ─── Seed content: one Email + one WhatsApp template per trigger ───
# Each entry is (slug_base, friendly name, email subject, email body, whatsapp body). The
# seeder below expands every entry into a "<slug>_email" and a "<slug>_whatsapp" doc, so
# every action in every module has a template on both channels.
#
# WhatsApp bodies are kept to a single short paragraph: Meta only delivers free-form text
# inside the 24h service window, so for business-initiated sends an admin still has to point
# the template at a Meta-approved one (meta_template_name) in the editor. The body here is
# what goes out in the free-form case and is the copy to mirror into the Meta template.
TEMPLATE_SEEDS = [
    # ─── Calendar: Sessions ───
    ("event_created", "Session Scheduled",
     "New Session Scheduled: {{event_title}}",
     "Hello {{name}},\n\nA new training session '{{event_title}}' has been scheduled.\nDate: {{date}}\nTime: {{time}}\nLink: {{meeting_link}}",
     "Hello {{name}}, the session '{{event_title}}' is scheduled for {{date}} at {{time}}. Join here: {{meeting_link}}"),
    ("event_updated", "Session Rescheduled",
     "Session Rescheduled: {{event_title}}",
     "Hello {{name}},\n\nThe session '{{event_title}}' has been moved to a new time.\nNew Date: {{date}}\nNew Time: {{time}}",
     "Hello {{name}}, the session '{{event_title}}' has been rescheduled to {{date}} at {{time}}."),
    ("event_deleted", "Session Cancelled",
     "Session Cancelled: {{event_title}}",
     "Hello {{name}},\n\nThe session '{{event_title}}' scheduled for {{date}} has been cancelled.",
     "Hello {{name}}, the session '{{event_title}}' on {{date}} has been cancelled."),
    ("session_complete", "Session Completed",
     "Session Completed: {{topic}}",
     "Hello {{user_name}},\n\nThe session '{{topic}}' has been completed. Thank you for attending.",
     "Hello {{user_name}}, the session '{{topic}}' is complete. Thank you for attending."),
    ("reminder", "Session Reminder",
     "Upcoming: {{title}} in {{reminder_time}}",
     "Hello {{name}},\n\nThis is a friendly reminder for '{{title}}' starting at {{event_time}}.\nLink: {{meeting_url}}",
     "Reminder: '{{title}}' starts at {{event_time}}. Link: {{meeting_url}}"),
    # ─── Upcoming reminders (scheduler-only) ───
    # Fired ONLY by the reminder scheduler when a task's/todo's reminder time arrives — never
    # on create or update, which use task_created / task_assigned / task_updated instead.
    # Kept SEPARATE from the Session Reminder so a task never renders the session-styled mail.
    # These seeds are the ONLY source of content for the two upcoming slugs — there is no
    # DEFAULT_TEMPLATES fallback for them (see notification_service), so if an admin deletes or
    # deactivates one, the reminder sends nothing rather than a body nobody configured.
    ("upcoming_task_reminder", "Upcoming Task Reminder",
     "⏰ Upcoming Task Reminder: {{title}}",
     UPCOMING_REMINDER_HTML_TEMPLATE,
     "Reminder: your task '{{title}}' is due {{task_deadline}}."),
    ("upcoming_todo_reminder", "Upcoming Todo Reminder",
     "⏰ Upcoming Todo Reminder: {{title}}",
     UPCOMING_REMINDER_HTML_TEMPLATE,
     "Reminder: your todo '{{title}}' is due {{task_deadline}}."),

    # ─── Calendar To-do ───
    # Fired once when a To-do is created (the series counts as one). Separate from the Session
    # triggers above: a todo is private and self-owned, so it must never render a session mail.
    ("todo_created", "Todo Created",
     "To-do added: {{todo_title}}",
     "Hello {{user_name}},\n\nYour to-do '{{todo_title}}' has been added to your calendar.\n\nDue Date: {{todo_due_date}}\nDue Time: {{todo_due_time}}\nPriority: {{priority}}\n{{occurrence_note}}\nNotes: {{description}}\n\nRegards,\nSparsh Notifications",
     "Your to-do '{{todo_title}}' was added. Due {{todo_due_date}} {{todo_due_time}}."),

    # ─── Task Management (Delegation) ───
    ("task_created", "Task Created",
     "New Task Assigned: {{task_name}}",
     "Hello {{assigned_user}},\n\nA new task '{{task_name}}' has been assigned to you by {{assigned_by}}.\n\nDeadline: {{deadline}}\nPriority: {{critical_level}}\nDescription: {{description}}\n\nRegards,\nSparsh Notifications",
     "Hello {{assigned_user}}, {{assigned_by}} has assigned you the task '{{task_name}}'. Deadline: {{deadline}} (Priority: {{critical_level}})."),
    ("task_assigned", "Task Assigned",
     "Task Assigned: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has assigned you the task '{{task_name}}'.\n\nDeadline: {{deadline}}\nPriority: {{critical_level}}\nDescription: {{description}}\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} has assigned you the task '{{task_name}}'. Deadline: {{deadline}}."),
    # The ASSIGNER's receipt, sent alongside (never instead of) the Task Assigned mail the
    # assignee gets. Its own recipient and its own placeholder set — {{assigner_name}},
    # {{assignee_name}}, {{task_name}}, {{priority}}, {{due_date}}, {{assigned_date}},
    # {{company_name}} — see task_notifications.notify_assigner_confirmation.
    ("task_assignment_confirmation", "Task Assignment Confirmation (Assigner)",
     "Assignment Confirmed: {{task_name}}",
     "Hello {{assigner_name}},\n\nYour task '{{task_name}}' has been assigned successfully.\n\nAssigned To: {{assignee_name}}\nPriority: {{priority}}\nDue Date: {{due_date}}\nAssigned On: {{assigned_date}}\nCompany: {{company_name}}\n\nThis is your confirmation as the assigner. {{assignee_name}} has been notified separately.\n\nRegards,\nSparsh Notifications",
     "Hello {{assigner_name}}, '{{task_name}}' has been assigned to {{assignee_name}}. Due {{due_date}} (Priority: {{priority}})."),
    ("task_updated", "Task Updated",
     "Task Updated: {{task_name}}",
     "Hello {{name}},\n\nThe task '{{task_name}}' was updated by {{actor_name}}.\n\nDeadline: {{deadline}}\nPriority: {{critical_level}}\nStatus: {{task_status}}\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} updated the task '{{task_name}}'. Current status: {{task_status}}."),
    ("task_deleted", "Task Deleted",
     "Task Deleted: {{task_name}}",
     "Hello {{name}},\n\nThe task '{{task_name}}' has been deleted by {{actor_name}}.\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, the task '{{task_name}}' has been deleted by {{actor_name}}."),
    ("task_accepted", "Task Accepted",
     "Task Accepted: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has accepted the task '{{task_name}}'.\n\nDeadline: {{deadline}}\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} has accepted the task '{{task_name}}'. Deadline: {{deadline}}."),
    ("task_completed", "Task Completed",
     "Task Completed: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has marked the task '{{task_name}}' as completed.\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} has completed the task '{{task_name}}'."),
    ("task_reopened", "Task Reopened",
     "Task Reopened: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has reopened the task '{{task_name}}'. It needs further work.\n\nReason: {{reason}}\nDeadline: {{deadline}}\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} has reopened the task '{{task_name}}'. Reason: {{reason}}"),
    ("task_verification_requested", "Verification Requested",
     "Verification Requested: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has submitted the task '{{task_name}}' for your verification.\n\nPlease review it and either approve the completion or reopen the task.\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} has submitted '{{task_name}}' for your verification. Please review and approve or reopen it."),
    ("task_verification_approved", "Verification Approved",
     "Verification Approved: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has verified and approved your completion of the task '{{task_name}}'.\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} has verified and approved your completion of '{{task_name}}'."),
    ("task_deadline_revised", "Deadline Revised",
     "Deadline Revised: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has revised the deadline for the task '{{task_name}}'.\n\nPrevious deadline: {{old_deadline}}\nNew deadline: {{new_deadline}}\nReason: {{reason}}\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, the deadline for '{{task_name}}' moved from {{old_deadline}} to {{new_deadline}}. Reason: {{reason}}"),
    ("task_deadline_revision_requested", "Deadline Revision Requested",
     "Deadline Revision Requested: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has requested a revision of the deadline for the task '{{task_name}}'.\n\nCurrent deadline: {{old_deadline}}\nRequested deadline: {{new_deadline}}\nReason: {{reason}}\n\nThe deadline has NOT changed yet - please approve or reject the request.\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} has requested the deadline for '{{task_name}}' be moved from {{old_deadline}} to {{new_deadline}}. Reason: {{reason}}. Please approve or reject it."),
    ("task_deadline_revision_approved", "Deadline Revision Approved",
     "Deadline Revision Approved: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has approved the deadline revision requested by {{requested_by_name}} for the task '{{task_name}}'.\n\nPrevious deadline: {{old_deadline}}\nNew deadline: {{new_deadline}}\nRemark: {{remark}}\n\nThe new deadline is now in force.\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} approved the deadline revision for '{{task_name}}'. The new deadline is {{new_deadline}}."),
    ("task_deadline_revision_rejected", "Deadline Revision Rejected",
     "Deadline Revision Rejected: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has rejected the deadline revision requested by {{requested_by_name}} for the task '{{task_name}}'.\n\nRequested deadline: {{new_deadline}}\nRemark: {{remark}}\n\nThe original deadline of {{old_deadline}} still stands.\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} rejected the deadline revision for '{{task_name}}'. The deadline stays {{old_deadline}}."),
    ("task_blocked", "Task Blocked",
     "Task Blocked: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has marked the task '{{task_name}}' as Blocked.\n\nReason: {{reason}}\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} has marked '{{task_name}}' as Blocked. Reason: {{reason}}"),
    ("task_dependent_on_other", "Dependent on Other",
     "Task Dependent on Other: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has marked the task '{{task_name}}' as Dependent on Other, waiting on {{doer_name}}.\n\nReason: {{reason}}\nDeadline: {{deadline}}\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, '{{task_name}}' is now Dependent on Other, waiting on {{doer_name}}. Reason: {{reason}}"),
    ("task_dependency_resolved", "Dependency Completed",
     "Dependency Completed: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has completed the dependency on the task '{{task_name}}'.\n\nThe task is back with you for review and final completion.\n\nDeadline: {{deadline}}\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} has completed the dependency on '{{task_name}}'. It is back with you to review and complete. Deadline: {{deadline}}."),
    ("task_follow_up_added", "Follow-up Added",
     "Follow-up on: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has raised a follow-up on the task '{{task_name}}'.\n\nRemark: {{remark}}\nDeadline: {{deadline}}\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} raised a follow-up on '{{task_name}}': {{remark}}"),
    ("task_subtask_created", "Subtask Created",
     "Subtask Created: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has created the subtask '{{task_name}}' under '{{parent_task}}'.\n\nDeadline: {{deadline}}\nPriority: {{critical_level}}\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} created the subtask '{{task_name}}' under '{{parent_task}}'. Deadline: {{deadline}}."),
    ("task_in_loop_added", "In Loop Person",
     "You're now in the loop on: {{task_name}}",
     "Hello {{name}},\n\n{{actor_name}} has added you to keep track of the task '{{task_name}}'.\n\nDeadline: {{deadline}}\nPriority: {{critical_level}}\n\nRegards,\nSparsh Notifications",
     "Hello {{name}}, {{actor_name}} has added you to keep track of the task '{{task_name}}'. Deadline: {{deadline}}."),

    # ─── User Management ───
    ("user_creation", "User Created",
     "Welcome to Sparsh 2.0",
     "Hello {{name}},\n\nYour account has been created.\nRole: {{new_role}}\nLogin here: {{login_url}}\nTemporary Password: {{password}}",
     "Hello {{name}}, your Sparsh account is ready. Log in at {{login_url}}."),
    ("user_edit", "Profile Updated",
     "Your Account Information Updated",
     "Hello {{name}},\n\nYour profile details were updated by {{updated_by}}.\nIf you did not authorize this, please contact support.",
     "Hello {{name}}, your Sparsh profile was updated by {{updated_by}}. Contact support if this wasn't you."),
    ("user_access_control_change", "Access Changed",
     "Your Access Level Has Changed",
     "Hello {{name}},\n\nYour role has been updated to '{{new_role}}' by {{updated_by}}.\nLogin here: {{login_url}}",
     "Hello {{name}}, your Sparsh role is now '{{new_role}}' (updated by {{updated_by}})."),
    ("company_registration", "New Company",
     "Welcome, {{company_name}}!",
     "Hello {{name}},\n\n{{company_name}} is now live on our platform.\nYou can manage your team and learners at: {{login_url}}",
     "Hello {{name}}, {{company_name}} is now live on Sparsh. Manage your team at {{login_url}}."),
    ("user_deleted", "User Access Removed",
     "Account Deactivation Notice",
     "Hello {{name}},\n\nYour access to the platform has been revoked.",
     "Hello {{name}}, your Sparsh access has been revoked."),

    # ─── Attendance ───
    ("attendance_thanks", "Attendance Thanks",
     "Participation Authenticated: {{event_title}}",
     "Hello {{user_name}},\n\nThank you for attending '{{event_title}}' at {{event_time}}.",
     "Hello {{user_name}}, thank you for attending '{{event_title}}' at {{event_time}}."),
    ("attendance_absent", "Attendance Absent",
     "Absence Noted: {{event_title}}",
     "Hello {{user_name}},\n\nWe missed you in '{{event_title}}' at {{event_time}}. Please review the resources.",
     "Hello {{user_name}}, we missed you at '{{event_title}}' ({{event_time}}). Please review the shared resources."),
]


@router.post("/initialize-templates")
async def initialize_default_templates(current_user: dict = Depends(get_current_user)):
    """Seed a staff-scope Email + WhatsApp template for every trigger in every module.

    Strictly additive and idempotent: a trigger that already has a template doc is left
    exactly as it is — existing copy, edits and Active/Inactive status are never touched or
    removed. Only genuinely missing (slug, scope, company) combinations are inserted, so this
    is safe to run repeatedly.
    """
    if current_user.get("role") != "superadmin":
         raise HTTPException(status_code=403, detail="Unauthorized")

    col = get_collection("notification_templates")

    created, skipped = [], []
    for slug_base, name, subject, email_body, whatsapp_body in TEMPLATE_SEEDS:
        for channel, body in (("email", email_body), ("whatsapp", whatsapp_body)):
            slug = f"{slug_base}_{channel}"
            # company_id: None also matches docs where the field was never set.
            exists = await col.find_one({"slug": slug, "scope": "staff", "company_id": None})
            if exists:
                skipped.append(slug)
                continue
            await col.insert_one({
                "name": f"{name} ({channel.upper()})",
                "slug": slug,
                "channel": channel,
                "subject": subject if channel == "email" else None,
                "body": body,
                "scope": "staff",
                "company_id": None,
                "is_active": True,
                "created_by": str(current_user["_id"]),
                "created_at": datetime.utcnow(),
            })
            created.append(slug)

    return {
        "message": f"Initialized {len(created)} template(s); {len(skipped)} already existed and were left untouched.",
        "created": created,
        "skipped": skipped,
    }


