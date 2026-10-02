"""Assistant-specific exception types."""
from __future__ import annotations


class AssistantError(Exception):
    """Base class for assistant errors."""


class ToolExecutionError(AssistantError):
    """A tool failed during execution."""


class ToolNotFoundError(AssistantError):
    """The model requested a tool that is not registered."""


class ScopeViolationError(AssistantError):
    """A query attempted to exceed the caller's permitted scope."""
