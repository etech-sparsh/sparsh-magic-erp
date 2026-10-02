from fastapi import APIRouter, Depends, HTTPException, status
from app.models.orm import ORMCreateRequest
from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection
from app.utils.orm_utils import sync_orm_to_calendar, ensure_orm_enabled
from bson import ObjectId
from datetime import datetime
from typing import List

router = APIRouter(prefix="/orm", tags=["ORM"])

# Fields that vary month-to-month. Structure (names, weightages, audit config,
# assignedUsers, frequency, etc.) is shared and always read from ORM_Configs;
# only these per-subsection values are partitioned by month in ORM_Monthly.
MONTHLY_VALUE_FIELDS = [
    "target", "achievement", "unitName", "remarks",
    "googleSheetLink", "googleFormLink", "surveyDoerName", "surveyDoerEmail",
    "auditChecklist", "teamEngagementChecklist", "budgetAdherenceChecklist",
]


def _current_period() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def _in_target_window(now: datetime = None) -> bool:
    """Target/achievement edits are only allowed inside the monthly window that
    opens on the 25th and closes on the 10th of the following month."""
    now = now or datetime.utcnow()
    return now.day >= 25 or now.day <= 10


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _target_or_achievement_changed(prior_params, new_params) -> bool:
    """True if any subsection's target or achievement value differs from what is
    stored (or a new subsection introduces a non-zero value)."""
    prior = {}
    for p in prior_params or []:
        for s in p.get("subsections", []):
            prior[(p.get("id"), s.get("id"))] = s

    for p in new_params or []:
        for s in p.get("subsections", []):
            key = (p.get("id"), s.get("id"))
            old = prior.get(key)
            if old is None:
                if _num(s.get("target")) != 0 or _num(s.get("achievement")) != 0:
                    return True
                continue
            if _num(s.get("target")) != _num(old.get("target")):
                return True
            if _num(s.get("achievement")) != _num(old.get("achievement")):
                return True
    return False


def _overlay_values(parameters, values, fields=None):
    """Overlay month-specific values from `values` (a {subsection_id: {...}} map)
    onto the shared structure in-place."""
    fields = fields or MONTHLY_VALUE_FIELDS
    for p in parameters:
        for s in p.get("subsections", []):
            mv = values.get(s.get("id"))
            if not mv:
                continue
            for f in fields:
                if f in mv and mv[f] is not None:
                    s[f] = mv[f]


def _reset_achievements(parameters):
    for p in parameters:
        for s in p.get("subsections", []):
            s["achievement"] = 0

def _extract_monthly_values(parameters):
    """Pull the per-month value fields out of a full parameters list into a
    {subsection_id: {field: value}} map for storage in ORM_Monthly."""
    values = {}
    for p in parameters:
        for s in p.get("subsections", []):
            sid = s.get("id")
            if sid is None:
                continue
            values[sid] = {f: s.get(f) for f in MONTHLY_VALUE_FIELDS if f in s}
    return values


async def _upsert_monthly(company_id: str, period: str, parameters):
    monthly_col = get_collection("ORM_Monthly")
    await monthly_col.update_one(
        {"company_id": company_id, "period": period},
        {
            "$set": {
                "company_id": company_id,
                "period": period,
                "values": _extract_monthly_values(parameters),
                "updated_at": datetime.utcnow(),
            },
            "$setOnInsert": {"created_at": datetime.utcnow()},
        },
        upsert=True,
    )


@router.post("")
async def save_orm(request: ORMCreateRequest, current_user: dict = Depends(get_current_user)):
    # Only clientadmin or admin can save the ORM configuration for their company
    if current_user.get("role") not in ["superadmin", "admin", "clientadmin"]:
        raise HTTPException(status_code=403, detail="Not authorized to design ORM")

    # Block client-side saves when ORM is disabled for the company.
    await ensure_orm_enabled(current_user, request.company_id)

    # Only the current month is editable; past months are read-only history.
    period = request.period or _current_period()
    if period != _current_period():
        raise HTTPException(status_code=403, detail="Past months are read-only and cannot be modified")

    col = get_collection("ORM_Configs")

    orm_data = request.model_dump()
    orm_data.pop("period", None)
    orm_data["updated_at"] = datetime.utcnow()

    # Check if ORM already exists for this company
    existing = await col.find_one({"company_id": request.company_id})

    # Client admins may only change target/achievement VALUES while the target
    # window is open (25th → 10th). Structural edits (weightages, assignments,
    # checklists, frequency) stay editable. Staff (superadmin/admin) bypass this
    # to handle exceptions and to apply approved change requests.
    if current_user.get("role") == "clientadmin" and not _in_target_window():
        prior_params = existing.get("parameters", []) if existing else []
        if _target_or_achievement_changed(prior_params, orm_data.get("parameters", [])):
            raise HTTPException(
                status_code=403,
                detail="Target window is closed. Targets and achievements can only be changed from the 25th to the 10th of each month. Submit a target-change request for staff approval.",
            )

    if existing:
        await col.update_one(
            {"company_id": request.company_id},
            {"$set": orm_data}
        )
    else:
        orm_data["created_at"] = datetime.utcnow()
        await col.insert_one(orm_data)

    # Persist this month's values separately so each month keeps its own snapshot.
    await _upsert_monthly(request.company_id, period, orm_data["parameters"])

    # Sync to calendar
    await sync_orm_to_calendar(request.company_id, orm_data["parameters"], str(current_user["_id"]))
    return {"message": "ORM saved successfully", "period": period}

@router.get("/{company_id}")
async def get_orm(company_id: str, period: str = None, current_user: dict = Depends(get_current_user)):
    # Client-side users can't read ORM for a company that has it disabled (staff bypass).
    await ensure_orm_enabled(current_user, company_id)

    col = get_collection("ORM_Configs")
    orm = await col.find_one({"company_id": company_id})

    if not orm:
        return {"parameters": [], "message": "No ORM found"}

    orm["_id"] = str(orm["_id"])

    period = period or _current_period()
    current_period = _current_period()
    parameters = orm.get("parameters", [])

    monthly_col = get_collection("ORM_Monthly")
    monthly = await monthly_col.find_one({"company_id": company_id, "period": period})

    if monthly:
        # This month already has its own saved snapshot.
        _overlay_values(parameters, monthly.get("values", {}))
        orm["has_month_data"] = True
    else:
        # No snapshot yet for this period. Carry forward the most recent prior
        # month's values (with achievements cleared), else fall back to the
        # config's embedded values as-is (legacy / first month).
        prior = await monthly_col.find_one(
            {"company_id": company_id, "period": {"$lt": period}},
            sort=[("period", -1)],
        )
        if prior:
            _overlay_values(parameters, prior.get("values", {}))
            _reset_achievements(parameters)
        orm["has_month_data"] = False

    orm["period"] = period
    orm["is_current_period"] = period == current_period
    orm["target_window_open"] = _in_target_window()
    orm["parameters"] = parameters
    return orm
