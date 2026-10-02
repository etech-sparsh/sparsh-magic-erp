"""In-process metrics registry.

Tracks per-tool latency/success/timeout counters and request-level rollups. This
is a process-local snapshot (good for a single worker / scraping endpoint); a
StatsD/Prometheus exporter can be added behind the same record_* calls later.
"""
from __future__ import annotations

from typing import Dict


class Metrics:
    def __init__(self):
        self.tools: Dict[str, dict] = {}
        self.requests = {"count": 0, "errors": 0, "total_ms": 0.0}
        self.rate_limited = 0
        self.input_flagged = 0

    def record_tool(self, name: str, success: bool, duration_ms: float, timeout: bool = False) -> None:
        s = self.tools.setdefault(
            name, {"calls": 0, "success": 0, "failure": 0, "timeouts": 0, "total_ms": 0.0, "max_ms": 0.0}
        )
        s["calls"] += 1
        s["success" if success else "failure"] += 1
        if timeout:
            s["timeouts"] += 1
        s["total_ms"] += duration_ms
        s["max_ms"] = max(s["max_ms"], duration_ms)

    def record_request(self, duration_ms: float, error: bool = False) -> None:
        self.requests["count"] += 1
        self.requests["total_ms"] += duration_ms
        if error:
            self.requests["errors"] += 1

    def snapshot(self) -> dict:
        tools = {}
        for name, s in self.tools.items():
            calls = s["calls"] or 1
            tools[name] = {
                **s,
                "avg_ms": round(s["total_ms"] / calls, 2),
                "success_rate": round(s["success"] / calls, 3),
            }
        req = self.requests
        count = req["count"] or 1
        return {
            "requests": {
                **req,
                "avg_ms": round(req["total_ms"] / count, 2),
                "error_rate": round(req["errors"] / count, 3),
            },
            "rate_limited": self.rate_limited,
            "input_flagged": self.input_flagged,
            "tools": tools,
        }

    def reset(self) -> None:
        self.__init__()


# Process-local singleton.
metrics = Metrics()
