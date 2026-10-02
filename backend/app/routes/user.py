from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from typing import List, Optional
from app.models.user import UserResponse, UserRole
from app.controllers.auth_controller import (
    get_current_active_user, get_current_user,
    check_role, get_password_hash
)
from app.db.mongodb import get_collection
from bson import ObjectId
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator
from app.services.notification_service import send_user_updated_email, send_access_control_email
from app.services.activity_log_service import log_activity

router = APIRouter(prefix="/users", tags=["Users"])


# ─── Reporting-Manager dropdown options ───
# Selectable managers for the User Create/Edit form, scoped to the SAME environment as the user
# being created/edited: pass `company_id` for a client company's users, omit it for internal
# staff. `exclude` drops the user being edited so they can't be their own manager. Defined
# before the /{user_id} routes so the static path wins.
@router.get("/reporting-manager-options")
async def reporting_manager_options(
    company_id: Optional[str] = None,
    exclude: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    from app.controllers.auth_controller import is_client_side_user
    perms = current_user.get("permissions", {})
    privileged = (current_user.get("role") in ("superadmin", "admin")
                  or perms.get("users", {}).get("read", False))
    if privileged:
        # User-manager: may build the list for any environment/company (the create/edit form
        # passes company_id for a client company, or omits it for internal staff).
        if company_id:
            coll, query = "learners", {"company_id": str(company_id), "is_active": {"$ne": False}}
        else:
            coll, query = "staff", {"is_active": {"$ne": False}}
    else:
        # Any authenticated user may resolve names within their OWN environment/company only
        # (used to display their own reporting manager on the profile page).
        if is_client_side_user(current_user):
            cid = current_user.get("company_id")
            if not cid:
                return []
            coll, query = "learners", {"company_id": str(cid), "is_active": {"$ne": False}}
        else:
            coll, query = "staff", {"is_active": {"$ne": False}}
    out = []
    for u in await get_collection(coll).find(query).to_list(2000):
        uid = str(u["_id"])
        if exclude and uid == str(exclude):
            continue
        out.append({
            "_id": uid,
            "full_name": (u.get("full_name")
                          or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
                          or u.get("email")),
            "email": u.get("email"),
            "role": u.get("role"),
            "designation": u.get("designation"),
        })
    out.sort(key=lambda x: (x["full_name"] or "").lower())
    return out


# ─── List Users (Combined) ───
@router.get("")
async def list_users(active_only: bool = False, company_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_read = permissions.get("users", {}).get("read", False)
    
    if current_user.get("role") != "superadmin" and not can_read:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = {}
    if active_only:
        query["is_active"] = {"$ne": False}
    if company_id:
        query["company_id"] = company_id

    staff = await get_collection("staff").find(query).to_list(1000)
    learners = await get_collection("learners").find(query).to_list(1000)
    
    all_users = staff + learners
    for u in all_users:
        u["_id"] = str(u["_id"])
        u.pop("password", None)
    return all_users

# ─── Models ───
class UserEditRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    mobile: Optional[str] = None
    role: Optional[str] = None
    session_type: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    reporting_manager: Optional[str] = None  # admin Edit form must be able to save this
    level: Optional[str] = None
    leadership_level: Optional[str] = None  # "L4" | "L5" | "L6" | "L7"; gates Leadership Score enrolment
    permissions: Optional[dict] = None

    @field_validator("leadership_level")
    @classmethod
    def _normalise_level(cls, v):
        """Accept l4/L4 alike, and refuse anything that is not a real level.

        Stored upper-cased because that is how `leadership_level_of()` compares it; a
        lower-case value would read back as "no level" and silently drop the leader out of
        every cycle.
        """
        if v is None:
            return None
        level = str(v).strip().upper()
        if not level:
            return ""
        if level not in ("L4", "L5", "L6", "L7"):
            raise ValueError("leadership_level must be L4, L5, L6, L7 or empty")
        return level

class UserStatusUpdate(BaseModel):
    is_active: bool

class SelfProfileUpdate(BaseModel):
    """Safe, self-editable profile fields for PATCH /users/me. Deliberately excludes
    role / permissions / is_active / email — those stay admin-only via PUT /users/{id}."""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    mobile: Optional[str] = None
    emergency_mobile: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    reporting_manager: Optional[str] = None
    joining_date: Optional[str] = None
    level: Optional[str] = None

# ─── Current User ───
@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: dict = Depends(get_current_active_user)):
    current_user["_id"] = str(current_user["_id"])
    # Surface the company's module access flags so the client can gate navigation:
    # ORM defaults to ON (pre-existing companies keep it), Delegation defaults to OFF
    # (opt-in per company — see auth_controller.is_company_delegation_enabled).
    company_id = current_user.get("company_id")
    if company_id:
        try:
            company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
            current_user["orm_enabled"] = bool(company.get("orm_enabled", True)) if company else True
            # TPMS is opt-in: absent flag means OFF, so an un-migrated company stays dark.
            current_user["tpms_enabled"] = bool(company.get("tpms_enabled", False)) if company else False
            # Task Management (Delegation) is opt-in too: absent flag means OFF. Gates the
            # Task Management sidebar module for client-side users (see utils/taskAccess.js).
            current_user["delegation_enabled"] = bool(company.get("delegation_enabled", False)) if company else False
            # HRMS has TWO doors, and the frontend needs to know which one is open.
            #
            #   hrms_enabled          -> the WHOLE module. Requires `is_internal` as well,
            #                            because payroll, employees, exits and Sparsh
            #                            Magic's own hiring are in-house only and no client
            #                            company may ever reach them.
            #   client_hiring_enabled -> the CLIENT HIRING track and nothing else, for a
            #                            client company whose toggle is on.
            #
            # These mirror `is_hrms_enabled` and `client_track_company` in
            # utils/hrms_access.py, which enforce the identical split server-side on every
            # HRMS call. This is the UI-gating mirror of those two, not a separate rule.
            #
            # They are deliberately mutually exclusive: a company is either the in-house
            # tenant or a client, never both, so no user ever holds both flags.
            _on = bool(company and company.get("hrms_enabled", False))
            _internal = bool(company and company.get("is_internal", False))
            current_user["hrms_enabled"] = _on and _internal
            current_user["client_hiring_enabled"] = _on and not _internal
        except Exception:
            current_user["orm_enabled"] = True
            current_user["tpms_enabled"] = False
            current_user["delegation_enabled"] = False
            current_user["hrms_enabled"] = False
            current_user["client_hiring_enabled"] = False
    return current_user

# ─── Helper to find user in any collection ───
async def find_user_by_id(user_id: str):
    for col_name in ["staff", "learners"]:
        user = await get_collection(col_name).find_one({"_id": ObjectId(user_id)})
        if user:
            return user, col_name
    return None, None

# ─── Update Own Profile (self-service) ───
# Any authenticated user can edit their own safe profile fields. Separate from
# PUT /users/{id}, which restricts staff editing to superadmin and is meant for admins
# managing *other* users. This never touches role/permissions/is_active/email.
@router.patch("/me")
async def update_my_profile(updates: SelfProfileUpdate, current_user: dict = Depends(get_current_active_user)):
    user_id = str(current_user["_id"])
    user, col_name = await find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Recompute full_name when either name part changes (mirrors update_user).
    if "first_name" in update_data or "last_name" in update_data:
        fn = update_data.get("first_name", user.get("first_name")) or ""
        ln = update_data.get("last_name", user.get("last_name")) or ""
        update_data["full_name"] = f"{fn} {ln}".strip()

    update_data["updated_at"] = datetime.utcnow()
    await get_collection(col_name).update_one({"_id": ObjectId(user_id)}, {"$set": update_data})

    refreshed = await get_collection(col_name).find_one({"_id": ObjectId(user_id)})
    refreshed["_id"] = str(refreshed["_id"])
    refreshed.pop("password", None)
    return refreshed

# ─── Get Single User ───
@router.get("/{user_id}")
async def get_user(user_id: str, current_user: dict = Depends(get_current_user)):
    user, _ = await find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # ─── Auth Check ───
    permissions = current_user.get("permissions", {})
    can_read = permissions.get("users", {}).get("read", False)
    
    is_authorized = current_user.get("role") == "superadmin" or can_read or str(current_user.get("_id")) == user_id
    
    if not is_authorized:
        if current_user.get("role") in ("clientadmin", "clientuser"):
            if user.get("company_id") != current_user.get("company_id"):
                raise HTTPException(status_code=403, detail="Not authorized to view this user")
        else:
            raise HTTPException(status_code=403, detail="Not authorized")

    user["_id"] = str(user["_id"])
    user.pop("password", None)
    return user

# ─── Update User ───
@router.put("/{user_id}")
async def update_user(user_id: str, updates: UserEditRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    user, col_name = await find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # ─── Auth Check ───
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("users", {}).get("update", False)
    
    is_authorized = current_user.get("role") == "superadmin" or can_update
    
    # ─── 1. Restrict Staff Management to Superadmin ───
    is_superadmin = current_user.get("role") == "superadmin"
    if col_name == "staff" and not is_superadmin:
        raise HTTPException(status_code=403, detail="Only superadmin can manage staff users")

    # ─── 2. Harden Self-Modification Check ───
    is_self = str(current_user["_id"]) == str(user_id)
    if is_self and not is_superadmin:
        if updates.role is not None or updates.permissions is not None:
            raise HTTPException(status_code=403, detail="Cannot modify your own role or permissions")

    if not is_authorized:
        if current_user.get("role") == "clientadmin":
            if user.get("company_id") != current_user.get("company_id"):
                 raise HTTPException(status_code=403, detail="Not authorized for this user")
        else:
             raise HTTPException(status_code=403, detail="Not authorized")

        
    update_data = updates.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    # ─── Recalculate full_name if first_name/last_name changed ───
    if "first_name" in update_data or "last_name" in update_data:
        # Use existing values if not being updated
        fn = update_data.get("first_name", user.get("first_name"))
        ln = update_data.get("last_name", user.get("last_name"))
        
        # Ensure fn and ln are strings, not None
        fn_str = fn if fn else ""
        ln_str = ln if ln else ""
        
        update_data["full_name"] = f"{fn_str} {ln_str}".strip()

    # ─── Email doubles as the login identity (auth resolves it across staff + learners),
    # so normalize it and reject a value already taken by another account ───
    if "email" in update_data:
        new_email = str(update_data["email"]).lower().strip()
        if new_email != user.get("email"):
            for col in ("staff", "learners"):
                clash = await get_collection(col).find_one(
                    {"email": new_email, "_id": {"$ne": ObjectId(user_id)}}
                )
                if clash:
                    raise HTTPException(status_code=409, detail="That email is already in use by another account")
        update_data["email"] = new_email

    # ─── Check for Role/Access Change ───
    old_role = user.get("role")
    new_role = update_data.get("role")
    updated_by = current_user.get("full_name") or current_user.get("first_name", "Admin")

    update_data["updated_at"] = datetime.utcnow()
    await get_collection(col_name).update_one({"_id": ObjectId(user_id)}, {"$set": update_data})

    # ─── Trigger Notifications ───
    if new_role and new_role != old_role:
        background_tasks.add_task(send_access_control_email, user, new_role, updated_by)
    else:
        background_tasks.add_task(send_user_updated_email, user, updated_by)

    return {"message": "User updated successfully and notification triggered", "full_name": update_data.get("full_name")}

# ─── Delete User ───
@router.delete("/{user_id}")
async def delete_user(user_id: str, current_user: dict = Depends(get_current_user)):
    user, col_name = await find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # ─── Auth Check ───
    permissions = current_user.get("permissions", {})
    can_delete = permissions.get("users", {}).get("delete", False)
    
    # ─── Restrict Staff Deletion to Superadmin ───
    if col_name == "staff" and current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Only superadmin can delete staff users")

    # ─── Roles & Permissions Check ───
    is_authorized = current_user.get("role") == "superadmin"
    
    if not is_authorized:
        if current_user.get("role") == "clientadmin":
            # ClientAdmin can only delete users from their own company
            if str(user.get("company_id")) != str(current_user.get("company_id")):
                raise HTTPException(status_code=403, detail="Not authorized to delete this user")
        elif not can_delete:
            raise HTTPException(status_code=403, detail="Not authorized to delete users")

    
    await get_collection(col_name).delete_one({"_id": ObjectId(user_id)})
    return {"message": "User deleted"}

# ─── Update User Status (Activate/Deactivate) ───
@router.patch("/{user_id}/status")
async def update_user_status(user_id: str, data: dict, current_user: dict = Depends(get_current_user)):
    user, col_name = await find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Auth check: Superadmin, Admin, or ClientAdmin (for their company)
    is_authorized = current_user.get("role") in ["superadmin", "admin"]
    if not is_authorized and current_user.get("role") == "clientadmin":
        if str(user.get("company_id")) == str(current_user.get("company_id")):
            is_authorized = True

    if not is_authorized:
        raise HTTPException(status_code=403, detail="Not authorized to change status for this user")

    new_status = data.get("is_active")
    if new_status is None:
        raise HTTPException(status_code=400, detail="is_active field is required")

    await get_collection(col_name).update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"is_active": new_status, "updated_at": datetime.utcnow()}}
    )

    action = "activated" if new_status else "deactivated"
    await log_activity(current_user, f"User {action.capitalize()}", "user", f"{action.capitalize()} user {user.get('email')}")
    
    return {"message": f"User {action} successfully"}


