from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class Task(BaseModel):
    title: str
    description: Optional[str] = None
    status: str = "pending"
    due_date: Optional[datetime] = None
    assigned_to: str # User ID
    created_by: str # User ID

class Event(BaseModel):
    title: str
    start_time: datetime
    end_time: datetime
    description: Optional[str] = None
    participants: List[str] = [] # User IDs

class Todo(BaseModel):
    task: str
    completed: bool = False
    user_id: str
