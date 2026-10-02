"""Shared-domain tools (cross-role).

Catalog (Phase 1+): search_knowledge (RAG bridge), get_calendar, lookup_entity.

Phase 3: search_knowledge. Importing it here runs its @tool decorator.
"""

from app.assistant.tools.shared import dashboard_tools  # noqa: E402,F401
from app.assistant.tools.shared import knowledge_tools  # noqa: E402,F401
from app.assistant.tools.shared import platform_tools  # noqa: E402,F401
from app.assistant.tools.shared import uploaded_files_tools  # noqa: E402,F401
