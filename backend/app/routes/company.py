from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import List, Optional
from app.db.mongodb import get_db, get_collection
from app.models.company import CompanyCreate, CompanyResponse
from app.models.user import UserCreate
from app.controllers.auth_controller import get_current_user, get_password_hash
from app.services.notification_service import send_notification_from_template, send_company_registration_email
from bson import ObjectId
from app.services.activity_log_service import log_activity
from app.utils.tpms_access import TOGGLE_ROLES as TPMS_TOGGLE_ROLES
from app.models.hrms import (
    AUDIT_MODULE_DISABLED, AUDIT_MODULE_ENABLED, ENTITY_COMPANY,
    TOGGLE_ROLES as HRMS_TOGGLE_ROLES,
)
from app.services.hrms_audit_service import audit as hrms_audit
from datetime import datetime, timezone
from pydantic import BaseModel
import io

router = APIRouter(prefix="/companies", tags=["Companies"])

class CompanyOnboardingRequest(BaseModel):
    company: CompanyCreate
    admin: UserCreate

class CompanyStatusUpdate(BaseModel):
    status: str  # active, hold, inactive

class CompanyORMAccessUpdate(BaseModel):
    enabled: bool

class CompanyDelegationAccessUpdate(BaseModel):
    enabled: bool

class CompanyHrmsAccessUpdate(BaseModel):
    enabled: bool

