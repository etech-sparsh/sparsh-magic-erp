"""Student curriculum tool: get_my_curriculum (batches → quarters)."""
from __future__ import annotations

from bson import ObjectId
from bson.errors import InvalidId

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult
from app.assistant.tools.registry import tool
from app.assistant.utils.serializers import serialize
from app.db.mongodb import get_collection

BATCH_FIELDS = ["name", "product_name", "description", "status", "start_date", "target_end_date"]
QUARTER_FIELDS = ["name", "status", "description", "start_date", "target_end_date"]


def _oid(value: str):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


@tool(
    name="get_my_curriculum",
    description=(
        "Get the current user's learning structure: the batch(es) they belong "
        "to and the quarters/modules within each (with status). Use for 'what "
        "batch am I in', 'what quarter am I on', 'what's my course plan', "
        "'what modules/quarters are there', 'my training program'."
    ),
    allowed_roles=["CU", "CA", "AD", "SA"],
    parameters={},
)
async def get_my_curriculum(ctx: UserContext) -> ToolResult:
    # Resolve the user's batches: prefer the (backfilled) batch_ids, fall back
    # to the company link. Membership is always via the company.
    batches = []
    oids = [o for o in (_oid(b) for b in ctx.batch_ids) if o]
    if oids:
        batches = await get_collection("batches").find({"_id": {"$in": oids}}).to_list(50)
    if not batches and ctx.company_id:
        batches = await get_collection("batches").find({"companies": ctx.company_id}).to_list(50)

    batch_ids = [str(b["_id"]) for b in batches]
    quarters = []
    if batch_ids:
        quarters = (
            await get_collection("quarters")
            .find({"batch_id": {"$in": batch_ids}})
            .to_list(200)
        )

    data = []
    for b in batches:
        bid = str(b["_id"])
        b_view = serialize(b, BATCH_FIELDS)
        b_view["quarters"] = [
            serialize(q, QUARTER_FIELDS) for q in quarters if q.get("batch_id") == bid
        ]
        data.append(b_view)

    return ToolResult.ok(
        "get_my_curriculum",
        data,
        sources=["batches", "quarters"],
        count=len(data),
        scope_applied=f"company:{ctx.company_id}" if ctx.company_id else f"personal:{ctx.user_id}",
    )
