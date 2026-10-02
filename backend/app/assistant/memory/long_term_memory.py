"""Durable per-user memory facts injected across conversations (optional). Phase 4."""
from __future__ import annotations

from typing import List

from app.assistant.schemas.context import UserContext


async def get_facts(ctx: UserContext) -> List[str]:
    """Return durable facts about the user for prompt injection. Phase 4."""
    raise NotImplementedError("long_term_memory.get_facts — Phase 4")
