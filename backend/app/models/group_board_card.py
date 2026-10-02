from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# Ideaboard cards (collection: "group_board_cards") -- a group-scoped kanban board with
# fixed columns (see BOARD_COLUMNS in group_board.py). Kept as its own collection rather
# than an embedded array on the group doc so drag/reorder can update a single card doc
# instead of rewriting one big nested array on every move.
class BoardCardCreate(BaseModel):
    column: str
    title: str
    description: Optional[str] = None
    assignee_id: Optional[str] = None


class BoardCardUpdate(BaseModel):
    column: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    assignee_id: Optional[str] = None


class BoardCardResponse(BaseModel):
    id: str
    group_id: str
    column: str
    title: str
    description: Optional[str] = None
    assignee_id: Optional[str] = None
    order: float
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
