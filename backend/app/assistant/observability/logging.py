"""Structured logging for the assistant.

Emits one JSON object per event, always carrying the active correlation id, so
logs can be correlated across the full request lifecycle.
"""
from __future__ import annotations

import json
import logging

from app.assistant.observability.correlation import get_correlation_id

_logger = logging.getLogger("assistant")


def log_event(event: str, **fields) -> None:
    payload = {"event": event, "cid": get_correlation_id()}
    payload.update(fields)
    _logger.info(json.dumps(payload, default=str))
