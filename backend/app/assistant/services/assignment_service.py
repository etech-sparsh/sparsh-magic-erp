"""Assignment retrieval service (V1 decision #2).

V1 models "assignments" as the union of:
  * `type:"task"` calendar events (across STAFF_CALENDER / LEARNER_CALENDER /
    calendar_events), and
  * `tasks[]` embedded in `session_templates`.

All assignment access goes through this service so the implementation can be
swapped wholesale if a standalone assignments module is introduced later
(see TD-4). Tools must NOT query task collections directly.

Phase 0: signatures only.
"""
from __future__ import annotations

from typing import Dict, List

from app.assistant.schemas.context import UserContext

# Calendar collections that may hold task-type events.
TASK_EVENT_COLLECTIONS = ["STAFF_CALENDER", "LEARNER_CALENDER", "calendar_events"]
SESSION_TEMPLATE_COLLECTION = "session_templates"


async def get_pending_assignments(ctx: UserContext) -> List[Dict]:
    """Pending (incomplete) assignments for the caller, scoped to them. Phase 1."""
    raise NotImplementedError("assignment_service.get_pending_assignments — Phase 1")


async def get_assignments(ctx: UserContext, include_completed: bool = True) -> List[Dict]:
    """All assignments visible to the caller within scope. Phase 1."""
    raise NotImplementedError("assignment_service.get_assignments — Phase 1")
