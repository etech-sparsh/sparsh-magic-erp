"""Tool primitives: the ToolSpec and the handler signature.

A tool handler is an async callable `(ctx: UserContext, **kwargs) -> ToolResult`.
Scope is derived from `ctx`; the LLM-visible parameter schema therefore never
includes identity fields.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List

from app.assistant.schemas.context import UserContext
from app.assistant.schemas.tool_result import ToolResult

ToolHandler = Callable[..., Awaitable[ToolResult]]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]            # JSON-schema "properties" map (no identity fields)
    allowed_roles: List[str]              # canonical levels: SA/AD/CA/CU
    handler: ToolHandler
    required: List[str] = field(default_factory=list)

    def openai_schema(self) -> dict:
        """Render the OpenAI function-calling schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                },
            },
        }

    async def run(self, ctx: UserContext, **kwargs) -> ToolResult:
        return await self.handler(ctx, **kwargs)
