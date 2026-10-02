"""TTL cache abstraction + named caches.

`TTLCache` is a small in-process cache with per-entry expiry and a size cap. It's
deliberately behind a minimal interface (get/set/invalidate/clear) so it can be
swapped for Redis/Memcached later without touching call sites.

Three named caches with distinct TTLs:
  * metadata_cache  — slow-changing metadata (accessible knowledge projects)
  * analytics_cache — analytics results (short TTL; data changes on new submissions)
  * knowledge_cache — knowledge retrieval results per (user, query)
"""
from __future__ import annotations

import time
from typing import Any, Optional

from app.assistant.config import config


class TTLCache:
    def __init__(self, ttl: float, max_size: int = 2000):
        self.ttl = ttl
        self.max_size = max_size
        self._store: dict = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        if len(self._store) >= self.max_size:
            # Evict the oldest inserted key (simple FIFO).
            self._store.pop(next(iter(self._store)), None)
        self._store[key] = (time.monotonic() + self.ttl, value)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def stats(self) -> dict:
        return {"entries": len(self._store), "ttl": self.ttl, "max_size": self.max_size}


metadata_cache = TTLCache(ttl=config.CACHE_METADATA_TTL)
analytics_cache = TTLCache(ttl=config.CACHE_ANALYTICS_TTL)
knowledge_cache = TTLCache(ttl=config.CACHE_KNOWLEDGE_TTL)


def clear_all() -> None:
    metadata_cache.clear()
    analytics_cache.clear()
    knowledge_cache.clear()