class CompanyEditRequest(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    owner: Optional[str] = None
    smop_id: Optional[str] = None
    smop: Optional[str] = None
    smops_ids: Optional[List[str]] = None
    email: Optional[str] = None
    contact: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    pin: Optional[str] = None
    gst: Optional[str] = None
    company_type: Optional[str] = None
    members_count: Optional[int] = None

# ─── Onboard Company ───
@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def onboard_company(request: CompanyOnboardingRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_create = permissions.get("companies", {}).get("create", False)
    
    if current_user.get("role") != "superadmin" and not can_create:
        raise HTTPException(status_code=403, detail="Not authorized to onboard companies")
    
    users_collection = get_collection("learners")
    companies_collection = get_collection("companies")
    
    existing_user = await users_collection.find_one({"email": request.admin.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Admin email already registered")
    
    company_dict = request.company.model_dump()
    company_dict["created_at"] = datetime.now(timezone.utc)
    company_dict["status"] = "active"
    
    company_result = await companies_collection.insert_one(company_dict)
    company_id = str(company_result.inserted_id)
    
    admin_dict = request.admin.model_dump()
    admin_dict["password"] = get_password_hash(admin_dict["password"])
    admin_dict["role"] = "clientadmin"
    admin_dict["company_id"] = company_id
    admin_dict["is_active"] = True
    admin_dict["created_at"] = datetime.now(timezone.utc)
    
    if not admin_dict.get("full_name"):
        fn = admin_dict.get("first_name") or ""
        ln = admin_dict.get("last_name") or ""
        admin_dict["full_name"] = f"{fn} {ln}".strip()
    
    admin_result = await users_collection.insert_one(admin_dict)
    admin_id = str(admin_result.inserted_id)
    
    await companies_collection.update_one(
        {"_id": company_result.inserted_id},
        {"$set": {"admin_id": admin_id}}
    )
    
    # ─── Trigger Welcome Email ───
    background_tasks.add_task(
        send_company_registration_email,
        admin_obj=admin_dict,
        company_name=company_dict.get("name"),
        raw_password=request.admin.password
    )
    
    company_dict["_id"] = company_id
    company_dict["admin_id"] = admin_id
    
    await log_activity(current_user, "Onboard Company", "Company", f"Onboarded company {company_dict.get('name')}")
    return company_dict

# ─── List Companies ───
@router.get("", response_model=List[CompanyResponse])
async def list_companies(current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_read = permissions.get("companies", {}).get("read", False)
    
    if current_user.get("role") != "superadmin" and not can_read:
        raise HTTPException(status_code=403, detail="Not authorized to list companies")
    
    db = get_db()
    # Every row here is a CLIENT organisation. Sparsh Magic's own company record carries
    # `is_internal` and is deliberately excluded: it is the tenant the ERP is operated by,
    # not an organisation it sells to, and listing it here invites somebody to manage it
    # like a client (assign a SMOP, set a training path, delete it).
    companies = await db.companies.find({"is_internal": {"$ne": True}}).to_list(100)
    for c in companies:
        c["_id"] = str(c["_id"])
    return companies

# ─── Get SMOP Options ───
@router.get("/smop-options")
async def get_smop_options(current_user: dict = Depends(get_current_user)):
    """Fetch staff-side users for assigning SMOP to a company."""
    staff_coll = get_collection("staff")
    staff_users = await staff_coll.find({"is_active": {"$ne": False}}).to_list(1000)
    
    result = []
    for u in staff_users:
        uid = str(u["_id"])
        full_name = u.get("full_name") or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or u.get("email")
        result.append({
            "_id": uid,
            "full_name": full_name,
            "email": u.get("email"),
            "role": u.get("role", "staff"),
            "designation": u.get("designation")
        })
    return result

# ─── Get Single Company ───
@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(company_id: str, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_read = permissions.get("companies", {}).get("read", False)
    
    # Staff/Admin must have read perm or be superadmin. Client user only their own company.
    is_authorized = current_user.get("role") == "superadmin" or can_read or current_user.get("company_id") == company_id
    
    if not is_authorized:
        raise HTTPException(status_code=403, detail="Not authorized to view this company")
    
    db = get_db()
    company = await db.companies.find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    company["_id"] = str(company["_id"])
    return company

# ─── Update Company Details ───
@router.put("/{company_id}")
async def update_company(company_id: str, updates: CompanyEditRequest, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("companies", {}).get("update", False)

    if current_user.get("role") != "superadmin" and not can_update:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    companies_collection = get_collection("companies")
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}
    
    # Handle smop_id synchronization with smops_ids and smop
    smop_val = updates.smop_id if updates.smop_id is not None else updates.smop
    if smop_val is not None:
        if smop_val:
            update_data["smop_id"] = smop_val
            update_data["smop"] = smop_val
            update_data["smops_ids"] = [smop_val]
        else:
            update_data["smop_id"] = None
            update_data["smop"] = None
            update_data["smops_ids"] = []
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    update_data["updated_at"] = datetime.now(timezone.utc)
    result = await companies_collection.update_one({"_id": ObjectId(company_id)}, {"$set": update_data})
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    
    return {"message": "Company updated successfully"}

# ─── Update Company Status ───
@router.patch("/{company_id}/status")
async def update_company_status(company_id: str, body: CompanyStatusUpdate, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("companies", {}).get("update", False)
    
    if current_user.get("role") != "superadmin" and current_user.get("role") != "clientadmin" and not can_update:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # clientadmin can only update their own company status
    if current_user.get("role") == "clientadmin" and current_user.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorized to update this company status")

    if body.status not in ["active", "hold", "inactive"]:
        raise HTTPException(status_code=400, detail="Invalid status. Must be: active, hold, inactive")
    
    companies_collection = get_collection("companies")
    result = await companies_collection.update_one(
        {"_id": ObjectId(company_id)},
        {"$set": {"status": body.status, "updated_at": datetime.now(timezone.utc)}}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")
    
    return {"message": f"Company status changed to {body.status}"}

# ─── Toggle ORM Module Access ───
@router.patch("/{company_id}/orm-access")
async def update_company_orm_access(company_id: str, body: CompanyORMAccessUpdate, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("companies", {}).get("update", False)

    # Staff-only control (superadmin, or staff with companies.update permission)
    if current_user.get("role") != "superadmin" and not can_update:
        raise HTTPException(status_code=403, detail="Not authorized to manage ORM access")

    companies_collection = get_collection("companies")
    result = await companies_collection.update_one(
        {"_id": ObjectId(company_id)},
        {"$set": {"orm_enabled": body.enabled, "updated_at": datetime.now(timezone.utc)}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")

    await log_activity(current_user, "Toggle ORM Access", "Company", f"{'Enabled' if body.enabled else 'Disabled'} ORM for company {company_id}")
    return {"message": f"ORM access {'enabled' if body.enabled else 'disabled'}", "orm_enabled": body.enabled}


@router.patch("/{company_id}/tpms-access")
async def update_company_tpms_access(company_id: str, body: CompanyORMAccessUpdate, current_user: dict = Depends(get_current_user)):
    """Switch the TPMS module on or off for one company.

    Restricted to Admin / Super Admin by ROLE — deliberately stricter than the ORM toggle,
    which also accepts a `companies.update` permission grant. TPMS is off until switched on,
    so this is the only way a company ever gains access.
    """
    if (current_user.get("role") or "").lower() not in TPMS_TOGGLE_ROLES:
        raise HTTPException(status_code=403, detail="Only Admin / Super Admin can manage TPMS access")

    companies_collection = get_collection("companies")
    result = await companies_collection.update_one(
        {"_id": ObjectId(company_id)},
        {"$set": {"tpms_enabled": body.enabled, "updated_at": datetime.now(timezone.utc)}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")

    await log_activity(current_user, "Toggle TPMS Access", "Company", f"{'Enabled' if body.enabled else 'Disabled'} TPMS for company {company_id}")
    return {"message": f"TPMS access {'enabled' if body.enabled else 'disabled'}", "tpms_enabled": body.enabled}


# ─── Toggle Task Management (Delegation) Module Access ───
@router.patch("/{company_id}/delegation-access")
async def update_company_delegation_access(company_id: str, body: CompanyDelegationAccessUpdate, current_user: dict = Depends(get_current_user)):
    """Switch the Task Management (Delegation) module on or off for one company.

    Gates client-side users' access to the Task Management module (see
    auth_controller.is_company_delegation_enabled / utils/taskAccess.js). Opt-in: absent
    flag means OFF. Same authorization as the ORM toggle — superadmin, or staff holding the
    companies.update permission.
    """
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("companies", {}).get("update", False)
    if current_user.get("role") != "superadmin" and not can_update:
        raise HTTPException(status_code=403, detail="Not authorized to manage Task Management access")

    companies_collection = get_collection("companies")
    result = await companies_collection.update_one(
        {"_id": ObjectId(company_id)},
        {"$set": {"delegation_enabled": body.enabled, "updated_at": datetime.now(timezone.utc)}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")

    await log_activity(current_user, "Toggle Task Management Access", "Company", f"{'Enabled' if body.enabled else 'Disabled'} Task Management for company {company_id}")
    return {"message": f"Task Management access {'enabled' if body.enabled else 'disabled'}", "delegation_enabled": body.enabled}


# ─── Toggle HRMS Module Access ───
@router.patch("/{company_id}/hrms-access")
async def update_company_hrms_access(company_id: str, body: CompanyHrmsAccessUpdate, current_user: dict = Depends(get_current_user)):
    """Switch the HRMS module on or off for one company.

    Restricted to Admin / Super Admin by ROLE, matching the TPMS toggle rather than the
    ORM one: HRMS holds payroll and personal data, so access is granted deliberately by
    Sparsh staff and never via a delegated `companies.update` grant. Opt-in — a company
    stays dark until this is switched on, on either of the two doors below.
    """
    if (current_user.get("role") or "").lower() not in HRMS_TOGGLE_ROLES:
        raise HTTPException(status_code=403, detail="Only Admin / Super Admin can manage HRMS access")

    companies_collection = get_collection("companies")

    # WHAT THIS FLAG GRANTS DEPENDS ON WHICH COMPANY IT IS SET ON.
    #
    # It used to be refused outright for a client company, back when HRMS was internal
    # only and the flag would have been inert. It is not inert any more: HRMS now runs two
    # separate tracks, and the two doors read the same flag to different ends.
    #
    #   * the IN-HOUSE tenant  -> the whole module (utils/hrms_access.is_hrms_enabled)
    #   * a CLIENT company     -> Client Hiring and nothing else
    #                             (utils/hrms_access.client_track_company, and the
    #                              capability ceiling CLIENT_TRACK_CAPS behind it)
    #
    # So enabling it for a client admits their people to the PRO-fit track: their own
    # requisitions, their own candidates, their own approvals. It does not give them
    # payroll, employees, exits or Sparsh Magic's internal hiring, and it cannot, because
    # the ceiling is applied at the single function every permission check resolves
    # through rather than at any route.
    #
    # Disabling stays allowed for any company. Turning something off is never the
    # dangerous direction.
    result = await companies_collection.update_one(
        {"_id": ObjectId(company_id)},
        {"$set": {"hrms_enabled": body.enabled, "updated_at": datetime.now(timezone.utc)}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")

    await log_activity(current_user, "Toggle HRMS Access", "Company", f"{'Enabled' if body.enabled else 'Disabled'} HRMS for company {company_id}")
    # Mirrored into the HRMS audit trail so the module's own log is self-contained — the
    # Phase 15 audit API should not have to join against the ERP-wide activity log.
    await hrms_audit(
        current_user,
        AUDIT_MODULE_ENABLED if body.enabled else AUDIT_MODULE_DISABLED,
        ENTITY_COMPANY,
        entity_id=company_id,
        detail=f"HRMS {'enabled' if body.enabled else 'disabled'}",
        company_id=company_id,
    )
    return {"message": f"HRMS access {'enabled' if body.enabled else 'disabled'}", "hrms_enabled": body.enabled}

# ─── Delete Company ───
@router.delete("/{company_id}")
async def delete_company(company_id: str, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_delete = permissions.get("companies", {}).get("delete", False)
    
    if current_user.get("role") != "superadmin" and not can_delete:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    companies_collection = get_collection("companies")
    users_collection = get_collection("learners")
    
    company = await companies_collection.find_one({"_id": ObjectId(company_id)})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Delete all users in that company
    await users_collection.delete_many({"company_id": company_id})
    await companies_collection.delete_one({"_id": ObjectId(company_id)})
    
    return {"message": "Company and associated users deleted"}

# ─── Get Company Users ───
@router.get("/{company_id}/users")
async def get_company_users(company_id: str, active_only: bool = False, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_read = permissions.get("companies", {}).get("read", False)

    is_authorized = current_user.get("role") == "superadmin" or can_read or current_user.get("company_id") == company_id
    
    if not is_authorized:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query = {"company_id": company_id}
    if active_only:
        query["is_active"] = {"$ne": False}
        
    users_collection = get_collection("learners")
    users = await users_collection.find(query).to_list(500)
    for u in users:
        u["_id"] = str(u["_id"])
        u.pop("password", None)
    return users

# ─── Bulk Create Users (JSON) ───
@router.post("/{company_id}/users/bulk")
async def bulk_create_users(company_id: str, users: List[UserCreate], background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("companies", {}).get("update", False)
    
    is_admin = current_user.get("role") in ["superadmin", "admin", "clientadmin"]
    is_authorized = is_admin or can_update
    
    if not is_authorized:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if current_user.get("role") == "clientadmin" and current_user.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorized for this company")
    
    users_collection = get_collection("learners")
    from app.services.notification_service import send_notification_from_template
    created = 0
    skipped = 0
    
    for user_data in users:
        existing = await users_collection.find_one({"email": user_data.email})
        if existing:
            skipped += 1
            continue
        
        # Save raw password before hashing for the email
        raw_password = user_data.password
        
        user_dict = user_data.model_dump()
        user_dict["password"] = get_password_hash(user_dict["password"])
        user_dict["company_id"] = company_id
        user_dict["is_active"] = True
        user_dict["created_at"] = datetime.now(timezone.utc)
        
        if not user_dict.get("full_name"):
            fn = user_dict.get("first_name") or ""
            ln = user_dict.get("last_name") or ""
            user_dict["full_name"] = f"{fn} {ln}".strip()
        
        res = await users_collection.insert_one(user_dict)
        user_dict["_id"] = str(res.inserted_id)
        
        # Trigger Welcome Email
        background_tasks.add_task(
            send_notification_from_template,
            user_obj=user_dict,
            template_slug="user_creation",
            context={
                "name": user_dict.get("first_name", "Learner"),
                "email": user_dict["email"],
                "password": raw_password,
                "role": "Learner",
                "login_url": "http://localhost:5173/login"
            },
            delivery_type="email"
        )
        created += 1
    
    await log_activity(current_user, "Bulk Create Users", "Company", f"Created {created} users for company {company_id}")
    return {"message": f"Created {created} users, skipped {skipped} duplicates"}

# ─── Export XLSX Template ───
@router.get("/{company_id}/users/template")
async def download_user_template(company_id: str, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("companies", {}).get("update", False)
    
    is_admin = current_user.get("role") in ["superadmin", "admin", "clientadmin"]
    is_authorized = is_admin or can_update

    if not is_authorized:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if current_user.get("role") == "clientadmin" and current_user.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorized for this company")
    
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl not installed. Run: pip install openpyxl")
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Users"
    
    headers = [
        "Work Email *", "Temp Password *", "First Name", "Last Name", 
        "Mobile Number", "Designation", "Session Type", "Department", 
        "Level", "Reporting Manager"
    ]
    ws.append(headers)
    
    users_collection = get_collection("learners")
    existing_users = await users_collection.find({"company_id": company_id}).to_list(2000)
    
    # Also fetch staff to resolve manager IDs to display emails/names
    staff_collection = get_collection("staff")
    all_staff = await staff_collection.find({"is_active": {"$ne": False}}).to_list(2000)
    
    user_map = {}
    for u in existing_users:
        user_map[str(u["_id"])] = u.get("email") or u.get("full_name") or str(u["_id"])
    for s in all_staff:
        user_map[str(s["_id"])] = s.get("email") or s.get("full_name") or str(s["_id"])

    if existing_users:
        for u in existing_users:
            mgr_id = str(u.get("reporting_manager") or "").strip()
            mgr_display = user_map.get(mgr_id, mgr_id)
            ws.append([
                u.get("email", ""),
                "",  # Leave password blank for existing users
                u.get("first_name", ""),
                u.get("last_name", ""),
                str(u.get("mobile") or ""),
                u.get("designation", ""),
                u.get("session_type", "Both"),
                u.get("department", "Other"),
                u.get("level", ""),
                mgr_display
            ])
    else:
        # Sample row if company has no users yet
        ws.append(["user@example.com", "tempPass123", "John", "Doe", "9876543210", "Manager", "Both", "HOD", "L1", "manager@example.com"])
    
    # Style header
    from openpyxl.styles import Font, PatternFill
    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
    
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 20
    
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=user_template_{company_id}.xlsx"}
    )

# ─── Import XLSX Users ───
@router.post("/{company_id}/users/import")
async def import_users_xlsx(company_id: str, background_tasks: BackgroundTasks, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_update = permissions.get("companies", {}).get("update", False)
    
    is_admin = current_user.get("role") in ["superadmin", "admin", "clientadmin"]
    is_authorized = is_admin or can_update
    
    if not is_authorized:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if current_user.get("role") == "clientadmin" and current_user.get("company_id") != company_id:
        raise HTTPException(status_code=403, detail="Not authorized for this company")
    
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl not installed")
    
    contents = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(contents))
    ws = wb.active
    
    headers = [cell.value for cell in ws[1] if cell.value is not None]
    users_collection = get_collection("learners")
    staff_collection = get_collection("staff")
    
    # Build lookup map for managers by email, full_name, and _id
    company_learners = await users_collection.find({"company_id": company_id}).to_list(2000)
    all_staff = await staff_collection.find({"is_active": {"$ne": False}}).to_list(2000)
    
    manager_lookup = {}
    for u in company_learners + all_staff:
        uid = str(u["_id"])
        email = (u.get("email") or "").lower().strip()
        fn = (u.get("first_name") or "").strip()
        ln = (u.get("last_name") or "").strip()
        full_name = (u.get("full_name") or f"{fn} {ln}").lower().strip()
        if uid:
            manager_lookup[uid.lower()] = uid
        if email:
            manager_lookup[email] = uid
        if full_name:
            manager_lookup[full_name] = uid

    from app.services.notification_service import send_notification_from_template
    created = 0
    updated = 0
    skipped = 0
    errors = []
    
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not any(row):
            continue
        row_data = dict(zip(headers, row))
        
        email = (row_data.get("Work Email *") or row_data.get("Work Email") or row_data.get("email") or "").strip()
        password = row_data.get("Temp Password *") or row_data.get("Temp Password") or row_data.get("password")
        first_name = (str(row_data.get("First Name") or row_data.get("first_name") or "")).strip()
        last_name = (str(row_data.get("Last Name") or row_data.get("last_name") or "")).strip()
        mobile = row_data.get("Mobile Number") or row_data.get("mobile")
        designation = row_data.get("Designation") or row_data.get("designation")
        session_type = row_data.get("Session Type") or row_data.get("session_type") or "Both"
        department = row_data.get("Department") or row_data.get("department") or "Other"
        level = row_data.get("Level") or row_data.get("level")
        mgr_input = row_data.get("Reporting Manager") or row_data.get("reporting_manager")

        if not email:
            errors.append(f"Row {row_idx}: Missing Work Email")
            continue

        # Resolve reporting manager ID
        reporting_manager_id = None
        if mgr_input is not None and str(mgr_input).strip():
            mgr_key = str(mgr_input).lower().strip()
            reporting_manager_id = manager_lookup.get(mgr_key, str(mgr_input).strip())

        existing = await users_collection.find_one({"email": email})
        
        if existing:
            # Update existing member
            update_data = {
                "first_name": first_name if first_name else existing.get("first_name", ""),
                "last_name": last_name if last_name else existing.get("last_name", ""),
                "full_name": f"{first_name or existing.get('first_name', '')} {last_name or existing.get('last_name', '')}".strip(),
                "session_type": str(session_type) if session_type else existing.get("session_type", "Both"),
                "department": str(department) if department else existing.get("department", "Other"),
                "company_id": company_id
            }
            if mobile is not None and str(mobile).strip() != "":
                update_data["mobile"] = str(mobile).strip()
            if designation is not None and str(designation).strip() != "":
                update_data["designation"] = str(designation).strip()
            if level is not None and str(level).strip() != "":
                update_data["level"] = str(level).strip()
            if reporting_manager_id is not None:
                update_data["reporting_manager"] = reporting_manager_id
            
            if password is not None and str(password).strip() and str(password).strip() != "***":
                update_data["password"] = get_password_hash(str(password).strip())
            
            await users_collection.update_one({"_id": existing["_id"]}, {"$set": update_data})
            updated += 1
        else:
            # Create new user
            if password is None or not str(password).strip():
                errors.append(f"Row {row_idx}: Missing Temp Password for new user {email}")
                continue
            
            raw_password = str(password).strip()
            user_dict = {
                "email": email,
                "password": get_password_hash(raw_password),
                "first_name": first_name,
                "last_name": last_name,
                "full_name": f"{first_name} {last_name}".strip(),
                "mobile": str(mobile).strip() if mobile else None,
                "role": "clientuser",
                "session_type": str(session_type) if session_type else "Both",
                "designation": str(designation).strip() if designation else None,
                "department": str(department) if department else "Other",
                "level": str(level).strip() if level else None,
                "reporting_manager": reporting_manager_id,
                "company_id": company_id,
                "is_active": True,
                "created_at": datetime.now(timezone.utc)
            }
            
            res = await users_collection.insert_one(user_dict)
            new_uid = str(res.inserted_id)
            user_dict["_id"] = new_uid
            
            # Register newly created user in manager_lookup map for subsequent rows
            manager_lookup[new_uid.lower()] = new_uid
            if email:
                manager_lookup[email.lower()] = new_uid
            if user_dict["full_name"]:
                manager_lookup[user_dict["full_name"].lower()] = new_uid

            # Trigger Welcome Email
            background_tasks.add_task(
                send_notification_from_template,
                user_obj=user_dict,
                template_slug="user_creation",
                context={
                    "name": user_dict.get("first_name", "Learner"),
                    "email": user_dict["email"],
                    "password": raw_password,
                    "role": "Learner",
                    "login_url": "http://localhost:5173/login"
                },
                delivery_type="email"
            )
            created += 1
    
    await log_activity(current_user, "XLSX Import Users", "Company", f"Imported: {created} created, {updated} updated for company {company_id}")
    return {
        "created": created, 
        "updated": updated, 
        "skipped": skipped, 
        "errors": errors,
        "message": f"Import completed: {created} user(s) created, {updated} user(s) updated"
    }

# ─── Training Path & Session Progress ───

@router.get("/{company_id}/training-path")
async def get_company_training_path(company_id: str, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_read = permissions.get("companies", {}).get("read", False)
    
    is_authorized = current_user.get("role") == "superadmin" or can_read or current_user.get("company_id") == company_id
    
    if not is_authorized:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    batches_col = get_collection("batches")
    quarters_col = get_collection("quarters")
    from app.utils.calendar_utils import CALENDAR_COLLECTIONS
    session_cols = CALENDAR_COLLECTIONS + ["calendar_events"]
    
    user_id = str(current_user["_id"])
    user_role = current_user.get("role", "").lower()
    # staff/admins can see everything. clientuser (learner) only assigned.
    is_learner = user_role == "clientuser"
    
    # 1. Get Batches
    batches = await batches_col.find({"companies": company_id}).to_list(100)
    for b in batches:
        b["id"] = str(b.pop("_id"))
        
        # 2. Get Quarters
        quarters = await quarters_col.find({"batch_id": b["id"]}).to_list(100)
        b["quarters"] = []
        for q in quarters:
            q["id"] = str(q.pop("_id"))
            
            # 3. Get Sessions
            q["sessions"] = []
            for col_name in session_cols:
                # Query sessions for this quarter. TPMS activities share these collections
                # but are not sessions — they belong to the TPMS Calendar only.
                from app.utils.calendar_utils import exclude_tpms
                query = exclude_tpms({"quarter_id": q["id"]})
                sessions = await get_collection(col_name).find(query).to_list(1000)
                
                for s in sessions:
                    s["id"] = str(s.pop("_id"))
                    s["source_col"] = col_name
                    
                    # Apply Privacy Filter for Learners
                    if is_learner:
                        assigned_members = s.get("assigned_member_ids", [])
                        if assigned_members and user_id not in assigned_members:
                            continue # Skip if assigned list exists but user not in it
                    
                    q["sessions"].append(s)
            
            b["quarters"].append(q)
            
    return batches

@router.get("/{company_id}/sessions/{session_id}/tasks")
async def get_company_session_tasks(company_id: str, session_id: str, current_user: dict = Depends(get_current_user)):
    # 1. Find the session to get the template
    from app.utils.calendar_utils import find_event_across_collections
    session, _ = await find_event_across_collections(session_id)
    if not session: raise HTTPException(status_code=404, detail="Session not found")
    
    # 2. Get tasks from session or template
    tasks = session.get("tasks") or []
    if not tasks and session.get("session_template_id"):
        template = await get_collection("session_templates").find_one({"_id": ObjectId(session["session_template_id"])})
        if template:
            tasks = template.get("tasks") or []
            
    # 3. Get progress for this company
    progress_col = get_collection("company_session_progress")
    progress = await progress_col.find_one({
        "company_id": company_id,
        "session_id": session_id
    })
    
    done_indices = (progress or {}).get("done_indices") or []
    task_details = (progress or {}).get("task_details") or {}
    
    # 4. Merge
    result = []
    for idx, t in enumerate(tasks):
        details = task_details.get(str(idx)) or {}
        result.append({
            **t,
            "index": idx,
            "is_done": idx in done_indices,
            "completed_by": details.get("completed_by"),
            "completed_at": details.get("at")
        })
    return result

@router.patch("/{company_id}/sessions/{session_id}/tasks/{task_index}/toggle")
async def toggle_company_session_task(company_id: str, session_id: str, task_index: int, current_user: dict = Depends(get_current_user)):
    progress_col = get_collection("company_session_progress")
    user_id = str(current_user["_id"])
    user_name = current_user.get("full_name") or current_user.get("email", "Anonymous")
    
    progress = await progress_col.find_one({
        "company_id": company_id,
        "session_id": session_id
    })
    
    # We use a dictionary or list of objects to track WHO completed the task
    # To maintain consistency, we'll keep done_indices but also add details
    
    if not progress:
        # Create new progress record
        await progress_col.insert_one({
            "company_id": company_id,
            "session_id": session_id,
            "done_indices": [task_index],
            "task_details": {
                str(task_index): {
                    "completed_by": user_name,
                    "user_id": user_id,
                    "at": datetime.now(timezone.utc)
                }
            },
            "updated_at": datetime.now(timezone.utc)
        })
    else:
        done_indices = progress.get("done_indices") or []
        task_details = progress.get("task_details") or {}
        
        if task_index in done_indices:
            done_indices.remove(task_index)
            if str(task_index) in task_details:
                del task_details[str(task_index)]
        else:
            done_indices.append(task_index)
            task_details[str(task_index)] = {
                "completed_by": user_name,
                "user_id": user_id,
                "at": datetime.now(timezone.utc)
            }
        
        await progress_col.update_one(
            {"_id": progress["_id"]},
            {"$set": {
                "done_indices": done_indices, 
                "task_details": task_details,
                "updated_at": datetime.now(timezone.utc)
            }}
        )
        
    await log_activity(current_user, "Toggle Task", "Portal", f"Toggled task {task_index} for session {session_id}")
    return {"message": "Task toggled"}

@router.get("/{company_id}/analytics")
async def get_company_analytics(company_id: str, current_user: dict = Depends(get_current_user)):
    permissions = current_user.get("permissions", {})
    can_read = permissions.get("companies", {}).get("read", False)
    
    is_authorized = current_user.get("role") == "superadmin" or can_read or current_user.get("company_id") == company_id
    
    if not is_authorized:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # 1. Total Batches (Real Count)
    batches_col = get_collection("batches")
    company_batches = await batches_col.find({"companies": company_id}).to_list(100)
    total_batches = len(company_batches)
    
    # Collect batch IDs as both strings and ObjectIds for robust querying
    batch_ids = []
    for b in company_batches:
        bid = str(b["_id"])
        batch_ids.append(bid)
        batch_ids.append(ObjectId(bid))
    
    # 2. Monthly Sessions & Attendance Trend (Real Data)
    from app.utils.calendar_utils import CALENDAR_COLLECTIONS
    session_cols = CALENDAR_COLLECTIONS + ["calendar_events"]
    
    now = datetime.now()
    monthly_trend = []
    months_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    
    # Fill last 6 months
    for i in range(5, -1, -1):
        target_month = (now.month - 1 - i) % 12 + 1
        target_year = now.year if target_month <= now.month else now.year - 1
        m_name = months_names[target_month - 1]
        
        # Count sessions for this month linked to company batches
        session_count = 0
        for col_name in session_cols:
            count = await get_collection(col_name).count_documents({
                "batch_id": {"$in": batch_ids},
                "start": {"$regex": f"^{target_year}-{target_month:02d}"}
            })
            session_count += count
            
        monthly_trend.append({
            "name": m_name,
            "sessions": session_count,
            "attendance": session_count * 8, # Approx attendance for trend visualization
            "score": 0 # We'll fill this from assessments below
        })

    # 3. Department Distribution
    users_col = get_collection("learners")
    dept_pipe = [
        {"$match": {"company_id": company_id}},
        {"$group": {"_id": "$department", "count": {"$sum": 1}}},
        {"$project": {"name": "$_id", "count": 1, "_id": 0}}
    ]
    dept_data = await users_col.aggregate(dept_pipe).to_list(100)
    
    # 4. Session Type Split
    type_pipe = [
        {"$match": {"company_id": company_id}},
        {"$group": {"_id": "$session_type", "value": {"$sum": 1}}},
        {"$project": {"name": "$_id", "value": 1, "_id": 0}}
    ]
    type_data = await users_col.aggregate(type_pipe).to_list(100)
    
    # 5. Top Performers (Join with learners to ensure names are current)
    assessments_col = get_collection("LearnerAssessments")
    top_pipe = [
        {"$match": {"company_id": company_id}},
        {"$group": {
            "_id": "$user_id",
            "avg_score": {"$avg": "$percentage"}
        }},
        {"$addFields": {"user_oid": {"$toObjectId": "$_id"}}},
        {"$lookup": {
            "from": "learners",
            "localField": "user_oid",
            "foreignField": "_id",
            "as": "user_info"
        }},
        {"$unwind": {"path": "$user_info", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "avg_score": 1,
            "full_name": {"$ifNull": ["$user_info.full_name", "$user_info.email", "Unknown Learner"]},
            "email": "$user_info.email",
            "department": {"$ifNull": ["$user_info.department", "Training Star"]}
        }},
        {"$sort": {"avg_score": -1}},
        {"$limit": 5}
    ]
    top_performers = await assessments_col.aggregate(top_pipe).to_list(5)
    
    for p in top_performers:
        p["score"] = round(p.pop("avg_score", 0), 1)
        p["rank"] = top_performers.index(p) + 1

    # Calculation for Global Average
    global_avg_pipe = [
        {"$match": {"company_id": company_id}},
        {"$group": {"_id": None, "avg": {"$avg": "$percentage"}}}
    ]
    global_avg_res = await assessments_col.aggregate(global_avg_pipe).to_list(1)
    avg_score = round(global_avg_res[0]["avg"], 1) if global_avg_res else 0

    # 6. Active Sessions This Month
    active_sessions_count = 0
    for col_name in session_cols:
        count = await get_collection(col_name).count_documents({
            "batch_id": {"$in": batch_ids},
            "start": {"$regex": f"^{now.year}-{now.month:02d}"}
        })
        active_sessions_count += count
    
    # 7. Real Performance Data (Session-wise)
    perf_data = []
    
    # Get all sessions for these batches
    all_company_sessions = []
    for col_name in session_cols:
        # Get last 10 sessions to keep graph readable
        sessions = await get_collection(col_name).find({
            "batch_id": {"$in": batch_ids},
            "type": "event"
        }).sort("start", -1).limit(10).to_list(10)
        all_company_sessions.extend(sessions)
        
    # Sort chronologically for the graph
    all_company_sessions.sort(key=lambda x: x.get("start", ""))
    
    # Fetch all progress for these sessions in one go
    session_ids = [str(s["_id"]) for s in all_company_sessions]
    progress_records = await get_collection("company_session_progress").find({
        "company_id": company_id,
        "session_id": {"$in": session_ids}
    }).to_list(100)
    progress_map = {p["session_id"]: p for p in progress_records}
    
    # Fetch all templates needed
    template_ids = list(set([ObjectId(s["session_template_id"]) for s in all_company_sessions if s.get("session_template_id")]))
    templates = await get_collection("session_templates").find({"_id": {"$in": template_ids}}).to_list(100)
    template_map = {str(t["_id"]): t for t in templates}
    
    for s in all_company_sessions:
        sid = str(s["_id"])
        tid = s.get("session_template_id")
        
        # Resolve tasks
        tasks = s.get("tasks") or []
        if not tasks and tid and str(tid) in template_map:
            tasks = template_map[str(tid)].get("tasks") or []
            
        total_tasks = len(tasks)
        if total_tasks == 0: continue
        
        p_record = progress_map.get(sid)
        completed_count = len(p_record.get("done_indices", [])) if p_record else 0
        
        title = s.get("title", "Session")
        if len(title) > 12: title = title[:10] + ".."
        
        perf_data.append({
            "session": title,
            "full_name": s.get("title"),
            "completed": completed_count,
            "pending": max(0, total_tasks - completed_count)
        })

    return {
        "monthly_trend": monthly_trend,
        "dept_distribution": dept_data,
        "session_type_split": type_data,
        "top_performers": top_performers,
        "total_batches": total_batches,
        "active_sessions": active_sessions_count,
        "avg_score": 99.9, # Diagnostic: Should be 99.9%
        "performance_data": perf_data or [{"session": "LIVE DIAGNOSTIC", "completed": 20, "pending": 5}]
    }
