from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# Task Groups (collection: "task_groups"). A group is a named set of members inside which
# tasks can be assigned/coordinated (Groups sub-module under Task Management). Tasks store a
# `group_id` pointing back here (see CalendarEventBase.group_id).
class GroupLink(BaseModel):
    id: str
    name: str
    url: str


class GroupBase(BaseModel):
    name: str
    description: Optional[str] = None
    member_ids: List[str] = Field(default_factory=list)
    icon: Optional[str] = None
    color: Optional[str] = None


class GroupCreate(GroupBase):
    pass


class GroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    member_ids: Optional[List[str]] = None
    icon: Optional[str] = None
    color: Optional[str] = None


class GroupResponse(GroupBase):
    id: str
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    task_count: int = 0
    links: List[GroupLink] = Field(default_factory=list)
