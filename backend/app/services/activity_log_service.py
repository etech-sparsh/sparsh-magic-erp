from datetime import datetime, timezone
from app.db.mongodb import get_collection
from app.models.activity_log import ActivityLog
import json

async def log_activity(user: dict, action: str, module: str, details: str = None, meta: dict = None):
    try:
        log_entry = {
            "user_id": str(user.get("_id") or user.get("id")),
            "user_name": user.get("full_name") or user.get("name") or "Unknown",
            "user_email": user.get("email", "unknown@domain.com"),
            "action": action,
            "module": module,
            "details": details,
            "metadata": meta or {},
            "timestamp": datetime.now(timezone.utc)
        }
        col = get_collection("activity_logs")
        await col.insert_one(log_entry)
    except Exception as e:
        print(f"FAILED TO LOG ACTIVITY: {str(e)}")
