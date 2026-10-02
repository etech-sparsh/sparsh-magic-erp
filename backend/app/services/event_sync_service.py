from bson import ObjectId
from app.db.mongodb import get_collection
from datetime import datetime

from app.utils.calendar_utils import find_event_across_collections
from datetime import datetime

async def sync_event_to_collection(calendar_event_id: str):
    """
    Synchronizes the calendar_event's attendance, resources, and contents
    into the separate 'events' collection for reporting/aggregation.
    """
    events_col = get_collection("events")
    
    cal_event, col_name = await find_event_across_collections(calendar_event_id)
    if not cal_event:
        return

        
    # Attendance mapping
    attendance_dict = cal_event.get("attendance", {})
    attendees_id = [uid for uid, present in attendance_dict.items() if present]
    absent_id = [uid for uid, present in attendance_dict.items() if not present]
    
    # Resources mapping
    resources_data = []
    for r in cal_event.get("resources", []):
        resources_data.append({
            "id": r.get("id"),
            "name": r.get("name"),
            "url": r.get("url"),
            "transcription": r.get("transcription")
        })
        
    # Contents mapping
    contents_data = []
    for c in cal_event.get("contents", []):
        contents_data.append({
            "id": c.get("id"),
            "name": c.get("name"),
            "url": c.get("url")
        })
        
    sync_doc = {
        "calendar_events_id": str(cal_event["_id"]),
        "attendees_id": attendees_id,
        "absent_id": absent_id,
        "resources": resources_data,
        "contents": contents_data,
        "updated_at": datetime.utcnow()
    }
    
    # Upsert the document
    await events_col.update_one(
        {"calender_events_id": str(cal_event["_id"])},
        {"$set": sync_doc},
        upsert=True
    )
