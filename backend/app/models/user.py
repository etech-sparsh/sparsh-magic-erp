from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime
from enum import Enum

class UserRole(str, Enum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    CLIENTADMIN = "clientadmin"
    CLIENTUSER = "clientuser"
    CUSTOM = "custom"

class UserBase(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None # Derivable or stored
    mobile: Optional[str] = None
    role: str = "clientuser"
    company_id: Optional[str] = None
    is_active: bool = True
    tag: Optional[str] = None  # "staff" or "learner"

    # Business specific fields
    session_type: Optional[str] = "None" # Core, Support, Both, None
    designation: Optional[str] = None
    department: Optional[str] = "Other" # HOD, Manager, Implementor, EA, MD, HR, Other
    # Leadership Score eligibility. "Applicable from L4 (Asst Managers) and above."
    #
    # Explicit, and deliberately NOT derived from `designation`: that field is free text,
    # so "Sr. Manager" and "Senior Manager" would land on different levels — or on none —
    # and a leader would silently drop out of a cycle with nothing on screen to say why.
    # Optional with a None default, so no existing user record changes meaning.
    leadership_level: Optional[str] = None  # "L4" | "L5" | "L6" | "L7"

    # Profile / HR fields (self-editable via PATCH /users/me — see user.py)
    emergency_mobile: Optional[str] = None
    reporting_manager: Optional[str] = None
    joining_date: Optional[str] = None  # ISO "YYYY-MM-DD"
    level: Optional[str] = None
    
    # Highly Granular CRUD Permissions
    permissions: dict = {
        "batches": {"create": False, "read": True, "update": False, "delete": False},
        "calendar": {"create": False, "read": True, "update": False, "delete": False},
        "users": {"create": False, "read": True, "update": False, "delete": False},
        "companies": {"create": False, "read": True, "update": False, "delete": False},
        "logs": {"create": False, "read": True, "update": False, "delete": False},
        "templates": {"create": False, "read": True, "update": False, "delete": False},
        "forms": {"create": False, "read": True, "update": False, "delete": False}
    }

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: str = Field(alias="_id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    orm_enabled: Optional[bool] = True  # Company-level ORM module access
    tpms_enabled: Optional[bool] = False  # Company-level TPMS module access (opt-in)
    # Company-level Task & Delegation access (opt-in). MUST be declared here: GET /users/me is
    # served through this response_model, and FastAPI drops any field the model does not
    # declare. Without it the value routes/user.py sets from the company record was silently
    # stripped from the payload, so `user.delegation_enabled` was undefined on the client and
    # utils/taskAccess.canAccessTaskManagement hid the module for every company user however
    # the company toggle was set.
    delegation_enabled: Optional[bool] = False
    # No leadership flag: Leadership Score follows `tpms_enabled`, so the client gates it
    # on the TPMS flag it already receives.

    hrms_enabled: Optional[bool] = False  # Company-level HRMS module access (opt-in)
    # Client Hiring access, the OTHER half of the HRMS toggle. `hrms_enabled` is only true
    # for the in-house tenant (it requires `is_internal`), so a client company's user must
    # be told about their own track separately or the module is invisible to them however
    # the company toggle is set. Third time this class has dropped a flag; see below.
    client_hiring_enabled: Optional[bool] = False

    # The client-side governance ladder (MD > HR > HOD > IMPLEMENTOR) that
    # auth_controller.client_rank already uses server-side. Declared here so it survives
    # response_model serialisation and reaches the client — HRMS maps it to an HRMS role
    # in features/hrms/access.js, and it must agree with the server's utils/hrms_access.py.
    #
    # Every module flag the frontend gates on has to be listed on this class. The same
    # omission has now bitten three times: the original `delegation_enabled` bug above;
    # then when these HRMS lines were dropped, leaving `hrmsAccessState()` permanently
    # 'unknown' and degrading every client user to the EMPLOYEE role; and again with
    # `client_hiring_enabled`, which routes/user.py set correctly while this class silently
    # stripped it, so Client Hiring was invisible to the very people it is for. The
    # regression guard in test_phase1_foundation.py asserts all of them stay declared.
    governance_role: Optional[str] = None

    class Config:
        populate_by_name = True
