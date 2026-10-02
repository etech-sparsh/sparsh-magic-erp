from fastapi import APIRouter, Depends, HTTPException
from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection
from app.utils.orm_utils import ensure_orm_enabled
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from bson import ObjectId

# Separate prefix (not under /orm) so it never collides with the greedy
# GET /orm/{company_id} route.
router = APIRouter(prefix="/orm-target-requests", tags=["ORM Target Requests"])

ALLOWED_FIELDS = {"target", "achievement"}
STAFF_ROLES = {"superadmin", "admin"}


class TargetChangeItem(BaseModel):
    parameter_id: str
    subsection_id: str
    field: str = "target"  # "target" | "achievement"
    parameter_name: Optional[str] = ""
    subsection_name: Optional[str] = ""
    current_value: Optional[float] = None
    requested_value: float


class TargetRequestCreate(BaseModel):
    period: str
    reason: str
    changes: List[TargetChangeItem]


class TargetRequestReview(BaseModel):
    action: str  # "approve" | "reject"
    note: Optional[str] = ""


def _serialize(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    return doc


@router.post("")
async def create_request(payload: TargetRequestCreate, current_user: dict = Depends(get_current_user)):
    role = current_user.get("role")
    if role not in ["clientadmin", "superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized to raise ORM target requests")

    company_id = current_user.get("company_id")
    if not company_id:
        raise HTTPException(status_code=400, detail="No company is associated with this account")

    await ensure_orm_enabled(current_user, company_id)

    if not payload.changes:
        raise HTTPException(status_code=400, detail="At least one target change is required")
    for c in payload.changes:
        if c.field not in ALLOWED_FIELDS:
            raise HTTPException(status_code=400, detail=f"Invalid field '{c.field}'")
    if not payload.reason.strip():
        raise HTTPException(status_code=400, detail="A reason is required for the change request")

    doc = {
        "company_id": company_id,
        "period": payload.period,
        "reason": payload.reason.strip(),
        "changes": [c.model_dump() for c in payload.changes],
        "status": "pending",
        "requested_by": str(current_user.get("_id")),
        "requested_by_name": current_user.get("name") or current_user.get("email") or "Client Admin",
        "created_at": datetime.utcnow(),
        "reviewed_by": None,
        "reviewed_by_name": None,
        "reviewed_at": None,
        "review_note": "",
    }
    res = await get_collection("ORM_Target_Requests").insert_one(doc)
    return {"message": "Target change request submitted for approval", "request": _serialize({**doc, "_id": res.inserted_id})}


@router.get("")
async def list_requests(
    company_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    role = current_user.get("role")
    query: dict = {}
    if role in STAFF_ROLES:
        # Staff can scope to a specific company or see everything.
        if company_id:
            query["company_id"] = company_id
    else:
        # Client-side users only ever see their own company's requests.
        query["company_id"] = current_user.get("company_id")

    if status_filter:
        query["status"] = status_filter

    cursor = get_collection("ORM_Target_Requests").find(query).sort("created_at", -1)
    docs = await cursor.to_list(length=500)
    return {"requests": [_serialize(d) for d in docs]}


async def _apply_change(company_id: str, period: str, change: dict):
    """Write an approved change into the live config and, for monthly periods,
    the month-partitioned snapshot — mirroring how save_orm / the sheet persist."""
    parameter_id = change.get("parameter_id")
    subsection_id = change.get("subsection_id")
    field = change.get("field", "target")
    value = change.get("requested_value")
    if field not in ALLOWED_FIELDS:
        return

    configs_col = get_collection("ORM_Configs")
    orm = await configs_col.find_one({"company_id": company_id})
    if orm:
        parameters = orm.get("parameters", [])
        updated = False
        for p in parameters:
            if p.get("id") == parameter_id:
                for s in p.get("subsections", []):
                    if s.get("id") == subsection_id:
                        s[field] = value
                        updated = True
                        break
            if updated:
                break
        if updated:
            await configs_col.update_one(
                {"company_id": company_id},
                {"$set": {"parameters": parameters, "updated_at": datetime.utcnow()}},
            )

    if isinstance(period, str) and len(period) == 7 and period[4] == "-":
        await get_collection("ORM_Monthly").update_one(
            {"company_id": company_id, "period": period},
            {
                "$set": {
                    "company_id": company_id,
                    "period": period,
                    f"values.{subsection_id}.{field}": value,
                    "updated_at": datetime.utcnow(),
                },
                "$setOnInsert": {"created_at": datetime.utcnow()},
            },
            upsert=True,
        )


@router.post("/{request_id}/review")
async def review_request(request_id: str, payload: TargetRequestReview, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Only staff (superadmin/admin) can review target requests")
    if payload.action not in ["approve", "reject"]:
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")

    try:
        oid = ObjectId(request_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request id")

    col = get_collection("ORM_Target_Requests")
    doc = await col.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")
    if doc.get("status") != "pending":
        raise HTTPException(status_code=400, detail=f"Request already {doc.get('status')}")

    if payload.action == "approve":
        for change in doc.get("changes", []):
            await _apply_change(doc["company_id"], doc.get("period"), change)
        new_status = "approved"
    else:
        new_status = "rejected"

    await col.update_one(
        {"_id": oid},
        {"$set": {
            "status": new_status,
            "reviewed_by": str(current_user.get("_id")),
            "reviewed_by_name": current_user.get("name") or current_user.get("email") or "Staff",
            "reviewed_at": datetime.utcnow(),
            "review_note": payload.note or "",
        }},
    )
    updated = await col.find_one({"_id": oid})
    return {"message": f"Request {new_status}", "request": _serialize(updated)}
