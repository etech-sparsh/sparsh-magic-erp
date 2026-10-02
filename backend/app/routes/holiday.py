from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from datetime import datetime, timezone
from bson import ObjectId

from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user, is_internal_user
from app.models.holiday import HolidayCreate, HolidayUpdate
from app.services.activity_log_service import log_activity

router = APIRouter(prefix="/holidays", tags=["Holidays"])

# Holiday management is restricted to Super Admin / Admin only. Any authenticated user can
# still READ holidays (client calendars + the task due-date picker block holiday dates for
# everyone); only superadmin/admin can create/update/delete the master list.
MANAGE_ROLES = ["superadmin", "admin"]


def _can_manage(current_user: dict) -> bool:
    return (current_user.get("role") or "").lower() in MANAGE_ROLES


def _serialize(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "holiday_name": doc.get("holiday_name"),
        "holiday_date": doc.get("holiday_date"),
        "description": doc.get("description"),
        "holiday_type": doc.get("holiday_type") or "Company",
        "status": doc.get("status") or "active",
        "created_by": doc.get("created_by"),
        "created_by_name": doc.get("created_by_name"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


@router.get("", response_model=List[dict])
async def list_holidays(
    search: Optional[str] = None,
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    col = get_collection("holidays")
    query = {}
    if status:
        query["status"] = status
    if search:
        query["holiday_name"] = {"$regex": search.strip(), "$options": "i"}
    # holiday_date is "YYYY-MM-DD", so year/month filter by string prefix.
    if year and month:
        query["holiday_date"] = {"$regex": f"^{year}-{month:02d}"}
    elif year:
        query["holiday_date"] = {"$regex": f"^{year}-"}
    elif month:
        query["holiday_date"] = {"$regex": f"^\\d{{4}}-{month:02d}"}

    docs = await col.find(query).sort("holiday_date", -1).to_list(1000)
    return [_serialize(d) for d in docs]


@router.post("", response_model=dict)
async def create_holiday(payload: HolidayCreate, current_user: dict = Depends(get_current_user)):
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to add holidays")

    data = payload.model_dump()
    data["holiday_name"] = (data.get("holiday_name") or "").strip()
    data["holiday_date"] = (data.get("holiday_date") or "").strip()
    if not data["holiday_name"] or not data["holiday_date"]:
        raise HTTPException(status_code=400, detail="Holiday name and date are required")

    col = get_collection("holidays")
    # Prevent duplicates: same date + same (case-insensitive) name.
    dup = await col.find_one({
        "holiday_date": data["holiday_date"],
        "holiday_name": {"$regex": f"^{data['holiday_name']}$", "$options": "i"},
    })
    if dup:
        raise HTTPException(status_code=409, detail="A holiday with this name already exists on that date")

    data["created_by"] = str(current_user["_id"])
    data["created_by_name"] = current_user.get("full_name") or current_user.get("email")
    data["created_at"] = datetime.now(timezone.utc)
    data["updated_at"] = None

    result = await col.insert_one(data)
    await log_activity(current_user, "Create Holiday", "Holiday", f"Holiday added: {data['holiday_name']} ({data['holiday_date']})")
    return {"id": str(result.inserted_id), "message": "Holiday created"}


@router.put("/{holiday_id}", response_model=dict)
async def update_holiday(holiday_id: str, payload: HolidayUpdate, current_user: dict = Depends(get_current_user)):
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update holidays")

    col = get_collection("holidays")
    existing = await col.find_one({"_id": ObjectId(holiday_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Holiday not found")

    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "holiday_name" in updates:
        updates["holiday_name"] = updates["holiday_name"].strip()
    if "holiday_date" in updates:
        updates["holiday_date"] = updates["holiday_date"].strip()

    # Re-check duplicates when name/date change.
    new_name = updates.get("holiday_name", existing.get("holiday_name"))
    new_date = updates.get("holiday_date", existing.get("holiday_date"))
    dup = await col.find_one({
        "_id": {"$ne": ObjectId(holiday_id)},
        "holiday_date": new_date,
        "holiday_name": {"$regex": f"^{new_name}$", "$options": "i"},
    })
    if dup:
        raise HTTPException(status_code=409, detail="A holiday with this name already exists on that date")

    updates["updated_at"] = datetime.now(timezone.utc)
    await col.update_one({"_id": ObjectId(holiday_id)}, {"$set": updates})
    await log_activity(current_user, "Update Holiday", "Holiday", f"Holiday updated: {new_name} ({new_date})")
    return {"message": "Holiday updated"}


@router.delete("/{holiday_id}", response_model=dict)
async def delete_holiday(holiday_id: str, current_user: dict = Depends(get_current_user)):
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to delete holidays")

    col = get_collection("holidays")
    existing = await col.find_one({"_id": ObjectId(holiday_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Holiday not found")

    await col.delete_one({"_id": ObjectId(holiday_id)})
    await log_activity(current_user, "Delete Holiday", "Holiday", f"Holiday removed: {existing.get('holiday_name')}")
    return {"message": "Holiday deleted"}
