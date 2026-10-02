"""Token cost estimation and persistent cost reporting.

Cost is computed from per-model token usage (UsageMeter.by_model) against a
configurable price table, then persisted per request to `assistant_cost` for
durable reporting/aggregation. Pricing values are approximate and configurable —
update PRICING to match your contracted rates.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.assistant.config import config
from app.assistant.observability.logging import log_event
from app.db.mongodb import get_collection

# USD per 1K tokens (approximate; configurable).
PRICING = {
    "gpt-4o": {"prompt": 0.0025, "completion": 0.01},
    "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
}


def estimate_cost(meter) -> dict:
    """Estimate USD cost from a UsageMeter's per-model breakdown."""
    total = 0.0
    breakdown = {}
    for model, u in (getattr(meter, "by_model", {}) or {}).items():
        price = PRICING.get(model)
        if not price:
            continue
        c = u["prompt"] / 1000 * price["prompt"] + u["completion"] / 1000 * price["completion"]
        breakdown[model] = round(c, 6)
        total += c
    return {"total_usd": round(total, 6), "by_model": breakdown}


async def record_cost(cid: str, user_id: str, meter) -> dict:
    """Persist a cost record for this request. Best-effort: never raises."""
    estimate = estimate_cost(meter)
    if not config.COST_REPORTING_ENABLED:
        return estimate
    try:
        await get_collection(config.COST_COLLECTION).insert_one(
            {
                "correlation_id": cid,
                "user_id": user_id,
                "usage": meter.as_dict(),
                "cost_usd": estimate["total_usd"],
                "cost_by_model": estimate["by_model"],
                "created_at": datetime.utcnow(),
            }
        )
    except Exception as exc:  # noqa: BLE001 — cost logging must never break a request
        log_event("cost_record_failed", error=str(exc))
    return estimate
