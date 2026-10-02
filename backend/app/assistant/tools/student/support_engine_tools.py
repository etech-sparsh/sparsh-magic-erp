"""Support Engine tool: get_support_engine_status (unlock guidance)."""
from __future__ import annotations

from typing import Optional

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.tools.registry import tool
from app.services import gpt_access_service


@tool(
    name="get_support_engine_status",
    description=(
        "Check the user's Sparsh Support Engine projects (the AI score cards / "
        "knowledge tools, e.g. 'Position Score Card', 'Team Engagement Index'): "
        "which are unlocked vs locked, and exactly what the user must complete to "
        "unlock each. Use for 'how do I unlock X', 'why is X locked', 'what can I "
        "access in the support engine', 'what's locked'. Pass `name` to ask about "
        "one specific project."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={
        "name": {
            "type": "string",
            "description": "Optional project name/keyword to filter to one project, e.g. 'Position Score Card'",
        },
    },
)
async def get_support_engine_status(ctx: UserContext, name: Optional[str] = None) -> ToolResult:
    # Same access/unlock logic the website uses — never drifts from the UI.
    projects = await gpt_access_service.get_projects_with_access(
        user_id=ctx.user_id,
        role=ctx.role,
        company_id=ctx.company_id,
        direct_batch_ids=ctx.batch_ids,
        lightweight=True,  # only title/description needed; skips ~10s heavy fetch
    )

    needle = (name or "").strip().lower()
    items = []
    for p in projects:
        title = p.get("title") or p.get("name") or "Untitled"
        if needle and needle not in title.lower():
            continue
        items.append({
            "name": title,
            "locked": bool(p.get("locked")),
            "lock_reason": p.get("lock_reason"),  # None when unlocked
            "description": (p.get("description") or "")[:200],
        })

    locked = sum(1 for i in items if i["locked"])
    data = {
        "projects": items,
        "total": len(items),
        "locked_count": locked,
        "unlocked_count": len(items) - locked,
        "note": (
            "Locked projects unlock automatically once the linked batch, quarter, "
            "or session is completed (see each lock_reason). An admin can also "
            "grant direct access. Projects not in the user's learning path are not listed."
        ),
    }
    return ToolResult.ok(
        "get_support_engine_status",
        data,
        sources=["gpt_projects", "gpt_permissions"],
        count=len(items),
        scope_applied=f"personal:{ctx.user_id}",
    )
