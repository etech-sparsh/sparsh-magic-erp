from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from app.db.mongodb import get_collection
from app.models.batch import BatchCreate, BatchUpdate
from app.controllers.auth_controller import get_current_user
from bson import ObjectId
from datetime import datetime

router = APIRouter(prefix="/batches", tags=["Batches"])

# ─── Create Batch ───
@router.post("", status_code=status.HTTP_201_CREATED)
async def create_batch(batch: BatchCreate, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_create = permissions.get("batches", {}).get("create", False)
    
    if current_user.get("role") != "superadmin" and not can_create:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    batches_col = get_collection("batches")
    batch_dict = batch.model_dump()
    batch_dict["status"] = "active"
    batch_dict["companies"] = []
    batch_dict["created_at"] = datetime.utcnow()
    batch_dict["company_count"] = 0
    
    # Clean empty strings to None
    for k in ["description", "start_date", "target_end_date"]:
        if not batch_dict.get(k):
            batch_dict[k] = None
    
    result = await batches_col.insert_one(batch_dict)
    batch_dict["_id"] = str(result.inserted_id)
    return batch_dict

# ─── List All Batches ───
@router.get("")
async def list_batches(current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_read = permissions.get("batches", {}).get("read", False)
    role = current_user.get("role")

    batches_col = get_collection("batches")

    if role == "superadmin" or can_read:
        batches = await batches_col.find().sort("created_at", -1).to_list(200)
    elif role in ("clientadmin", "clientuser"):
        company_id = current_user.get("company_id")
        batches = await batches_col.find({"companies": company_id}).sort("created_at", -1).to_list(200)
    else:
        raise HTTPException(status_code=403, detail="Not authorized")

    for b in batches:
        b["_id"] = str(b["_id"])
        b["company_count"] = len(b.get("companies", []))
    return batches

# ─── Get Single Batch ───
@router.get("/{batch_id}")
async def get_batch(batch_id: str, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_read = permissions.get("batches", {}).get("read", False)
    
    if current_user.get("role") != "superadmin" and not can_read:
        raise HTTPException(status_code=403, detail="Not authorized")
    batches_col = get_collection("batches")
    batch = await batches_col.find_one({"_id": ObjectId(batch_id)})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    batch["_id"] = str(batch["_id"])
    batch["company_count"] = len(batch.get("companies", []))
    return batch

# ─── Update Batch ───
@router.put("/{batch_id}")
async def update_batch(batch_id: str, updates: BatchUpdate, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("batches", {}).get("update", False)
    
    if current_user.get("role") != "superadmin" and not can_update:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    batches_col = get_collection("batches")
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    update_data["updated_at"] = datetime.utcnow()
    result = await batches_col.update_one({"_id": ObjectId(batch_id)}, {"$set": update_data})
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"message": "Batch updated"}

# ─── Update Batch Status ───
@router.patch("/{batch_id}/status")
async def update_batch_status(batch_id: str, body: dict, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("batches", {}).get("update", False)
    
    if current_user.get("role") != "superadmin" and not can_update:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    new_status = body.get("status")
    if new_status not in ["active", "completed", "paused"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    batches_col = get_collection("batches")
    result = await batches_col.update_one(
        {"_id": ObjectId(batch_id)},
        {"$set": {"status": new_status, "updated_at": datetime.utcnow()}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"message": f"Batch status changed to {new_status}"}

# ─── Delete Batch ───
@router.delete("/{batch_id}")
async def delete_batch(batch_id: str, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_delete = permissions.get("batches", {}).get("delete", False)
    
    if current_user.get("role") != "superadmin" and not can_delete:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    batches_col = get_collection("batches")
    result = await batches_col.delete_one({"_id": ObjectId(batch_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"message": "Batch deleted"}

# ─── Add Companies to Batch ───
@router.post("/{batch_id}/companies")
async def add_companies_to_batch(batch_id: str, company_ids: List[str], current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("batches", {}).get("update", False)
    
    if current_user.get("role") != "superadmin" and not can_update:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    batches_col = get_collection("batches")
    batch = await batches_col.find_one({"_id": ObjectId(batch_id)})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    existing = set(batch.get("companies", []))
    new_companies = [cid for cid in company_ids if cid not in existing]
    
    if new_companies:
        await batches_col.update_one(
            {"_id": ObjectId(batch_id)},
            {"$push": {"companies": {"$each": new_companies}}}
        )
    
    return {"message": f"Added {len(new_companies)} companies", "skipped": len(company_ids) - len(new_companies)}

# ─── Remove Company from Batch ───
@router.delete("/{batch_id}/companies/{company_id}")
async def remove_company_from_batch(batch_id: str, company_id: str, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("batches", {}).get("update", False)
    
    if current_user.get("role") != "superadmin" and not can_update:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    batches_col = get_collection("batches")
    await batches_col.update_one(
        {"_id": ObjectId(batch_id)},
        {"$pull": {"companies": company_id}}
    )
    return {"message": "Company removed from batch"}

# ─── Get Batch Companies (with details) ───
@router.get("/{batch_id}/companies")
async def get_batch_companies(batch_id: str, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_read = permissions.get("batches", {}).get("read", False)
    
    if current_user.get("role") != "superadmin" and not can_read:
        raise HTTPException(status_code=403, detail="Not authorized")
    batches_col = get_collection("batches")
    companies_col = get_collection("companies")
    
    batch = await batches_col.find_one({"_id": ObjectId(batch_id)})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    company_ids = batch.get("companies", [])
    if not company_ids:
        return []
    
    companies = await companies_col.find({
        "_id": {"$in": [ObjectId(cid) for cid in company_ids]}
    }).to_list(100)
    
    for c in companies:
        c["_id"] = str(c["_id"])
    return companies

# ─── Merge Batches ───
@router.post("/{batch_id}/merge")
async def merge_batches(batch_id: str, body: dict, current_user: dict = Depends(get_current_user)):
    """Merge source_batch_id into batch_id. Combines companies, optionally deletes source."""
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("batches", {}).get("update", False)
    
    if current_user.get("role") != "superadmin" and not can_update:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    source_id = body.get("source_batch_id")
    delete_source = body.get("delete_source", False)
    
    if not source_id:
        raise HTTPException(status_code=400, detail="source_batch_id required")
    
    batches_col = get_collection("batches")
    
    target = await batches_col.find_one({"_id": ObjectId(batch_id)})
    source = await batches_col.find_one({"_id": ObjectId(source_id)})
    
    if not target or not source:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    # Merge companies (dedup)
    existing = set(target.get("companies", []))
    new_companies = [cid for cid in source.get("companies", []) if cid not in existing]
    
    if new_companies:
        await batches_col.update_one(
            {"_id": ObjectId(batch_id)},
            {"$push": {"companies": {"$each": new_companies}}}
        )
    
    merged_count = len(new_companies)
    
    if delete_source:
        await batches_col.delete_one({"_id": ObjectId(source_id)})
    
    return {
        "message": f"Merged {merged_count} companies from '{source.get('name')}' into '{target.get('name')}'",
        "source_deleted": delete_source
    }

# ─── Shift Company Between Batches ───
@router.post("/{batch_id}/companies/{company_id}/shift")
async def shift_company(batch_id: str, company_id: str, body: dict, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("batches", {}).get("update", False)
    
    if current_user.get("role") != "superadmin" and not can_update:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    target_batch_id = body.get("target_batch_id")
    if not target_batch_id:
        raise HTTPException(status_code=400, detail="target_batch_id required")
    
    batches_col = get_collection("batches")
    
    # 1. Remove from source
    await batches_col.update_one(
        {"_id": ObjectId(batch_id)},
        {"$pull": {"companies": company_id}}
    )
    
    # 2. Add to target (with dedup)
    target = await batches_col.find_one({"_id": ObjectId(target_batch_id)})
    if not target:
        raise HTTPException(status_code=404, detail="Target batch not found")
        
    if company_id not in target.get("companies", []):
        await batches_col.update_one(
            {"_id": ObjectId(target_batch_id)},
            {"$push": {"companies": company_id}}
        )
        
    return {"message": "Company shifted successfully"}

