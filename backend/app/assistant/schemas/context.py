"""Authenticated user context injected into every request.

Tools derive their data scope from this object (built server-side from the JWT),
NEVER from arguments the LLM emits. This is the security keystone described in
the architecture doc (§3).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class UserContext(BaseModel):
    user_id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str = "clientuser"                 # superadmin/admin/clientadmin/clientuser/custom
    tag: Optional[str] = None                # "staff" | "learner"
    company_id: Optional[str] = None
    batch_ids: List[str] = Field(default_factory=list)
    course_ids: List[str] = Field(default_factory=list)   # quarters; resolved in Phase 1+
    permissions: Dict = Field(default_factory=dict)
