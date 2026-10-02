"""FastAPI dependencies for the assistant.

`get_user_context` builds a UserContext from the authenticated user once per
request. Tools receive this object and derive their scope from it — the LLM never
passes identity arguments.
"""
from __future__ import annotations

from typing import List

from fastapi import Depends

from app.assistant.caching import cache
from app.assistant.schemas.context import UserContext
from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection


def build_user_context(current_user: dict) -> UserContext:
    """Derive a UserContext from a raw user document (staff/learners)."""
    # Normalize batch references — the codebase stores both `batch_ids` (list)
    # and a singular `batch_id` (see gpt.py access logic).
    batch_ids = current_user.get("batch_ids") or []
    if not isinstance(batch_ids, list):
        batch_ids = [batch_ids]
    single_batch = current_user.get("batch_id")
    if single_batch and single_batch not in batch_ids:
        batch_ids.append(single_batch)

    company_id = current_user.get("company_id")

    return UserContext(
        user_id=str(current_user.get("_id")),
        email=current_user.get("email"),
        full_name=current_user.get("full_name") or current_user.get("email"),
        role=current_user.get("role", "clientuser"),
        tag=current_user.get("tag"),
        company_id=str(company_id) if company_id else None,
        batch_ids=[str(b) for b in batch_ids if b],
        course_ids=[],  # quarters resolved from batch_ids in Phase 1+
        permissions=current_user.get("permissions") or {},
    )


async def _resolve_batch_ids(company_id: str) -> List[str]:
    """Resolve the batches a company belongs to.

    User documents don't store `batch_ids`; membership is via the company
    (`batches.companies`). Several LMS tools (progress, curriculum, knowledge
    scope) need the batch set, so we resolve it once per request and cache it
    (membership changes rarely).
    """
    cache_key = f"ctx_batches:{company_id}"
    cached = cache.metadata_cache.get(cache_key)
    if cached is not None:
        return cached
    batches = await get_collection("batches").find({"companies": company_id}).to_list(100)
    ids = [str(b["_id"]) for b in batches]
    cache.metadata_cache.set(cache_key, ids)
    return ids


async def get_user_context(
    current_user: dict = Depends(get_current_user),
) -> UserContext:
    ctx = build_user_context(current_user)
    # Backfill batch membership from the company link when absent on the user doc.
    if not ctx.batch_ids and ctx.company_id:
        ctx.batch_ids = await _resolve_batch_ids(ctx.company_id)
    return ctx
