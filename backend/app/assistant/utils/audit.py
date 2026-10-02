"""Audit logging for assistant interactions.

Thin wrapper over structured logging (always carries the correlation id). A
durable audit trail to `activity_logs` can be layered on the same call without
changing call sites.
"""
from __future__ import annotations

from app.assistant.observability.logging import log_event
from app.assistant.schemas.context import UserContext


def log_interaction(ctx: UserContext, event: str, **fields) -> None:
    """Emit a structured audit event for an assistant interaction."""
    log_event(event, user=ctx.user_id, role=ctx.role, **fields)
