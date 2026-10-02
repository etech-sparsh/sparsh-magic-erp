from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from datetime import datetime, timezone
from bson import ObjectId
from pydantic import BaseModel

from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user, require_task_access
from app.models.group_board_card import BoardCardCreate, BoardCardUpdate
from app.routes.group import _is_member_or_manager

# Ideaboard is part of Task Management -> internal-Sparsh-only.
router = APIRouter(prefix="/groups/{group_id}/board", tags=["Group Board"], dependencies=[Depends(require_task_access)])

# Fixed columns (not user-configurable, per product decision) -- enforced here at the
# route level rather than as a Pydantic Literal, matching how tasks.py enforces
# WORKFLOW_STATUSES as a plain route-level list.
BOARD_COLUMNS = ["todo", "in_progress", "done"]

ORDER_GAP = 1000.0


class MoveCardBody(BaseModel):
    column: str
    before_id: Optional[str] = None
    after_id: Optional[str] = None


def _serialize(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "group_id": doc.get("group_id"),
        "column": doc.get("column"),
        "title": doc.get("title"),
        "description": doc.get("description"),
        "assignee_id": doc.get("assignee_id"),
        "order": doc.get("order"),
        "created_by": doc.get("created_by"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


async def _get_group_or_404(group_id: str) -> dict:
    group_doc = await get_collection("task_groups").find_one({"_id": ObjectId(group_id)})
    if not group_doc:
        raise HTTPException(status_code=404, detail="Group not found")
    return group_doc


async def _authorize(group_id: str, current_user: dict) -> dict:
    group_doc = await _get_group_or_404(group_id)
    if not _is_member_or_manager(group_doc, current_user):
        raise HTTPException(status_code=403, detail="Not authorized for this group's board")
    return group_doc


async def _next_order(group_id: str, column: str) -> float:
    col = get_collection("group_board_cards")
    last = await col.find({"group_id": group_id, "column": column}).sort("order", -1).limit(1).to_list(1)
    return (last[0]["order"] + ORDER_GAP) if last else ORDER_GAP


@router.get("", response_model=List[dict])
async def list_board_cards(group_id: str, current_user: dict = Depends(get_current_user)):
    await _authorize(group_id, current_user)
    docs = await get_collection("group_board_cards").find({"group_id": group_id}).sort("order", 1).to_list(2000)
    return [_serialize(d) for d in docs]


@router.post("", response_model=dict)
async def create_board_card(group_id: str, payload: BoardCardCreate, current_user: dict = Depends(get_current_user)):
    await _authorize(group_id, current_user)
    if payload.column not in BOARD_COLUMNS:
        raise HTTPException(status_code=400, detail=f"column must be one of {BOARD_COLUMNS}")
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Card title is required")

    order = await _next_order(group_id, payload.column)
    doc = {
        "group_id": group_id,
        "column": payload.column,
        "title": title,
        "description": (payload.description or "").strip() or None,
        "assignee_id": payload.assignee_id,
        "order": order,
        "created_by": str(current_user["_id"]),
        "created_at": datetime.now(timezone.utc),
        "updated_at": None,
    }
    result = await get_collection("group_board_cards").insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize(doc)


@router.patch("/{card_id}", response_model=dict)
async def update_board_card(group_id: str, card_id: str, payload: BoardCardUpdate, current_user: dict = Depends(get_current_user)):
    await _authorize(group_id, current_user)
    col = get_collection("group_board_cards")
    existing = await col.find_one({"_id": ObjectId(card_id), "group_id": group_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Card not found")

    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "column" in updates:
        if updates["column"] not in BOARD_COLUMNS:
            raise HTTPException(status_code=400, detail=f"column must be one of {BOARD_COLUMNS}")
        if updates["column"] != existing.get("column"):
            # Plain field-edit path (no explicit position given) -- append to the end of
            # the target column. Drag-and-drop moves with a specific position go through
            # POST /{card_id}/move instead, which computes a precise fractional order.
            updates["order"] = await _next_order(group_id, updates["column"])
    if "title" in updates:
        updates["title"] = updates["title"].strip()
    updates["updated_at"] = datetime.now(timezone.utc)

    await col.update_one({"_id": ObjectId(card_id)}, {"$set": updates})
    updated = await col.find_one({"_id": ObjectId(card_id)})
    return _serialize(updated)


@router.post("/{card_id}/move", response_model=dict)
async def move_board_card(group_id: str, card_id: str, body: MoveCardBody, current_user: dict = Depends(get_current_user)):
    await _authorize(group_id, current_user)
    if body.column not in BOARD_COLUMNS:
        raise HTTPException(status_code=400, detail=f"column must be one of {BOARD_COLUMNS}")

    col = get_collection("group_board_cards")
    existing = await col.find_one({"_id": ObjectId(card_id), "group_id": group_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Card not found")

    before = await col.find_one({"_id": ObjectId(body.before_id)}) if body.before_id else None
    after = await col.find_one({"_id": ObjectId(body.after_id)}) if body.after_id else None

    if before and after:
        new_order = (before["order"] + after["order"]) / 2
    elif after:
        new_order = after["order"] - ORDER_GAP
    elif before:
        new_order = before["order"] + ORDER_GAP
    else:
        new_order = await _next_order(group_id, body.column)

    await col.update_one(
        {"_id": ObjectId(card_id)},
        {"$set": {"column": body.column, "order": new_order, "updated_at": datetime.now(timezone.utc)}},
    )
    updated = await col.find_one({"_id": ObjectId(card_id)})
    return _serialize(updated)


@router.delete("/{card_id}", response_model=dict)
async def delete_board_card(group_id: str, card_id: str, current_user: dict = Depends(get_current_user)):
    await _authorize(group_id, current_user)
    result = await get_collection("group_board_cards").delete_one({"_id": ObjectId(card_id), "group_id": group_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Card not found")
    return {"message": "Card deleted"}