# ─── Get User Activity/History ───
@router.get("/{user_id}/activity")
async def get_user_activity(user_id: str, current_user: dict = Depends(get_current_user)):
    """Returns learning progress, attendance, and activity history for a member."""
    user, _ = await find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # ─── Auth Check ───
    permissions = current_user.get("permissions", {})
    can_read = permissions.get("users", {}).get("read", False)
    
    authorized = False
    if current_user.get("role") == "superadmin" or can_read:
        authorized = True
    elif str(current_user.get("_id")) == user_id:
        authorized = True
    elif current_user.get("role") in ("clientadmin", "clientuser"):
        if user.get("company_id") == current_user.get("company_id"):
            authorized = True

    if not authorized:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Learnings (Mix of content and assessments)
    learnings = []
    
    # 1. Assessments
    assessments_col = get_collection("LearnerAssessments")
    q_ass = await assessments_col.find({"user_id": user_id}).sort("submitted_at", -1).to_list(100)
    for a in q_ass:
        a["_id"] = str(a["_id"])
        learners_item = {
            "_id": a["_id"],
            "name": a.get("session_title", "Assessment"),
            "completed": a.get("percentage", 0),
            "date": a.get("submitted_at"),
            "type": "assessment",
            "status": "Completed" if a.get("passed") else "Failed"
        }
        learnings.append(learners_item)

    # 2. Manual/Module Learnings
    learnings_col = get_collection("learnings")
    manual_learns = await learnings_col.find({"user_id": user_id}).sort("date", -1).to_list(100)
    for l in manual_learns:
        l["_id"] = str(l["_id"])
        if not any(x["_id"] == l["_id"] for x in learnings):
            learnings.append({
                "_id": l["_id"],
                "name": l.get("module_name", "Module"),
                "completed": l.get("progress", 0),
                "date": l.get("date"),
                "type": "module",
                "status": l.get("status", "In Progress")
            })
    
    # Attendance
    attendance_col = get_collection("attendance")
    attendance = await attendance_col.find({"user_id": user_id}).sort("date", -1).to_list(100)
    for a in attendance:
        a["_id"] = str(a["_id"])
    
    # Activity log
    activity_col = get_collection("activity_logs")
    activities = await activity_col.find({"user_id": user_id}).sort("timestamp", -1).to_list(100)
    for act in activities:
        act["_id"] = str(act["_id"])
    
    return {
        "learnings": learnings,
        "attendance": attendance,
        "activities": activities
    }

