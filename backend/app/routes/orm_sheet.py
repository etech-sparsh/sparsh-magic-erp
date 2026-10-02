from fastapi import APIRouter, Depends, HTTPException, status
from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection
from app.utils.orm_utils import ensure_orm_enabled
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from bson import ObjectId

router = APIRouter(prefix="/orm/sheet", tags=["ORM Sheet"])

class ORMSubmissionItem(BaseModel):
    sno: int
    checkpoint: Optional[str] = None
    max_marks: Optional[float] = 0.0
    response: Optional[str] = None
    remarks: Optional[str] = ""
    
    # Budget Cost Adherence fields
    particulars: Optional[str] = None
    head: Optional[str] = None
    subhead: Optional[str] = None
    rate: Optional[float] = 0.0
    target: Optional[float] = 0.0
    actual: Optional[float] = 0.0
    gap: Optional[float] = 0.0
    raised_by: Optional[str] = ""
    raised_to: Optional[str] = ""
    reason: Optional[str] = ""

    # Team Engagement fields
    question: Optional[str] = None
    min_marks: Optional[float] = 0.0
    marks_given: Optional[float] = 0.0
    review: Optional[str] = ""

    # Revenue Target vs Achievement fields
    achievement: Optional[float] = 0.0

    # NPS / CSI fields
    sheet_id: Optional[str] = ""
    form_id: Optional[str] = ""

class ORMSubmissionRequest(BaseModel):
    parameter_id: str
    subsection_id: str
    period: str # "YYYY-MM" (monthly) or "YYYY-[Q]Q" (quarterly)
    checklist: List[ORMSubmissionItem]

@router.get("/assigned")
async def get_assigned_subsections(current_user: dict = Depends(get_current_user)):
    company_id = current_user.get("company_id")
    if not company_id:
        return {"parameters": []}

    await ensure_orm_enabled(current_user, company_id)

    configs_col = get_collection("ORM_Configs")
    orm = await configs_col.find_one({"company_id": company_id})
    if not orm:
        return {"parameters": []}
    
    role = current_user.get("role")
    user_id = str(current_user.get("_id"))
    
    # Clientadmin, admin, and superadmin see all parameters and subsections
    if role in ["superadmin", "admin", "clientadmin"]:
        return {"parameters": orm.get("parameters", [])}

    filtered_params = []
    for param in orm.get("parameters", []):
        is_param_assigned = user_id in param.get("assignedUsers", [])
        filtered_subs = []
        for sub in param.get("subsections", []):
            is_sub_assigned = user_id in sub.get("assignedUsers", [])
            # User has access if they are assigned globally to the parameter, or specifically to the subsection
            if is_param_assigned or is_sub_assigned:
                filtered_subs.append(sub)
                
        if filtered_subs:
            param_copy = dict(param)
            param_copy["subsections"] = filtered_subs
            filtered_params.append(param_copy)
            
    return {"parameters": filtered_params}

@router.get("/submission-status")
async def get_submission_status(
    parameter_id: str,
    subsection_id: str,
    period: str,
    current_user: dict = Depends(get_current_user)
):
    company_id = current_user.get("company_id")
    user_id = str(current_user.get("_id"))
    
    submissions_col = get_collection("ORM_Submissions")
    
    if parameter_id == "p4":
        existing = await submissions_col.find_one({
            "company_id": company_id,
            "user_id": user_id,
            "parameter_id": parameter_id,
            "subsection_id": subsection_id,
            "period": period
        })
        if existing:
            existing["_id"] = str(existing["_id"])
            return {"already_submitted": True, "submission": existing}
        return {"already_submitted": False}
        
    # For all other parameters (Process Score, Budget Cost Adherence), check if ANY user has submitted
    existing = await submissions_col.find_one({
        "company_id": company_id,
        "parameter_id": parameter_id,
        "subsection_id": subsection_id,
        "period": period
    })
    
    if existing:
        existing["_id"] = str(existing["_id"])
        submitted_by_me = str(existing.get("user_id")) == user_id
        return {
            "already_submitted": True, 
            "submission": existing,
            "submitted_by_me": submitted_by_me,
            "submitted_by_name": existing.get("user_name", "another user")
        }
        
    return {"already_submitted": False}

