from fastapi import APIRouter, Depends, HTTPException
from typing import List
from datetime import datetime, timezone
from bson import ObjectId

from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user, require_task_access
from app.models.group import GroupCreate, GroupUpdate, GroupLink
from app.services.activity_log_service import log_activity
from app.utils.calendar_utils import CALENDAR_COLLECTIONS

# Task Groups are part of the Task Management module -> internal-Sparsh-only (see
# require_task_access). Router-level dependency 403s client-side users on every endpoint.
router = APIRouter(prefix="/groups", tags=["Groups"], dependencies=[Depends(require_task_access)])

# Staff/admins manage groups; regular users can see groups they're a member of. Mirrors the
# management-role convention used by the Holiday and Task modules.
MANAGE_ROLES = ["superadmin", "admin", "coach", "staff", "clientadmin"]
TASK_COLLECTIONS = CALENDAR_COLLECTIONS + ["calendar_events"]


def _can_manage(current_user: dict) -> bool:
    role = (current_user.get("role") or "").lower()
    if role in MANAGE_ROLES:
        return True
    return bool(current_user.get("permissions", {}).get("tasks", {}).get("create"))


def _is_member_or_manager(group_doc: dict, current_user: dict) -> bool:
    """Any group member (or a manager) can view the group's tasks/activity and add
    board cards/links — the same "any participant can add sub-items" rule tasks
    already follow for checklist/comments/attachments. Reused by tasks.py's
    scope=="group" and group_board.py so this authorization logic lives in one place."""
    if _can_manage(current_user):
        return True
    user_id = str(current_user["_id"])
    if group_doc.get("created_by") == user_id:
        return True
    return user_id in (group_doc.get("member_ids") or [])


async def _task_count(group_id: str) -> int:
    total = 0
    for col_name in TASK_COLLECTIONS:
        total += await get_collection(col_name).count_documents(
            {"type": "task", "group_id": group_id, "deleted_at": None}
        )
    return total


def _serialize(doc: dict, task_count: int = 0) -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name"),
        "description": doc.get("description"),
        "member_ids": doc.get("member_ids") or [],
        "icon": doc.get("icon"),
        "color": doc.get("color"),
        "links": doc.get("links") or [],
        "created_by": doc.get("created_by"),
        "created_by_name": doc.get("created_by_name"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "task_count": task_count,
    }


@router.get("", response_model=List[dict])
async def list_groups(current_user: dict = Depends(get_current_user)):
    col = get_collection("task_groups")
    role = (current_user.get("role") or "").lower()
    uid = str(current_user["_id"])

    query = {}
    # Non-managers only see groups they created or are a member of.
    if role not in MANAGE_ROLES:
        query = {"$or": [{"created_by": uid}, {"member_ids": uid}]}

    docs = await col.find(query).sort("created_at", -1).to_list(500)
    out = []
    for d in docs:
        out.append(_serialize(d, await _task_count(str(d["_id"]))))
    return out


@router.post("", response_model=dict)
async def create_group(payload: GroupCreate, current_user: dict = Depends(get_current_user)):
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to create groups")

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required")

    col = get_collection("task_groups")
    data = {
        "name": name,
        "description": (payload.description or "").strip() or None,
        "member_ids": payload.member_ids or [],
        "icon": payload.icon,
        "color": payload.color,
        "links": [],
        "created_by": str(current_user["_id"]),
        "created_by_name": current_user.get("full_name") or current_user.get("email"),
        "created_at": datetime.now(timezone.utc),
        "updated_at": None,
    }
    result = await col.insert_one(data)
    await log_activity(current_user, "Create Group", "Group", f"Group created: {name}")
    return {"id": str(result.inserted_id), "message": "Group created"}


@router.get("/{group_id}", response_model=dict)
async def get_group(group_id: str, current_user: dict = Depends(get_current_user)):
    col = get_collection("task_groups")
    doc = await col.find_one({"_id": ObjectId(group_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Group not found")
    return _serialize(doc, await _task_count(group_id))


@router.put("/{group_id}", response_model=dict)
async def update_group(group_id: str, payload: GroupUpdate, current_user: dict = Depends(get_current_user)):
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update groups")

    col = get_collection("task_groups")
    existing = await col.find_one({"_id": ObjectId(group_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Group not found")

    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "name" in updates:
        updates["name"] = updates["name"].strip()
    updates["updated_at"] = datetime.now(timezone.utc)
    await col.update_one({"_id": ObjectId(group_id)}, {"$set": updates})
    await log_activity(current_user, "Update Group", "Group", f"Group updated: {updates.get('name', existing.get('name'))}")
    return {"message": "Group updated"}


@router.delete("/{group_id}", response_model=dict)
async def delete_group(group_id: str, current_user: dict = Depends(get_current_user)):
    if not _can_manage(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to delete groups")

    col = get_collection("task_groups")
    existing = await col.find_one({"_id": ObjectId(group_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Group not found")

    # Orphan (don't delete) the group's tasks -- removing an organizational label should
    # never destroy real task work. Board cards have no meaning without their group, so
    # those are hard-deleted.
    for col_name in TASK_COLLECTIONS:
        await get_collection(col_name).update_many({"group_id": group_id}, {"$set": {"group_id": None}})
    await get_collection("group_board_cards").delete_many({"group_id": group_id})

    await col.delete_one({"_id": ObjectId(group_id)})
    await log_activity(current_user, "Delete Group", "Group", f"Group removed: {existing.get('name')}")
    return {"message": "Group deleted"}


@router.post("/{group_id}/links", response_model=dict)
async def add_group_link(group_id: str, body: dict, current_user: dict = Depends(get_current_user)):
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Link URL is required")
    name = (body.get("name") or "").strip() or url

    col = get_collection("task_groups")
    existing = await col.find_one({"_id": ObjectId(group_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Group not found")
    if not _is_member_or_manager(existing, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update this group")

    link = {"id": str(ObjectId()), "name": name, "url": url}
    await col.update_one({"_id": ObjectId(group_id)}, {"$push": {"links": link}})
    await log_activity(current_user, "Add Group Link", "Group", f"Group {group_id}: {url}")
    return link


@router.delete("/{group_id}/links/{link_id}", response_model=dict)
async def delete_group_link(group_id: str, link_id: str, current_user: dict = Depends(get_current_user)):
    col = get_collection("task_groups")
    existing = await col.find_one({"_id": ObjectId(group_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Group not found")
    if not _is_member_or_manager(existing, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to update this group")

    await col.update_one({"_id": ObjectId(group_id)}, {"$pull": {"links": {"id": link_id}}})
    return {"message": "Link removed"}
