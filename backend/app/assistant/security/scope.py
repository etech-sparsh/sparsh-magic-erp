"""ScopeFilter — injects RBAC data scope into tool queries.

Skeleton for Phase 0. Field names differ per collection (e.g. batches use
`companies`, assessments use `company_id`/`user_id`); per-collection refinement
lands with the concrete tools in Phase 1. The contract here is stable:

    scope = ScopeFilter(ctx)
    query = scope.apply_company(query)     # company-restrict for client roles
    query = scope.apply_personal(query)    # caller-only for learners
"""
from __future__ import annotations

from typing import Dict

from app.assistant.schemas.context import UserContext
from app.assistant.security.rbac import (
    ROLE_AD,
    ROLE_CA,
    ROLE_CU,
    ROLE_SA,
    normalize_role,
)


class ScopeFilter:
    def __init__(self, ctx: UserContext):
        self.ctx = ctx
        self.level = normalize_role(ctx.role)

    def describe(self) -> str:
        """Human-readable scope string for ToolResult.meta.scope_applied."""
        if self.level == ROLE_SA:
            return "global"
        if self.level == ROLE_AD:
            return "coaching"
        if self.level == ROLE_CA:
            return f"company:{self.ctx.company_id}"
        return f"personal:{self.ctx.user_id}"

    def apply_company(self, query: Dict, field: str = "companies") -> Dict:
        """Restrict by company for client roles. No-op for SA/AD."""
        if self.level in (ROLE_CA, ROLE_CU) and self.ctx.company_id:
            query[field] = self.ctx.company_id
        return query

    def apply_personal(self, query: Dict, field: str = "user_id") -> Dict:
        """Restrict to the caller (learner personal data). No-op for staff/admin."""
        if self.level == ROLE_CU:
            query[field] = self.ctx.user_id
        return query
