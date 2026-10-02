"""Role normalization for the assistant.

The Tool Catalog uses four canonical scope levels: SA, AD, CA, CU. System roles
(and tags) are mapped onto these. Unknown/custom roles fall back to the LEAST
privileged level (CU) — fail-closed by design. Custom roles with elevated access
are resolved against the `roles` collection in a later phase (see check_permission).
"""
from __future__ import annotations

from typing import Optional

ROLE_SA = "SA"   # superadmin — global
ROLE_AD = "AD"   # admin / staff / coach — coaching-wide
ROLE_CA = "CA"   # clientadmin — company scope
ROLE_CU = "CU"   # clientuser (learner) — personal scope

_ROLE_MAP = {
    "superadmin": ROLE_SA,
    "admin": ROLE_AD,
    "coach": ROLE_AD,
    "staff": ROLE_AD,
    "clientadmin": ROLE_CA,
    "clientuser": ROLE_CU,
    "clientdoer": ROLE_CU,   # task-doer learner — personal scope
}


def normalize_role(role: Optional[str]) -> str:
    """Map a system role string to a canonical scope level (fail-closed to CU)."""
    if not role:
        return ROLE_CU
    return _ROLE_MAP.get(role.lower(), ROLE_CU)
