from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

class PermissionScope(str, Enum):
    GLOBAL = "global"       # SuperAdmin scope
    COACHING = "coaching"   # Admin scope
    COMPANY = "company"     # ClientAdmin scope
    PERSONAL = "personal"   # ClientDoer scope

class PermissionAction(str, Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    APPROVE = "approve"
    ASSIGN = "assign"
    EXPORT = "export"
    MANAGE = "manage"

class Permission(BaseModel):
    module: str             # e.g., "LMS", "Users", "Companies", "Tasks"
    actions: List[PermissionAction]
    scope: PermissionScope

class RoleBase(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: List[Permission]
    company_id: Optional[str] = None # If null, it's a global/system role

class RoleCreate(RoleBase):
    pass

class RoleResponse(RoleBase):
    id: str = Field(alias="_id")

    class Config:
        populate_by_name = True
