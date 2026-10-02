from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from app.db.mongodb import get_collection
from app.models.session_template import SessionTemplateCreate, SessionTemplateUpdate
from app.controllers.auth_controller import get_current_user
from bson import ObjectId
from datetime import datetime

router = APIRouter(prefix="/session-templates", tags=["Session Templates"])

STAFF_ROLES = {"superadmin", "admin", "coach", "staff"}

# Grading is server-side (calendar_events submit endpoint), so learners never
# need the answer keys the templates carry. Strip them from reads for non-staff
# — otherwise any learner JWT can fetch every quiz answer over REST (including
# from inside the assessment player, which loads the template to render a quiz).
_ANSWER_KEY_FIELDS = ("correct_option_index", "expected_answer", "expected_keywords", "checker_instructions")


def _strip_answer_keys(template: dict, current_user: dict) -> dict:
    if current_user.get("role") in STAFF_ROLES:
        return template
    for assessment in template.get("assessments") or []:
        if not isinstance(assessment, dict):
            continue
        for q in assessment.get("questions") or []:
            if isinstance(q, dict):
                for field in _ANSWER_KEY_FIELDS:
                    q.pop(field, None)
    return template


# ─── Create Session Template ───
@router.post("", status_code=status.HTTP_201_CREATED)
async def create_template(template: SessionTemplateCreate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        if not current_user.get("permissions", {}).get("templates", {}).get("create"):
            raise HTTPException(status_code=403, detail="Not authorized")
    
    templates_col = get_collection("session_templates")
    template_dict = template.model_dump()
    template_dict["created_at"] = datetime.utcnow()
            
    result = await templates_col.insert_one(template_dict)
    template_dict["_id"] = str(result.inserted_id)
    return template_dict

# ─── List All Session Templates ───
@router.get("")
async def list_templates(current_user: dict = Depends(get_current_user)):
    templates_col = get_collection("session_templates")
    templates = await templates_col.find().sort("created_at", -1).to_list(100)
    for t in templates:
        t["_id"] = str(t["_id"])
        _strip_answer_keys(t, current_user)
    return templates

# ─── Get Single Session Template ───
@router.get("/{template_id}")
async def get_template(template_id: str, current_user: dict = Depends(get_current_user)):
    templates_col = get_collection("session_templates")
    template = await templates_col.find_one({"_id": ObjectId(template_id)})
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    template["_id"] = str(template["_id"])
    return _strip_answer_keys(template, current_user)

# ─── Update Session Template ───
@router.put("/{template_id}")
async def update_template(template_id: str, updates: SessionTemplateUpdate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        if not current_user.get("permissions", {}).get("templates", {}).get("update"):
            raise HTTPException(status_code=403, detail="Not authorized")
    
    templates_col = get_collection("session_templates")
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
        
    update_data["updated_at"] = datetime.utcnow()
    result = await templates_col.update_one({"_id": ObjectId(template_id)}, {"$set": update_data})
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"message": "Template updated"}

# ─── Add/Replace Tasks ───
@router.post("/{template_id}/tasks")
async def update_tasks(template_id: str, tasks: List[dict], current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        if not current_user.get("permissions", {}).get("templates", {}).get("update"):
            raise HTTPException(status_code=403, detail="Not authorized")
    
    templates_col = get_collection("session_templates")
    result = await templates_col.update_one(
        {"_id": ObjectId(template_id)},
        {"$set": {"tasks": tasks}}
    )
    return {"message": f"Updated tasks for template {template_id}"}

# ─── Add/Replace Assessments ───
@router.post("/{template_id}/assessments")
async def update_assessments(template_id: str, assessments: List[dict], current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        if not current_user.get("permissions", {}).get("templates", {}).get("update"):
            raise HTTPException(status_code=403, detail="Not authorized")
    
    templates_col = get_collection("session_templates")
    result = await templates_col.update_one(
        {"_id": ObjectId(template_id)},
        {"$set": {"assessments": assessments}}
    )
    return {"message": f"Updated assessments for template {template_id}"}


# ─── Delete Session Template ───
@router.delete("/{template_id}")
async def delete_template(template_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "superadmin":
        if not current_user.get("permissions", {}).get("templates", {}).get("delete"):
            raise HTTPException(status_code=403, detail="Not authorized")
    
    templates_col = get_collection("session_templates")
    result = await templates_col.delete_one({"_id": ObjectId(template_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"message": "Template deleted"}
