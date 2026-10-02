"""Feature flags and rollout controls.

`is_enabled_for(ctx)` is the single gate the router consults before serving a
request. Rollout modes:
  * all        — everyone (subject to ENABLED_ROLES)
  * allowlist  — only user_ids/emails in ROLLOUT_ALLOWLIST
  * percentage — deterministic hash bucket < ROLLOUT_PERCENT
"""
from __future__ import annotations

import hashlib
from typing import Tuple

from app.assistant.config import config
from app.assistant.schemas.context import UserContext


def _bucket(user_id: str) -> int:
    digest = hashlib.sha256((user_id or "").encode()).hexdigest()
    return int(digest, 16) % 100


def is_enabled_for(ctx: UserContext) -> Tuple[bool, str]:
    """Return (enabled, reason)."""
    if not config.ENABLED:
        return False, "assistant_disabled"

    if config.ENABLED_ROLES and ctx.role not in config.ENABLED_ROLES:
        return False, "role_not_enabled"

    mode = config.ROLLOUT_MODE
    if mode == "allowlist":
        allowed = ctx.user_id in config.ROLLOUT_ALLOWLIST or (
            ctx.email and ctx.email in config.ROLLOUT_ALLOWLIST
        )
        return (True, "allowlist") if allowed else (False, "not_in_allowlist")
    if mode == "percentage":
        return (_bucket(ctx.user_id) < config.ROLLOUT_PERCENT, "percentage")
    return True, "ok"


def snapshot() -> dict:
    return {
        "enabled": config.ENABLED,
        "streaming": config.STREAMING_ENABLED,
        "rag": config.RAG_ENABLED,
        "analytics": config.ANALYTICS_ENABLED,
        "guardrails": config.GUARDRAILS_ENABLED,
        "rate_limit": config.RATE_LIMIT_ENABLED,
        "rollout_mode": config.ROLLOUT_MODE,
        "rollout_percent": config.ROLLOUT_PERCENT,
        "enabled_roles": config.ENABLED_ROLES or "all",
    }
