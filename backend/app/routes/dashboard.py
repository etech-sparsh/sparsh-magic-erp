from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict
from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user, check_role
from app.models.user import UserRole
from datetime import datetime, timedelta
from bson import ObjectId

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/stats")
async def get_dashboard_stats(current_user: dict = Depends(get_current_user)):
    role = current_user.get("role", "").lower()
    company_id = current_user.get("company_id")
    
    #スタッフ or 会社管理 or 一般的な学習者
    is_staff = role in ["superadmin", "admin", "coach"]
    
    companies_col = get_collection("companies")
    batches_col = get_collection("batches")
    learners_col = get_collection("learners")
    from app.utils.calendar_utils import CALENDAR_COLLECTIONS
    session_cols = CALENDAR_COLLECTIONS + ["calendar_events"]

    # 1. KPIs
    if is_staff:
        registered_entities = await companies_col.count_documents({})
        active_batches = await batches_col.count_documents({"status": "active"})
        strategic_learners = await learners_col.count_documents({})
    else:
        # For company users (admin/user)
        registered_entities = 1 # Just their own
        # Count batches that have this company associated, or just batches conceptually
        active_batches = await batches_col.count_documents({"status": "active", "company_id": company_id})
        # My Team members
        strategic_learners = await learners_col.count_documents({"company_id": company_id})

    # 2. Session Velocity (Completed in last 30 days)
    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
    session_velocity = 0
    
    # 3. Operational Pulse (Last 14 Days)
    pulse_data = []
    today = datetime.utcnow().date()
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        day_str = day.strftime("%d %b")
        count = 0
        
        # Count sessions only — exclude type=="task" so completed Task Management to-dos
        # (which also carry status=="completed") never inflate the session pulse. Keeps
        # Calendar/session stats independent of Task/Delegation data. (Session Mix below
        # already applies this same exclusion.)
        for col_name in session_cols:
            query = {
                "start": {"$regex": f"^{day.isoformat()}"},
                "status": "completed",
                "type": {"$ne": "task"},
            }
            if not is_staff:
                query["company_id"] = company_id

            count += await get_collection(col_name).count_documents(query)
        pulse_data.append({"name": day_str, "sessions": count})

    # Total Velocity for the KPI (30 days) — sessions only (exclude type=="task" so completed
    # tasks don't leak into the session count; keeps Calendar and Task/Delegation independent).
    for col_name in session_cols:
        query = {
            "status": "completed",
            "start": {"$gte": thirty_days_ago},
            "type": {"$ne": "task"},
        }
        if not is_staff:
            query["company_id"] = company_id
        session_velocity += await get_collection(col_name).count_documents(query)

    # 4. Session Mix (Pie Chart)
    mix_data = []
    mix_counts = {"Strategic": 0, "Technical": 0, "Operational": 0, "Other": 0}
    for col_name in session_cols:
        query = {}
        if not is_staff:
            query["company_id"] = company_id
            
        cursor = get_collection(col_name).find(query)
        async for session in cursor:
            # Skip personal to-do entries (type=="task"): they are not coaching
            # sessions and otherwise dominate the "Other" slice, making the mix
            # meaningless. (Mirrors the assistant's get_dashboard_stats.)
            if session.get("type") == "task": continue
            s_type = session.get("session_type") or "Other"
            if any(kw in s_type for kw in ["Direct", "Strategy", "CEO"]): mix_counts["Strategic"] += 1
            elif any(kw in s_type for kw in ["Review", "Module", "Session"]): mix_counts["Technical"] += 1
            elif any(kw in s_type for kw in ["Support", "Check"]): mix_counts["Operational"] += 1
            else: mix_counts["Other"] += 1
    
    colors = {
        "Strategic": "var(--accent-indigo)", 
        "Technical": "var(--accent-orange)", 
        "Operational": "var(--accent-green)", 
        "Other": "var(--text-muted)"
    }
    for k, v in mix_counts.items():
        if v > 0:
            mix_data.append({"name": k, "value": v, "color": colors.get(k, "var(--text-muted)")})

    # 5. Attendance (If learner, calculate for their company)
    attendance_rate = 0
    if not is_staff:
        attendance_col = get_collection("attendance")
        # Simplified: count present vs total records for the company
        # First find all learners of this company
        company_learners = await learners_col.find({"company_id": company_id}, {"_id": 1}).to_list(1000)
        learner_ids = [str(l["_id"]) for l in company_learners]
        
        if learner_ids:
            total_records = await attendance_col.count_documents({"user_id": {"$in": learner_ids}})
            present_records = await attendance_col.count_documents({"user_id": {"$in": learner_ids}, "status": "present"})
            if total_records > 0:
                attendance_rate = round((present_records / total_records) * 100)

    return {
        "kpis": {
            "registered_entities": registered_entities,
            "active_batches": active_batches,
            "strategic_learners": strategic_learners,
            "session_velocity": session_velocity,
            "attendance_rate": attendance_rate # Added for learners
        },
        "operational_pulse": pulse_data,
        "session_mix": mix_data
    }
