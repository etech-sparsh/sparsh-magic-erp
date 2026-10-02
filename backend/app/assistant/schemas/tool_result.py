"""Shared, typed result contract returned by EVERY assistant tool.

Keeping a single envelope keeps the tool layer consistent as the catalog grows:
the orchestrator can uniformly inspect success/error, surface `sources` for
attribution, and hand a compact view back to the LLM during the tool-call loop.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class ToolResultMeta(BaseModel):
    """Provenance + diagnostics for a single tool invocation."""

    tool: str                                   # tool name that produced this
    sources: List[str] = Field(default_factory=list)  # collections/services read
    count: Optional[int] = None                 # row count when data is a list
    scope_applied: Optional[str] = None         # e.g. "personal:<uid>", "company:<id>"
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ToolResult(BaseModel):
    """Uniform envelope for tool output."""

    success: bool
    data: Any = None
    error: Optional[str] = None
    meta: ToolResultMeta

    # ── Constructors ──────────────────────────────────────────────────────
    @classmethod
    def ok(
        cls,
        tool: str,
        data: Any,
        sources: Optional[List[str]] = None,
        count: Optional[int] = None,
        scope_applied: Optional[str] = None,
    ) -> "ToolResult":
        if count is None and isinstance(data, list):
            count = len(data)
        return cls(
            success=True,
            data=data,
            meta=ToolResultMeta(
                tool=tool,
                sources=sources or [],
                count=count,
                scope_applied=scope_applied,
            ),
        )

    @classmethod
    def fail(
        cls,
        tool: str,
        error: str,
        sources: Optional[List[str]] = None,
    ) -> "ToolResult":
        return cls(
            success=False,
            data=None,
            error=error,
            meta=ToolResultMeta(tool=tool, sources=sources or []),
        )

    # ── Views ─────────────────────────────────────────────────────────────
    def for_llm(self) -> dict:
        """Compact representation fed back to the model in the tool-call loop."""
        if not self.success:
            return {"success": False, "error": self.error}
        return {"success": True, "data": self.data, "count": self.meta.count}