# ─── Learner Reports ───
@router.get("/me/reports")
async def get_my_reports(current_user: dict = Depends(get_current_active_user)):
    user_id = str(current_user["_id"])
    
    # 1. Activities
    activity_col = get_collection("activity_logs")
    activities = await activity_col.find({"user_id": user_id}).sort("timestamp", -1).to_list(100)
    for act in activities:
        act["_id"] = str(act["_id"])
        
    # 2. Assessments
    assessment_col = get_collection("LearnerAssessments") # Fixed typo in logic
    # Also check the typo version if it exists
    assessments_legacy = await get_collection("LearnerAsessments").find({"user_id": user_id}).to_list(100)
    assessments_new = await assessment_col.find({"user_id": user_id}).to_list(100)
    
    all_assessments = assessments_legacy + assessments_new
    for ass in all_assessments:
        ass["_id"] = str(ass["_id"])
    
    # Sort by submitted_at
    all_assessments.sort(key=lambda x: x.get("submitted_at", ""), reverse=True)

    # 3. Calculate Stats
    total_activities = len(activities)
    quizzes_taken = len(all_assessments)
    quizzes_passed = len([a for a in all_assessments if a.get("passed")])
    
    return {
        "stats": {
            "total_activities": total_activities,
            "quizzes_taken": quizzes_taken,
            "quizzes_passed": quizzes_passed,
            "pass_rate": round((quizzes_passed / quizzes_taken * 100) if quizzes_taken > 0 else 0, 1)
        },
        "activities": activities,
        "assessments": all_assessments
    }

    return {"message": f"Welcome, Admin {current_user['full_name']}"}