@router.post("/submit")
async def submit_orm_sheet(
    request: ORMSubmissionRequest,
    current_user: dict = Depends(get_current_user)
):
    company_id = current_user.get("company_id")
    await ensure_orm_enabled(current_user, company_id)

    user_id = str(current_user.get("_id"))
    user_name = current_user.get("name", "Learner")
    email = current_user.get("email", "")

    submissions_col = get_collection("ORM_Submissions")
    
    # 1. Double check duplicate submissions
    if request.parameter_id == "p4":
        existing = await submissions_col.find_one({
            "company_id": company_id,
            "user_id": user_id,
            "parameter_id": request.parameter_id,
            "subsection_id": request.subsection_id,
            "period": request.period
        })
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"You have already submitted a response for {request.period}."
            )
    else:
        existing = await submissions_col.find_one({
            "company_id": company_id,
            "parameter_id": request.parameter_id,
            "subsection_id": request.subsection_id,
            "period": request.period
        })
        if existing:
            submitted_by_name = existing.get("user_name", "another user")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"This assessment has already been completed and locked by {submitted_by_name} for this period."
            )
        
    # 2. Get survey level for p4/engagement surveys to handle anonymity
    is_engagement = request.parameter_id == "p4" or any(item.question is not None for item in request.checklist)
    survey_level = "public"
    
    if is_engagement:
        configs_col = get_collection("ORM_Configs")
        orm_config = await configs_col.find_one({"company_id": company_id})
        if orm_config:
            for p in orm_config.get("parameters", []):
                if p.get("id") == request.parameter_id:
                    for s in p.get("subsections", []):
                        if s.get("id") == request.subsection_id:
                            survey_level = s.get("surveyLevel", "public")
                            break
                            
        if survey_level.lower() == "anonymous":
            user_name = "Anonymous"
            email = "Anonymous"

    # 3. Calculate scores
    total_obtained = 0.0
    total_max = 0.0
    processed_checklist = []

    is_budget = request.parameter_id == "p5" or any(item.particulars is not None for item in request.checklist)
    is_revenue = request.parameter_id == "p1"
    is_nps = request.parameter_id == "p3"

    if is_nps:
        item = request.checklist[0] if request.checklist else None
        target = float(item.target or 0.0) if item else 0.0
        achievement = float(item.achievement or 0.0) if item else 0.0
        sheet_id = (item.sheet_id or "") if item else ""
        form_id = (item.form_id or "") if item else ""
        remarks = (item.remarks or "") if item else ""

        if target == 0:
            adherence = 100.0 if achievement == 0 else 100.0
        else:
            adherence = (achievement / target) * 100.0
            adherence = max(0.0, min(100.0, adherence))

        total_obtained = round(adherence, 2)
        total_max = 100.0
        processed_checklist.append({
            "sno": 1,
            "target": target,
            "achievement": achievement,
            "sheet_id": sheet_id,
            "form_id": form_id,
            "remarks": remarks,
            "adherence_percentage": round(adherence, 2)
        })
    elif is_revenue:
        # Single-row form: target (read-only from config) + achievement (user input) + remarks
        item = request.checklist[0] if request.checklist else None
        target = float(item.target or 0.0) if item else 0.0
        achievement = float(item.achievement or 0.0) if item else 0.0
        remarks = (item.remarks or "") if item else ""

        if target == 0:
            adherence = 100.0 if achievement == 0 else 100.0
        else:
            adherence = (achievement / target) * 100.0
            adherence = max(0.0, min(100.0, adherence))

        total_obtained = round(adherence, 2)
        total_max = 100.0
        processed_checklist.append({
            "sno": 1,
            "target": target,
            "achievement": achievement,
            "remarks": remarks,
            "adherence_percentage": round(adherence, 2)
        })
    elif is_budget:
        row_scores = []
        for item in request.checklist:
            target = item.target or 0.0
            actual = item.actual or 0.0
            gap = round(target - actual, 2)
            
            # Calculate adherence percentage for this row
            if target == 0.0:
                adherence = 100.0 if actual == 0.0 else 0.0
            else:
                adherence = (1.0 - abs(gap) / target) * 100.0
                adherence = max(0.0, min(100.0, adherence))
                
            row_scores.append(adherence)
            
            processed_checklist.append({
                "sno": item.sno,
                "particulars": item.particulars or "",
                "head": item.head or "",
                "subhead": item.subhead or "",
                "rate": item.rate or 0.0,
                "target": target,
                "actual": actual,
                "gap": gap,
                "raised_by": item.raised_by or "",
                "raised_to": item.raised_to or "",
                "reason": item.reason or "",
                "adherence_percentage": round(adherence, 2)
            })
        total_obtained = round(sum(row_scores) / len(row_scores), 2) if row_scores else 100.0
        total_max = 100.0
    elif is_engagement:
        for item in request.checklist:
            min_marks = float(item.min_marks or 0.0)
            marks_given = float(item.marks_given or 0.0)
            marks_given = max(0.0, min(min_marks, marks_given))
            
            total_obtained += marks_given
            total_max += min_marks
            
            processed_checklist.append({
                "sno": item.sno,
                "question": item.question,
                "min_marks": min_marks,
                "marks_given": marks_given,
                "review": item.review or ""
            })
    else:
        for item in request.checklist:
            total_max += item.max_marks
            obtained = item.max_marks if item.response == "Yes" else 0.0
            total_obtained += obtained
            
            processed_checklist.append({
                "sno": item.sno,
                "checkpoint": item.checkpoint,
                "max_marks": item.max_marks,
                "response": item.response,
                "obtained_marks": obtained,
                "remarks": item.remarks or ""
            })
        
    submission_doc = {
        "company_id": company_id,
        "user_id": user_id,
        "user_name": user_name,
        "email": email,
        "parameter_id": request.parameter_id,
        "subsection_id": request.subsection_id,
        "period": request.period,
        "score": total_obtained,
        "max_marks": total_max,
        "checklist": processed_checklist,
        "submitted_at": datetime.utcnow()
    }
    
    await submissions_col.insert_one(submission_doc)
    
    # 4. Aggregate all submissions for this period and subsection to calculate average score
    cursor = submissions_col.find({
        "company_id": company_id,
        "parameter_id": request.parameter_id,
        "subsection_id": request.subsection_id,
        "period": request.period
    })
    all_subs = await cursor.to_list(length=1000)
    
    if all_subs:
        if is_engagement:
            total_min_all = 0.0
            total_given_all = 0.0
            for s in all_subs:
                for item in s.get("checklist", []):
                    total_min_all += float(item.get("min_marks") or 0.0)
                    total_given_all += float(item.get("marks_given") or 0.0)

            if total_min_all > 0:
                avg_score = (total_given_all / total_min_all) * 100.0
            else:
                avg_score = 0.0
            avg_score = round(avg_score, 2)
        elif is_revenue or is_nps:
            # Use the raw submitted achievement value (single-user lock means one submission)
            latest = all_subs[-1]
            raw_achievement = 0.0
            for item in latest.get("checklist", []):
                raw_achievement = float(item.get("achievement") or 0.0)
                break
            avg_score = round(raw_achievement, 2)
        else:
            avg_score = sum(s["score"] for s in all_subs) / len(all_subs)
            # Round to 2 decimal places
            avg_score = round(avg_score, 2)

        # 5. Periodically fill 'Achievement' in Performance Matrix (ORM_Configs)
        configs_col = get_collection("ORM_Configs")
        orm = await configs_col.find_one({"company_id": company_id})

        if orm:
            parameters = orm.get("parameters", [])
            updated = False
            for param in parameters:
                if param.get("id") == request.parameter_id:
                    for sub in param.get("subsections", []):
                        if sub.get("id") == request.subsection_id:
                            sub["achievement"] = avg_score
                            updated = True
                            break
                    if updated:
                        break

            if updated:
                await configs_col.update_one(
                    {"company_id": company_id},
                    {"$set": {"parameters": parameters, "updated_at": datetime.utcnow()}}
                )

        # 5b. Also persist the achievement into the month-partitioned store so each
        # month keeps its own snapshot. Only monthly periods ("YYYY-MM") map to the
        # Performance Matrix month view; quarterly periods are handled by the live config.
        if len(request.period) == 7 and request.period[4] == "-":
            monthly_col = get_collection("ORM_Monthly")
            await monthly_col.update_one(
                {"company_id": company_id, "period": request.period},
                {
                    "$set": {
                        "company_id": company_id,
                        "period": request.period,
                        f"values.{request.subsection_id}.achievement": avg_score,
                        "updated_at": datetime.utcnow(),
                    },
                    "$setOnInsert": {"created_at": datetime.utcnow()},
                },
                upsert=True,
            )
                
    return {
        "message": "ORM sheet submitted successfully",
        "obtained_score": total_obtained,
        "max_score": total_max
    }
