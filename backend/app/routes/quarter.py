from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from app.db.mongodb import get_collection
from app.models.quarter import QuarterCreate, QuarterUpdate
from app.controllers.auth_controller import get_current_user
from bson import ObjectId
from datetime import datetime

router = APIRouter(prefix="/quarters", tags=["Quarters"])

# ─── Create Quarter ───
@router.post("", status_code=status.HTTP_201_CREATED)
async def create_quarter(quarter: QuarterCreate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        if not current_user.get("permissions", {}).get("batches", {}).get("create"):
             raise HTTPException(status_code=403, detail="Not authorized")
    
    quarters_col = get_collection("quarters")
    batches_col = get_collection("batches")
    
    # Verify batch exists
    if not await batches_col.find_one({"_id": ObjectId(quarter.batch_id)}):
         raise HTTPException(status_code=404, detail="Batch not found")
         
    quarter_dict = quarter.model_dump()
    quarter_dict["status"] = "active"
    quarter_dict["created_at"] = datetime.utcnow()
    
    # Clean empty strings
    for k in ["description", "start_date", "target_end_date"]:
        if not quarter_dict.get(k):
            quarter_dict[k] = None
            
    result = await quarters_col.insert_one(quarter_dict)
    quarter_dict["_id"] = str(result.inserted_id)
    return quarter_dict

# ─── Quarter Analytics ───
@router.get("/{quarter_id}/analytics")
async def get_quarter_analytics(quarter_id: str, current_user: dict = Depends(get_current_user)):
    quarters_col = get_collection("quarters")
    quarter = await quarters_col.find_one({"_id": ObjectId(quarter_id)})
    if not quarter:
        raise HTTPException(status_code=404, detail="Quarter not found")
        
    # Stats logic
    from app.utils.calendar_utils import CALENDAR_COLLECTIONS
    
    total_sessions = 0
    total_attendance_sum = 0
    sessions_with_attendance = 0
    total_tasks = 0
    completed_tasks = 0
    
    for col_name in (CALENDAR_COLLECTIONS + ["calendar_events"]):
        col = get_collection(col_name)
        # Sessions
        sessions = await col.find({"quarter_id": quarter_id, "type": "event"}).to_list(1000)
        total_sessions += len(sessions)
        for s in sessions:
            att = s.get("attendance", {})
            if att:
                present = sum(1 for v in att.values() if v is True)
                total = len(att)
                if total > 0:
                    total_attendance_sum += (present / total) * 100
                    sessions_with_attendance += 1
        
        # Tasks
        tasks = await col.find({"quarter_id": quarter_id, "type": "task"}).to_list(1000)
        total_tasks += len(tasks)
        completed_tasks += sum(1 for t in tasks if t.get("status") == "completed")
        
    avg_attendance = round(total_attendance_sum / sessions_with_attendance) if sessions_with_attendance > 0 else 0
    task_rate = round((completed_tasks / total_tasks) * 100) if total_tasks > 0 else 0
    
    # Companies from parent batch
    batch_col = get_collection("batches")
    active_companies = 0
    if quarter.get("batch_id"):
        batch = await batch_col.find_one({"_id": ObjectId(quarter["batch_id"])})
        if batch:
            active_companies = len(batch.get("companies", []))
            
    return {
        "total_sessions": total_sessions,
        "avg_attendance": f"{avg_attendance}%",
        "active_companies": active_companies,
        "tasks_done": f"{task_rate}%"
    }

# ─── List Quarters ───
@router.get("")
async def list_quarters(batch_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    quarters_col = get_collection("quarters")
    query = {}
    if batch_id:
        query["batch_id"] = batch_id
        
    quarters = await quarters_col.find(query).sort("created_at", 1).to_list(1000)
    for q in quarters:
        q["_id"] = str(q["_id"])
    return quarters

# ─── Get Single Quarter ───
@router.get("/{quarter_id}")
async def get_quarter(quarter_id: str, current_user: dict = Depends(get_current_user)):
    quarters_col = get_collection("quarters")
    quarter = await quarters_col.find_one({"_id": ObjectId(quarter_id)})
    if not quarter:
        raise HTTPException(status_code=404, detail="Quarter not found")
    quarter["_id"] = str(quarter["_id"])
    return quarter

# ─── Update Quarter ───
@router.put("/{quarter_id}")
async def update_quarter(quarter_id: str, updates: QuarterUpdate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        if not current_user.get("permissions", {}).get("batches", {}).get("update"):
             raise HTTPException(status_code=403, detail="Not authorized")
    
    quarters_col = get_collection("quarters")
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
        
    update_data["updated_at"] = datetime.utcnow()
    result = await quarters_col.update_one({"_id": ObjectId(quarter_id)}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Quarter not found")
    return {"message": "Quarter updated"}

# ─── Delete Quarter ───
@router.delete("/{quarter_id}")
async def delete_quarter(quarter_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        if not current_user.get("permissions", {}).get("batches", {}).get("delete"):
             raise HTTPException(status_code=403, detail="Not authorized")
    
    quarters_col = get_collection("quarters")
    result = await quarters_col.delete_one({"_id": ObjectId(quarter_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Quarter not found")
    return {"message": "Quarter deleted"}