@router.get("/{user_id}/analytics")
async def get_user_analytics(user_id: str, current_user: dict = Depends(get_current_user)):
    user, _ = await find_user_by_id(user_id)
    if not user: raise HTTPException(status_code=404, detail="User not found")
    
    # Auth check
    permissions = current_user.get("permissions", {})
    can_read = permissions.get("users", {}).get("read", False)
    
    authorized = current_user.get("role") == "superadmin" or can_read or str(current_user.get("_id")) == user_id
    
    if not authorized:
        if current_user.get("role") in ("clientadmin", "clientuser"):
            if user.get("company_id") != current_user.get("company_id"):
                raise HTTPException(status_code=403, detail="Not authorized")
        else:
            raise HTTPException(status_code=403, detail="Not authorized")

    # 1. Weekly Scores (Last 8 assessments)
    assessments_col = get_collection("LearnerAssessments")
    assessments_new = await assessments_col.find({"user_id": user_id}).sort("submitted_at", 1).to_list(100)
    # Plus legacy if any
    assessments_old = await get_collection("LearnerAsessments").find({"user_id": user_id}).sort("submitted_at", 1).to_list(100)
    all_ass = assessments_old + assessments_new
    all_ass.sort(key=lambda x: x.get("submitted_at", ""))
    
    weekly_scores = []
    for i, ass in enumerate(all_ass[-8:]):
        weekly_scores.append({
            "week": f"A{i+1}",
            "score": ass.get("percentage", 0),
            "target": 85
        })

    # 2. Attendance Summary (Monthly)
    attendance_col = get_collection("attendance")
    attendance = await attendance_col.find({"user_id": user_id}).to_list(500)
    
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    monthly_att = {} # {month_name: {"present": 0, "absent": 0}}
    
    for a in attendance:
        dt = a.get("date")
        if isinstance(dt, str):
            try: dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            except: continue
        if not dt: continue
        
        m_name = months[dt.month - 1]
        if m_name not in monthly_att: monthly_att[m_name] = {"present": 0, "absent": 0}
        
        status = a.get("status", "absent").lower()
        if status == "present": monthly_att[m_name]["present"] += 1
        else: monthly_att[m_name]["absent"] += 1

    attendance_data = [{"name": m, **v} for m, v in monthly_att.items()]
    # Ensure some order
    attendance_data.sort(key=lambda x: months.index(x["name"]))

    # 3. Learning Progress (Top Modules)
    module_scores = {}
    total_percentage = 0
    for ass in all_ass:
        mod = ass.get("session_title", "General")
        if mod not in module_scores: module_scores[mod] = []
        module_scores[mod].append(ass.get("percentage", 0))
        total_percentage += ass.get("percentage", 0)
    
    learning_progress = []
    for mod, scores in module_scores.items():
        avg = round(sum(scores) / len(scores), 1)
        learning_progress.append({ "name": mod, "completed": avg, "total": 100 })

    avg_score = round(total_percentage / len(all_ass), 1) if all_ass else 0

    # 4. Active Sessions for User
    batch_id = user.get("batch_id")
    active_sessions_count = 0
    if batch_id:
        from app.utils.calendar_utils import CALENDAR_COLLECTIONS
        session_cols = CALENDAR_COLLECTIONS + ["calendar_events"]
        now = datetime.now()
        for col_name in session_cols:
            count = await get_collection(col_name).count_documents({
                "batch_id": batch_id,
                "start": {"$regex": f"^{now.year}-{now.month:02d}"}
            })
            active_sessions_count += count

    return {
        "weekly_scores": weekly_scores,
        "attendance_data": attendance_data,
        "learning_progress": learning_progress[:5],
        "avg_score": avg_score,
        "active_sessions": active_sessions_count,
        "task_stats": [
            {"name": "Completed", "value": len([a for a in all_ass if a.get("passed")])},
            {"name": "Pending", "value": max(0, 10 - len(all_ass))}, # Example: assuming 10 core modules
            {"name": "Other", "value": 0}
        ]
    }
