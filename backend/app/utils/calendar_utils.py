from app.db.mongodb import get_collection
from bson import ObjectId

CALENDAR_COLLECTIONS = [
    "STAFF_CALENDER",
    "LEARNER_CALENDER"
]

# TPMS activities are stored in these same collections, tagged `kind: "tpms_activity"`, so
# they reuse the ERP's recurrence engine and reminder scheduler. They are NOT sessions and
# must not surface in the Session Calendar or any company session list — TPMS has its own
# calendar. Merge this into any session-side query.
#
# `$ne` also matches documents with no `kind` field at all, which is every ordinary session,
# so this narrows nothing except TPMS.
TPMS_EVENT_KIND = "tpms_activity"
EXCLUDE_TPMS = {"kind": {"$ne": TPMS_EVENT_KIND}}


def exclude_tpms(query: dict) -> dict:
    """Return `query` with TPMS activities filtered out.

    Kept as a helper so session-side callers cannot forget the clause, and so the rule lives
    in one place if the discriminator ever changes.
    """
    merged = dict(query or {})
    merged["kind"] = {"$ne": TPMS_EVENT_KIND}
    return merged

async def find_user_by_id(user_id: str):
    """Fallback search across all user-related collections."""
    if not user_id or user_id == "null" or user_id == "undefined": return None
    try:
        oid = ObjectId(user_id) if isinstance(user_id, str) and len(user_id) == 24 else user_id
        for col in ["staff", "learners"]:
            user = await get_collection(col).find_one({"_id": oid})
            if user: return user
    except: pass
    return None

async def get_target_collection_name(event_dict: dict):
    # If explicitly linked to a batch or has learner/client assignments, it's a LEARNER_CALENDER event
    if event_dict.get("batch_id") or event_dict.get("learner_id"):
        return "LEARNER_CALENDER"
    
    # Check assigned_member_ids for learners
    assigned_ids = event_dict.get("assigned_member_ids", [])
    if not isinstance(assigned_ids, list): assigned_ids = [assigned_ids]
    
    for aid in assigned_ids:
        if not aid or aid == "null": continue
        user = await find_user_by_id(aid)
        if user:
            role = user.get("role", "").lower()
            if any(r in role for r in ["learner", "client"]):
                return "LEARNER_CALENDER"
                
    # Default to STAFF_CALENDER
    return "STAFF_CALENDER"

async def find_event_across_collections(event_id: str):
    if not event_id: return None, None
    try:
        oid = ObjectId(event_id)
        for col_name in CALENDAR_COLLECTIONS:
            doc = await get_collection(col_name).find_one({"_id": oid})
            if doc: return doc, col_name
        doc = await get_collection("calendar_events").find_one({"_id": oid})
        if doc: return doc, "calendar_events"
    except: pass
    return None, None
