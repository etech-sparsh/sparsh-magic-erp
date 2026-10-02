"""Superadmin (SA) org-wide tools — Tier 1.

These tools expose organization-wide data (all batches, companies, users, and
platform KPIs) and are therefore restricted to `allowed_roles=["SA"]`. The
registry enforces this at both schema-exposure and execution time, so AD/CA/CU
callers never see or run them — admins remain limited to their company-scoped
toolset.

Two safety properties hold for every tool here:
  * **Global scope is intentional** — no apply_company/apply_personal filter is
    applied; `scope_applied="global"` is recorded for audit/attribution.
  * **No PII leaves the building** — records about *other* users/companies are
    projected through `serialize_public`, which strips emails, phone numbers,
    addresses, and auth metadata even if a field is whitelisted by mistake.

Queries mirror the existing REST admin endpoints (routes/batch.py,
routes/dashboard.py, routes/user.py) so behaviour stays consistent.
"""
from __future__ import annotations

from typing import Optional

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.tools.registry import tool
from app.assistant.utils.serializers import serialize_public
from app.db.mongodb import get_collection

# Whitelisted projections (PII is stripped again by serialize_public as a backstop).
_BATCH_FIELDS = ["name", "product_name", "description", "status",
                 "start_date", "target_end_date", "created_at"]
_COMPANY_FIELDS = ["name", "domain", "company_type", "city", "state", "country",
                   "members_count", "status", "is_active", "created_at"]
_USER_FIELDS = ["full_name", "first_name", "last_name", "role", "tag",
                "company_id", "designation", "department", "is_active",
                "session_type", "created_at"]

_BATCH_STATUSES = {"active", "completed", "paused"}
_COMPANY_STATUSES = {"active", "hold", "inactive"}


def _clamp(limit, default: int, hard_max: int) -> int:
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(limit, hard_max))


@tool(
    name="list_batches",
    description=(
        "List ALL training batches across the whole organization (every company), "
        "with status, product, dates and how many companies are in each. "
        "Superadmin only. Use for 'show all batches', 'how many active batches', "
        "'which batches are running'. Optionally filter by status."
    ),
    allowed_roles=["SA"],
    parameters={
        "status": {
            "type": "string",
            "enum": ["active", "completed", "paused"],
            "description": "Optional status filter.",
        },
        "limit": {"type": "integer", "description": "Max batches to return (default 100, max 200)."},
    },
)
async def list_batches(ctx: UserContext, status: Optional[str] = None, limit: int = 100) -> ToolResult:
    query: dict = {}
    if status:
        if status not in _BATCH_STATUSES:
            return ToolResult.fail("list_batches", f"Invalid status '{status}'.")
        query["status"] = status

    docs = (
        await get_collection("batches")
        .find(query)
        .sort("created_at", -1)
        .to_list(_clamp(limit, 100, 200))
    )

    data = []
    for b in docs:
        view = serialize_public(b, _BATCH_FIELDS)
        view["company_count"] = len(b.get("companies", []))
        data.append(view)

    return ToolResult.ok(
        "list_batches", data, sources=["batches"], count=len(data), scope_applied="global",
    )


@tool(
    name="list_companies",
    description=(
        "List ALL companies/clients in the organization with type, location, "
        "member count and status. Superadmin only. Use for 'show all companies', "
        "'how many clients do we have', 'list companies on hold'. Optionally "
        "filter by status. Contact details (email/phone/address) are not exposed."
    ),
    allowed_roles=["SA"],
    parameters={
        "status": {
            "type": "string",
            "enum": ["active", "hold", "inactive"],
            "description": "Optional status filter.",
        },
        "limit": {"type": "integer", "description": "Max companies to return (default 100, max 200)."},
    },
)
async def list_companies(ctx: UserContext, status: Optional[str] = None, limit: int = 100) -> ToolResult:
    query: dict = {}
    if status:
        if status not in _COMPANY_STATUSES:
            return ToolResult.fail("list_companies", f"Invalid status '{status}'.")
        query["status"] = status

    docs = (
        await get_collection("companies")
        .find(query)
        .sort("created_at", -1)
        .to_list(_clamp(limit, 100, 200))
    )
    data = [serialize_public(c, _COMPANY_FIELDS) for c in docs]

    return ToolResult.ok(
        "list_companies", data, sources=["companies"], count=len(data), scope_applied="global",
    )


@tool(
    name="get_platform_stats",
    description=(
        "Organization-wide KPIs for the whole platform: total companies, active "
        "batches, total learners and staff. Superadmin only. Use for 'platform "
        "overview', 'how many learners/companies/batches in total', 'system stats'."
    ),
    allowed_roles=["SA"],
    parameters={},
)
async def get_platform_stats(ctx: UserContext) -> ToolResult:
    companies = get_collection("companies")
    batches = get_collection("batches")
    learners = get_collection("learners")
    staff = get_collection("staff")

    total_learners = await learners.count_documents({})
    inactive_learners = await learners.count_documents({"is_active": False})
    data = {
        "total_companies": await companies.count_documents({}),
        "active_batches": await batches.count_documents({"status": "active"}),
        "total_batches": await batches.count_documents({}),
        "total_learners": total_learners,
        "active_learners": total_learners - inactive_learners,
        "inactive_learners": inactive_learners,
        "total_staff": await staff.count_documents({}),
    }

    return ToolResult.ok(
        "get_platform_stats",
        data,
        sources=["companies", "batches", "learners", "staff"],
        scope_applied="global",
    )


@tool(
    name="list_users",
    description=(
        "List users across the WHOLE organization (staff and learners), with "
        "name, role, company, department and active status. Superadmin only. Use "
        "for 'list all users', 'who are the coaches', 'how many learners in "
        "company X'. Optionally filter by role or company. Emails and phone "
        "numbers are never returned."
    ),
    allowed_roles=["SA"],
    parameters={
        "role": {
            "type": "string",
            "description": "Optional role filter, e.g. 'superadmin', 'admin', 'coach', 'clientadmin', 'clientuser'.",
        },
        "company_id": {"type": "string", "description": "Optional company id to restrict learners to one company."},
        "active_only": {"type": "boolean", "description": "Only include active users (default false)."},
        "limit": {"type": "integer", "description": "Max users to return (default 100, max 500)."},
    },
)
async def list_users(
    ctx: UserContext,
    role: Optional[str] = None,
    company_id: Optional[str] = None,
    active_only: bool = False,
    limit: int = 100,
) -> ToolResult:
    query: dict = {}
    if role:
        query["role"] = role
    if company_id:
        query["company_id"] = company_id
    if active_only:
        query["is_active"] = {"$ne": False}

    cap = _clamp(limit, 100, 500)
    # Users live across two collections (staff = admins/coaches, learners = clients).
    # Staff carry no company_id, so a company filter naturally excludes them.
    staff_docs = [] if company_id else await get_collection("staff").find(query).to_list(cap)
    learner_docs = await get_collection("learners").find(query).to_list(cap)

    data = [serialize_public(u, _USER_FIELDS) for u in (staff_docs + learner_docs)][:cap]

    return ToolResult.ok(
        "list_users", data, sources=["staff", "learners"], count=len(data), scope_applied="global",
    )
