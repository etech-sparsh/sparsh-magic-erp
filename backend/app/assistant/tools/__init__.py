"""Tool layer.

Tools are organized by domain (student/teacher/admin/shared) per the Tool
Catalog. Each tool registers via the `@tool` decorator in registry.py, declares
its `allowed_roles`, and returns a `ToolResult`. The registry exposes only the
tools a given role may use.

Phase 0: domain modules are empty placeholders; no tools are implemented yet.
"""
