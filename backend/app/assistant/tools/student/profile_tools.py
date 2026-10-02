"""Student profile tool: get_my_profile."""
from __future__ import annotations

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.tools.registry import tool
from app.assistant.utils.serializers import serialize
from app.utils.calendar_utils import find_user_by_id

# Whitelisted, non-sensitive profile fields (serializer also drops secrets).
PROFILE_FIELDS = [
    "full_name", "first_name", "last_name", "role", "tag",
    "company_id", "designation", "department",
    "batch_ids", "batch_id", "session_type", "is_active",
]


@tool(
    name="get_my_profile",
    description=(
        "Get the current user's own profile details (name, email, role, "
        "company, department, designation, batches). Use for questions like "
        "'what's my role', 'which batch am I in', or 'show my profile'."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={},
)
async def get_my_profile(ctx: UserContext) -> ToolResult:
    # Users live in `staff`/`learners`; resolve via the shared helper (TD-2: never
    # touch a unified `users` collection).
    user = await find_user_by_id(ctx.user_id)
    if not user:
        return ToolResult.fail("get_my_profile", "Profile not found")

    data = serialize(user, PROFILE_FIELDS)
    return ToolResult.ok(
        "get_my_profile",
        data,
        sources=["staff/learners"],
        scope_applied=f"personal:{ctx.user_id}",
    )
