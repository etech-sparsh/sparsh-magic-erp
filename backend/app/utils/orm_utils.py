from app.db.mongodb import get_collection
from app.models.calendar_event import Reminder
from datetime import datetime, timedelta
from bson import ObjectId
import calendar

STAFF_ROLES = {"superadmin", "admin"}


async def is_orm_enabled(company_id: str) -> bool:
    """Whether ORM is enabled for a company. Missing flag defaults to enabled so
    existing companies keep working until a superadmin explicitly disables ORM."""
    if not company_id:
        return False
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
    except Exception:
        return True
    if not company:
        return True
    return bool(company.get("orm_enabled", True))


async def ensure_orm_enabled(current_user: dict, company_id: str):
    """Raise 403 for client-side users when their company's ORM access is off.
    Staff (superadmin/admin) always pass so they can manage/report on ORM."""
    from fastapi import HTTPException
    if current_user.get("role") in STAFF_ROLES:
        return
    if not await is_orm_enabled(company_id):
        raise HTTPException(status_code=403, detail="ORM is not enabled for this company. Contact your administrator.")

async def sync_orm_to_calendar(company_id: str, parameters: list, saving_user_id: str = None):
    col = get_collection("calendar_events")
    
    # Delete existing ORM events for this company
    await col.delete_many({"company_id": company_id, "type": "orm_reminder"})
    
    events_to_create = []
    
    # Get client admin IDs to include them in the calendar
    users_col = get_collection("users")
    client_admins = await users_col.find({"company_id": company_id, "role": "clientadmin"}).to_list(100)
    admin_ids = [str(a["_id"]) for a in client_admins]
    
    now = datetime.utcnow()
    # Generate for the next 12 months
    for i in range(12):
        month_date = now + timedelta(days=30 * i)
        year = month_date.year
        month = month_date.month
        
        for param in parameters:
            for sub in param.get("subsections", []):
                freq = sub.get("frequency", "none")
                if freq == "none":
                    continue
                
                day = sub.get("dayOfMonth", 1)
                
                # Check frequency
                should_trigger = False
                if freq == "monthly":
                    should_trigger = True
                elif freq == "quarterly":
                    if month in [1, 4, 7, 10]: # Standard quarters
                        should_trigger = True
                elif freq == "six_monthly":
                    if month in [1, 7]: # Half years
                        should_trigger = True
                
                if should_trigger:
                    # Adjust day if month has fewer days
                    last_day = calendar.monthrange(year, month)[1]
                    trigger_day = min(day, last_day)
                    
                    event_date = datetime(year, month, trigger_day, 10, 0) # 10 AM
                    
                    if event_date < now:
                        continue
                        
                    assigned_users = sub.get("assignedUsers", [])
                    target_ids = list(set(assigned_users + admin_ids))
                    
                    event = {
                        "title": f"ORM Reminder: {sub['name']}",
                        "type": "orm_reminder",
                        "start": event_date.isoformat() + "Z",
                        "end": (event_date + timedelta(hours=1)).isoformat() + "Z",
                        "company_id": company_id,
                        "user_id": saving_user_id,
                        "description": f"Scheduled reminder for ORM Parameter: {param['name']} - Subsection: {sub['name']}",
                        "assigned_member_ids": target_ids,
                        "reminders": [
                            {
                                "id": f"rem_{datetime.utcnow().timestamp()}",
                                "parent_type": "event",
                                "reminder_type": "email",
                                "timing_type": "before",
                                "offset_minutes": 0,
                                "sent": False,
                                "created_at": datetime.utcnow()
                            }
                        ],
                        "color": "var(--accent-orange)",
                        "bg": "var(--accent-orange-bg)"
                    }
                    events_to_create.append(event)
    
    if events_to_create:
        await col.insert_many(events_to_create)
