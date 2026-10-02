"""Request correlation IDs.

A correlation id is generated (or taken from an inbound `X-Request-ID` header) at
the edge of every assistant request and stored in a contextvar so every layer —
orchestrator, tools, services, logging, cost — can stamp the same id without
threading it through every signature.
"""
from __future__ import annotations

import contextvars
import uuid
from typing import Optional

_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "assistant_correlation_id", default="-"
)


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def begin_request(inbound: Optional[str] = None) -> str:
    """Set the correlation id for this request (reuse inbound header if present)."""
    cid = (inbound or "").strip() or new_id()
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str:
    return _correlation_id.get()
