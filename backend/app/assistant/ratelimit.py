"""Per-user rate limiting (sliding window).

In-process sliding-window limiter. For multi-worker deployments this should be
backed by a shared store (Redis); the `check()` interface stays the same.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from app.assistant.config import config


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        self.max = max_requests
        self.window = window_seconds
        self._hits: dict = defaultdict(deque)

    def check(self, key: str):
        """Return (allowed: bool, retry_after_seconds: float)."""
        now = time.monotonic()
        dq = self._hits[key]
        while dq and now - dq[0] > self.window:
            dq.popleft()
        if len(dq) >= self.max:
            return False, round(self.window - (now - dq[0]), 2)
        dq.append(now)
        return True, 0.0

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter(config.RATE_LIMIT_MAX, config.RATE_LIMIT_WINDOW)
